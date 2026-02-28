import os
import discord
import sqlite3
import requests
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput, Select

TOKEN = os.getenv("DISCORD_TOKEN")
PANEL_CHANNEL_ID = 1476976182523068478
OWNER_ID = 1472930278874939445

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ================= DB =================
conn = sqlite3.connect("data.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    verified INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS charges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER
)
""")
conn.commit()

def is_verified(user_id):
    cursor.execute("SELECT verified FROM users WHERE user_id=?", (user_id,))
    data = cursor.fetchone()
    return data and data[0] == 1

# ================= 김프 =================
previous_premium = None
panel_message = None

def get_rate():
    return float(requests.get("https://open.er-api.com/v6/latest/USD").json()["rates"]["KRW"])

def get_usdt():
    return float(requests.get("https://api.upbit.com/v1/ticker?markets=KRW-USDT").json()[0]["trade_price"])

def get_kimchi():
    rate = get_rate()
    price = get_usdt()
    premium = round(((price / rate) - 1) * 100, 2)
    return premium, rate

def arrow(cur, prev):
    if prev is None: return "➖"
    if cur > prev: return "▲"
    if cur < prev: return "▼"
    return "➖"

def embed_create(premium, rate, arrow_mark):
    e = discord.Embed(title="🪙 레제 코인대행", color=0x5865F2)
    e.add_field(name="💰 재고", value="0원", inline=False)
    e.add_field(name="📊 김프", value=f"{premium}% {arrow_mark}", inline=False)
    e.add_field(name="💵 환율", value=f"{rate}원", inline=False)
    e.add_field(name="🕒 마지막 갱신", value=(datetime.utcnow()+timedelta(hours=9)).strftime("%H:%M:%S"), inline=False)
    return e

# ================= 본인인증 =================
class VerifyModal(Modal, title="본인인증"):
    name = TextInput(label="이름 입력")

    async def on_submit(self, interaction: discord.Interaction):
        cursor.execute("INSERT OR REPLACE INTO users(user_id,name,verified) VALUES(?,?,1)",
                       (interaction.user.id, self.name.value))
        conn.commit()
        await interaction.response.send_message("본인인증 완료", ephemeral=True)

# ================= 충전 =================
charge_counter = 1

class ChargeModal(Modal, title="충전"):
    amount = TextInput(label="금액 (숫자만 입력)")

    async def on_submit(self, interaction: discord.Interaction):
        global charge_counter

        if not self.amount.value.isdigit():
            await interaction.response.send_message("숫자만 입력", ephemeral=True)
            return

        cursor.execute("SELECT name FROM users WHERE user_id=?", (interaction.user.id,))
        name = cursor.fetchone()[0]

        amount = int(self.amount.value)
        cursor.execute("INSERT INTO charges(user_id,amount) VALUES(?,?)",
                       (interaction.user.id, amount))
        conn.commit()

        guild = interaction.guild
        owner = await guild.fetch_member(OWNER_ID)

        channel_name = f"충전접수-{charge_counter:04d}"
        charge_counter += 1

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True),
            owner: discord.PermissionOverwrite(view_channel=True)
        }

        channel = await guild.create_text_channel(channel_name, overwrites=overwrites)

        embed = discord.Embed(title="충전 요청")
        embed.add_field(name="신청자", value=interaction.user.mention)
        embed.add_field(name="입금자명", value=name)
        embed.add_field(name="금액", value=f"{amount}원")

        await channel.send(embed=embed, view=ChargeAdminView(interaction.user))
        await interaction.response.send_message("충전요청이 접수되었습니다.", ephemeral=True)

class ChargeAdminView(View):
    def __init__(self, user):
        super().__init__(timeout=None)
        self.user = user

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("관리자만 가능합니다.", ephemeral=True)
            return
        await self.user.send("승인")
        await interaction.response.send_message("5초 후 삭제", ephemeral=True)
        await interaction.channel.send("5초 후 삭제")
        await discord.utils.sleep_until(discord.utils.utcnow() + timedelta(seconds=5))
        await interaction.channel.delete()

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("관리자만 가능합니다.", ephemeral=True)
            return
        await self.user.send("거부")
        await interaction.response.send_message("5초 후 삭제", ephemeral=True)
        await interaction.channel.send("5초 후 삭제")
        await discord.utils.sleep_until(discord.utils.utcnow() + timedelta(seconds=5))
        await interaction.channel.delete()

# ================= 통신사 =================
class CarrierSelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="SKT"),
            discord.SelectOption(label="KT"),
            discord.SelectOption(label="LGU+"),
            discord.SelectOption(label="알뜰폰")
        ]
        super().__init__(placeholder="통신사 선택", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "알뜰폰":
            await interaction.response.send_message(view=AltCarrierView(), ephemeral=True)
        else:
            await interaction.response.send_message(f"{self.values[0]}", ephemeral=True)

class AltCarrierSelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="알뜰폰 SKT"),
            discord.SelectOption(label="알뜰폰 KT"),
            discord.SelectOption(label="알뜰폰 LGU+"),
        ]
        super().__init__(placeholder="알뜰폰 선택", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"{self.values[0]}", ephemeral=True)

class CarrierView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CarrierSelect())

class AltCarrierView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(AltCarrierSelect())

# ================= 메인 패널 =================
class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💳 충전")
    async def charge(self, interaction: discord.Interaction, button: Button):
        if not is_verified(interaction.user.id):
            await interaction.response.send_modal(VerifyModal())
            return
        await interaction.response.send_modal(ChargeModal())

    @discord.ui.button(label="📊 계산")
    async def calc(self, interaction: discord.Interaction, button: Button):
        if not is_verified(interaction.user.id):
            await interaction.response.send_modal(VerifyModal())
            return
        await interaction.response.send_message("계산", ephemeral=True)

    @discord.ui.button(label="💸 송금")
    async def send(self, interaction: discord.Interaction, button: Button):
        if not is_verified(interaction.user.id):
            await interaction.response.send_modal(VerifyModal())
            return
        await interaction.response.send_message("송금", ephemeral=True)

    @discord.ui.button(label="📌 정보")
    async def info(self, interaction: discord.Interaction, button: Button):
        if not is_verified(interaction.user.id):
            await interaction.response.send_modal(VerifyModal())
            return
        await interaction.response.send_message("정보", ephemeral=True)

    @discord.ui.button(label="📱 통신사")
    async def carrier(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(view=CarrierView(), ephemeral=True)

# ================= 패널 자동 갱신 =================
@tasks.loop(seconds=30)
async def update_panel():
    global previous_premium
    premium, rate = get_kimchi()
    arr = arrow(premium, previous_premium)
    previous_premium = premium
    await panel_message.edit(embed=embed_create(premium, rate, arr), view=PanelView())

@bot.event
async def on_ready():
    global panel_message, previous_premium
    channel = await bot.fetch_channel(PANEL_CHANNEL_ID)
    premium, rate = get_kimchi()
    previous_premium = premium

    panel_message = await channel.send(
        embed=embed_create(premium, rate, "➖"),
        view=PanelView()
    )

    update_panel.start()

bot.run(TOKEN)
