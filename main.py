import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput, Select
import os
import asyncpg
import aiohttp
from datetime import datetime, timedelta

# ====== [1. 설정 및 ID] ======
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_USER_ID = 1472930278874939445
LOG_CHANNEL_ID = 1476976182523068478

RANKS = {
    50000000: 1476788776658534501, 10000000: 1476788690696011868, 
    3000000: 1476788607569104946, 1000000: 1476788508076146689,  
    500000: 1476788430850752532, 300000: 1476788381940973741,   
    100000: 1476788291448865019, 0: 1476788194346274936         
}

stock_amount = "현재 자판기 미완성"
current_k_premium = "데이터 수집 중..."
last_update_time = "대기 중"
last_otc_message = None 

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 

def get_kst_now():
    return datetime.utcnow() + timedelta(hours=9)

# ====== [2. 본인인증 관련 UI 클래스] ======

class AdminVerifyApproveView(View):
    def __init__(self, target_user_id, bot):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id
        self.bot = bot

    @discord.ui.button(label="승인", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: Button):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET is_verified = TRUE WHERE user_id = $1", self.target_user_id)
        await interaction.response.send_message(f"✅ <@{self.target_user_id}>님 승인 완료", ephemeral=True)
        await interaction.message.delete()

class UserDetailModal(Modal):
    def __init__(self, bot, carrier):
        super().__init__(title=f"{carrier} 본인확인 정보 입력")
        self.bot = bot
        self.u_name = TextInput(label="이름", placeholder="홍길동", min_length=2, max_length=5)
        self.u_birth = TextInput(label="주민번호 앞자리-성별", placeholder="990101-1", min_length=8, max_length=8)
        self.u_phone = TextInput(label="전화번호", placeholder="01012345678", min_length=10, max_length=11)
        self.u_bank = TextInput(label="은행명", placeholder="카카오뱅크")
        self.u_account = TextInput(label="계좌번호", placeholder="숫자만 입력")
        self.add_item(self.u_name); self.add_item(self.u_birth); self.add_item(self.u_phone); self.add_item(self.u_bank); self.add_item(self.u_account)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        name = self.u_name.value
        masked_name = name[0] + "x" + name[-1] if len(name) > 2 else name[0] + "x"
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            embed = discord.Embed(title="🛡️ 본인인증 신청", color=discord.Color.blue())
            embed.add_field(name="유저", value=interaction.user.mention)
            embed.add_field(name="이름", value=masked_name, inline=True)
            embed.add_field(name="번호", value=self.u_phone.value, inline=True)
            embed.add_field(name="계좌", value=f"{self.u_bank.value} {self.u_account.value}", inline=False)
            await log_ch.send(embed=embed, view=AdminVerifyApproveView(interaction.user.id, self.bot))
        await interaction.followup.send("✅ 인증 신청이 접수되었습니다.", ephemeral=True)

class CarrierSelectView(View):
    def __init__(self, bot):
        super().__init__(timeout=60); self.bot = bot
        options = [discord.SelectOption(label=f"{n} 알뜰폰", value=f"{n} 알뜰폰") for n in ["SKT", "KT", "LGU+"]]
        self.select = Select(placeholder="알뜰폰 통신사 선택", options=options)
        self.select.callback = self.select_callback; self.add_item(self.select)
    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(UserDetailModal(self.bot, self.select.values[0]))

class MainCarrierView(View):
    def __init__(self, bot):
        super().__init__(timeout=60); self.bot = bot
    @discord.ui.button(label="SKT", style=discord.ButtonStyle.secondary)
    async def skt(self, interaction: discord.Interaction, button: Button): await interaction.response.send_modal(UserDetailModal(self.bot, "SKT"))
    @discord.ui.button(label="KT", style=discord.ButtonStyle.secondary)
    async def kt(self, interaction: discord.Interaction, button: Button): await interaction.response.send_modal(UserDetailModal(self.bot, "KT"))
    @discord.ui.button(label="LGU+", style=discord.ButtonStyle.secondary)
    async def lgu(self, interaction: discord.Interaction, button: Button): await interaction.response.send_modal(UserDetailModal(self.bot, "LGU+"))
    @discord.ui.button(label="알뜰폰", style=discord.ButtonStyle.primary)
    async def mvno(self, interaction: discord.Interaction, button: Button): await interaction.response.edit_message(content="알뜰폰 세부 선택", view=CarrierSelectView(self.bot))

# ====== [3. 자판기 및 관리자 UI 클래스] ======

