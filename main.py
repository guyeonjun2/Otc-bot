import os
import discord
import sqlite3
import requests
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord.ui import View, Modal, TextInput

TOKEN = os.getenv("DISCORD_TOKEN")  # Railway 환경변수 사용
PANEL_CHANNEL_ID = 1476976182523068478
OWNER_ID = 1472930278874939445

intents = discord.Intents.all()
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

def ensure_user(user_id):
    cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?,0)", (user_id,))
    conn.commit()

def add_balance(user_id, amount):
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()

def sub_balance(user_id, amount):
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))
    conn.commit()

def get_balance(user_id):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0

# ================= 김프 =================
panel_message = None
previous_premium = None

def get_kimchi():
    try:
        rate = float(requests.get("https://open.er-api.com/v6/latest/USD", timeout=5).json()["rates"]["KRW"])
        price = float(requests.get("https://api.upbit.com/v1/ticker?markets=KRW-USDT", timeout=5).json()[0]["trade_price"])
        premium = round(((price / rate) - 1) * 100, 2)
        return premium, rate
    except:
        return 0, 0

def arrow(cur, prev):
    if prev is None: return "➖"
    if cur > prev: return "▲"
    if cur < prev: return "▼"
    return "➖"

def create_embed(premium, rate, arr):
    color = 0x2ecc71 if arr == "▲" else 0xe74c3c if arr == "▼" else 0x5865F2

    embed = discord.Embed(
        title="🪙 레제 코인대행",
        description="신속한 코인대행 지금 이용해보세요!.\n아래 버튼들을 눌러 원하는 기능을 선택하세요.",
        color=color
    )

    embed.add_field(name="──────────────", value="📊 **실시간 시세**", inline=False)
    embed.add_field(name="김프", value=f"**{premium}%** {arr}", inline=True)
    embed.add_field(name="환율 (USD/KRW)", value=f"**{rate:,.0f}원**", inline=True)
    embed.add_field(
        name="──────────────",
        value=f"⌚ 마지막 갱신: {(datetime.utcnow()+timedelta(hours=9)).strftime('%H:%M:%S')}",
        inline=False
    )

    embed.set_footer(text="REZE OTC | Made by REZE")
    return embed

@tasks.loop(seconds=30)
async def update_panel():
    global previous_premium, panel_message
    premium, rate = get_kimchi()
    arr = arrow(premium, previous_premium)
    previous_premium = premium
    if panel_message:
        await panel_message.edit(embed=create_embed(premium, rate, arr), view=PanelView())

# ================= 관리자 체크 =================
async def admin_only(interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("관리자만 사용 가능합니다.", ephemeral=True)
        return False
    return True

# ================= 충전 =================
class ChargeModal(Modal, title="충전 요청"):
    amount = TextInput(label="금액")

    async def on_submit(self, interaction):
        guild = interaction.guild
        amount = int(self.amount.value)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True),
            guild.get_member(OWNER_ID): discord.PermissionOverwrite(view_channel=True)
        }

        channel = await guild.create_text_channel(
            name=f"충전-{interaction.user.name}",
            overwrites=overwrites
        )

        embed = discord.Embed(title="💳 충전 요청", color=0x3498db)
        embed.add_field(name="요청자", value=interaction.user.mention, inline=False)
        embed.add_field(name="금액", value=f"{amount:,}원", inline=False)
        embed.add_field(name="상태", value="⏳ 승인 대기중", inline=False)

        await channel.send(embed=embed, view=ChargeAdminView(interaction.user.id, amount))
        await interaction.response.send_message("충전 요청 채널이 생성되었습니다.", ephemeral=True)

class ChargeAdminView(View):
    def __init__(self, user_id, amount):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.amount = amount

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction, button):
        if not await admin_only(interaction): return
        add_balance(self.user_id, self.amount)
        await interaction.response.send_message("✅ 충전 승인 완료")
        await interaction.channel.delete(delay=3)

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction, button):
        if not await admin_only(interaction): return
        await interaction.response.send_message("❌ 충전 거부 완료")
        await interaction.channel.delete(delay=3)

# ================= 송금 =================
class SendModal(Modal, title="송금 요청"):
    amount = TextInput(label="금액")
    coin_type = TextInput(label="코인 종류 (예: USDT, BTC)")
    coin_address = TextInput(label="코인 주소")

    async def on_submit(self, interaction):
        guild = interaction.guild
        amount = int(self.amount.value)

        if get_balance(interaction.user.id) < amount:
            await interaction.response.send_message("잔액이 부족합니다.", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True),
            guild.get_member(OWNER_ID): discord.PermissionOverwrite(view_channel=True)
        }

        channel = await guild.create_text_channel(
            name=f"송금-{interaction.user.name}",
            overwrites=overwrites
        )

        embed = discord.Embed(title="💸 송금 요청", color=0xf1c40f)
        embed.add_field(name="요청자", value=interaction.user.mention, inline=False)
        embed.add_field(name="금액", value=f"{amount:,}원", inline=False)
        embed.add_field(name="코인 종류", value=self.coin_type.value, inline=False)
        embed.add_field(name="코인 주소", value=self.coin_address.value, inline=False)
        embed.add_field(name="상태", value="⏳ 승인 대기중", inline=False)

        await channel.send(embed=embed, view=SendAdminView(interaction.user.id, amount))
        await interaction.response.send_message("송금 요청 채널이 생성되었습니다.", ephemeral=True)

class SendAdminView(View):
    def __init__(self, user_id, amount):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.amount = amount

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction, button):
        if not await admin_only(interaction): return
        sub_balance(self.user_id, self.amount)
        await interaction.response.send_message("✅ 송금 승인 완료")
        await interaction.channel.delete(delay=3)

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction, button):
        if not await admin_only(interaction): return
        await interaction.response.send_message("❌ 송금 거부 완료")
        await interaction.channel.delete(delay=3)

# ================= 패널 =================
class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="충전", style=discord.ButtonStyle.primary, row=0)
    async def charge(self, interaction, button):
        await interaction.response.send_modal(ChargeModal())

    @discord.ui.button(label="송금", style=discord.ButtonStyle.secondary, row=0)
    async def send(self, interaction, button):
        await interaction.response.send_modal(SendModal())

    @discord.ui.button(label="계산", style=discord.ButtonStyle.success, row=1)
    async def calc(self, interaction, button):
        await interaction.response.send_message("계산 기능 준비중입니다.", ephemeral=True)

    @discord.ui.button(label="정보", style=discord.ButtonStyle.secondary, row=1)
    async def info(self, interaction, button):
        ensure_user(interaction.user.id)
        bal = get_balance(interaction.user.id)
        await interaction.response.send_message(f"💰 현재 잔액: {bal:,}원", ephemeral=True)

# ================= READY =================
@bot.event
async def on_ready():
    global panel_message, previous_premium
    print("봇 준비 완료")

    class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    channel = await bot.fetch_channel(PANEL_CHANNEL_ID)
    premium, rate = get_kimchi()
    previous_premium = premium

    panel_message = await channel.send(
        embed=create_embed(premium, rate, "➖"),
        view=PanelView()
    )

    update_panel.start()

bot.run(TOKEN)
