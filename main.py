import os
import discord
import requests
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord.ui import View, Modal, TextInput

TOKEN = os.getenv("DISCORD_TOKEN")

VERIFY_CHANNEL_ID = 1476976182523068478
OWNER_ID = 1472930278874939445
PANEL_CHANNEL_ID = 1476976182523068478  # ✅ 자판기 생성 채널

BANNER_URL = "https://cdn.discordapp.com/attachments/1476942061747044463/1477299593598468309/REZE_COIN_OTC.gif?ex=69a441f6&is=69a2f076&hm=ffa3babff8587f9ebae5a7241dae6f83f25257b4cbb4588908859c01249bd678&"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

panel_message = None
previous_premium = None
verified_users = {}  # {user_id: 이름}
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
    embed = discord.Embed(
        title="🪙 레제 코인대행",
        description="신속한 코인대행",
        color=0x5865F2
    )
    embed.add_field(name="💰 재고", value="0원", inline=False)
    embed.add_field(name="📊 김프", value=f"{premium}% {arrow}", inline=False)
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
        await self.user.send("✅ 인증 승인 완료")
        await interaction.response.send_message("승인 완료", ephemeral=True)


class VerifyModal(Modal, title="본인 인증"):
    def __init__(self):
        super().__init__()
        self.name = TextInput(label="이름")
        self.add_item(self.name)

    async def on_submit(self, interaction: discord.Interaction):
        channel = bot.get_channel(VERIFY_CHANNEL_ID)

        embed = discord.Embed(title="📥 인증 요청")
        embed.add_field(name="유저", value=interaction.user.mention)
        embed.add_field(name="이름", value=self.name.value)

        await channel.send(embed=embed, view=ApproveView(interaction.user, self.name.value))
        await interaction.response.send_message("인증 요청 접수", ephemeral=True)


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
            await self.user.send("✅ 충전 승인 완료")
        except:
            pass

        await interaction.response.send_message("5초 후 채널 삭제", ephemeral=True)
        await interaction.channel.send("✅ 승인 완료\n5초 후 삭제")

        await discord.utils.sleep_until(discord.utils.utcnow() + timedelta(seconds=5))
        await interaction.channel.delete()

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("관리자만 가능합니다.", ephemeral=True)
            return

        try:
            await self.user.send("❌ 충전 거부")
        except:
            pass

        await interaction.response.send_message("5초 후 채널 삭제", ephemeral=True)
        await interaction.channel.send("❌ 거부 완료\n5초 후 삭제")

        await discord.utils.sleep_until(discord.utils.utcnow() + timedelta(seconds=5))
        await interaction.channel.delete()


class ChargeModal(Modal, title="충전 신청"):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.amount = TextInput(label="금액 (숫자만)")
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        global charge_counter

        if not self.amount.value.isdigit():
            await interaction.response.send_message("숫자만 입력", ephemeral=True)
            return

        guild = interaction.guild
        owner = await guild.fetch_member(OWNER_ID)

        channel_name = f"충전접수-{charge_counter:04d}"
        charge_counter += 1

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            self.user: discord.PermissionOverwrite(view_channel=True),
            owner: discord.PermissionOverwrite(view_channel=True)
        }

        channel = await guild.create_text_channel(channel_name, overwrites=overwrites)

        embed = discord.Embed(title="💳 충전 요청")
        embed.add_field(name="신청자", value=self.user.mention)
        embed.add_field(name="입금자명", value=verified_users[self.user.id])
        embed.add_field(name="금액", value=f"{self.amount.value}원")

        await channel.send(embed=embed, view=ChargeApproveView(self.user))
        await interaction.response.send_message("충전요청 접수 완료", ephemeral=True)


# =========================
# 자판기 패널
# =========================

class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="인증")
    async def verify_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal())

    @discord.ui.button(label="충전")
    async def charge_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in verified_users:
            await interaction.response.send_message("인증 필요", ephemeral=True)
            return
        await interaction.response.send_modal(ChargeModal(interaction.user))


@tasks.loop(seconds=30)
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

    print(f"{bot.user} 실행 완료")

    channel = await bot.fetch_channel(PANEL_CHANNEL_ID)

    premium, rate = calculate_kimchi_premium()
    previous_premium = premium

    panel_message = await channel.send(
        embed=create_embed(premium, rate, "➖"),
        view=PanelView()
    )

    update_panel.start()


bot.run(TOKEN)
