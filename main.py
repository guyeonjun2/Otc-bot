import os
import discord
import sqlite3
import requests
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput, Select

# ================= 설정 =================
TOKEN = os.getenv("DISCORD_TOKEN")
PANEL_CHANNEL_ID = 1476976182523068478
OWNER_ID = 1472930278874939445

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= DB (기존 기능 유지) =================
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

# ================= 기능 함수 =================
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
    if cur > prev: return "🔺"
    if cur < prev: return "🔻"
    return "➖"

# ================= UI 디자인 (이미지 참고 수정) =================

def create_main_embed(premium, rate, arr):
    embed = discord.Embed(
        title="🪙 레제 코인대행",
        description="```코인대행 자판기 서비스를 이용해보세요.\n아래 메뉴에서 원하는 기능을 선택하세요.```",
        color=0x2b2d31  # 다크 테마 색상
    )
    
    # 정보 섹션 (김프/환율)
    embed.add_field(
        name="📊 시장 정보",
        value=f"> **김프:** `{premium}%` {arr}\n> **환율:** `{rate}원`",
        inline=False
    )
    
    # 업데이트 정보
    now = (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
    embed.set_footer(text=f"made by Leje | 마지막 갱신: {now}")
    return embed

class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    # 첫 번째 줄: 정보 확인용 (이미지의 공지사항/이벤트/제품목록 위치)
    @discord.ui.button(label="공지사항", style=discord.ButtonStyle.secondary, custom_id="notice_btn", row=0)
    async def notice(self, interaction, button):
        await interaction.response.send_message("📌 공지사항: 현재 정상 영업 중입니다.", ephemeral=True)

    @discord.ui.button(label="계산기", style=discord.ButtonStyle.secondary, custom_id="calc_btn", row=0)
    async def calc(self, interaction, button):
        # 기존 CalcModal이 코드에 없었으므로 간단한 안내로 대체 (필요시 추가 구현)
        await interaction.response.send_message("🧮 계산기 기능은 준비 중입니다.", ephemeral=True)

    @discord.ui.button(label="이용방법", style=discord.ButtonStyle.secondary, custom_id="guide_btn", row=0)
    async def guide(self, interaction, button):
        await interaction.response.send_message("❓ 인증 후 충전 -> 송금 순서로 이용해주세요.", ephemeral=True)

    # 두 번째 줄: 주요 거래 (이미지의 구매하기/잔액충전/내정보 위치)
    @discord.ui.button(label="송금하기", style=discord.ButtonStyle.primary, custom_id="send_btn", row=1)
    async def send(self, interaction, button):
        if not is_verified(interaction.user.id):
            view = View(); view.add_item(VerifySelect())
            await interaction.response.send_message("⚠️ 본인인증이 필요합니다.", view=view, ephemeral=True)
            return
        await interaction.response.send_modal(SendModal())

    @discord.ui.button(label="잔액 충전", style=discord.ButtonStyle.success, custom_id="charge_btn", row=1)
    async def charge(self, interaction, button):
        if not is_verified(interaction.user.id):
            view = View(); view.add_item(VerifySelect())
            await interaction.response.send_message("⚠️ 본인인증이 필요합니다.", view=view, ephemeral=True)
            return
        ensure_user(interaction.user.id)
        await interaction.response.send_modal(ChargeModal())

    @discord.ui.button(label="내 정보", style=discord.ButtonStyle.secondary, custom_id="info_btn", row=1)
    async def info(self, interaction, button):
        ensure_user(interaction.user.id)
        bal = get_balance(interaction.user.id)
        verified_status = "✅ 인증됨" if is_verified(interaction.user.id) else "❌ 미인증"
        await interaction.response.send_message(f"👤 **{interaction.user.name}**님 정보\n- 상태: {verified_status}\n- 잔액: `{bal:,}원`", ephemeral=True)

# ================= 나머지 로직 (기존 코드와 동일) =================

@tasks.loop(seconds=30)
async def update_panel():
    global previous_premium, panel_message
    if panel_message:
        premium, rate = get_kimchi()
        arr = arrow(premium, previous_premium)
        previous_premium = premium
        try:
            await panel_message.edit(embed=create_main_embed(premium, rate, arr), view=PanelView())
        except:
            pass

async def admin_only(interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("관리자 전용 권한입니다.", ephemeral=True)
        return False
    return True

# --- 인증/충전/송금 관련 Modal 및 View 클래스 (기존 로직 유지) ---
class VerifySelect(Select):
    def __init__(self):
        options = [discord.SelectOption(label="LGU+"), discord.SelectOption(label="KT"), discord.SelectOption(label="SKT")]
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
        cursor.execute("UPDATE users SET name=?, verified=0 WHERE user_id=?", (self.name.value, interaction.user.id))
        conn.commit()
        embed = discord.Embed(title="🔔 새 인증 요청", color=0xFEE75C)
        embed.add_field(name="유저", value=interaction.user.mention); embed.add_field(name="이름", value=self.name.value)
        embed.add_field(name="계좌", value=f"{self.bank.value} / {self.account.value}", inline=False)
        owner = await bot.fetch_user(OWNER_ID)
        await owner.send(embed=embed, view=VerifyAdminView(interaction.user.id))
        await interaction.response.send_message("✅ 인증 요청이 관리자에게 전달되었습니다.", ephemeral=True)

class VerifyAdminView(View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id
    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction, button):
        if not await admin_only(interaction): return
        cursor.execute("UPDATE users SET verified=1 WHERE user_id=?", (self.user_id,))
        conn.commit()
        user = await bot.fetch_user(self.user_id); await user.send("✅ 본인인증이 승인되었습니다.")
        await interaction.response.send_message("승인 처리됨", ephemeral=True)

# 충전/송금 관련 Modal은 기존과 동일하되, 디자인 가독성을 위해 임베드만 약간 정리됨
class ChargeModal(Modal, title="충전 요청"):
    amount = TextInput(label="충전 금액 (숫자만)")
    async def on_submit(self, interaction):
        amount = int(self.amount.value)
        overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False), 
                      interaction.user: discord.PermissionOverwrite(view_channel=True),
                      interaction.guild.get_member(OWNER_ID): discord.PermissionOverwrite(view_channel=True)}
        channel = await interaction.guild.create_text_channel(name=f"충전-{interaction.user.name}", overwrites=overwrites)
        embed = discord.Embed(title="💳 충전 요청", description=f"{interaction.user.mention}님의 요청", color=0x3498db)
        embed.add_field(name="금액", value=f"**{amount:,}원**")
        await channel.send(embed=embed, view=ChargeAdminView(interaction.user.id, amount))
        await interaction.response.send_message(f"📍 {channel.mention} 채널이 생성되었습니다.", ephemeral=True)

