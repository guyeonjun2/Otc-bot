# 수정 완료된 전체 코드 내용을 문자열로 작성합니다.

code = import os
import discord
import sqlite3
import requests
from datetime import datetime, timedelta
from discord.ext import commands
from discord.ui import View, Modal, TextInput

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = 1472930278874939445
PANEL_CHANNEL_ID = 1476976182523068478

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= DB =================
conn = sqlite3.connect("data.db")
cursor = conn.cursor()

cursor.execute(\"\"\"
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    verified INTEGER DEFAULT 0
)
\"\"\")
conn.commit()

def ensure_user(user_id):
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()

def is_verified(user_id):
    ensure_user(user_id)
    cursor.execute("SELECT verified FROM users WHERE user_id=?", (user_id,))
    result = cursor.fetchone()
    return result and result[0] == 1

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
        description="신속한 코인대행 지금 이용해보세요.\\n아래 버튼들을 눌러 원하는 기능을 선택하세요.",
        color=0x000000
    )
    embed.add_field(name=divider, value="📊 실시간 시세", inline=False)
    embed.add_field(name="김프", value=f"{premium}%", inline=False)
    embed.add_field(name="환율 (USD/KRW)", value=f"{rate:,.0f}원", inline=False)
    embed.add_field(name=divider,
                    value=f"⌚ 마지막 갱신: {(datetime.utcnow()+timedelta(hours=9)).strftime('%H:%M:%S')}",
                    inline=False)
    return embed

# ================= 본인인증 =================
class VerifyModal(Modal, title="본인 인증"):
    name = TextInput(label="이름")
    phone = TextInput(label="전화번호")
    rrn = TextInput(label="주민등록번호 앞 6자리")
    bank = TextInput(label="은행명")
    account = TextInput(label="계좌번호")

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

        await owner.send(embed=embed, view=OwnerDecisionView(interaction.user.id))
        await interaction.response.send_message("요청이 전송되었습니다.", ephemeral=True)

class OwnerDecisionView(View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success, custom_id="verify_approve")
    async def approve(self, interaction, button):
        cursor.execute("UPDATE users SET verified=1 WHERE user_id=?", (self.user_id,))
        conn.commit()

        user = await bot.fetch_user(self.user_id)
        await user.send("✅ 본인인증이 승인되었습니다.")
        await interaction.response.send_message("본인인증 승인 완료", ephemeral=True)

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger, custom_id="verify_reject")
    async def reject(self, interaction, button):
        user = await bot.fetch_user(self.user_id)
        await user.send("❌ 본인인증이 거부되었습니다.")
        await interaction.response.send_message("거부 완료", ephemeral=True)

# ================= 패널 =================
class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    async def require_verify(self, interaction):
        await interaction.followup.send(
            "본인인증 후 이용 가능합니다.",
            view=VerifyStartView(),
            ephemeral=True
        )

    @discord.ui.button(label="충전", style=discord.ButtonStyle.primary, row=0, custom_id="btn_charge")
    async def charge(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        if not is_verified(interaction.user.id):
            await self.require_verify(interaction)
            return
        await interaction.followup.send("충전 기능 실행", ephemeral=True)

    @discord.ui.button(label="송금", style=discord.ButtonStyle.secondary, row=0, custom_id="btn_send")
    async def send(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        if not is_verified(interaction.user.id):
            await self.require_verify(interaction)
            return
        await interaction.followup.send("송금 기능 실행", ephemeral=True)

    @discord.ui.button(label="계산", style=discord.ButtonStyle.success, row=0, custom_id="btn_calc")
    async def calc(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        if not is_verified(interaction.user.id):
            await self.require_verify(interaction)
            return
        await interaction.followup.send("계산 기능 실행", ephemeral=True)

    @discord.ui.button(label="정보", style=discord.ButtonStyle.secondary, row=0, custom_id="btn_info")
    async def info(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        if not is_verified(interaction.user.id):
            await self.require_verify(interaction)
            return
        await interaction.followup.send("정보 기능 실행", ephemeral=True)

class VerifyStartView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="본인인증 시작", style=discord.ButtonStyle.primary)
    async def start(self, interaction, button):
        await interaction.response.send_modal(VerifyModal())

# ================= 실행 =================
@bot.event
async def on_ready():
    print("봇 준비 완료")
    bot.add_view(PanelView())
    bot.add_view(OwnerDecisionView(0))

    channel = await bot.fetch_channel(PANEL_CHANNEL_ID)
    premium, rate = get_kimchi()

    await channel.send(
        embed=create_embed(premium, rate),
        view=PanelView()
    )

bot.run(TOKEN)
"""

file_path = "/mnt/data/reze_final_code.txt"

with open(file_path, "w", encoding="utf-8") as f:
    f.write(code)

file_path
