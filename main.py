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

# ====== [2. 본인인증 시스템 (통신사 개별 분리)] ======

class AdminVerifyApproveView(View):
    def __init__(self, target_user_id, bot):
        super().__init__(timeout=None); self.target_user_id = target_user_id; self.bot = bot
    @discord.ui.button(label="승인", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: Button):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET is_verified = TRUE WHERE user_id = $1", self.target_user_id)
        await interaction.response.send_message(f"✅ <@{self.target_user_id}>님 인증 승인 완료", ephemeral=True)
        try:
            user = await self.bot.fetch_user(self.target_user_id)
            await user.send("🎊 본인인증이 완료되었습니다! 이제 모든 메뉴 이용이 가능합니다.")
        except: pass
        await interaction.message.delete()

class UserDetailModal(Modal):
    def __init__(self, bot, carrier):
        super().__init__(title=f"{carrier} 인증 정보 입력"); self.bot = bot
        self.u_name = TextInput(label="이름", placeholder="실명 입력", min_length=2)
        self.u_phone = TextInput(label="전화번호", placeholder="'-' 제외 숫자만")
        self.u_bank = TextInput(label="은행명", placeholder="입금하실 은행명")
        self.u_account = TextInput(label="계좌번호", placeholder="입금 확인용 계좌번호")
        for i in [self.u_name, self.u_phone, self.u_bank, self.u_account]: self.add_item(i)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            embed = discord.Embed(title="🛡️ 본인인증 신청 접수", color=discord.Color.blue())
            embed.add_field(name="신청자", value=interaction.user.mention)
            embed.add_field(name="성함", value=self.u_name.value, inline=True)
            embed.add_field(name="연락처", value=self.u_phone.value, inline=True)
            embed.add_field(name="계좌 정보", value=f"{self.u_bank.value} / {self.u_account.value}", inline=False)
            await log_ch.send(embed=embed, view=AdminVerifyApproveView(interaction.user.id, self.bot))
        await interaction.followup.send("✅ 인증 신청이 완료되었습니다. 관리자 승인을 기다려주세요.", ephemeral=True)

class MVNOCarrierView(View):
    def __init__(self, bot):
        super().__init__(timeout=60); self.bot = bot
    @discord.ui.button(label="SKT 알뜰폰", style=discord.ButtonStyle.secondary)
    async def skt_a(self, interaction, btn): await interaction.response.send_modal(UserDetailModal(self.bot, "SKT 알뜰폰"))
    @discord.ui.button(label="KT 알뜰폰", style=discord.ButtonStyle.secondary)
    async def kt_a(self, interaction, btn): await interaction.response.send_modal(UserDetailModal(self.bot, "KT 알뜰폰"))
    @discord.ui.button(label="LGU+ 알뜰폰", style=discord.ButtonStyle.secondary)
    async def lgu_a(self, interaction, btn): await interaction.response.send_modal(UserDetailModal(self.bot, "LGU+ 알뜰폰"))

class MainCarrierView(View):
    def __init__(self, bot):
        super().__init__(timeout=60); self.bot = bot
    @discord.ui.button(label="SKT", style=discord.ButtonStyle.secondary)
    async def skt(self, interaction, btn): await interaction.response.send_modal(UserDetailModal(self.bot, "SKT"))
    @discord.ui.button(label="KT", style=discord.ButtonStyle.secondary)
    async def kt(self, interaction, btn): await interaction.response.send_modal(UserDetailModal(self.bot, "KT"))
    @discord.ui.button(label="LGU+", style=discord.ButtonStyle.secondary)
    async def lgu(self, interaction, btn): await interaction.response.send_modal(UserDetailModal(self.bot, "LGU+"))
    @discord.ui.button(label="알뜰폰", style=discord.ButtonStyle.primary)
    async def mvno(self, interaction, btn): await interaction.response.edit_message(content="**알뜰폰 통신사를 선택해주세요.**", view=MVNOCarrierView(self.bot))

# ====== [3. 자판기 메인 View (모든 버튼 및 멘트 복구)] ======

