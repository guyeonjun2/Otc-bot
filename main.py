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

    @discord.ui.button(label="✈️ 송금", style=discord.ButtonStyle.primary, emoji="✈️", row=0)
    async def send_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("송금 기능입니다.", ephemeral=True)

    @discord.ui.button(label="💳 충전", style=discord.ButtonStyle.success, emoji="💳", row=0)
    async def charge_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("충전 기능입니다.", ephemeral=True)

    @discord.ui.button(label="🙎‍♂️ 정보", style=discord.ButtonStyle.secondary, emoji="📊", row=0)
    async def info_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("정보 기능입니다.", ephemeral=True)

    @discord.ui.button(label="🧮 계산", style=discord.ButtonStyle.secondary, emoji="🧮", row=1)
    async def calc_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("계산 기능입니다.", ephemeral=True)


@bot.event
async def on_ready():
    print(f"{bot.user} 로그인 완료")

    channel_id = 1476942061747044463 # 🔥 채널 ID 입력
    channel = bot.get_channel(channel_id)

    embed = discord.Embed(
        title="🪙 레제 코인대행",
        description="신속한 코인대행",
        color=0x5865F2  # 💜 보라색 왼쪽 세로줄
    )

    embed.add_field(name="💰 재고", value="0원", inline=False)
    embed.add_field(name="📊 김프", value="0%", inline=False)
    embed.add_field(name="💵 환율", value="0원", inline=False)
    embed.add_field(name="📌 안내", value="코인대행은 역시 레제코인대행", inline=False)

    await channel.send(embed=embed, view=PanelView())


bot.run(TOKEN)
