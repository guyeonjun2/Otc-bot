import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import os, asyncpg, aiohttp, re, asyncio
from datetime import datetime, timedelta

# [설정]
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

# 변수
stock_amount = "현재 자판기 미완성"
current_k_premium = "데이터 수집 중..."
last_otc_message = None 

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# ---------------------------------------------------------
# [관리자 전용: 본인인증 승인/거부 뷰]
# ---------------------------------------------------------
class AdminVerifyView(View):
    def __init__(self, target_id, bot):
        super().__init__(timeout=None); self.target_id = target_id; self.bot = bot

    @discord.ui.button(label="✅ 인증 승인", style=discord.ButtonStyle.green)
    async def approve(self, it, btn):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET is_verified = TRUE WHERE user_id = $1", self.target_id)
        await it.response.send_message("✅ 해당 유저 인증을 승인했습니다.", ephemeral=True)
        await it.message.delete()

    @discord.ui.button(label="❌ 인증 거부", style=discord.ButtonStyle.danger)
    async def reject(self, it, btn):
        await it.response.send_message("❌ 해당 유저 인증을 거부했습니다.", ephemeral=True)
        await it.message.delete()

# ---------------------------------------------------------
# [관리자 전용: 입금 승인/거부 뷰]
# ---------------------------------------------------------
class AdminDepositView(View):
    def __init__(self, rid, uid, amt, bot):
        super().__init__(timeout=None); self.rid=rid; self.uid=uid; self.amt=amt; self.bot=bot

    @discord.ui.button(label="✅ 입금 확인(승인)", style=discord.ButtonStyle.green)
    async def ok(self, it, btn):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET balance = balance + $1, total_spent = total_spent + $1 WHERE user_id = $2", self.amt, self.uid)
            await conn.execute("UPDATE deposit_requests SET status = 'completed' WHERE id = $1", self.rid)
        await it.response.send_message(f"✅ 충전 완료 ({self.amt:,}원)", ephemeral=True)
        await it.message.delete()

    @discord.ui.button(label="❌ 거부", style=discord.ButtonStyle.danger)
    async def no(self, it, btn):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE deposit_requests SET status = 'rejected' WHERE id = $1", self.rid)
        await it.response.send_message("❌ 입금 거부 처리됨", ephemeral=True)
        await it.message.delete()

# ---------------------------------------------------------
# [유저용: 인증 및 충전 모달]
# ---------------------------------------------------------
class UserVerifyModal(Modal):
    def __init__(self, bot, carrier):
        super().__init__(title=f"{carrier} 본인인증"); self.bot = bot
        self.u_name = TextInput(label="성함", placeholder="실명 입력")
        self.u_phone = TextInput(label="연락처", placeholder="'-' 제외")
        self.u_acc = TextInput(label="계좌정보", placeholder="은행 및 계좌번호")
        for i in [self.u_name, self.u_phone, self.u_acc]: self.add_item(i)

    async def on_submit(self, it):
        await it.response.defer(ephemeral=True)
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            embed = discord.Embed(title="🛡️ 본인인증 신청", color=0x3498db)
            embed.add_field(name="신청자", value=it.user.mention)
            embed.add_field(name="정보", value=f"이름: {self.u_name.value}\n번호: {self.u_phone.value}\n계좌: {self.u_acc.value}")
            await log_ch.send(embed=embed, view=AdminVerifyView(it.user.id, self.bot))
        await it.followup.send("✅ 인증 신청이 전송되었습니다. 관리자 승인을 기다려주세요.", ephemeral=True)

class ChargeModal(Modal):
    def __init__(self, bot):
        super().__init__(title="💰 충전 신청"); self.bot = bot
        self.sender = TextInput(label="입금자명", placeholder="성함")
        self.amount = TextInput(label="금액", placeholder="숫자만")
        self.add_item(self.sender); self.add_item(self.amount)

    async def on_submit(self, it):
        await it.response.defer(ephemeral=True)
        num = "".join(filter(str.isdigit, self.amount.value))
        if not num: return await it.followup.send("❌ 숫자만 입력하세요.", ephemeral=True)
        amt, name = int(num), self.sender.value.strip()
        async with self.bot.db.acquire() as conn:
            rid = await conn.fetchval("INSERT INTO deposit_requests (user_id, sender_name, amount) VALUES ($1, $2, $3) RETURNING id", it.user.id, name, amt)
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            embed = discord.Embed(title="💰 충전 신청", color=0xf1c40f)
            embed.add_field(name="신청자", value=it.user.mention); embed.add_field(name="정보", value=f"{name} / {amt:,}원")
            await log_ch.send(embed=embed, view=AdminDepositView(rid, it.user.id, amt, self.bot))
        await it.followup.send(f"✅ {amt:,}원 신청 완료! [ {name} ] 성함으로 입금해주세요.", ephemeral=True)