class OTCView(View):
    def __init__(self, bot):
        super().__init__(timeout=None); self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        async with self.bot.db.acquire() as conn:
            u = await conn.fetchrow("SELECT is_verified FROM users WHERE user_id = $1", interaction.user.id)
        if u and u['is_verified']: return True
        await interaction.response.send_message("🔒 본인인증이 완료된 유저만 이용 가능합니다.", view=MainCarrierView(self.bot), ephemeral=True)
        return False

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary)
    async def charge(self, interaction, btn):
        modal = Modal(title="💰 충전 신청"); amt = TextInput(label="금액", placeholder="숫자만 입력"); modal.add_item(amt)
        async def cb(intact):
            async with self.bot.db.acquire() as conn:
                await conn.execute("INSERT INTO deposit_requests (user_id, amount) VALUES ($1, $2)", intact.user.id, int(amt.value))
            await intact.response.send_message(f"✅ {int(amt.value):,}원 충전 신청 완료!", ephemeral=True)
        modal.on_submit = cb; await interaction.response.send_modal(modal)

    @discord.ui.button(label="📤 송금", style=discord.ButtonStyle.primary)
    async def transfer(self, interaction, btn):
        await interaction.response.send_message("📤 현재 송금 기능은 준비 중입니다. 관리자에게 문의하세요.", ephemeral=True)

    @discord.ui.button(label="📊 정보", style=discord.ButtonStyle.secondary)
    async def info(self, interaction, btn):
        async with self.bot.db.acquire() as conn:
            u = await conn.fetchrow("SELECT balance, total_spent FROM users WHERE user_id = $1", interaction.user.id)
        bal = u['balance'] if u else 0; spent = u['total_spent'] if u else 0
        
        current_rank = "일반"
        for amt, r_id in sorted(RANKS.items(), reverse=True):
            if spent >= amt:
                role = interaction.guild.get_role(r_id)
                current_rank = role.name if role else "등급 미설정"
                break

        embed = discord.Embed(title=f"👤 {interaction.user.name} 님의 정보", color=discord.Color.blue())
        embed.add_field(name="💰 보유 잔액", value=f"**{bal:,.0f}원**", inline=True)
        embed.add_field(name="📈 누적 이용액", value=f"**{spent:,.0f}원**", inline=True)
        embed.add_field(name="💎 현재 등급", value=f"**{current_rank}**", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="❓ 도움말", style=discord.ButtonStyle.secondary)
    async def help(self, interaction, btn):
        # 관리자님이 사용하시던 도움말 멘트 그대로 복구
        help_멘트 = (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "**🪙 레제 코인대행 이용 안내**\n\n"
            "**1. 충전 방법**\n"
            "└ [충전] 버튼 클릭 -> 금액 입력 -> 안내된 계좌 입금\n\n"
            "**2. 송금 방법**\n"
            "└ [송금] 버튼 클릭 -> 주소 및 수량 입력 -> 자동 전송\n\n"
            "**3. 주의 사항**\n"
            "└ 본인 명의 계좌가 아닐 경우 처리가 지연됩니다.\n"
            "└ 모든 거래는 24시간 모니터링 됩니다.\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        await interaction.response.send_message(help_멘트, ephemeral=True)

# ====== [4. 관리자 패널 및 봇 로직] ======

class AdminPanelView(View):
    def __init__(self, bot):
        super().__init__(timeout=None); self.bot = bot
    @discord.ui.button(label="📦 재고 수정", style=discord.ButtonStyle.primary)
    async def edit(self, interaction, btn):
        modal = Modal(title="재고 수정"); txt = TextInput(label="문구", default=stock_amount); modal.add_item(txt)
        async def cb(intact):
            global stock_amount; stock_amount = txt.value
            await intact.response.send_message("✅ 재고 수정 완료", ephemeral=True)
        modal.on_submit = cb; await interaction.response.send_modal(modal)

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
    async def setup_hook(self):
        self.db = await asyncpg.create_pool(DATABASE_URL)
        async with self.db.acquire() as conn:
            await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance NUMERIC DEFAULT 0, total_spent NUMERIC DEFAULT 0, is_verified BOOLEAN DEFAULT FALSE);")
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
                embed.add_field(name="🕒 갱신 (KST)", value=f"```{last_update_time}```", inline=False)
                embed.set_footer(text="신속한 대행 | 레제 코인대행")
                await last_otc_message.edit(embed=embed, view=OTCView(self))
        except: pass

bot = MyBot()

@bot.tree.command(name="otc", description="자판기 출력")
async def otc_slash(interaction: discord.Interaction):
    global last_otc_message
    if interaction.user.id != ADMIN_USER_ID: return await interaction.response.send_message("권한 없음", ephemeral=True)
    await interaction.response.defer()
    embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
    embed.add_field(name="💰 재고", value=f"```{stock_amount}```", inline=False)
    embed.add_field(name="📈 김프", value=f"```{current_k_premium}```", inline=False)
    embed.add_field(name="🕒 갱신 (KST)", value=f"```{last_update_time}```", inline=False)
    embed.set_footer(text="신속한 대행 | 레제 코인대행")
    last_otc_message = await interaction.followup.send(embed=embed, view=OTCView(bot))

@bot.tree.command(name="관리자", description="관리자 패널 호출")
async def admin_panel(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_USER_ID or interaction.channel_id != LOG_CHANNEL_ID:
        return await interaction.response.send_message("❌ 지정된 채널에서 관리자만 사용 가능합니다.", ephemeral=True)
    await interaction.response.send_message("⚙️ 레제 운영진 전용 패널", view=AdminPanelView(bot), ephemeral=True)

if TOKEN: bot.run(TOKEN)
