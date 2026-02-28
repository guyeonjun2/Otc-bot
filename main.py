import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import os, asyncpg, aiohttp, re
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

# ====== [2. 본인인증 관리 시스템 (승인/거부)] ======
class AdminVerifyView(View):
    def __init__(self, target_id, bot):
        super().__init__(timeout=None)
        self.target_id = target_id
        self.bot = bot

    @discord.ui.button(label="✅ 인증 승인", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: Button):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET is_verified = TRUE WHERE user_id = $1", self.target_id)
        await interaction.response.send_message(f"✅ <@{self.target_id}> 님 인증 승인 완료", ephemeral=True)
        try:
            user = await self.bot.fetch_user(self.target_id)
            await user.send("🛡️ **본인인증 완료:** 이제 자판기의 모든 기능을 이용하실 수 있습니다!")
        except: pass
        await interaction.message.delete()

    @discord.ui.button(label="❌ 인증 거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(f"❌ <@{self.target_id}> 님 인증 거부 처리", ephemeral=True)
        try:
            user = await self.bot.fetch_user(self.target_id)
            await user.send("🛡️ **본인인증 거부:** 입력하신 정보가 부정확합니다. 다시 시도해주세요.")
        except: pass
        await interaction.message.delete()

class UserVerifyModal(Modal):
    def __init__(self, bot, carrier):
        super().__init__(title=f"{carrier} 본인인증 정보 입력")
        self.bot = bot
        self.u_name = TextInput(label="성함", placeholder="실명 입력")
        self.u_phone = TextInput(label="연락처", placeholder="'-' 제외 숫자만")
        self.u_bank = TextInput(label="은행명", placeholder="입금 은행")
        self.u_acc = TextInput(label="계좌번호", placeholder="계좌번호")
        for i in [self.u_name, self.u_phone, self.u_bank, self.u_acc]: self.add_item(i)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            embed = discord.Embed(title="🛡️ 본인인증 신청 접수", color=discord.Color.blue())
            embed.add_field(name="신청자", value=interaction.user.mention, inline=True)
            embed.add_field(name="정보", value=f"이름: {self.u_name.value}\n번호: {self.u_phone.value}\n은행: {self.u_bank.value}\n계좌: {self.u_acc.value}", inline=False)
            await log_ch.send(embed=embed, view=AdminVerifyView(interaction.user.id, self.bot))
        await interaction.followup.send("✅ 인증 신청이 완료되었습니다. 관리자 승인을 기다려주세요.", ephemeral=True)

class CarrierSelectView(View):
    def __init__(self, bot): super().__init__(timeout=60); self.bot = bot
    @discord.ui.button(label="SKT", style=discord.ButtonStyle.secondary)
    async def skt(self, it, b): await it.response.send_modal(UserVerifyModal(self.bot, "SKT"))
    @discord.ui.button(label="KT", style=discord.ButtonStyle.secondary)
    async def kt(self, it, b): await it.response.send_modal(UserVerifyModal(self.bot, "KT"))
    @discord.ui.button(label="LGU+", style=discord.ButtonStyle.secondary)
    async def lgu(self, it, b): await it.response.send_modal(UserVerifyModal(self.bot, "LGU+"))

# ====== [3. 충전 시스템 (승인/거부)] ======
class AdminDepositView(View):
    def __init__(self, rid, uid, amt, bot):
        super().__init__(timeout=None); self.rid=rid; self.uid=uid; self.amt=amt; self.bot=bot
    
    @discord.ui.button(label="✅ 입금 승인", style=discord.ButtonStyle.green)
    async def ok(self, it, b):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET balance = balance + $1, total_spent = total_spent + $1 WHERE user_id = $2", self.amt, self.uid)
            await conn.execute("UPDATE deposit_requests SET status = 'completed' WHERE id = $1", self.rid)
        await it.response.send_message("✅ 충전 승인 완료", ephemeral=True)
        await it.message.delete()

    @discord.ui.button(label="❌ 입금 거부", style=discord.ButtonStyle.danger)
    async def no(self, it, b):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE deposit_requests SET status = 'rejected' WHERE id = $1", self.rid)
        await it.response.send_message("❌ 충전 거부 완료", ephemeral=True)
        await it.message.delete()

class ChargeModal(Modal):
    def __init__(self, bot):
        super().__init__(title="💰 충전 신청"); self.bot = bot
        self.sender = TextInput(label="입금자명", placeholder="정확한 성함")
        self.amount = TextInput(label="입금 금액", placeholder="숫자만 입력")
        self.add_item(self.sender); self.add_item(self.amount)

    async def on_submit(self, it: discord.Interaction):
        await it.response.defer(ephemeral=True)
        num = "".join(filter(str.isdigit, self.amount.value))
        if not num: return await it.followup.send("❌ 숫자만 입력하세요.", ephemeral=True)
        amt, name = int(num), self.sender.value.strip()
        async with self.bot.db.acquire() as conn:
            rid = await conn.fetchval("INSERT INTO deposit_requests (user_id, sender_name, amount) VALUES ($1, $2, $3) RETURNING id", it.user.id, name, amt)
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            embed = discord.Embed(title="💰 충전 신청 알림", color=discord.Color.gold())
            embed.add_field(name="신청자", value=it.user.mention); embed.add_field(name="입금자", value=name); embed.add_field(name="금액", value=f"{amt:,}원")
            await log_ch.send(embed=embed, view=AdminDepositView(rid, it.user.id, amt, self.bot))
        await it.followup.send(f"✅ {amt:,}원 신청 완료! [ {name} ] 성함으로 입금해주세요.", ephemeral=True)

# ====== [4. 메인 자판기 뷰] ======
class OTCView(View):
    def __init__(self, bot): super().__init__(timeout=None); self.bot = bot
    
    async def check_verify(self, it):
        async with self.bot.db.acquire() as conn:
            u = await conn.fetchrow("SELECT is_verified FROM users WHERE user_id = $1", it.user.id)
        if u and u['is_verified']: return True
        await it.response.send_message("🔒 **본인인증 후 이용 가능합니다.**\n아래 버튼을 눌러 인증을 진행해주세요.", view=CarrierSelectView(self.bot), ephemeral=True)
        return False

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary, row=0)
    async def c(self, it, b): 
        if await self.check_verify(it): await it.response.send_modal(ChargeModal(self.bot))

    @discord.ui.button(label="📤 송금", style=discord.ButtonStyle.primary, row=0)
    async def t(self, it, b): 
        if await self.check_verify(it): await it.response.send_message("📤 송금 서비스 점검 중입니다.", ephemeral=True)

    @discord.ui.button(label="📊 정보", style=discord.ButtonStyle.secondary, row=1)
    async def i(self, it, b):
        if not await self.check_verify(it): return
        async with self.bot.db.acquire() as conn:
            u = await conn.fetchrow("SELECT balance, total_spent FROM users WHERE user_id = $1", it.user.id)
        bal, spent = (u['balance'], u['total_spent']) if u else (0, 0)
        rank = "일반"
        for v, rid in sorted(RANKS.items(), reverse=True):
            if spent >= v:
                r = it.guild.get_role(rid); rank = r.name if r else "등급 미설정"; break
        embed = discord.Embed(title=f"👤 {it.user.name} 님 정보", color=discord.Color.blue())
        embed.add_field(name="잔액", value=f"{bal:,.0f}원"); embed.add_field(name="누적", value=f"{spent:,.0f}원"); embed.add_field(name="등급", value=rank, inline=False)
        await it.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="❓ 도움말", style=discord.ButtonStyle.secondary, row=1)
    async def h(self, it, b):
        await it.response.send_message("🪙 **레제 코인대행**\n1. 본인인증 승인 후 충전 가능\n2. 입금자명 미일치 시 충전 지연", ephemeral=True)

