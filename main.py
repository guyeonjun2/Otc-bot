import os
import discord
import requests
from discord.ext import commands, tasks
from discord.ui import View

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

panel_message = None
previous_premium = None  # 🔥 이전 김프 저장용
BANNER_URL = "https://cdn.discordapp.com/attachments/1476942061747044463/1477299593598468309/REZE_COIN_OTC.gif?ex=69a441f6&is=69a2f076&hm=ffa3babff8587f9ebae5a7241dae6f83f25257b4cbb4588908859c01249bd678&"


# ===== 환율 =====
def get_exchange_rate():
    url = "https://open.er-api.com/v6/latest/USD"
    data = requests.get(url).json()
    return float(data["rates"]["KRW"])


# ===== 업비트 USDT 가격 =====
def get_upbit_usdt_price():
    url = "https://api.upbit.com/v1/ticker?markets=KRW-USDT"
    data = requests.get(url).json()
    return float(data[0]["trade_price"])


# ===== 김프 계산 =====
def calculate_kimchi_premium():
    rate = get_exchange_rate()
    upbit_price = get_upbit_usdt_price()

    premium = ((upbit_price / rate) - 1) * 100
    return round(premium, 2), round(rate, 2)


# ===== 방향 화살표 계산 =====
def get_arrow(current, previous):
    if previous is None:
        return "➖"
    if current > previous:
        return "▲"
    elif current < previous:
        return "▼"
    else:
        return "➖"


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


def create_embed(premium, rate, arrow):
    embed = discord.Embed(
        title="🪙 레제 코인대행",
        description="신속한 코인대행",
        color=0x5865F2  # 💜 항상 보라색
    )

    embed.add_field(name="💰 재고", value="0원", inline=False)
    embed.add_field(
        name="📊 김프 (USDT 기준)",
        value=f"{premium}% {arrow}",
        inline=False
    )
    embed.add_field(name="💵 환율", value=f"{rate}원", inline=False)

    embed.set_image(url=BANNER_URL)

    return embed


@tasks.loop(seconds=60)
async def update_panel():
    global panel_message, previous_premium

    premium, rate = calculate_kimchi_premium()
    arrow = get_arrow(premium, previous_premium)

    previous_premium = premium

    if panel_message:
        await panel_message.edit(
            embed=create_embed(premium, rate, arrow),
            view=PanelView()
        )


@bot.event
async def on_ready():
    global panel_message, previous_premium

    print(f"{bot.user} 로그인 완료")

    channel_id = 1476942061747044463
    channel = await bot.fetch_channel(channel_id)

    premium, rate = calculate_kimchi_premium()
    previous_premium = premium

    panel_message = await channel.send(
        embed=create_embed(premium, rate, "➖"),
        view=PanelView()
    )

    update_panel.start()


bot.run(TOKEN)
