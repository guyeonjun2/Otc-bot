import os
import discord
from discord.ext import commands
from discord.ui import View

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    # 1줄 3개 버튼
    @discord.ui.button(label="송금", style=discord.ButtonStyle.secondary, emoji="✈️", row=0)
    async def send_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("송금 기능입니다.", ephemeral=True)

    @discord.ui.button(label="충전", style=discord.ButtonStyle.secondary, emoji="💳", row=0)
    async def charge_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("충전 기능입니다.", ephemeral=True)

    @discord.ui.button(label="정보", style=discord.ButtonStyle.secondary, emoji="🎯", row=0)
    async def info_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("정보 기능입니다.", ephemeral=True)

    # 아래 한 줄 계산 버튼
    @discord.ui.button(label="계산", style=discord.ButtonStyle.secondary, emoji="🧮", row=1)
    async def calc_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("계산 기능입니다.", ephemeral=True)


@bot.event
async def on_ready():
    print(f"{bot.user} 로그인 완료")

    channel_id = YOUR_CHANNEL_ID  # 🔥 채널 ID 입력
    channel = bot.get_channel(channel_id)

    embed = discord.Embed(
        description=(
            "## 🪙 레제 코인대행\n"
            "> 신속한 코인대행\n"
            "\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "💰 **재고:** 인생이   📊 **김프:** 이런걸까\n"
            "💵 **환율:** 쌰갈!!\n"
            "\n"
            "*괜차나...딩딩딩딩딩*\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        color=0x2b2d31  # 디스코드 다크톤 느낌
    )

    await channel.send(embed=embed, view=PanelView())


bot.run(TOKEN)