class ChargeAdminView(View):
    def __init__(self, user_id, amount):
        super().__init__(timeout=None)
        self.user_id, self.amount = user_id, amount
    @discord.ui.button(label="충전 승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction, button):
        if not await admin_only(interaction): return
        add_balance(self.user_id, self.amount)
        user = await bot.fetch_user(self.user_id); await user.send(f"✅ {self.amount:,}원이 충전되었습니다.")
        await interaction.channel.delete()

class SendModal(Modal, title="송금 요청"):
    amount = TextInput(label="송금 금액 (숫자만)")
    async def on_submit(self, interaction):
        amount = int(self.amount.value)
        if get_balance(interaction.user.id) < amount:
            await interaction.response.send_message("❌ 잔액이 부족합니다.", ephemeral=True); return
        overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                      interaction.user: discord.PermissionOverwrite(view_channel=True),
                      interaction.guild.get_member(OWNER_ID): discord.PermissionOverwrite(view_channel=True)}
        channel = await interaction.guild.create_text_channel(name=f"송금-{interaction.user.name}", overwrites=overwrites)
        embed = discord.Embed(title="💸 송금 요청", description=f"{interaction.user.mention}님의 요청", color=0xf1c40f)
        embed.add_field(name="금액", value=f"**{amount:,}원**")
        await channel.send(embed=embed, view=SendAdminView(interaction.user.id, amount))
        await interaction.response.send_message(f"📍 {channel.mention} 채널이 생성되었습니다.", ephemeral=True)

class SendAdminView(View):
    def __init__(self, user_id, amount):
        super().__init__(timeout=None)
        self.user_id, self.amount = user_id, amount
    @discord.ui.button(label="송금 완료(차감)", style=discord.ButtonStyle.success)
    async def approve(self, interaction, button):
        if not await admin_only(interaction): return
        sub_balance(self.user_id, self.amount)
        user = await bot.fetch_user(self.user_id); await user.send(f"✅ {self.amount:,}원 송금 처리가 완료되었습니다.")
        await interaction.channel.delete()

# ================= 실행부 =================
@bot.event
async def on_ready():
    global panel_message, previous_premium
    print(f"Logged in as {bot.user}")
    bot.add_view(PanelView())
    
    channel = await bot.fetch_channel(PANEL_CHANNEL_ID)
    premium, rate = get_kimchi()
    previous_premium = premium
    
    # 기존 메시지 삭제 후 새로 생성하거나 업데이트
    await channel.purge(limit=10) # 깨끗한 환경을 위해 기존 메시지 정리 (선택사항)
    panel_message = await channel.send(embed=create_main_embed(premium, rate, "➖"), view=PanelView())
    update_panel.start()

bot.run(TOKEN)
