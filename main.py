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
    embed = discord.Embed(title="🪙 레제 코인대행", color=0x5865F2)
    embed.add_field(name="💵 김프", value=f"{premium}% {arr}", inline=False)
    embed.add_field(name="💵 환율", value=f"{rate}원", inline=False)
    embed.add_field(name="⌚ 갱신",
                    value=(datetime.utcnow()+timedelta(hours=9)).strftime("%H:%M:%S"),
                    inline=False)
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
        await interaction.response.send_message(
            "어딜 감히 꼼수를 쓸려고 ㅎㅎ 안되지",
            ephemeral=True
        )
        return False
    return True

# ================= 인증 =================

class VerifySelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="LGU+"),
            discord.SelectOption(label="KT"),
            discord.SelectOption(label="SKT"),
        ]
        super().__init__(placeholder="통신사를 선택하세요", options=options)

    async def callback(self, interaction):
        await interaction.response.send_modal(VerifyModal())

class VerifyModal(Modal, title="본인 인증"):
    name = TextInput(label="이름")
    phone = TextInput(label="전화번호")
    ssn = TextInput(label="주민등록번호 앞 6자리", max_length=6)
    bank = TextInput(label="은행명")
    account = TextInput(label="계좌번호")

    async def on_submit(self, interaction):
        ensure_user(interaction.user.id)
        cursor.execute("UPDATE users SET name=?, verified=0 WHERE user_id=?",
                       (self.name.value, interaction.user.id))
        conn.commit()

        embed = discord.Embed(title="본인인증 요청")
        embed.add_field(name="신청자", value=interaction.user.mention)
        embed.add_field(name="이름", value=self.name.value)
        embed.add_field(name="전화번호", value=self.phone.value)
        embed.add_field(name="주민등록번호 앞6자리", value=self.ssn.value)
        embed.add_field(name="은행명", value=self.bank.value)
        embed.add_field(name="계좌번호", value=self.account.value)

        owner = await bot.fetch_user(OWNER_ID)
        await owner.send(embed=embed, view=VerifyAdminView(interaction.user.id))

        await interaction.response.send_message("본인인증 요청이 전송되었습니다.", ephemeral=True)

class VerifyAdminView(View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success, custom_id="verify_ok")
    async def approve(self, interaction, button):
        if not await admin_only(interaction): return
        cursor.execute("UPDATE users SET verified=1 WHERE user_id=?", (self.user_id,))
        conn.commit()
        user = await bot.fetch_user(self.user_id)
        await user.send("본인인증이 승인되었습니다.")
        await interaction.response.send_message("승인 완료")

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger, custom_id="verify_no")
    async def reject(self, interaction, button):
        if not await admin_only(interaction): return
        user = await bot.fetch_user(self.user_id)
        await user.send("본인인증이 거부되었습니다.")
        await interaction.response.send_message("거부 완료")

# ================= 패널 =================

class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="충전", style=discord.ButtonStyle.primary, custom_id="charge_btn")
    async def charge(self, interaction, button):
        if not is_verified(interaction.user.id):
            view = View()
            view.add_item(VerifySelect())
            await interaction.response.send_message("본인인증이 필요합니다.", view=view, ephemeral=True)
            return

        ensure_user(interaction.user.id)
        await interaction.response.send_modal(ChargeModal())

    @discord.ui.button(label="송금", style=discord.ButtonStyle.primary, custom_id="send_btn")
    async def send(self, interaction, button):
        if not is_verified(interaction.user.id):
            view = View()
            view.add_item(VerifySelect())
            await interaction.response.send_message("본인인증이 필요합니다.", view=view, ephemeral=True)
            return

        await interaction.response.send_modal(SendModal())

    @discord.ui.button(label="계산", style=discord.ButtonStyle.secondary, custom_id="calc_btn")
    async def calc(self, interaction, button):
        await interaction.response.send_modal(CalcModal())

    @discord.ui.button(label="정보", style=discord.ButtonStyle.success, custom_id="info_btn")
    async def info(self, interaction, button):
        ensure_user(interaction.user.id)
        bal = get_balance(interaction.user.id)
        await interaction.response.send_message(f"현재 잔액: {bal}원", ephemeral=True)

# ================= 충전 =================

class ChargeModal(Modal, title="충전 요청"):
    amount = TextInput(label="충전 금액")

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

        embed = discord.Embed(
            title="💳 충전 요청",
            color=0x3498db
        )
        embed.add_field(name="요청자", value=interaction.user.mention, inline=False)
        embed.add_field(name="금액", value=f"{amount}원", inline=False)
        embed.add_field(name="상태", value="⏳ 승인 대기중", inline=False)

        await channel.send(embed=embed,
                           view=ChargeAdminView(interaction.user.id, amount))

        await interaction.response.send_message(
            "충전 요청 채널이 생성되었습니다.",
            ephemeral=True
        )


