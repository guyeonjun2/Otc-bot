import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import os, asyncpg, aiohttp, re
from datetime import datetime, timedelta

# ====== [1. 기본 설정] ======
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

# 변수 초기화
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
class VerifyModal(Modal):
    def __init__(self, bot, carrier):
        super().__init__(title=f"{carrier} 본인인증")
        self.bot = bot
        self.u_name = TextInput(label="성함", placeholder="실명 입력")
        self.u_phone = TextInput(label="연락처", placeholder="'-' 제외 숫자만")
        self.u_acc = TextInput(label="계좌정보", placeholder="은행명 및 계좌번호")
        for i in [self.u_name, self.u_phone, self.u_acc]: self.add_item(i)

    async def on_submit(self, it: discord.Interaction):
        await it.response.defer(ephemeral=True)
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            embed = discord.Embed(title="🛡️ 본인인증 신청", color=discord.Color.blue())
            embed.add_field(name="신청자", value=it.user.mention)
            embed.add_field(name="정보", value=f"성함: {self.u_name.value}\n번호: {self.u_phone.value}\n계좌: {self.u_acc.value}")
            await log_ch.send(embed=embed, view=VerifyApproveView(it.user.id, self.bot))
        await it.followup.send("✅ 인증 신청 완료! 관리자 승인을 기다려주세요.", ephemeral=True)

class VerifyApproveView(View):
    def __init__(self, uid, bot):
        super().__init__(timeout=None); self.uid = uid; self.bot = bot
    @discord.ui.button(label="✅ 승인", style=discord.ButtonStyle.green)
    async def ok(self, it, btn):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET is_verified = TRUE WHERE user_id = $1", self.uid)
        await it.response.send_message(f"✅ <@{self.uid}> 님 승인 완료", ephemeral=True); await it.message.delete()

class CarrierView(View):
    def __init__(self, bot): super().__init__(timeout=60); self.bot = bot
    @discord.ui.button(label="SKT", style=discord.ButtonStyle.secondary)
    async def s(self, it, b): await it.response.send_modal(VerifyModal(self.bot, "SKT"))
    @discord.ui.button(label="KT", style=discord.ButtonStyle.secondary)
    async def k(self, it, b): await it.response.send_modal(VerifyModal(self.bot, "KT"))
    @discord.ui.button(label="LGU+", style=discord.ButtonStyle.secondary)
    async def l(self, it, b): await it.response.send_modal(VerifyModal(self.bot, "LGU+"))

# ====== [3. 충전 시스템] ======
class ChargeModal(Modal):
    def __init__(self, bot):
        super().__init__(title="💰 충전 신청"); self.bot = bot
        self.sender = TextInput(label="입금자명", placeholder="정확한 성함")
        self.amount = TextInput(label="입금 금액", placeholder="숫자만 입력 (쉼표 제외)")
        self.add_item(self.sender); self.add_item(self.amount)

    async def on_submit(self, it: discord.Interaction):
        await it.response.defer(ephemeral=True) # 3초 타임아웃 방지
        raw = "".join(filter(str.isdigit, self.amount.value))
        if not raw: return await it.followup.send("❌ 숫자만 입력해주세요.", ephemeral=True)
        
        amt, name = int(raw), self.sender.value.strip()
        async with self.bot.db.acquire() as conn:
            rid = await conn.fetchval("INSERT INTO deposit_requests (user_id, sender_name, amount) VALUES ($1, $2, $3) RETURNING id", it.user.id, name, amt)
        
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            embed = discord.Embed(title="💰 충전 신청", color=discord.Color.gold())
            embed.add_field(name="신청자", value=it.user.mention)
            embed.add_field(name="금액", value=f"{amt:,}원 (입금자: {name})")
            await log_ch.send(embed=embed, view=DepositApproveView(rid, it.user.id, amt, self.bot))
        await it.followup.send(f"✅ {amt:,}원 신청 완료! [ {name} ] 성함으로 입금해주세요.", ephemeral=True)

