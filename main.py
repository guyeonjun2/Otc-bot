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

verified_users = {}   # {user_id: 이름}
charge_counter = 1


# =========================
# 김프 시스템
# =========================

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
    embed = discord.Embed(title="🪙 레제 코인대행", description="신속한 코인대행", color=0x5865F2)
    embed.add_field(name="💰 재고", value="0원", inline=False)
    embed.add_field(name="📊 김프 (USDT 기준)", value=f"{premium}% {arrow}", inline=False)
    embed.add_field(name="💵 환율", value=f"{rate}원", inline=False)
    embed.add_field(name="🕒 마지막 갱신", value=get_kst(), inline=False)
    embed.set_image(url=BANNER_URL)
    return embed


# =========================
# 인증 시스템
# =========================

class ApproveView(View):
    def __init__(self, user, name):
        super().__init__(timeout=None)
        self.user = user
        self.name = name

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("관리자만 가능합니다.", ephemeral=True)
            return

        verified_users[self.user.id] = self.name
        await self.user.send("✅ 인증 승인이 완료되었습니다.")
        await interaction.response.send_message("승인 완료", ephemeral=True)

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("관리자만 가능합니다.", ephemeral=True)
            return

        await self.user.send("❌ 인증이 거부되었습니다.")
        await interaction.response.send_message("거부 완료", ephemeral=True)


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

        embed = discord.Embed(title="📥 신규 인증 요청", color=0x5865F2)
        embed.add_field(name="유저", value=interaction.user.mention, inline=False)
        embed.add_field(name="통신사", value=self.carrier, inline=False)
        embed.add_field(name="이름", value=self.name.value, inline=False)

        if verify_channel:
            await verify_channel.send(
                embed=embed,
                view=ApproveView(interaction.user, self.name.value)
            )

        await interaction.response.send_message("인증 요청이 접수되었습니다.", ephemeral=True)


# =========================
# 충전 시스템
# =========================

class ChargeApproveView(View):
    def __init__(self, user):
        super().__init__(timeout=None)
        self.user = user

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("관리자만 가능합니다.", ephemeral=True)
            return

        try:
            await self.user.send("✅ 충전이 승인되었습니다.")
        except:
            pass

        await interaction.response.send_message("승인 완료 (5초 후 삭제)", ephemeral=True)
        await interaction.channel.send("✅ 승인 완료\n5초 후 채널 삭제")

        await discord.utils.sleep_until(discord.utils.utcnow() + timedelta(seconds=5))
        await interaction.channel.delete()

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("관리자만 가능합니다.", ephemeral=True)
            return

        try:
            await self.user.send("❌ 충전이 거부되었습니다.")
        except:
            pass

        await interaction.response.send_message("거부 완료 (5초 후 삭제)", ephemeral=True)
        await interaction.channel.send("❌ 거부 완료\n5초 후 채널 삭제")

        await discord.utils.sleep_until(discord.utils.utcnow() + timedelta(seconds=5))
        await interaction.channel.delete()


class ChargeModal(Modal, title="충전 신청"):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.amount = TextInput(label="충전 금액 (숫자만 입력)")
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        global charge_counter

        if not self.amount.value.isdigit():
            await interaction.response.send_message("금액은 숫자만 입력 가능합니다.", ephemeral=True)
            return

        amount = self.amount.value
        name = verified_users[self.user.id]

        guild = interaction.guild
        channel_name = f"충전접수-{charge_counter:04d}"
        charge_counter += 1

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            self.user: discord.PermissionOverwrite(view_channel=True),
            guild.get_member(OWNER_ID): discord.PermissionOverwrite(view_channel=True),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }

        channel = await guild.create_text_channel(channel_name, overwrites=overwrites)

        embed = discord.Embed(title="💳 충전 요청", color=0x5865F2)
        embed.add_field(name="신청자", value=self.user.mention, inline=False)
        embed.add_field(name="입금자명", value=name, inline=False)
        embed.add_field(name="금액", value=f"{amount}원", inline=False)

        await channel.send(embed=embed, view=ChargeApproveView(self.user))
        await interaction.response.send_message("충전요청이 접수되었습니다.", ephemeral=True)


# =========================
# 통신사 선택
# =========================

class CarrierView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="LGU+")
    async def lgu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal("LGU+"))

    @discord.ui.button(label="KT")
    async def kt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal("KT"))

    @discord.ui.button(label="SKT")
    async def skt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal("SKT"))


# =========================
# 메인 패널
# =========================

class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    async def require_verify(self, interaction):
        await interaction.response.send_message(
            "본인 인증 후 이용 가능합니다.",
            view=CarrierView(),
            ephemeral=True
        )

    @discord.ui.button(label="송금")
    async def send_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in verified_users:
            await self.require_verify(interaction)
            return
        await interaction.response.send_message("송금 기능입니다.", ephemeral=True)

    @discord.ui.button(label="충전")
    async def charge_btn(self, interaction: discord.Interation, button: discord.ui.Button):
        if interaction.user.id not in verified_users:
            await self.require_verify(interaction)
            return
        await interaction.response.send_modal(ChargeModal(interaction.user))

    @discord.ui.button(label="정보")
    async def info_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in verified_users:
            await self.require_verify(interaction)
            return
        await interaction.response.send_message("정보 기능입니다.", ephemeral=True)

    @discord.ui.button(label="계산")
    async def calc_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in verified_users:
            await self.require_verify(interaction)
            return
        await interaction.response.send_message("계산 기능입니다.", ephemeral=True)


# =========================
# 30초 갱신
# =========================

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

    channel = await bot.fetch_channel(PANEL_CHANNEL_ID)

    premium, rate = calculate_kimchi_premium()
    previous_premium = premium

    panel_message = await channel.send(
        embed=create_embed(premium, rate, "➖"),
        view=PanelView()
    )

    update_panel.start()
    print(f"{bot.user} 실행 완료")


bot.run(TOKEN)
