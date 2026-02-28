import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import os, asyncpg, aiohttp, re
from datetime import datetime, timedelta

# ====== [1. 설정] ======
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
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# ====== [2. 본인인증 모달 & 뷰] ======
class UserDetailModal(Modal):
    def __init__(self, bot, carrier):
        super().__init__(title=f"{carrier} 인증 정보"); self.bot = bot
        self.u_name = TextInput(label="이름", placeholder="실명"); self.u_phone = TextInput(label="번호", placeholder="'-' 제외")
        self.u_bank = TextInput(label="은행", placeholder="입금 은행"); self.u_acc = TextInput(label="계좌", placeholder="계좌번호")
        for i in [self.u_name, self.u_phone, self.u_bank, self.u_acc]: self.add_item(i)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
        embed = discord.Embed(title="🛡️ 인증 신청", color=discord.Color.blue())
        embed.add_field(name="유저", value=interaction.user.mention)
        embed.add_field(name="정보", value=f"{self.u_name.value} / {self.u_phone.value}\n{self.u_bank.value} / {self.u_acc.value}")
        await log_ch.send(embed=embed, view=VerifyApproveView(interaction.user.id, self.bot))
        await interaction.followup.send("✅ 인증 신청 완료!", ephemeral=True)

class VerifyApproveView(View):
    def __init__(self, target_id, bot):
        super().__init__(timeout=None); self.target_id = target_id; self.bot = bot
    @discord.ui.button(label="인증 승인", style=discord.ButtonStyle.green)
    async def approve(self, it, btn):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET is_verified = TRUE WHERE user_id = $1", self.target_id)
        await it.response.send_message("✅ 승인됨", ephemeral=True); await it.message.delete()

class CarrierView(View):
    def __init__(self, bot):
        super().__init__(timeout=60); self.bot = bot
    @discord.ui.button(label="SKT", style=discord.ButtonStyle.gray)
    async def skt(self, it, b): await it.response.send_modal(UserDetailModal(self.bot, "SKT"))
    @discord.ui.button(label="KT", style=discord.ButtonStyle.gray)
    async def kt(self, it, b): await it.response.send_modal(UserDetailModal(self.bot, "KT"))
    @discord.ui.button(label="LGU+", style=discord.ButtonStyle.gray)
    async def lgu(self, it, b): await it.response.send_modal(UserDetailModal(self.bot, "LGU+"))

# ====== [3. 충전/정보/도움말/송금 자판기] ======
class ChargeModal(Modal):
    def __init__(self, bot):
        super().__init__(title="💰 충전 신청"); self.bot = bot
        self.u_sender = TextInput(label="입금자명", placeholder="성함"); self.u_amount = TextInput(label="금액", placeholder="숫자만")
        self.add_item(self.u_sender); self.add_item(self.u_amount)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        raw_amt = "".join(filter(str.isdigit, self.u_amount.value))
        if not raw_amt: return await interaction.followup.send("❌ 숫자만 입력하세요.", ephemeral=True)
        amt, sender = int(raw_amt), self.u_sender.value.strip()
        async with self.bot.db.acquire() as conn:
            rid = await conn.fetchval("INSERT INTO deposit_requests (user_id, sender_name, amount) VALUES ($1, $2, $3) RETURNING id", interaction.user.id, sender, amt)
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            embed = discord.Embed(title="💰 충전 신청", color=discord.Color.gold())
            embed.add_field(name="유저", value=interaction.user.mention); embed.add_field(name="입금자", value=sender); embed.add_field(name="금액", value=f"{amt:,}원")
            await log_ch.send(embed=embed, view=DepositApproveView(rid, interaction.user.id, amt, self.bot))
        await interaction.followup.send(f"✅ {amt:,}원 신청 완료!", ephemeral=True)

class DepositApproveView(View):
    def __init__(self, rid, uid, amt, bot):
        super().__init__(timeout=None); self.rid=rid; self.uid=uid; self.amt=amt; self.bot=bot
    @discord.ui.button(label="입금 승인", style=discord.ButtonStyle.green)
    async def ok(self, it, b):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET balance = balance + $1, total_spent = total_spent + $1 WHERE user_id = $2", self.amt, self.uid)
        await it.response.send_message("✅ 승인됨", ephemeral=True); await it.message.delete()

class OTCView(View):
    def __init__(self, bot): super().__init__(timeout=None); self.bot = bot
    
    async def check_v(self, it):
        async with self.bot.db.acquire() as conn:
            u = await conn.fetchrow("SELECT is_verified FROM users WHERE user_id = $1", it.user.id)
        if u and u['is_verified']: return True
        await it.response.send_message("🔒 본인인증이 필요합니다.", view=CarrierView(self.bot), ephemeral=True); return False

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary)
    async def c(self, it, b): 
        if await self.check_v(it): await it.response.send_modal(ChargeModal(self.bot))
    
    @discord.ui.button(label="📤 송금", style=discord.ButtonStyle.primary)
    async def t(self, it, b): 
        if await self.check_v(it): await it.response.send_message("📤 송금 서비스 준비 중", ephemeral=True)

    @discord.ui.button(label="📊 정보", style=discord.ButtonStyle.secondary)
    async def i(self, it, b):
        if not await self.check_v(it): return
        async with self.bot.db.acquire() as conn:
            u = await conn.fetchrow("SELECT balance, total_spent FROM users WHERE user_id = $1", it.user.id)
        bal, spent = (u['balance'], u['total_spent']) if u else (0, 0)
        rank = "일반"
        for v, rid in sorted(RANKS.items(), reverse=True):
            if spent >= v: 
                r = it.guild.get_role(rid); rank = r.name if r else "등급없음"; break
        await it.response.send_message(f"👤 {it.user.name}\n💰 잔액: {bal:,.0f}원\n💎 등급: {rank}", ephemeral=True)

    @discord.ui.button(label="❓ 도움말", style=discord.ButtonStyle.secondary)
    async def h(self, it, b): await it.response.send_message("도움말 내용...", ephemeral=True)

# ====== [4. 봇 메인] ======
class MyBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=intents)
    async def setup_hook(self):
        self.db = await asyncpg.create_pool(DATABASE_URL)
        async with self.db.acquire() as conn:
            await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance NUMERIC DEFAULT 0, total_spent NUMERIC DEFAULT 0, is_verified BOOLEAN DEFAULT FALSE);")
            await conn.execute("CREATE TABLE IF NOT EXISTS deposit_requests (id SERIAL PRIMARY KEY, user_id BIGINT, sender_name TEXT, amount NUMERIC, status TEXT DEFAULT 'pending');")
        await self.tree.sync()

bot = MyBot()
@bot.tree.command(name="otc")
async def otc(it):
    if it.user.id != ADMIN_USER_ID: return
    await it.response.send_message(embed=discord.Embed(title="🪙 레제 코인대행", description="아래 버튼을 이용하세요."), view=OTCView(bot))

if TOKEN: bot.run(TOKEN)
