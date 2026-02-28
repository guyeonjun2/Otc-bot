import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import os, asyncpg, aiohttp, re
from datetime import datetime, timedelta

# ====== [1. 설정] ======
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_USER_ID = 1472930278874939445
LOG_CHANNEL_ID = 1476976182523068478  # 로그 채널 ID 확인 필수

# 등급 역할 ID
RANKS = {
    50000000: 1476788776658534501, 10000000: 1476788690696011868, 
    3000000: 1476788607569104946, 1000000: 1476788508076146689,  
    500000: 1476788430850752532, 300000: 1476788381940973741,   
    100000: 1476788291448865019, 0: 1476788194346274936         
}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# ====== [2. 충전 승인 뷰] ======
class DepositApproveView(View):
    def __init__(self, rid, uid, amt, bot):
        super().__init__(timeout=None); self.rid=rid; self.uid=uid; self.amt=amt; self.bot=bot
    @discord.ui.button(label="✅ 입금 승인", style=discord.ButtonStyle.green)
    async def ok(self, it, b):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET balance = balance + $1, total_spent = total_spent + $1 WHERE user_id = $2", self.amt, self.uid)
            await conn.execute("UPDATE deposit_requests SET status = 'completed' WHERE id = $1", self.rid)
        await it.response.send_message(f"✅ <@{self.uid}> 님 충전 승인 완료", ephemeral=True); await it.message.delete()

# ====== [3. 충전 신청 모달 (핵심 수정)] ======
class ChargeModal(Modal):
    def __init__(self, bot):
        super().__init__(title="💰 충전 신청"); self.bot = bot
        self.u_sender = TextInput(label="입금자명", placeholder="입금하실 성함", min_length=2)
        self.u_amount = TextInput(label="입금 금액", placeholder="숫자만 입력 (예: 50000)")
        self.add_item(self.u_sender); self.add_item(self.u_amount)

    async def on_submit(self, interaction):
        # 1. 즉시 응답 지연 (이게 없으면 3초 뒤 무반응 에러남)
        await interaction.response.defer(ephemeral=True)
        
        try:
            # 2. 숫자만 추출
            raw_amt = "".join(filter(str.isdigit, self.u_amount.value))
            if not raw_amt: return await interaction.followup.send("❌ 금액은 숫자만 입력해주세요.", ephemeral=True)
            amt, sender = int(raw_amt), self.u_sender.value.strip()

            # 3. DB 저장
            async with self.bot.db.acquire() as conn:
                rid = await conn.fetchval("INSERT INTO deposit_requests (user_id, sender_name, amount) VALUES ($1, $2, $3) RETURNING id", interaction.user.id, sender, amt)

            # 4. 로그 채널 알림 (실패해도 유저 알림은 가도록 구성)
            log_ch = self.bot.get_channel(LOG_CHANNEL_ID) or await self.bot.fetch_channel(LOG_CHANNEL_ID)
            if log_ch:
                embed = discord.Embed(title="💰 새로운 충전 신청", color=discord.Color.gold())
                embed.add_field(name="신청자", value=interaction.user.mention)
                embed.add_field(name="입금자", value=sender)
                embed.add_field(name="금액", value=f"{amt:,}원")
                await log_ch.send(embed=embed, view=DepositApproveView(rid, interaction.user.id, amt, self.bot))
            
            # 5. 유저에게 최종 응답
            await interaction.followup.send(f"✅ {amt:,}원 신청 완료!\n[ {sender} ] 성함으로 입금해주세요.", ephemeral=True)

        except Exception as e:
            print(f"❌ 전송 에러 발생: {e}") # 터미널에 에러 찍힘
            await interaction.followup.send(f"❌ 오류가 발생했습니다. 관리자에게 문의하세요.\n(에러: {e})", ephemeral=True)

# ====== [4. 본인인증 & 메인 자판기] ======
class UserDetailModal(Modal):
    def __init__(self, bot, carrier):
        super().__init__(title=f"{carrier} 인증 정보"); self.bot = bot
        self.u_name = TextInput(label="이름", placeholder="실명"); self.u_phone = TextInput(label="번호", placeholder="'-' 제외")
        self.u_bank = TextInput(label="은행", placeholder="은행명"); self.u_acc = TextInput(label="계좌", placeholder="계좌번호")
        for i in [self.u_name, self.u_phone, self.u_bank, self.u_acc]: self.add_item(i)

    async def on_submit(self, it):
        await it.response.defer(ephemeral=True)
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID) or await self.bot.fetch_channel(LOG_CHANNEL_ID)
        if log_ch:
            embed = discord.Embed(title="🛡️ 본인인증 신청", color=discord.Color.blue())
            embed.add_field(name="유저", value=it.user.mention)
            embed.add_field(name="정보", value=f"{self.u_name.value} / {self.u_phone.value}\n{self.u_bank.value} / {self.u_acc.value}")
            await log_ch.send(embed=embed) # 관리자가 수동 승인하거나 DB 업데이트 필요
        await it.followup.send("✅ 인증 신청 완료!", ephemeral=True)

class CarrierView(View):
    def __init__(self, bot): super().__init__(timeout=60); self.bot = bot
    @discord.ui.button(label="SKT", style=discord.ButtonStyle.gray)
    async def skt(self, it, b): await it.response.send_modal(UserDetailModal(self.bot, "SKT"))
    @discord.ui.button(label="KT", style=discord.ButtonStyle.gray)
    async def kt(self, it, b): await it.response.send_modal(UserDetailModal(self.bot, "KT"))
    @discord.ui.button(label="LGU+", style=discord.ButtonStyle.gray)
    async def lgu(self, it, b): await it.response.send_modal(UserDetailModal(self.bot, "LGU+"))

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
        if await self.check_v(it): await it.response.send_message("📤 송금 서비스 점검 중 (관리자 문의)", ephemeral=True)

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
    async def h(self, it, b): await it.response.send_message("1. 충전: 무통장 입금\n2. 송금: 코인 전송\n3. 본인인증 필수", ephemeral=True)

# ====== [5. 봇 시작] ======
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
    await it.response.send_message(embed=discord.Embed(title="🪙 레제 코인대행", description="원하시는 메뉴를 선택하세요."), view=OTCView(bot))

if TOKEN: bot.run(TOKEN)
