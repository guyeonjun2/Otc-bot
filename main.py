import os
import discord
import sqlite3
import requests
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput, Select

TOKEN = os.getenv("DISCORD_TOKEN")
PANEL_CHANNEL_ID = 1476976182523068478  # 자판기 채널 ID
OWNER_ID = 1472930278874939445  # 관리자 ID

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

def is_verified(user_id):
    cursor.execute("SELECT verified FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row and row[0] == 1

def get_balance(user_id):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0

def add_balance(user_id, amount):
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()

def sub_balance(user_id, amount):
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))
    conn.commit()

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
    e.add_field(name="💰 재고", value="운영중", inline=False)
    e.add_field(name="📊 김프", value=f"{premium}% {arrow_mark}", inline=False)
    e.add_field(name="💵 환율", value=f"{rate}원", inline=False)
    e.add_field(name="🕒 마지막 갱신",
                value=(datetime.utcnow()+timedelta(hours=9)).strftime("%H:%M:%S"),
                inline=False)
    return e

# ================= 인증 =================

class VerifySelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="LGU+"),
            discord.SelectOption(label="KT"),
            discord.SelectOption(label="SKT"),
        ]
        super().__init__(placeholder="통신사를 선택하세요", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(VerifyModal(self.values[0]))

class VerifyModal(Modal, title="본인 인증"):
    def __init__(self, telecom):
        super().__init__()
        self.telecom = telecom
        self.name = TextInput(label="이름")
        self.phone = TextInput(label="전화번호")
        self.ssn = TextInput(label="주민등록번호 앞 6자리", max_length=6)
        self.bank = TextInput(label="은행명")
        self.account = TextInput(label="계좌번호")
        self.add_item(self.name)
        self.add_item(self.phone)
        self.add_item(self.ssn)
        self.add_item(self.bank)
        self.add_item(self.account)

    async def on_submit(self, interaction: discord.Interaction):
        cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)", (interaction.user.id,))
        cursor.execute("UPDATE users SET name=?, verified=1 WHERE user_id=?",
                       (self.name.value, interaction.user.id))
        conn.commit()
        await interaction.response.send_message("인증 완료", ephemeral=True)

# ================= 충전 =================

class ChargeModal(Modal, title="충전 신청"):
    amount = TextInput(label="충전 금액")

    async def on_submit(self, interaction: discord.Interaction):
        amount = int(self.amount.value)
        channel = await interaction.guild.create_text_channel(f"충전요청-{interaction.user.name}")
        embed = discord.Embed(title="충전 요청")
        embed.add_field(name="신청자", value=interaction.user.mention)
        embed.add_field(name="금액", value=amount)
        await channel.send("@everyone", embed=embed,
                           view=ChargeAdminView(interaction.user.id, amount))
        await interaction.response.send_message("충전 요청 완료", ephemeral=True)

class ChargeAdminView(View):
    def __init__(self, user_id, amount):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.amount = amount

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success, custom_id="charge_approve")
    async def approve(self, interaction: discord.Interaction, button: Button):
        add_balance(self.user_id, self.amount)
        await interaction.response.send_message("충전 승인 완료")

# ================= 송금 =================

class SendModal(Modal, title="송금 신청"):
    address = TextInput(label="주소")
    amount = TextInput(label="금액")

    async def on_submit(self, interaction: discord.Interaction):
        amount = int(self.amount.value)
        if get_balance(interaction.user.id) < amount:
            await interaction.response.send_message("잔액 부족", ephemeral=True)
            return
        channel = await interaction.guild.create_text_channel(f"송금요청-{interaction.user.name}")
        embed = discord.Embed(title="송금 요청")
        embed.add_field(name="신청자", value=interaction.user.mention)
        embed.add_field(name="주소", value=self.address.value)
        embed.add_field(name="금액", value=amount)
        await channel.send("@everyone", embed=embed,
                           view=SendAdminView(interaction.user.id, amount))
        await interaction.response.send_message("송금 요청 완료", ephemeral=True)