class OTCView(View):
    def __init__(self, bot):
        super().__init__(timeout=None); self.bot = bot
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        async with self.bot.db.acquire() as conn:
            user = await conn.fetchrow("SELECT is_verified FROM users WHERE user_id = $1", interaction.user.id)
        if user and user['is_verified']: return True
        await interaction.response.send_message("🔒 본인인증이 필요합니다.", view=MainCarrierView(self.bot), ephemeral=True)
        return False

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary)
    async def charge(self, interaction: discord.Interaction, button: Button):
        modal = Modal(title="충전 신청")
        amt = TextInput(label="금액 (숫자만)"); modal.add_item(amt)
        async def cb(intact):
            async with self.bot.db.acquire() as conn:
                await conn.execute("INSERT INTO deposit_requests (user_id, amount) VALUES ($1, $2)", intact.user.id, int(amt.value))
            await intact.response.send_message("✅ 신청 완료", ephemeral=True)
        modal.on_submit = cb; await interaction.response.send_modal(modal)

class AdminPanelView(View):
    def __init__(self, bot):
        super().__init__(timeout=None); self.bot = bot
    @discord.ui.button(label="📦 재고 수정", style=discord.ButtonStyle.primary)
    async def edit_stock(self, interaction: discord.Interaction, button: Button):
        modal = Modal(title="재고 수정")
        txt = TextInput(label="문구", default=stock_amount); modal.add_item(txt)
        async def cb(intact):
            global stock_amount; stock_amount = txt.value
            await intact.response.send_message("수정 완료", ephemeral=True)
        modal.on_submit = cb; await interaction.response.send_modal(modal)

# ====== [4. 봇 클래스 및 실행 (정의 순서 중요)] ======

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
    async def setup_hook(self):
        self.db = await asyncpg.create_pool(DATABASE_URL)
        async with self.db.acquire() as conn:
            await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance NUMERIC DEFAULT 0, total_spent NUMERIC DEFAULT 0, is_verified BOOLEAN DEFAULT FALSE);")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;")
            await conn.execute("CREATE TABLE IF NOT EXISTS deposit_requests (id SERIAL PRIMARY KEY, user_id BIGINT, amount NUMERIC, status TEXT DEFAULT 'pending');")
        await self.tree.sync()
        self.update_premium_loop.start()
    
    @tasks.loop(minutes=1.0)
    async def update_premium_loop(self):
        global current_k_premium, last_update_time, last_otc_message
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.upbit.com/v1/ticker?markets=KRW-BTC") as r:
                    upbit = (await r.json())[0]['trade_price']
                async with session.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT") as r:
                    binance = float((await r.json())['price'])
                async with session.get("https://open.er-api.com/v6/latest/USD") as r:
                    ex = (await r.json())['rates']['KRW']
            current_k_premium = f"{((upbit / (binance * ex)) - 1) * 100:.2f}%"
            last_update_time = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
            if last_otc_message:
                embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
                embed.add_field(name="💰 재고", value=f"```{stock_amount}```", inline=False)
                embed.add_field(name="📈 김프", value=f"```{current_k_premium}```", inline=False)
                await last_otc_message.edit(embed=embed, view=OTCView(self))
        except: pass

# ★ 여기서 봇 인스턴스를 먼저 생성합니다 ★
bot = MyBot()

# ====== [5. 명령어 (이제 bot이 정의되었으므로 에러 안 남)] ======

@bot.tree.command(name="otc", description="자판기 출력 (관리자 전용)")
async def otc_slash(interaction: discord.Interaction):
    global last_otc_message
    if interaction.user.id != ADMIN_USER_ID: return await interaction.response.send_message("권한 없음", ephemeral=True)
    await interaction.response.defer()
    embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
    embed.add_field(name="💰 재고", value=f"```{stock_amount}```", inline=False)
    embed.add_field(name="📈 김프", value=f"```{current_k_premium}```", inline=False)
    last_otc_message = await interaction.followup.send(embed=embed, view=OTCView(bot))

@bot.tree.command(name="관리자", description="관리자 패널 호출")
async def admin_panel(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_USER_ID or interaction.channel_id != LOG_CHANNEL_ID:
        return await interaction.response.send_message("권한이 없거나 채널이 틀립니다.", ephemeral=True)
    await interaction.response.send_message("⚙️ 관리 패널", view=AdminPanelView(bot), ephemeral=True)

if TOKEN: bot.run(TOKEN)