# ---------------------------------------------------------
# [메인 뷰 및 본인인증 통제]
# ---------------------------------------------------------
class CarrierView(View):
    def __init__(self, bot): super().__init__(timeout=60); self.bot = bot
    @discord.ui.button(label="SKT", style=discord.ButtonStyle.gray)
    async def skt(self, it, b): await it.response.send_modal(UserVerifyModal(self.bot, "SKT"))
    @discord.ui.button(label="KT", style=discord.ButtonStyle.gray)
    async def kt(self, it, b): await it.response.send_modal(UserVerifyModal(self.bot, "KT"))
    @discord.ui.button(label="LGU+", style=discord.ButtonStyle.gray)
    async def lgu(self, it, b): await it.response.send_modal(UserVerifyModal(self.bot, "LGU+"))

class OTCView(View):
    def __init__(self, bot): super().__init__(timeout=None); self.bot = bot
    
    async def auth_check(self, it):
        async with self.bot.db.acquire() as conn:
            verified = await conn.fetchval("SELECT is_verified FROM users WHERE user_id = $1", it.user.id)
        if verified: return True
        await it.response.send_message("🔒 **본인인증 후 이용 가능합니다.**", view=CarrierView(self.bot), ephemeral=True)
        return False

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary, row=0)
    async def btn_charge(self, it, b):
        if await self.auth_check(it): await it.response.send_modal(ChargeModal(self.bot))

    @discord.ui.button(label="📤 송금", style=discord.ButtonStyle.primary, row=0)
    async def btn_send(self, it, b):
        if await self.auth_check(it): await it.response.send_message("📤 송금은 관리자에게 문의바랍니다.", ephemeral=True)

    @discord.ui.button(label="📊 정보", style=discord.ButtonStyle.secondary, row=1)
    async def btn_info(self, it, b):
        if not await self.auth_check(it): return
        async with self.bot.db.acquire() as conn:
            u = await conn.fetchrow("SELECT balance, total_spent FROM users WHERE user_id = $1", it.user.id)
        bal, spent = (u['balance'], u['total_spent']) if u else (0, 0)
        rank = "일반"
        for v, rid in sorted(RANKS.items(), reverse=True):
            if spent >= v:
                role = it.guild.get_role(rid); rank = role.name if role else "등급 미설정"; break
        await it.response.send_message(f"👤 **{it.user.name}**\n잔액: {bal:,.0f}원 | 누적: {spent:,.0f}원 | 등급: {rank}", ephemeral=True)

    @discord.ui.button(label="❓ 도움말", style=discord.ButtonStyle.secondary, row=1)
    async def btn_help(self, it, b):
        await it.response.send_message("🪙 **레제 OTC 이용안내**\n1. 본인인증 승인 대기\n2. 승인 후 충전 신청 및 입금\n3. 정보 확인", ephemeral=True)

# ---------------------------------------------------------
# [봇 코어]
# ---------------------------------------------------------
class MyBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=intents)
    async def setup_hook(self):
        self.db = await asyncpg.create_pool(DATABASE_URL)
        async with self.db.acquire() as conn:
            await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance NUMERIC DEFAULT 0, total_spent NUMERIC DEFAULT 0, is_verified BOOLEAN DEFAULT FALSE);")
            await conn.execute("CREATE TABLE IF NOT EXISTS deposit_requests (id SERIAL PRIMARY KEY, user_id BIGINT, sender_name TEXT, amount NUMERIC, status TEXT DEFAULT 'pending');")
        await self.tree.sync()
        self.update_info.start()

    @tasks.loop(minutes=1.0)
    async def update_info(self):
        global current_k_premium, last_otc_message
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get("https://api.upbit.com/v1/ticker?markets=KRW-BTC") as r: up = (await r.json())[0]['trade_price']
                async with s.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT") as r: bi = float((await r.json())['price'])
                async with s.get("https://open.er-api.com/v6/latest/USD") as r: ex = (await r.json())['rates']['KRW']
            current_k_premium = f"{((up / (bi * ex)) - 1) * 100:.2f}%"
            if last_otc_message:
                embed = discord.Embed(title="🪙 레제 코인대행", color=0x2ecc71)
                embed.add_field(name="💰 재고", value=f"```{stock_amount}```", inline=False)
                embed.add_field(name="📈 김프", value=f"```{current_k_premium}```", inline=False)
                embed.add_field(name="🕒 갱신", value=f"```{datetime.now().strftime('%H:%M:%S')}```", inline=False)
                await last_otc_message.edit(embed=embed, view=OTCView(self))
        except: pass

bot = MyBot()
@bot.tree.command(name="otc")
async def otc(it):
    global last_otc_message
    if it.user.id != ADMIN_USER_ID: return
    await it.response.defer()
    embed = discord.Embed(title="🪙 레제 코인대행", color=0x2ecc71)
    embed.add_field(name="💰 재고", value=f"```{stock_amount}```", inline=False)
    embed.add_field(name="📈 김프", value=f"```{current_k_premium}```", inline=False)
    embed.add_field(name="🕒 갱신", value=f"```대기 중```", inline=False)
    last_otc_message = await it.followup.send(embed=embed, view=OTCView(bot))

if TOKEN: bot.run(TOKEN)