class SendAdminView(View):
    def __init__(self, user_id, amount):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.amount = amount

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success, custom_id="send_approve")
    async def approve(self, interaction: discord.Interaction, button: Button):
        sub_balance(self.user_id, self.amount)
        await interaction.response.send_message("송금 승인 완료")

# ================= 영수증 =================

class ReceiptModal(Modal, title="영수증 발급"):
    channel_id = TextInput(label="전송할 채널 ID")
    coin = TextInput(label="코인")
    amount = TextInput(label="금액")
    network = TextInput(label="네트워크")
    txid = TextInput(label="트랜잭션")

    async def on_submit(self, interaction: discord.Interaction):
        channel = await bot.fetch_channel(int(self.channel_id.value))
        embed = discord.Embed(title="🚀 송금이 완료되었습니다!")
        embed.description = "요청하신 송금이 블록체인 상에서 확인되었습니다."
        embed.add_field(name="코인", value=self.coin.value, inline=False)
        embed.add_field(name="금액", value=self.amount.value, inline=False)
        embed.add_field(name="네트워크", value=self.network.value, inline=False)
        embed.add_field(name="상태", value="✅ 전송 완료", inline=False)
        embed.add_field(name="🔗 트랜잭션", value=self.txid.value, inline=False)
        await channel.send(embed=embed)
        await interaction.response.send_message("영수증 전송 완료", ephemeral=True)

class ReceiptPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🧾 영수증 발급", style=discord.ButtonStyle.success, custom_id="receipt_panel_button")
    async def receipt_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("관리자 전용입니다.", ephemeral=True)
            return
        await interaction.response.send_modal(ReceiptModal())

# ================= 패널 =================

class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    async def check_verify(self, interaction):
        if is_verified(interaction.user.id):
            return True
        view = View()
        view.add_item(VerifySelect())
        await interaction.response.send_message("본인인증이 필요합니다.", view=view, ephemeral=True)
        return False

    @discord.ui.button(label="💳 충전", style=discord.ButtonStyle.primary, custom_id="panel_charge")
    async def charge(self, interaction: discord.Interaction, button: Button):
        if not await self.check_verify(interaction): return
        await interaction.response.send_modal(ChargeModal())

    @discord.ui.button(label="💸 송금", style=discord.ButtonStyle.primary, custom_id="panel_send")
    async def send(self, interaction: discord.Interaction, button: Button):
        if not await self.check_verify(interaction): return
        await interaction.response.send_modal(SendModal())

    @discord.ui.button(label="📊 계산", style=discord.ButtonStyle.secondary, custom_id="panel_calc")
    async def calc(self, interaction: discord.Interaction, button: Button):
        if not await self.check_verify(interaction): return
        await interaction.response.send_message("계산 기능", ephemeral=True)

    @discord.ui.button(label="📌 정보", style=discord.ButtonStyle.secondary, custom_id="panel_info")
    async def info(self, interaction: discord.Interaction, button: Button):
        if not await self.check_verify(interaction): return
        await interaction.response.send_message(f"현재 잔액: {get_balance(interaction.user.id)}원", ephemeral=True)

# ================= 자동 실행 =================

@bot.event
async def on_ready():
    global panel_message, previous_premium
    print("봇 준비 완료")

    bot.add_view(PanelView())
    bot.add_view(ReceiptPanelView())

    # 자판기 생성
    channel = await bot.fetch_channel(PANEL_CHANNEL_ID)
    premium, rate = get_kimchi()
    previous_premium = premium
    panel_message = await channel.send(embed=embed_create(premium, rate, "➖"), view=PanelView())

    # 영수증 패널 DM 전송
    owner = await bot.fetch_user(OWNER_ID)
    await owner.send("영수증 발급 패널", view=ReceiptPanelView())

bot.run(TOKEN)
