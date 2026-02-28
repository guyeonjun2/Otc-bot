import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import os
import asyncpg
import aiohttp
from datetime import datetime

# ====== [1. 설정 및 ID] ======
TOKEN = os.getenv("TOKEN")
DATABASE_URL = "postgresql://postgres:ftdLqBhVQzpuEqKhtwUILzuOepuOoMGG@centerbeam.proxy.rlwy.net:30872/railway"

ADMIN_USER_ID = 1472930278874939445
LOG_CHANNEL_ID = 1476976182523068478

RANKS = {
    50000000: 1476788776658534501, 10000000: 1476788690696011868, 
    3000000: 1476788607569104946, 1000000: 1476788508076146689,  
    500000: 1476788430850752532, 300000: 1476788381940973741,   
    100000: 1476788291448865019, 0: 1476788194346274936         
}

# 전역 변수 초기화
stock_amount = "현재 자판기 미완성"
current_k_premium = "데이터 수집 중..."
last_update_time = "대기 중"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # DB 연결
        self.db = await asyncpg.create_pool(DATABASE_URL)
        async with self.db.acquire() as conn:
            await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance NUMERIC DEFAULT 0, total_spent NUMERIC DEFAULT 0);")
            await conn.execute("CREATE TABLE IF NOT EXISTS deposit_requests (id SERIAL PRIMARY KEY, user_id BIGINT, amount NUMERIC, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT NOW());")
        
        await self.tree.sync()
        # [중요] 루프 시작
        if not self.update_premium_loop.is_running():
            self.update_premium_loop.start() 
        print("✅ 모든 시스템 정상 가동 및 루프 시작")

    # ====== [실시간 김프 계산 루프] ======
    @tasks.loop(minutes=1.0)
    async def update_premium_loop(self):
        global current_k_premium, last_update_time
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.upbit.com/v1/ticker?markets=KRW-BTC", timeout=10) as resp:
                    upbit_data = await resp.json()
                    upbit_p = upbit_data[0]['trade_price']
                async with session.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=10) as resp:
                    binance_data = await resp.json()
                    binance_p = float(binance_data['price'])
                async with session.get("https://open.er-api.com/v6/latest/USD", timeout=10) as resp:
                    ex_data = await resp.json()
                    ex_rate = ex_data['rates']['KRW']

                premium = ((upbit_p / (binance_p * ex_rate)) - 1) * 100
                current_k_premium = f"{premium:.2f}%"
                last_update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            print(f"⚠️ 시세 업데이트 실패: {e}")

bot = MyBot()

# --- 이하 View 및 로직 생략 (기존 코드와 동일하게 유지하세요) ---
# (ApproveView, OTCView, update_member_rank 함수들)

@bot.tree.command(name="otc", description="메뉴 호출")
async def otc_slash(interaction: discord.Interaction):
    await interaction.response.defer()
    embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
    embed.add_field(name="💰 재고", value=f"```{stock_amount}```", inline=False)
    embed.add_field(name="📈 김프", value=f"```{current_k_premium}```", inline=False)
    embed.add_field(name="🕒 갱신", value=f"```{last_update_time}```", inline=False)
    embed.set_footer(text="신속한 대행 | 레제 코인대행")
    await interaction.followup.send(embed=embed, view=OTCView())

if TOKEN:
    bot.run(TOKEN)
