import os
import discord
from discord.ext import commands
from discord.ui import View

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


class MainView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="송금", style=discord.ButtonStyle.primary, emoji="✈️")
    async def send_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("송금 기능입니다.", ephemeral=True)

    @discord.ui.button(label="충전", style=discord.ButtonStyle.success, emoji="💳")
    async def charge_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("충전 기능입니다.", ephemeral=True)

    @discord.ui.button(label="정보", style=discord.ButtonStyle.secondary, emoji="📊")
    async def info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("정보 기능입니다.", ephemeral=True)

    @discord.ui.button(label="계산", style=discord.ButtonStyle.secondary, emoji="🧮")
    async def calc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("계산 기능입니다.", ephemeral=True)


@bot.event
async def on_ready():
    print(f"{bot.user} 로그인 완료")

    channel_id = 1476942061747044463  # 🔥 여기에 채널 ID 숫자 넣기
    channel = bot.get_channel(channel_id)

    embed = discord.Embed(
        title="🪙 레제 코인대행",
        description="신속한 코인대행",
        color=0x2ecc71
    )

    embed.add_field(name="💰 재고", value="개발중", inline=True)
    embed.add_field(name="📊 김프", value="먹고살기", inline=True)
    embed.add_field(name="💵 환율", value="힘들다", inline=False)
    embed.add_field(name="📌 안내", value="쌰갈", inline=False)

    await channel.send(embed=embed, view=MainView())


bot.run(TOKEN)
