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
    verified INTEGER DEFAULT 0,
    balance INTEGER DEFAULT 0
)
""")
conn.commit()

def is_verified(user_id):
    cursor.execute("SELECT verified FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row and row[0] == 1

def get_balance(user_id):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0

# ================= 김프 =================
previous_premium = None
panel_message = None

def get_rate():
    try:
        return float(requests.get("https://open.er-api.com/v6/latest/USD", timeout=5).json()["rates"]["KRW"])
    except:
        return 0

def get_usdt():
    try:
        return float(requests.get("https://api.upbit.com/v1/ticker?markets=KRW-USDT", timeout=5).json()[0]["trade_price"])
    except:
        return 0

def get_kimchi():
    rate = get_rate()
    price = get_usdt()
    if rate == 0:
        return 0, rate
    premium = round(((price / rate) - 1) * 100, 2)
    return premium, rate

def arrow(cur, prev):
    if prev is None: return "➖"
    if cur > prev: return "▲"
    if cur < prev: return "▼"
    return "➖"

def embed_create(premium, rate, arrow_mark):
    e = discord.Embed(title="🪙 레제 코인대행", color=0x5865F2)
    e.add_field(name="💰 재고", value="0", inline=False)
    e.add_field(name="📊 김프", value=f"{premium}% {arrow_mark}", inline=False)
    e.add_field(name="💵 환율", value=f"{rate}원", inline=False)
    e.add_field(
        name="🕒 마지막 갱신",
        value=(datetime.utcnow()+timedelta(hours=9)).strftime("%H:%M:%S"),
        inline=False
    )
    return e

# ================= 인증 =================

class VerifyModal(Modal, title="본인 인증"):
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id
        self.name = TextInput(label="이름")
        self.add_item(self.name)

    async def on_submit(self, interaction: discord.Interaction):
        cursor.execute("INSERT OR REPLACE INTO users (user_id, name, verified, balance) VALUES (?, ?, 0, COALESCE((SELECT balance FROM users WHERE user_id=?),0))",
                       (self.user_id, self.name.value, self.user_id))
        conn.commit()

        embed = discord.Embed(title="인증 요청")
        embed.add_field(name="신청자", value=interaction.user.mention)
        embed.add_field(name="이름", value=self.name.value)

        owner = await bot.fetch_user(OWNER_ID)
        await owner.send(embed=embed, view=VerifyAdminView(self.user_id))

        await interaction.response.send_message("인증 요청이 전송되었습니다.", ephemeral=True)

class VerifyAdminView(View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: Button):
        cursor.execute("UPDATE users SET verified=1 WHERE user_id=?", (self.user_id,))
        conn.commit()
        await interaction.response.send_message("승인 완료", ephemeral=True)

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("거부 완료", ephemeral=True)

# ================= 패널 =================

class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    async def check_verify(self, interaction):
        if is_verified(interaction.user.id):
            return True
        await interaction.response.send_modal(VerifyModal(interaction.user.id))
        return False

    @discord.ui.button(label="💳 충전")
    async def charge(self, interaction: discord.Interaction, button: Button):
        if not await self.check_verify(interaction):
            return
        await interaction.response.send_message("충전 기능 준비중", ephemeral=True)

    @discord.ui.button(label="💸 송금")
    async def send(self, interaction: discord.Interaction, button: Button):
        if not await self.check_verify(interaction):
            return
        await interaction.response.send_message("송금 기능 준비중", ephemeral=True)

    @discord.ui.button(label="📊 계산")
    async def calc(self, interaction: discord.Interaction, button: Button):
        if not await self.check_verify(interaction):
            return
        await interaction.response.send_message("계산", ephemeral=True)

    @discord.ui.button(label="📌 정보")
    async def info(self, interaction: discord.Interaction, button: Button):
        if not await self.check_verify(interaction):
            return
        await interaction.response.send_message("정보", ephemeral=True)

# ================= 자동 갱신 =================

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