# ====== [5. 봇 시작] ======
class MyBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=intents)
    async def setup_hook(self):
        self.db = await asyncpg.create_pool(DATABASE_URL)
        async with self.db.acquire() as conn:
            await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance NUMERIC DEFAULT 0, total_spent NUMERIC DEFAULT 0, is_verified BOOLEAN DEFAULT FALSE);")
            await conn.execute("CREATE TABLE IF NOT EXISTS deposit_requests (id SERIAL PRIMARY KEY, user_id BIGINT, sender_name TEXT, amount NUMERIC, status TEXT DEFAULT 'pending');")
        await self.tree.sync()
        self.update_loop.start()

    @tasks.loop(minutes=1.0)
    async def update_loop(self):
        global current_k_premium, last_update_time, last_otc_message
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get("https://api.upbit.com/v1/ticker?markets=KRW-BTC") as r: up = (await r.json())[0]['trade_price']
                async with s.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT") as r: bi = float((await r.json())['price'])
                async with s.get("https://open.er-api.com/v6/latest/USD") as r: ex = (await r.json())['rates']['KRW']
            current_k_premium = f"{((up / (bi * ex)) - 1) * 100:.2f}%"
            last_update_time = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
            if last_otc_message:
                embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
                embed.add_field(name="💰 재고", value=f"```{stock_amount}```", inline=False)
                embed.add_field(name="📈 김프", value=f"```{current_k_premium}```", inline=False)
                embed.add_field(name="🕒 갱신", value=f"```{last_update_time}```", inline=False)
                await last_otc_message.edit(embed=embed, view=OTCView(self))
        except: pass

bot = MyBot()
@bot.tree.command(name="otc")
async def otc(it):
    global last_otc_message
    if it.user.id != ADMIN_USER_ID: return
    await it.response.defer()
    embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
    embed.add_field(name="💰 재고", value=f"```{stock_amount}```", inline=False)
    embed.add_field(name="📈 김프", value=f"```{current_k_premium}```", inline=False)
    embed.add_field(name="🕒 갱신", value=f"```{last_update_time}```", inline=False)
    last_otc_message = await it.followup.send(embed=embed, view=OTCView(bot))

if TOKEN: bot.run(TOKEN)
