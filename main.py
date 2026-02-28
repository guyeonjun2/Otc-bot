import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
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

# 전역 변수
stock_amount = "현재 자판기 미완성"
current_k_premium = "데이터 수집 중..."
last_update_time = "대기 중"
last_otc_message = None  # 가장 최근에 보낸 /otc 메시지를 저장할 변수

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 

def get_kst_now():
    return datetime.utcnow() + timedelta(hours=9)

# ====== [2. 뷰 클래스] ======
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
                        INSERT INTO users (user_id, balance, total_spent) VALUES ($1, $2::numeric, $2::numeric)
                        ON CONFLICT (user_id) DO UPDATE SET balance = users.balance + EXCLUDED.balance, total_spent = users.total_spent + EXCLUDED.total_spent
                        RETURNING total_spent, balance
                    """, self.user_id, self.amount)
                    await conn.execute("UPDATE deposit_requests SET status='approved' WHERE user_id=$1 AND amount=$2::numeric AND status='pending'", self.user_id, self.amount)
            
            member = interaction.guild.get_member(self.user_id)
            if member:
                # update_member_rank 함수는 별도로 정의하거나 클래스 메서드로 포함
                await update_member_rank(member, user_data['total_spent'])
                try: await member.send(f"💰 **{self.amount:,.0f}원** 충전 완료!")
                except: pass
            await interaction.followup.send("승인 완료", ephemeral=True)
            await interaction.message.delete()
        except Exception as e:
            await interaction.followup.send(f"오류: {e}", ephemeral=True)

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
            if not amt_input.value.isdigit(): return await intact.followup.send("숫자만 입력!", ephemeral=True)
            async with self.bot.db.acquire() as conn:
                await conn.execute("INSERT INTO deposit_requests (user_id, amount) VALUES ($1, $2::numeric)", intact.user.id, int(amt_input.value))
            await intact.followup.send("✅ 신청 완료!", ephemeral=True)
            log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
            if log_ch: await log_ch.send(f"🔔 요청: <@{intact.user.id}> {int(amt_input.value):,}원", view=ApproveView(intact.user.id, int(amt_input.value), self.bot))
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
        embed.add_field(name="💰 잔액", value=f"{bal:,.0f}원")
        await interaction.followup.send(embed=embed, ephemeral=True)

# ====== [3. 봇 클래스] ======
class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.db = await asyncpg.create_pool(DATABASE_URL)
        await self.tree.sync()
        self.update_premium_loop.start()
        print("✅ 시스템 가동 및 자동 갱신 시작")

    @tasks.loop(minutes=1.0)
    async def update_premium_loop(self):
        global current_k_premium, last_update_time, last_otc_message
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.upbit.com/v1/ticker?markets=KRW-BTC", timeout=5) as resp:
                    upbit_p = (await resp.json())[0]['trade_price']
                async with session.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5) as resp:
                    binance_p = float((await resp.json())['price'])
                async with session.get("https://open.er-api.com/v6/latest/USD", timeout=5) as resp:
                    ex_rate = (await resp.json())['rates']['KRW']

            premium = ((upbit_p / (binance_p * ex_rate)) - 1) * 100
            current_k_premium = f"{premium:.2f}%"
            last_update_time = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')

            # [핵심] 기존에 보낸 메시지가 있다면 자동으로 수정
            if last_otc_message:
                try:
                    new_embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
                    new_embed.add_field(name="💰 재고", value=f"```{stock_amount}```", inline=False)
                    new_embed.add_field(name="📈 김프", value=f"```{current_k_premium}```", inline=False)
                    new_embed.add_field(name="🕒 갱신 (KST)", value=f"```{last_update_time}```", inline=False)
                    new_embed.set_footer(text="신속한 대행 | 레제 코인대행")
                    await last_otc_message.edit(embed=new_embed)
                except: last_otc_message = None # 메시지가 삭제된 경우 대비
        except Exception as e: print(f"갱신 에러: {e}")

bot = MyBot()

async def update_member_rank(member, total_spent):
    target_role_id = 1476788194346274936
    for amount, role_id in sorted(RANKS.items(), reverse=True):
        if total_spent >= amount:
            target_role_id = role_id
            break
    roles_to_remove = [discord.Object(id=rid) for rid in RANKS.values() if rid != target_role_id]
    try:
        await member.remove_roles(*roles_to_remove)
        await member.add_roles(discord.Object(id=target_role_id))
    except: pass

@bot.tree.command(name="otc", description="메뉴 호출")
async def otc_slash(interaction: discord.Interaction):
    global last_otc_message
    await interaction.response.defer()
    embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
    embed.add_field(name="💰 재고", value=f"```{stock_amount}```", inline=False)
    embed.add_field(name="📈 김프", value=f"```{current_k_premium}```", inline=False)
    embed.add_field(name="🕒 갱신 (KST)", value=f"```{last_update_time}```", inline=False)
    embed.set_footer(text="신속한 대행 | 레제 코인대행")
    
    msg = await interaction.followup.send(embed=embed, view=OTCView(bot))
    last_otc_message = msg # 최근 메시지로 등록

if TOKEN: bot.run(TOKEN)
