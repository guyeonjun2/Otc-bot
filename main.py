import os
import discord
import sqlite3
import requests
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord.ui import View, Modal, TextInput, Select

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = 1472930278874939445
PANEL_CHANNEL_ID = 1476976182523068478

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= DB =================
conn = sqlite3.connect("data.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
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

# ================= 시세 =================
def get_kimchi():
    try:
        rate = float(requests.get("https://open.er-api.com/v6/latest/USD").json()["rates"]["KRW"])
        price = float(requests.get("https://api.upbit.com/v1/ticker?markets=KRW-USDT").json()[0]["trade_price"])
        premium = round(((price / rate) - 1) * 100, 2)
        return premium, rate
    except:
        return 0, 0

def create_embed(premium, rate):
    divider = "────────────────────────────"
    embed = discord.Embed(
        title="# 레제 코인대행",
        description="신속한 코인대행 지금 이용해보세요.\n아래 버튼들을 눌러 원하는 기능을 선택하세요.",
        color=0x000000
    )
    embed.add_field(name=divider, value="📊 **실시간 시세**", inline=False)
    embed.add_field(name="김프", value=f"{premium}%", inline=False)
    embed.add_field(name="환율 (USD/KRW)", value=f"{rate:,.0f}원", inline=False)
    embed.add_field(name=divider,
                    value=f"⌚ 마지막 갱신: {(datetime.utcnow()+timedelta(hours=9)).strftime('%H:%M:%S')}",
                    inline=False)
    embed.set_footer(text="REZE OTC | Made by REZE")
    return embed

# ================= 본인인증 모달 =================
class VerifyModal(Modal, title="본인 인증"):
    name = TextInput(label="이름")
    phone = TextInput(label="전화번호")
    rrn = TextInput(label="주민등록번호 앞 6자리")
    bank = TextInput(label="은행명")
    account = TextInput(label="계좌번호")

    def __init__(self, action_type):
        super().__init__()
        self.action_type = action_type

    async def on_submit(self, interaction):
        owner = await bot.fetch_user(OWNER_ID)

        embed = discord.Embed(
            title="📨 본인인증 요청",
            color=0x000000
        )
        embed.add_field(name="이름", value=self.name.value, inline=False)
        embed.add_field(name="전화번호", value=self.phone.value, inline=False)
        embed.add_field(name="주민번호6자리", value=self.rrn.value, inline=False)
        embed.add_field(name="은행명", value=self.bank.value, inline=False)
        embed.add_field(name="계좌번호", value=self.account.value, inline=False)
        embed.add_field(name="요청자", value=interaction.user.mention, inline=False)

        await owner.send(embed=embed, view=OwnerDecisionView(interaction.user.id, self.action_type))
        await interaction.response.send_message("요청이 전송되었습니다.", ephemeral=True)

# ================= 통신사 선택 =================
class CarrierView(View):
    def __init__(self, action_type):
        super().__init__(timeout=60)
        self.action_type = action_type

        self.add_item(
            Select(
                placeholder="통신사를 선택하세요",
                options=[
                    discord.SelectOption(label="SKT"),
                    discord.SelectOption(label="KT"),
                    discord.SelectOption(label="LG U+")
                ]
            )
        )

        self.children[0].callback = self.select_callback

    async def select_callback(self, interaction):
        await interaction.response.send_modal(VerifyModal(self.action_type))

# ================= 오너 승인/거부 =================
class OwnerDecisionView(View):
    def __init__(self, user_id, action_type):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.action_type = action_type

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction, button):
        user = await bot.fetch_user(self.user_id)
        await user.send("✅ 본인인증이 승인되었습니다.")
        await interaction.response.send_message("승인 완료", ephemeral=True)

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction, button):
        user = await bot.fetch_user(self.user_id)
        await user.send("❌ 본인인증이 거부되었습니다.")
        await interaction.response.send_message("거부 완료", ephemeral=True)

# ================= 패널 버튼 =================
class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    async def require_verify(self, interaction):
        embed = discord.Embed(
            title="📱 본인인증 필요",
            description="서비스 이용을 위해 본인인증을 진행해주세요.\n통신사를 선택하세요.",
            color=0x000000
        )

        await interaction.response.send_message(
            embed=embed,
            view=CarrierView("본인인증"),
            ephemeral=True
        )

    @discord.ui.button(label="충전", style=discord.ButtonStyle.primary, row=0)
    async def charge(self, interaction, button):
        if not is_verified(interaction.user.id):
            await self.require_verify(interaction)
            return

        await interaction.response.send_message("충전 기능 실행", ephemeral=True)

    @discord.ui.button(label="송금", style=discord.ButtonStyle.secondary, row=0)
    async def send(self, interaction, button):
        if not is_verified(interaction.user.id):
            await self.require_verify(interaction)
            return

        await interaction.response.send_message("송금 기능 실행", ephemeral=True)

    @discord.ui.button(label="계산", style=discord.ButtonStyle.success, row=0)
    async def calc(self, interaction, button):
        if not is_verified(interaction.user.id):
            await self.require_verify(interaction)
            return

        await interaction.response.send_message("계산 기능 실행", ephemeral=True)

    @discord.ui.button(label="정보", style=discord.ButtonStyle.secondary, row=0)
    async def info(self, interaction, button):
        if not is_verified(interaction.user.id):
            await self.require_verify(interaction)
            return

        ensure_user(interaction.user.id)
        cursor.execute("SELECT balance FROM users WHERE user_id=?", (interaction.user.id,))
        balance = cursor.fetchone()[0]

        embed = discord.Embed(
            title="📋 내 정보",
            color=0x000000
        )
        embed.add_field(name="인증 상태", value="✅ 인증 완료", inline=False)
        embed.add_field(name="보유 잔액", value=f"{balance:,}원", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= 실행 =================
@bot.event
async def on_ready():
    print("봇 준비 완료")

    channel = await bot.fetch_channel(PANEL_CHANNEL_ID)
    premium, rate = get_kimchi()

    await channel.send(
        embed=create_embed(premium, rate),
        view=PanelView()
    )

bot.run(TOKEN)