class DepositApproveView(View):
    def __init__(self, rid, uid, amt, bot):
        super().__init__(timeout=None); self.rid=rid; self.uid=uid; self.amt=amt; self.bot=bot
    @discord.ui.button(label="✅ 입금 확인/승인", style=discord.ButtonStyle.green)
    async def ok(self, it, b):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET balance = balance + $1, total_spent = total_spent + $1 WHERE user_id = $2", self.amt, self.uid)
            await conn.execute("UPDATE deposit_requests SET status = 'completed' WHERE id = $1", self.rid)
        await it.response.send_message("✅ 충전 승인 완료", ephemeral=True); await it.message.delete()

# ====== [4. 메인 자판기 뷰] ======
class OTCView(View):
    def __init__(self, bot): super().__init__(timeout=None); self.bot = bot
    
    async def is_v(self, it):
        async with self.bot.db.acquire() as conn:
            u = await conn.fetchrow("SELECT is_verified FROM users WHERE user_id = $1", it.user.id)
        if u and u['is_verified']: return True
        await it.response.send_message("🔒 본인인증이 필요합니다.", view=CarrierView(self.bot), ephemeral=True); return False

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary, row=0)
    async def btn_c(self, it, b):
        if await self.is_v(it): await it.response.send_modal(ChargeModal(self.bot))

    @discord.ui.button(label="📤 송금", style=discord.ButtonStyle.primary, row=0)
    async def btn_t(self, it, b):
        if await self.is_v(it): await it.response.send_message("📤 송금 서비스 점검 중 (관리자 문의)", ephemeral=True)

    @discord.ui.button(label="📊 정보", style=discord.ButtonStyle.secondary, row=1)
    async def btn_i(self, it, b):
        if not await self.is_v(it): return
        async with self.bot.db.acquire() as conn:
            u = await conn.fetchrow("SELECT balance, total_spent FROM users WHERE user_id = $1", it.user.id)
        bal, spent = (u['balance'], u['total_spent']) if u else (0, 0)
        rank = "일반"
        for v, rid in sorted(RANKS.items(), reverse=True):
            if spent >= v:
                role = it.guild.get_role(rid); rank = role.name if role else "등급 미설정"; break
        embed = discord.Embed(title=f"👤 {it.user.name} 님 정보", color=discord.Color.blue())
        embed.add_field(name="잔액", value=f"{bal:,.0f}원"); embed.add_field(name="누적", value=f"{spent:,.0f}원"); embed.add_field(name="등급", value=rank, inline=False)
        await it.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="❓ 도움말", style=discord.ButtonStyle.secondary, row=1)
    async def btn_h(self, it, b):
        await it.response.send_message("🪙 **이용 안내**\n1. 충전 신청 후 성함에 맞춰 입금\n2. 본인인증 완료 후 모든 기능 활성화", ephemeral=True)

# ====== [5. 봇 메인] ======
class MyBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=intents)
    async def setup_hook(self):
        self.db = await asyncpg.create_pool(DATABASE_URL)
        async with self.db.acquire() as conn:
            await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance NUMERIC DEFAULT 0, total_spent NUMERIC DEFAULT 0, is_verified BOOLEAN DEFAULT FALSE);")
            await conn.execute("CREATE TABLE IF NOT EXISTS deposit_requests (id SERIAL PRIMARY KEY, user_id BIGINT, sender_name TEXT, amount NUMERIC, status TEXT DEFAULT 'pending');")
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
                # 요청하신 순서: 재고 -> 김프 -> 갱신
                embed.add_field(name="💰 재고", value=f"```{stock_amount}```", inline=False)
                embed.add_field(name="📈 김프", value=f"```{current_k_premium}```", inline=False)
                embed.add_field(name="🕒 갱신", value=f"```{last_update_time}```", inline=False)
                await last_otc_message.edit(embed=embed, view=OTCView(self))
        except: pass

bot = MyBot()

@bot.tree.command(name="otc")
async def otc(it: discord.Interaction):
    global last_otc_message
    if it.user.id != ADMIN_USER_ID: return
    await it.response.defer()
    embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
    embed.add_field(name="💰 재고", value=f"```{stock_amount}```", inline=False)
    embed.add_field(name="📈 김프", value=f"```{current_k_premium}```", inline=False)
    embed.add_field(name="🕒 갱신", value=f"```{last_update_time}```", inline=False)
    last_otc_message = await it.followup.send(embed=embed, view=OTCView(bot))

if TOKEN: bot.run(TOKEN)