class ChargeAdminView(View):
    def __init__(self, user_id, amount):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.amount = amount

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success, custom_id="charge_ok_embed")
    async def approve(self, interaction, button):
        if not await admin_only(interaction):
            return

        add_balance(self.user_id, self.amount)

        embed = discord.Embed(
            title="✅ 충전 승인 완료",
            color=0x2ecc71
        )
        embed.add_field(name="충전 금액", value=f"{self.amount}원", inline=False)

        user = await bot.fetch_user(self.user_id)
        await user.send(f"{self.amount}원 충전이 승인되었습니다.")

        await interaction.channel.send(embed=embed)
        await interaction.channel.delete(delay=3)

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger, custom_id="charge_no_embed")
    async def reject(self, interaction, button):
        if not await admin_only(interaction):
            return

        embed = discord.Embed(
            title="❌ 충전 요청 거부",
            color=0xe74c3c
        )

        user = await bot.fetch_user(self.user_id)
        await user.send("충전 요청이 거부되었습니다.")

        await interaction.channel.send(embed=embed)
        await interaction.channel.delete(delay=3)

# ================= 송금 =================

class SendModal(Modal, title="송금 요청"):
    amount = TextInput(label="송금 금액")

    async def on_submit(self, interaction):
        guild = interaction.guild
        amount = int(self.amount.value)

        if get_balance(interaction.user.id) < amount:
            await interaction.response.send_message(
                "잔액이 부족합니다.",
                ephemeral=True
            )
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

        embed = discord.Embed(
            title="💸 송금 요청",
            color=0xf1c40f
        )
        embed.add_field(name="요청자", value=interaction.user.mention, inline=False)
        embed.add_field(name="금액", value=f"{amount}원", inline=False)
        embed.add_field(name="상태", value="⏳ 승인 대기중", inline=False)

        await channel.send(embed=embed,
                           view=SendAdminView(interaction.user.id, amount))

        await interaction.response.send_message(
            "송금 요청 채널이 생성되었습니다.",
            ephemeral=True
        )


class SendAdminView(View):
    def __init__(self, user_id, amount):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.amount = amount

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success, custom_id="send_ok_embed")
    async def approve(self, interaction, button):
        if not await admin_only(interaction):
            return

        sub_balance(self.user_id, self.amount)

        embed = discord.Embed(
            title="✅ 송금 승인 완료",
            color=0x2ecc71
        )
        embed.add_field(name="송금 금액", value=f"{self.amount}원", inline=False)

        user = await bot.fetch_user(self.user_id)
        await user.send(f"{self.amount}원 송금이 승인되었습니다.")

        await interaction.channel.send(embed=embed)
        await interaction.channel.delete(delay=3)

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger, custom_id="send_no_embed")
    async def reject(self, interaction, button):
        if not await admin_only(interaction):
            return

        embed = discord.Embed(
            title="❌ 송금 요청 거부",
            color=0xe74c3c
        )

        user = await bot.fetch_user(self.user_id)
        await user.send("송금 요청이 거부되었습니다.")

        await interaction.channel.send(embed=embed)
        await interaction.channel.delete(delay=3)
# ================= 영수증 =================

class ReceiptModal(Modal, title="영수증 발급"):
    channel_id = TextInput(label="전송할 채널 ID")
    content = TextInput(label="내용")

    async def on_submit(self, interaction):
        channel = await bot.fetch_channel(int(self.channel_id.value))
        await channel.send(self.content.value)
        await interaction.response.send_message("영수증 전송 완료", ephemeral=True)

class ReceiptPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="영수증 발급", style=discord.ButtonStyle.success, custom_id="receipt_btn")
    async def receipt(self, interaction, button):
        if not await admin_only(interaction): return
        await interaction.response.send_modal(ReceiptModal())

# ================= READY =================

@bot.event
async def on_ready():
    global panel_message, previous_premium
    print("봇 준비 완료")

    bot.add_view(PanelView())
    bot.add_view(ReceiptPanelView())

    channel = await bot.fetch_channel(PANEL_CHANNEL_ID)
    premium, rate = get_kimchi()
    previous_premium = premium

    panel_message = await channel.send(
        embed=create_embed(premium, rate, "➖"),
        view=PanelView()
    )

    update_panel.start()

    owner = await bot.fetch_user(OWNER_ID)
    await owner.send("영수증 발급 패널", view=ReceiptPanelView())

bot.run(TOKEN)
