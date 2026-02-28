import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import os
import asyncpg
import aiohttp
import re
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

# ====== [2. 본인인증 시스템] ======
class UserDetailModal(Modal):
    def __init__(self, bot, carrier):
        super().__init__(title=f"{carrier} 인증 정보 입력"); self.bot = bot
        self.u_name = TextInput(label="이름", placeholder="실명 입력"); self.u_phone = TextInput(label="전화번호", placeholder="'-' 제외 숫자만")
        self.u_bank = TextInput(label="은행명", placeholder="입금하실 은행명"); self.u_account = TextInput(label="계좌번호", placeholder="계좌번호")
        for i in [self.u_name, self.u_phone, self.u_bank, self.u_account]: self.add_item(i)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            embed = discord.Embed(title="🛡️ 본인인증 신청", color=discord.Color.blue())
            embed.add_field(name="신청자", value=interaction.user.mention)
            embed.add_field(name="정보", value=f"{self.u_name.value} / {self.u_phone.value}\n{self.u_bank.value} / {self.u_account.value}")
            await log_ch.send(embed=embed, view=AdminVerifyApproveView(interaction.user.id, self.bot))
        await interaction.followup.send("✅ 인증 신청 완료! 관리자 승인을 기다려주세요.", ephemeral=True)

class AdminVerifyApproveView(View):
    def __init__(self, target_id, bot):
        super().__init__(timeout=None); self.target_id = target_id; self.bot = bot
    @discord.ui.button(label="✅ 승인", style=discord.ButtonStyle.green)
    async def approve(self, interaction, btn):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET is_verified = TRUE WHERE user_id = $1", self.target_id)
        await interaction.response.send_message("✅ 인증 완료", ephemeral=True); await interaction.message.delete()

class MVNOCarrierView(View):
    def __init__(self, bot):
        super().__init__(timeout=60); self.bot = bot
    @discord.ui.button(label="SKT 알뜰", style=discord.ButtonStyle.secondary)
    async def skt_a(self, it, b): await it.response.send_modal(UserDetailModal(self.bot, "SKT 알뜰"))
    @discord.ui.button(label="KT 알뜰", style=discord.ButtonStyle.secondary)
    async def kt_a(self, it, b): await it.response.send_modal(UserDetailModal(self.bot, "KT 알뜰"))
    @discord.ui.button(label="LGU+ 알뜰", style=discord.ButtonStyle.secondary)
    async def lgu_a(self, it, b): await it.response.send_modal(UserDetailModal(self.bot, "LGU+ 알뜰"))

class MainCarrierView(View):
    def __init__(self, bot):
        super().__init__(timeout=60); self.bot = bot
    @discord.ui.button(label="SKT", style=discord.ButtonStyle.secondary)
    async def skt(self, it, b): await it.response.send_modal(UserDetailModal(self.bot, "SKT"))
    @discord.ui.button(label="KT", style=discord.ButtonStyle.secondary)
    async def kt(self, it, b): await it.response.send_modal(UserDetailModal(self.bot, "KT"))
    @discord.ui.button(label="LGU+", style=discord.ButtonStyle.secondary)
    async def lgu(self, it, b): await it.response.send_modal(UserDetailModal(self.bot, "LGU+"))
    @discord.ui.button(label="알뜰폰", style=discord.ButtonStyle.primary)
    async def mvno(self, it, b): await it.response.edit_message(content="알뜰폰 선택", view=MVNOCarrierView(self.bot))

# ====== [3. 충전 시스템] ======
class DepositApproveView(View):
    def __init__(self, request_id, user_id, amount, bot):
        super().__init__(timeout=None)
        self.request_id = request_id; self.user_id = user_id; self.amount = amount; self.bot = bot

    @discord.ui.button(label="✅ 승인", style=discord.ButtonStyle.green)
    async def approve(self, it, btn):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET balance = balance + $1, total_spent = total_spent + $1 WHERE user_id = $2", self.amount, self.user_id)
            await conn.execute("UPDATE deposit_requests SET status = 'completed' WHERE id = $1", self.request_id)
        await it.response.send_message("✅ 승인 완료", ephemeral=True); await it.message.delete()

    @discord.ui.button(label="❌ 거부", style=discord.ButtonStyle.danger)
    async def reject(self, it, btn):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE deposit_requests SET status = 'rejected' WHERE id = $1", self.request_id)
        await it.response.send_message("❌ 거부 완료", ephemeral=True); await it.message.delete()

class ChargeModal(Modal):
    def __init__(self, bot):
        super().__init__(title="💰 충전 신청"); self.bot = bot
        self.u_sender = TextInput(label="입금자명", placeholder="정확한 성함 입력")
        self.u_amount = TextInput(label="입금 금액", placeholder="숫자만 입력")
        self.add_item(self.u_sender); self.add_item(self.u_amount)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            amt = int(re.sub(r'[^0-9]', '', self.u_amount.value))
            sender = self.u_sender.value.strip()
            async with self.bot.db.acquire() as conn:
                req_id = await conn.fetchval("INSERT INTO deposit_requests (user_id, sender_name, amount, status) VALUES ($1, $2, $3, 'pending') RETURNING id", interaction.user.id, sender, amt)
            log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
            if log_ch:
                embed = discord.Embed(title="💰 충전 신청", color=discord.Color.gold())
                embed.add_field(name="신청자", value=interaction.user.mention); embed.add_field(name="입금자", value=sender); embed.add_field(name="금액", value=f"{amt:,}원")
                await log_ch.send(embed=embed, view=DepositApproveView(req_id, interaction.user.id, amt, self.bot))
            await interaction.followup.send(f"✅ {amt:,}원 신청 완료! [ {sender} ] 성함으로 입금해주세요.", ephemeral=True)
        except: await interaction.followup.send("❌ 금액은 숫자만 입력하세요.", ephemeral=True)

