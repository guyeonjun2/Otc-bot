import os
import discord
from discord.ext import commands
from discord.ui import Button, View

TOKEN = os.getenv("DISCORD_TOKEN")  # Railway 환경변수에 토큰 넣어두기

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

    @discord.ui.button(label="정보", style=discord.ButtonStyle.secondary, emoji="🎯")
    async def info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("정보 확인 기능입니다.", ephemeral=True)

    @discord.ui.button(label="계산", style=discord.ButtonStyle.secondary, emoji="🧮")
    async def calc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("계산 기능입니다.", ephemeral=True)


@bot.event
async def on_ready():
    print(f"{bot.user} 로그인 완료")


@bot.command()
async def 레제코인대행(ctx):
    embed = discord.Embed(
        title="🪙 레제 코인대행",
        description="신속한 코인 대행",
        color=0x2ecc71
    )

    embed.add_field(name="💰 재고", value="개발중", inline=True)
    embed.add_field(name="📊 김프", value="개발중", inline=True)
    embed.add_field(name="💵 환율", value="개발중", inline=False)
    embed.add_field(name="📌 안내", value="개발중", inline=False)

    embed.set_image(url="https://cdn.discordapp.com/attachments/1476942061747044463/1477299593598468309/REZE_COIN_OTC.gif?ex=69a441f6&is=69a2f076&hm=ffa3babff8587f9ebae5a7241dae6f83f25257b4cbb4588908859c01249bd678&")  # 배너 이미지 넣고 싶으면 링크 교체

    await ctx.send(embed=embed, view=MainView())


bot.run(TOKEN)
