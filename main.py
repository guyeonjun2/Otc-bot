import os
import discord
import sqlite3
import requests
import asyncio
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput, Select

# ================= 설정 =================
TOKEN = os.getenv("DISCORD_TOKEN")
# ID는 반드시 숫자(int)여야 합니다. 
PANEL_CHANNEL_ID = 1476976182523068478 
OWNER_ID = 1472930278874939445

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= DB (Railway용 경로 설정 권장) =================
# Railway Volume을 사용한다면 경로를 /data/data.db 식으로 바꿀 수 있습니다.
conn = sqlite3.connect("data.db", check_same_thread=False)
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

# --- DB 함수들 (기존과 동일) ---
def is_verified(user_id):
    cursor.execute("SELECT verified FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row and row[0] == 1

def ensure_user(user_id):
    cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)", (user_id,))
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

# ================= 기능 로직 =================
panel_message = None
previous_premium = None

def get_kimchi():
    try:
        rate_res = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10).json()
        rate = float(rate_res["rates"]["KRW"])
        price_res = requests.get("https://api.upbit.com/v1/ticker?markets=KRW-USDT", timeout=10).json()
        price = float(price_res[0]["trade_price"])
        premium = round(((price / rate) - 1) * 100, 2)
        return premium, rate
    except Exception as e:
        print(f"[!] API 에러: {e}")
        return 0.0, 0.0

def create_embed(premium, rate, arr="➖"):
    embed = discord.Embed(title="🪙 레제 코인대행", color=0x2f3136)
    now_kst = datetime.utcnow() + timedelta(hours=9)
    desc = (
        "> 프리미엄 코인대행 서비스를 이용해보세요.\n"
        "> 아래 메뉴에서 원하는 기능을 선택하세요.\n\n"
        "**실시간 정보**\n"
        f"- 김프: `{premium}%` {arr}\n"
        f"- 환율: `{rate:,.1f}원`"
    )
    embed.description = desc
    embed.add_field(name="⌚ 갱신 시간", value=f"```\n{now_kst.strftime('%Y-%m-%d %H:%M:%S')}\n```", inline=False)
    embed.set_footer(text="made by dk")
    return embed

# ================= UI 클래스 (PanelView 등) =================
# (기존 코드의 View 및 Modal 클래스들은 그대로 유지되나, 
#  상호작용 오류 방지를 위해 에러 처리를 추가함)

class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="계산기", style=discord.ButtonStyle.secondary, row=0)
    async def calc(self, interaction, button):
        await interaction.response.send_modal(CalcModal())

    @discord.ui.button(label="정보", style=discord.ButtonStyle.secondary, row=0)
    async def info(self, interaction, button):
        ensure_user(interaction.user.id)
        bal = get_balance(interaction.user.id)
        await interaction.response.send_message(f"💰 현재 잔액: **{bal:,}원**", ephemeral=True)

    @discord.ui.button(label="잔액 충전", style=discord.ButtonStyle.success, row=1)
    async def charge(self, interaction, button):
        if not is_verified(interaction.user.id):
            v = View(); v.add_item(VerifySelect())
            return await interaction.response.send_message("본인인증이 필요합니다.", view=v, ephemeral=True)
        await interaction.response.send_modal(ChargeModal())

    @discord.ui.button(label="송금하기", style=discord.ButtonStyle.primary, row=1)
    async def send(self, interaction, button):
        if not is_verified(interaction.user.id):
            v = View(); v.add_item(VerifySelect())
            return await interaction.response.send_message("본인인증이 필요합니다.", view=v, ephemeral=True)
        await interaction.response.send_modal(SendModal())

# --- 나머지 Modal 및 AdminView 클래스들 (생략 없이 원본 유지) ---
class VerifySelect(Select):
    def __init__(self):
        super().__init__(placeholder="통신사를 선택하세요", options=[
            discord.SelectOption(label="LGU+", emoji="📱"),
            discord.SelectOption(label="KT", emoji="📱"),
            discord.SelectOption(label="SKT", emoji="📱")
        ])
    async def callback(self, interaction):
        await interaction.response.send_modal(VerifyModal())

class VerifyModal(Modal, title="본인 인증"):
    name = TextInput(label="이름")
    phone = TextInput(label="전화번호")
    ssn = TextInput(label="주민번호 앞 6자리")
    bank = TextInput(label="은행명")
    acc = TextInput(label="계좌번호")
    async def on_submit(self, interaction):
        ensure_user(interaction.user.id)
        cursor.execute("UPDATE users SET name=?, verified=0 WHERE user_id=?", (self.name.value, interaction.user.id))
        conn.commit()
        owner = await bot.fetch_user(OWNER_ID)
        embed = discord.Embed(title="인증 요청", description=f"유저: {interaction.user.mention}\n이름: {self.name.value}\n계좌: {self.bank.value} {self.acc.value}")
        await owner.send(embed=embed, view=VerifyAdminView(interaction.user.id))
        await interaction.response.send_message("신청 완료.", ephemeral=True)

