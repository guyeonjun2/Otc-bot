import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput, Select
import os
import asyncpg
import aiohttp
import random
from datetime import datetime, timedelta

# ====== [1. 기본 설정 및 ID] ======
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_USER_ID = 1472930278874939445
LOG_CHANNEL_ID = 1476976182523068478

# 등급 설정
RANKS = {
    50000000: 1476788776658534501, 10000000: 1476788690696011868, 
    3000000: 1476788607569104946, 1000000: 1476788508076146689,  
    500000: 1476788430850752532, 300000: 1476788381940973741,   
    100000: 1476788291448865019, 0: 1476788194346274936         
}

# 전역 변수
stock_amount = "현재 자판기 미완성"
current_k_premium = "데이터 수집 중..."
last_update_time = "대기 중"
last_otc_message = None 

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 

def get_kst_now():
    return datetime.utcnow() + timedelta(hours=9)

# ====== [2. 본인인증 시스템] ======

# 관리자 승인 뷰
class AdminVerifyApproveView(View):
    def __init__(self, target_user_id, bot):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id
        self.bot = bot

    @discord.ui.button(label="승인", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: Button):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET is_verified = TRUE WHERE user_id = $1", self.target_user_id)
        
        member = interaction.guild.get_member(self.target_user_id)
        if member:
            try: await member.send("🎊 본인인증이 완료되었습니다! 이제 `/otc` 명령어를 쳐서 메뉴를 이용하실 수 있습니다.")
            except: pass
        await interaction.response.send_message("인증 승인이 완료되었습니다.", ephemeral=True)
        await interaction.message.delete()

# 상세 정보 입력 모달
class UserDetailModal(Modal):
    def __init__(self, bot, carrier):
        super().__init__(title=f"{carrier} 본인확인 정보 입력")
        self.bot = bot
        
        self.u_name = TextInput(label="이름", placeholder="실명 입력 (예: 홍길동)", min_length=2, max_length=5)
        self.u_birth = TextInput(label="주민등록번호 앞자리 + 성별", placeholder="예: 990101-1", min_length=8, max_length=8)
        self.u_phone = TextInput(label="전화번호", placeholder="'-' 제외 숫자만 입력", min_length=10, max_length=11)
        self.u_bank = TextInput(label="은행명", placeholder="예: 카카오뱅크")
        self.u_account = TextInput(label="계좌번호", placeholder="'-' 제외 숫자만 입력")

        self.add_item(self.u_name)
        self.add_item(self.u_birth)
        self.add_item(self.u_phone)
        self.add_item(self.u_bank)
        self.add_item(self.u_account)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        name = self.u_name.value
        masked_name = name[0] + "x" + name[-1] if len(name) > 2 else name[0] + "x"
        
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            embed = discord.Embed(title="🛡️ 본인인증 승인 요청", color=discord.Color.blue())
            embed.add_field(name="유저", value=interaction.user.mention)
            embed.add_field(name="확인용 성함", value=f"**{masked_name}**", inline=True)
            embed.add_field(name="전화번호", value=f"**{self.u_phone.value}**", inline=True)
            embed.add_field(name="생년월일/성별", value=self.u_birth.value, inline=True)
            embed.add_field(name="계좌 정보", value=f"{self.u_bank.value} / {self.u_account.value}", inline=False)
            embed.set_footer(text="입금자명과 대조하여 승인 여부를 결정하세요.")
            await log_ch.send(embed=embed, view=AdminVerifyApproveView(interaction.user.id, self.bot))
        
        await interaction.followup.send("✅ 인증 신청이 정상적으로 접수되었습니다.\n관리자가 정보 대조 후 승인해 드립니다.", ephemeral=True)

