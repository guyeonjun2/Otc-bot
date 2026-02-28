import os
import discord
import asyncpg
from discord.ext import commands

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

intents = discord.Intents.default()

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents
        )
        self.db = None

    async def setup_hook(self):
        # DB 연결
        self.db = await asyncpg.create_pool(DATABASE_URL)

        # 테이블 생성
        async with self.db.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS otc_orders (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

        # persistent view 등록
        self.add_view(OTCView(self))

        # 슬래시 명령어 동기화
        await self.tree.sync()


bot = Bot()


# ✅ 버튼 View
class OTCView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)  # 🔥 필수
        self.bot = bot

    @discord.ui.button(
        label="구매하기",
        style=discord.ButtonStyle.green,
        custom_id="otc_buy_button"  # 🔥 필수
    )
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO otc_orders (user_id) VALUES ($1)",
                interaction.user.id
            )

        await interaction.response.send_message(
            "✅ 주문이 접수되었습니다!",
            ephemeral=True
        )


# ✅ 슬래시 명령어
@bot.tree.command(name="otc", description="OTC 구매 패널 열기")
async def otc(interaction: discord.Interaction):
    await interaction.response.send_message(
        "OTC 구매를 원하시면 아래 버튼을 눌러주세요.",
        view=OTCView(bot)
    )


@bot.event
async def on_ready():
    print(f"{bot.user} 로그인 완료")


bot.run(TOKEN)