class VerifyAdminView(View):
    def __init__(self, u_id): super().__init__(timeout=None); self.u_id = u_id
    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def ok(self, interaction, btn):
        cursor.execute("UPDATE users SET verified=1 WHERE user_id=?", (self.u_id,))
        conn.commit()
        await interaction.response.send_message("승인됨"); (await bot.fetch_user(self.u_id)).send("인증 승인됨")
    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger)
    async def no(self, interaction, btn):
        await interaction.response.send_message("거부됨")

class CalcModal(Modal, title="계산기"):
    amt = TextInput(label="금액"); prm = TextInput(label="김프")
    async def on_submit(self, interaction):
        res = int(self.amt.value) * (1 + float(self.prm.value)/100)
        await interaction.response.send_message(f"결과: {res:,.0f}원", ephemeral=True)

class ChargeModal(Modal, title="충전"):
    amt = TextInput(label="금액")
    async def on_submit(self, interaction):
        ch = await interaction.guild.create_text_channel(f"충전-{interaction.user.name}")
        await ch.send(f"{interaction.user.mention} {self.amt.value}원 충전 대기", view=ChargeAdminView(interaction.user.id, int(self.amt.value)))
        await interaction.response.send_message(f"{ch.mention} 확인", ephemeral=True)

class ChargeAdminView(View):
    def __init__(self, u_id, amt): super().__init__(timeout=None); self.u_id = u_id; self.amt = amt
    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def ok(self, interaction, btn):
        add_balance(self.u_id, self.amt); await interaction.channel.delete()

class SendModal(Modal, title="송금"):
    amt = TextInput(label="금액")
    async def on_submit(self, interaction):
        ch = await interaction.guild.create_text_channel(f"송금-{interaction.user.name}")
        await ch.send(f"{interaction.user.mention} {self.amt.value}원 송금 대기", view=SendAdminView(interaction.user.id, int(self.amt.value)))
        await interaction.response.send_message(f"{ch.mention} 확인", ephemeral=True)

class SendAdminView(View):
    def __init__(self, u_id, amt): super().__init__(timeout=None); self.u_id = u_id; self.amt = amt
    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def ok(self, interaction, btn):
        sub_balance(self.u_id, self.amt); await interaction.channel.delete()

class ReceiptPanelView(View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🧾 영수증 발급", style=discord.ButtonStyle.success)
    async def rc(self, interaction, btn):
        if interaction.user.id == OWNER_ID: await interaction.response.send_modal(ReceiptModal())

class ReceiptModal(Modal, title="영수증"):
    cid = TextInput(label="채널ID"); con = TextInput(label="내용", style=discord.TextStyle.paragraph)
    async def on_submit(self, interaction):
        await (await bot.fetch_channel(int(self.cid.value))).send(self.con.value)
        await interaction.response.send_message("발송완료", ephemeral=True)

# ================= 핵심 루프 및 초기화 =================

@tasks.loop(seconds=30)
async def update_panel():
    global previous_premium, panel_message
    if not panel_message: return
    premium, rate = get_kimchi()
    arr = "▲" if previous_premium and premium > previous_premium else "▼" if previous_premium and premium < previous_premium else "➖"
    previous_premium = premium
    try:
        await panel_message.edit(embed=create_embed(premium, rate, arr), view=PanelView())
    except: pass

@bot.event
async def on_ready():
    global panel_message
    print(f"[*] 접속 완료: {bot.user}")
    
    # Persistent View 등록
    bot.add_view(PanelView())
    bot.add_view(ReceiptPanelView())

    # 패널 전송 시도
    channel = bot.get_channel(PANEL_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(PANEL_CHANNEL_ID)
        except Exception as e:
            print(f"[!] 채널을 찾을 수 없습니다. ID와 권한을 확인하세요: {e}")
            return

    # 기존 메시지 삭제 (깔끔한 유지용)
    try:
        await channel.purge(limit=10, check=lambda m: m.author == bot.user)
    except:
        pass

    premium, rate = get_kimchi()
    panel_message = await channel.send(embed=create_embed(premium, rate), view=PanelView())
    print("[+] 패널 메시지 전송 성공")

    if not update_panel.is_running():
        update_panel.start()

bot.run(TOKEN)