# 통신사 선택 뷰
class CarrierSelectView(View):
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot
        options = [
            discord.SelectOption(label="SKT 알뜰폰", value="SKT 알뜰폰"),
            discord.SelectOption(label="KT 알뜰폰", value="KT 알뜰폰"),
            discord.SelectOption(label="LGU+ 알뜰폰", value="LGU+ 알뜰폰"),
        ]
        self.select = Select(placeholder="알뜰폰 통신사를 선택하세요", options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(UserDetailModal(self.bot, self.select.values[0]))

class MainCarrierView(View):
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot

    @discord.ui.button(label="SKT", style=discord.ButtonStyle.secondary)
    async def skt(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(UserDetailModal(self.bot, "SKT"))

    @discord.ui.button(label="KT", style=discord.ButtonStyle.secondary)
    async def kt(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(UserDetailModal(self.bot, "KT"))

    @discord.ui.button(label="LGU+", style=discord.ButtonStyle.secondary)
    async def lgu(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(UserDetailModal(self.bot, "LGU+"))

    @discord.ui.button(label="알뜰폰", style=discord.ButtonStyle.primary)
    async def mvno(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(content="**알뜰폰 세부 통신사를 선택해주세요.**", view=CarrierSelectView(self.bot))

# ====== [3. 자판기 메인 메뉴 기능] ======

class ApproveView(View):
    def __init__(self, user_id, amount, bot):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.amount = amount
        self.bot = bot

    @discord.ui.button(label="✅ 승인", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        try:
            async with self.bot.db.acquire() as conn:
                async with conn.transaction():
                    user_data = await conn.fetchrow("""
                        INSERT INTO users (user_id, balance, total_spent) VALUES ($1, $2, $2)
                        ON CONFLICT (user_id) DO UPDATE SET balance = users.balance + EXCLUDED.balance, total_spent = users.total_spent + EXCLUDED.total_spent
                        RETURNING total_spent
                    """, self.user_id, self.amount)
                    await conn.execute("UPDATE deposit_requests SET status='approved' WHERE user_id=$1 AND amount=$2 AND status='pending'", self.user_id, self.amount)
            
            member = interaction.guild.get_member(self.user_id)
            if member: await update_member_rank(member, user_data['total_spent'])
            await interaction.followup.send("✅ 승인 완료", ephemeral=True)
            await interaction.message.delete()
        except Exception as e:
            await interaction.followup.send(f"❌ 오류: {e}", ephemeral=True)

class OTCView(View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary)
    async def charge(self, interaction: discord.Interaction, button: Button):
        modal = Modal(title="💰 충전 신청")
        amt_input = TextInput(label="충전 금액", placeholder="숫자만 입력")
        modal.add_item(amt_input)
        async def on_modal_submit(intact: discord.Interaction):
            await intact.response.defer(ephemeral=True)
            if not amt_input.value.isdigit(): return await intact.followup.send("숫자만 입력하세요!", ephemeral=True)
            async with self.bot.db.acquire() as conn:
                await conn.execute("INSERT INTO deposit_requests (user_id, amount) VALUES ($1, $2)", intact.user.id, int(amt_input.value))
            await intact.followup.send("✅ 신청 완료! 관리자 확인을 기다려주세요.", ephemeral=True)
            log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
            if log_ch: await log_ch.send(f"🔔 **충전 요청**: <@{intact.user.id}>님이 {int(amt_input.value):,}원 요청", view=ApproveView(intact.user.id, int(amt_input.value), self.bot))
        modal.on_submit = on_modal_submit
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="📊 정보", style=discord.ButtonStyle.secondary)
    async def info(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        async with self.bot.db.acquire() as conn:
            user = await conn.fetchrow("SELECT balance, total_spent FROM users WHERE user_id = $1", interaction.user.id)
        bal = user['balance'] if user else 0
        spent = user['total_spent'] if user else 0
        embed = discord.Embed(title=f"👤 {interaction.user.display_name} 정보", color=discord.Color.blue())
        embed.add_field(name="💰 보유 잔액", value=f"**{bal:,.0f}원**", inline=True)
        embed.add_field(name="📈 누적 이용액", value=f"**{spent:,.0f}원**", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

# ====== [4. 봇 클래스 및 메인 로직] ======

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.db = await asyncpg.create_pool(DATABASE_URL)
        async with self.db.acquire() as conn:
            # 테이블 생성
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY, 
                    balance NUMERIC DEFAULT 0, 
                    total_spent NUMERIC DEFAULT 0
                );
            """)
            # ★ 오류 해결 핵심: is_verified 컬럼 강제 추가 ★
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;")
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS deposit_requests (
                    id SERIAL PRIMARY KEY, user_id BIGINT, amount NUMERIC, 
                    status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT NOW()
                );
            """)
        
        await self.tree.sync()
        if not self.update_premium_loop.is_running():
            self.update_premium_loop.start() 
        print("✅ DB 연동 및 시스템 가동 완료")

    @tasks.loop(minutes=1.0)
    async def update_premium_loop(self):
        global current_k_premium, last_update_time, last_otc_message
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.upbit.com/v1/ticker?markets=KRW-BTC") as resp:
                    upbit_p = (await resp.json())[0]['trade_price']
                async with session.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT") as resp:
                    binance_p = float((await resp.json())['price'])
                async with session.get("https://open.er-api.com/v6/latest/USD") as resp:
                    ex_rate = (await resp.json())['rates']['KRW']

            premium = ((upbit_p / (binance_p * ex_rate)) - 1) * 100
            current_k_premium = f"{premium:.2f}%"
            last_update_time = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')

            if last_otc_message:
                try:
                    new_embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
                    new_embed.add_field(name="💰 재고", value=f"```{stock_amount}```", inline=False)
                    new_embed.add_field(name="📈 김프", value=f"```{current_k_premium}```", inline=False)
                    new_embed.add_field(name="🕒 갱신 (KST)", value=f"```{last_update_time}```", inline=False)
                    new_embed.set_footer(text="신속한 대행 | 레제 코인대행")
                    await last_otc_message.edit(embed=new_embed, view=OTCView(self))
                except: last_otc_message = None
        except: pass

bot = MyBot()

async def update_member_rank(member, total_spent):
    target_role_id = 1476788194346274936
    for amount, role_id in sorted(RANKS.items(), reverse=True):
        if total_spent >= amount:
            target_role_id = role_id
            break
    all_rank_ids = list(RANKS.values())
    roles_to_remove = [discord.Object(id=rid) for rid in all_rank_ids if rid != target_role_id and any(r.id == rid for r in member.roles)]
    try:
        if roles_to_remove: await member.remove_roles(*roles_to_remove)
        target_role = member.guild.get_role(target_role_id)
        if target_role: await member.add_roles(target_role)
    except: pass

@bot.tree.command(name="otc", description="자판기 메뉴 호출")
async def otc_slash(interaction: discord.Interaction):
    global last_otc_message
    
    async with bot.db.acquire() as conn:
        user = await conn.fetchrow("SELECT is_verified FROM users WHERE user_id = $1", interaction.user.id)
    
    # 인증 여부 체크
    if not user or not user['is_verified']:
        embed = discord.Embed(title="🔒 본인인증 필요", description="서비스 이용을 위해 통신사 선택 후 인증을 완료해주세요.", color=discord.Color.red())
        return await interaction.response.send_message(embed=embed, view=MainCarrierView(bot), ephemeral=True)

    await interaction.response.defer()
    embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
    embed.add_field(name="💰 재고", value=f"```{stock_amount}```", inline=False)
    embed.add_field(name="📈 김프", value=f"```{current_k_premium}```", inline=False)
    embed.add_field(name="🕒 갱신 (KST)", value=f"```{last_update_time}```", inline=False)
    embed.set_footer(text="신속한 대행 | 레제 코인대행")
    
    msg = await interaction.followup.send(embed=embed, view=OTCView(bot))
    last_otc_message = msg

if TOKEN: bot.run(TOKEN)
