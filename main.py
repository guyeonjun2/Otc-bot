import discord
from discord.ext import commands, tasks
import os
import datetime

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ====== 실시간 값 (나중에 자동연동 가능) ======
stock_amount = "5,000,000원"
kimchi_premium = "1.14%"
last_update = "방금 전"

# ====== 버튼 UI ======
class OTCView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary)
    async def charge(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("관리자에게 문의해주세요.", ephemeral=True)

    @discord.ui.button(label="📤 송금", style=discord.ButtonStyle.primary)
    async def send(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("송금 접수 요청이 접수되었습니다.", ephemeral=True)

    @discord.ui.button(label="📊 정보", style=discord.ButtonStyle.secondary)
    async def info(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("OTC 운영 정보입니다.", ephemeral=True)

    @discord.ui.button(label="🧮 계산기", style=discord.ButtonStyle.secondary)
    async def calc(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("계산기 기능은 추후 추가됩니다.", ephemeral=True)

# ====== 봇 실행시 ======
@bot.event
async def on_ready():
    print(f"봇 로그인 완료: {bot.user}")
    bot.add_view(OTCView())

# ====== 명령어 ======
@bot.command()
async def otc(ctx):
    embed = discord.Embed(
        title="REZE OTC [코인송금대행]",
        color=discord.Color.blue()
    )
    embed.add_field(name="💰 실시간 재고", value=stock_amount, inline=False)
    embed.add_field(name="📈 실시간 김프", value=kimchi_premium, inline=False)
    embed.add_field(name="⏰ 마지막 갱신", value=last_update, inline=False)

    embed.set_footer(text="신속 , 친절 | 안전 OTC")

    await ctx.send(embed=embed, view=OTCView())

bot.run(TOKEN)