# ====== [4. 메인 자판기 View] ======
class OTCView(View):
    def __init__(self, bot):
        super().__init__(timeout=None); self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        async with self.bot.db.acquire() as conn:
            u = await conn.fetchrow("SELECT is_verified FROM users WHERE user_id = $1", interaction.user.id)
        if u and u['is_verified']: return True
        await interaction.response.send_message("🔒 본인인증이 필요합니다.", view=MainCarrierView(self.bot), ephemeral=True)
        return False

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary)
    async def charge(self, it, btn): await it.response.send_modal(ChargeModal(self.bot))

    @discord.ui.button(label="📤 송금", style=discord.ButtonStyle.primary)
    async def transfer(self, it, btn): await it.response.send_message("📤 현재 송금 기능은 점검 중입니다.", ephemeral=True)

    @discord.ui.button(label="📊 정보", style=discord.ButtonStyle.secondary)
    async def info(self, it, btn):
        async with self.bot.db.acquire() as conn:
            u = await conn.fetchrow("SELECT balance, total_spent FROM users WHERE user_id = $1", it.user.id)
        bal, spent = (u['balance'], u['total_spent']) if u else (0, 0)
        rank_name = "일반"
        for amt, r_id in sorted(RANKS.items(), reverse=True):
            if spent >= amt:
                role = it.guild.get_role(r_id); rank_name = role.name if role else "등급 미설정"; break
        embed = discord.Embed(title=f"👤 {it.user.name} 님", color=discord.Color.blue())
        embed.add_field(name="잔액", value=f"{bal:,.0f}원"); embed.add_field(name="누적", value=f"{spent:,.0f}원"); embed.add_field(name="등급", value=rank_name, inline=False)
        await it.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="❓ 도움말", style=discord.ButtonStyle.secondary)
    async def help(self, it, btn):
        msg = "━━━━━━━━━━━━━━━━━━━━\n**🪙 레제 코인대행 이용 안내**\n\n**1. 충전**: 신청 후 입금 시 자동/수동 승인\n**2. 송금**: 준비 중\n**3. 주의**: 24시간 모니터링 중\n━━━━━━━━━━━━━━━━━━━━"
        await it.response.send_message(msg, ephemeral=True)

# ====== [5. 봇 시스템] ======
class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.db = await asyncpg.create_pool(DATABASE_URL)
        async with self.db.acquire() as conn:
            await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance NUMERIC DEFAULT 0, total_spent NUMERIC DEFAULT 0, is_verified BOOLEAN DEFAULT FALSE);")
            await conn.execute("CREATE TABLE IF NOT EXISTS deposit_requests (id SERIAL PRIMARY KEY, user_id BIGINT, sender_name TEXT, amount NUMERIC, status TEXT DEFAULT 'pending');")
            try: await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;")
            except: pass
        await self.tree.sync()
        self.update_premium_loop.start()

    async def on_message(self, message):
        if message.channel.id == LOG_CHANNEL_ID and "[입금알림]" in message.content:
            try:
                amt_m = re.search(r'([0-9,]+)원', message.content)
                name_m = re.search(r'([가-힣]{2,4})', message.content.split("원")[-1])
                if amt_m and name_m:
                    amt, name = int(amt_m.group(1).replace(",", "")), name_m.group(1)
                    async with self.db.acquire() as conn:
                        rec = await conn.fetchrow("SELECT id, user_id FROM deposit_requests WHERE sender_name = $1 AND amount = $2 AND status = 'pending' ORDER BY id ASC LIMIT 1", name, amt)
                        if rec:
                            await conn.execute("UPDATE users SET balance = balance + $1, total_spent = total_spent + $1 WHERE user_id = $2", amt, rec['user_id'])
                            await conn.execute("UPDATE deposit_requests SET status = 'completed' WHERE id = $1", rec['id'])
                            await message.add_reaction("✅")
                            u = await self.fetch_user(rec['user_id']); await u.send(f"✅ {amt:,.0f}원 자동 충전 완료!")
            except: pass
        await self.process_commands(message)

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
                embed.add_field(name="🕒 갱신", value=f"```{last_update_time}```", inline=False)
                await last_otc_message.edit(embed=embed, view=OTCView(self))
        except: pass

bot = MyBot()

@bot.tree.command(name="otc", description="자판기 출력")
async def otc_slash(interaction):
    global last_otc_message
    if interaction.user.id != ADMIN_USER_ID: return await interaction.response.send_message("권한 없음", ephemeral=True)
    await interaction.response.defer()
    embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
    embed.add_field(name="💰 재고", value=f"```{stock_amount}```", inline=False)
    embed.add_field(name="📈 김프", value=f"```{current_k_premium}```", inline=False)
    embed.add_field(name="🕒 갱신", value=f"```{last_update_time}```", inline=False)
    last_otc_message = await interaction.followup.send(embed=embed, view=OTCView(bot))

if TOKEN: bot.run(TOKEN)
