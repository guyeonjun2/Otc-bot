import os
import discord
import requests
import asyncio
from discord.ext import commands, tasks
from discord.ui import View

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

panel_message = None  # 패널 메시지 저장용


def get_exchange_rate():
    url = "https://open.er-api.com/v6/latest/USD"
    data = requests.get(url).json()
    return data["rates"]["KRW"]


def get_binance_price():
    url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
    data = requests.get(url).json()
    return float(data["price"])


def get_upbit_price():
    url = "https://api.upbit.com/v1/ticker?markets=KRW-BTC"
    data = requests.get(url).json()
    return float(data[0]["trade_price"])


def calculate_kimchi_premium():
    rate = get_exchange_rate()
    binance = get_binance_price()
    upbit = get_upbit_price()

    premium = ((upbit / (binance * rate)) - 1) * 100
    return round(premium, 2), round(rate, 2)


class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="송금", style=discord.ButtonStyle.primary, emoji="✈️", row=0)
    async def send_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("송금 기능입니다.", ephemeral=True)

    @discord.ui.button(label="충전", style=discord.ButtonStyle.success, emoji="💳", row=0)
    async def charge_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("충전 기능입니다.", ephemeral=True)

    @discord.ui.button(label="정보", style=discord.ButtonStyle.secondary, emoji="📊", row=0)
    async def info_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("정보 기능입니다.", ephemeral=True)

    @discord.ui.button(label="계산", style=discord.ButtonStyle.secondary, emoji="🧮", row=1)
    async def calc_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("계산 기능입니다.", ephemeral=True)


@tasks.loop(seconds=60)
async def update_panel():
    global panel_message

    premium, rate = calculate_kimchi_premium()

    embed = discord.Embed(
        title="🪙 레제 코인대행",
        description="신속한 코인대행",
        color=0x5865F2
    )

    embed.add_field(name="💰 재고", value="0원", inline=False)
    embed.add_field(name="📊 김프", value=f"{premium}%", inline=False)
    embed.add_field(name="💵 환율", value=f"{rate}원", inline=False)

    if panel_message:
        await panel_message.edit(embed=embed, view=PanelView())


@bot.event
async def on_ready():
    global panel_message

    print(f"{bot.user} 로그인 완료")

    channel_id = 1476942061747044463
    channel = await bot.fetch_channel(channel_id)

    premium, rate = calculate_kimchi_premium()

    embed = discord.Embed(
        title="🪙 레제 코인대행",
        description="신속한 코인대행",
        color=0x5865F2
    )

    embed.add_field(name="💰 재고", value="0원", inline=False)
    embed.add_field(name="📊 김프", value=f"{premium}%", inline=False)
    embed.add_field(name="💵 환율", value=f"{rate}원", inline=False)

    panel_message = await channel.send(embed=embed, view=PanelView())

    update_panel.start()


bot.run(TOKEN)
