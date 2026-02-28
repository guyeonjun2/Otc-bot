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

# 등급 설정
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

# ====== [2. 충전 승인/거부 View] ======
class DepositApproveView(View):
    def __init__(self, request_id, user_id, amount, bot):
        super().__init__(timeout=None)
        self.request_id = request_id; self.user_id = user_id; self.amount = amount; self.bot = bot

    @discord.ui.button(label="✅ 승인", style=discord.ButtonStyle.green)
    async def approve(self, interaction, button):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET balance = balance + $1, total_spent = total_spent + $1 WHERE user_id = $2", self.amount, self.user_id)
            await conn.execute("UPDATE deposit_requests SET status = 'completed' WHERE id = $1", self.request_id)
        await interaction.response.send_message(f"✅ 승인 완료", ephemeral=True)
        try:
            user = await self.bot.fetch_user(self.user_id)
            await user.send(f"💰 **충전 완료:** {self.amount:,}원이 지급되었습니다.")
        except: pass
        await interaction.message.delete()

    @discord.ui.button(label="❌ 거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction, button):
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE deposit_requests SET status = 'rejected' WHERE id = $1", self.request_id)
        await interaction.response.send_message("❌ 거부 처리됨.", ephemeral=True)
        await interaction.message.delete()

# ====== [3. 충전 신청 모달 (입력 오류 수정)] ======
class ChargeModal(Modal):
    def __init__(self, bot):
        super().__init__(title="💰 충전 신청"); self.bot = bot
        self.u_sender = TextInput(label="입금자명", placeholder="정확한 성함 입력")
        self.u_amount = TextInput(label="입금 금액", placeholder="숫자만 입력 (예: 50000)")
        self.add_item(self.u_sender); self.add_item(self.u_amount)

    async def on_submit(self, interaction: discord.Interaction):
        # 숫자 추출 로직 강화 (공백이나 '원' 같은 문자 제거)
        raw_amt = re.sub(r'[^0-9]', '', self.u_amount.value)
        if not raw_amt:
            return await interaction.response.send_message("❌ 금액은 숫자만 입력해주세요.", ephemeral=True)
        
        amt = int(raw_amt)
        sender = self.u_sender.value.strip()

        async with self.bot.db.acquire() as conn:
            req_id = await conn.fetchval("INSERT INTO deposit_requests (user_id, sender_name, amount, status) VALUES ($1, $2, $3, 'pending') RETURNING id", interaction.user.id, sender, amt)
        
        log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            embed = discord.Embed(title="💰 충전 신청 접수", color=discord.Color.gold())
            embed.add_field(name="입금자명", value=sender, inline=True)
            embed.add_field(name="신청금액", value=f"{amt:,}원", inline=True)
            embed.set_footer(text=f"신청자 ID: {interaction.user.id}")
            await log_ch.send(embed=embed, view=DepositApproveView(req_id, interaction.user.id, amt, self.bot))
        
        await interaction.response.send_message(f"✅ {amt:,}원 신청 완료! 성함 [ {sender} ](으)로 입금해주세요.", ephemeral=True)

# ====== [4. 자판기 메인 (버튼 4개 복구)] ======
class OTCView(View):
    def __init__(self, bot):
        super().__init__(timeout=None); self.bot = bot

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary)
    async def charge(self, interaction, btn):
        await interaction.response.send_modal(ChargeModal(self.bot))

    @discord.ui.button(label="📤 송금", style=discord.ButtonStyle.primary)
    async def transfer(self, interaction, btn):
        await interaction.response.send_message("📤 현재 송금 기능은 준비 중입니다. 관리자에게 문의하세요.", ephemeral=True)

    @discord.ui.button(label="📊 정보", style=discord.ButtonStyle.secondary)
    async def info(self, interaction, btn):
        async with self.bot.db.acquire() as conn:
            u = await conn.fetchrow("SELECT balance, total_spent FROM users WHERE user_id = $1", interaction.user.id)
        bal = u['balance'] if u else 0; spent = u['total_spent'] if u else 0
        
        # 등급 계산
        current_rank = "일반"
        for amt, r_id in sorted(RANKS.items(), reverse=True):
            if spent >= amt:
                role = interaction.guild.get_role(r_id)
                current_rank = role.name if role else "등급 미설정"
                break

        embed = discord.Embed(title=f"👤 {interaction.user.name} 님 정보", color=discord.Color.blue())
        embed.add_field(name="💰 잔액", value=f"**{bal:,.0f}원**", inline=True)
        embed.add_field(name="📈 누적", value=f"**{spent:,.0f}원**", inline=True)
        embed.add_field(name="💎 등급", value=f"**{current_rank}**", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="❓ 도움말", style=discord.ButtonStyle.secondary)
    async def help(self, interaction, btn):
        help_text = (
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
        await interaction.response.send_message(help_text, ephemeral=True)

# ====== [5. 봇 메인 (자동충전 인식 포함)] ======
class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.db = await asyncpg.create_pool(DATABASE_URL)
        async with self.db.acquire() as conn:
            await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance NUMERIC DEFAULT 0, total_spent NUMERIC DEFAULT 0);")
            await conn.execute("CREATE TABLE IF NOT EXISTS deposit_requests (id SERIAL PRIMARY KEY, user_id BIGINT, sender_name TEXT, amount NUMERIC, status TEXT DEFAULT 'pending');")
        await self.tree.sync()
        self.update_premium_loop.start()

    async def on_message(self, message):
        if message.channel.id == LOG_CHANNEL_ID and "[입금알림]" in message.content:
            try:
                amt_m = re.search(r'([0-9,]+)원', message.content)
                name_m = re.search(r'([가-힣]{2,4})', message.content.split("원")[-1])
                if amt_m and name_m:
                    amt = int(amt_m.group(1).replace(",", "")); name = name_m.group(1)
                    async with self.db.acquire() as conn:
                        rec = await conn.fetchrow("SELECT id, user_id FROM deposit_requests WHERE sender_name = $1 AND amount = $2 AND status = 'pending' ORDER BY id ASC LIMIT 1", name, amt)
                        if rec:
                            await conn.execute("UPDATE users SET balance = balance + $1, total_spent = total_spent + $1 WHERE user_id = $2", amt, rec['user_id'])
                            await conn.execute("UPDATE deposit_requests SET status = 'completed' WHERE id = $1", rec['id'])
                            await message.add_reaction("✅")
                            try:
                                u = await self.fetch_user(rec['user_id'])
                                await u.send(f"✅ 입금 자동 확인! **{amt:,.0f}원** 충전 완료.")
                            except: pass
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

if TOKEN: bot.run(TOKEN)
