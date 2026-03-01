import os
import discord
import sqlite3
import requests
import asyncio # 비동기 대기용 추가
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput, Select

# 환경 변수 및 설정
TOKEN = os.getenv("DISCORD_TOKEN")
PANEL_CHANNEL_ID = 1476976182523068478
OWNER_ID = 1472930278874939445

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= DB =================
conn = sqlite3.connect("data.db", check_same_thread=False) # 스레드 안전성 확보
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

# ================= UI & 김프 =================
panel_message = None
previous_premium = None

def get_kimchi():
    try:
        # 타임아웃을 넉넉히 잡고 에러 발생 시 기본값 반환
        rate_res = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10).json()
        rate = float(rate_res["rates"]["KRW"])
        
        price_res = requests.get("https://api.upbit.com/v1/ticker?markets=KRW-USDT", timeout=10).json()
        price = float(price_res[0]["trade_price"])
        
        premium = round(((price / rate) - 1) * 100, 2)
        return premium, rate
    except Exception as e:
        print(f"API 호출 오류: {e}")
        return 0.0, 0.0

def arrow(cur, prev):
    if prev is None or cur == prev: return "➖"
    if cur > prev: return "▲"
    if cur < prev: return "▼"
    return "➖"

def create_embed(premium, rate, arr):
    embed = discord.Embed(title="🪙 레제 코인대행", color=0x2f3136)
    
    # KST (한국 시간) 계산
    now_kst = datetime.utcnow() + timedelta(hours=9)
    
    desc = (
        "> 프리미엄 코인대행 서비스를 이용해보세요.\n"
        "> 아래 메뉴에서 원하는 기능을 선택하세요.\n\n"
        "**실시간 정보**\n"
        f"- 김프: `{premium}%` {arr}\n"
        f"- 환율: `{rate:,.1f}원`" # 천단위 콤마 추가
    )
    embed.description = desc
    
    embed.add_field(name="⌚ 갱신 시간", 
                    value=f"```\n{now_kst.strftime('%Y-%m-%d %H:%M:%S')}\n```", 
                    inline=False)
    
    embed.set_footer(text="made by dk")
    return embed

@tasks.loop(seconds=30)
async def update_panel():
    global previous_premium, panel_message
    if panel_message is None:
        return

    premium, rate = get_kimchi()
    arr = arrow(premium, previous_premium)
    previous_premium = premium
    
    try:
        await panel_message.edit(embed=create_embed(premium, rate, arr), view=PanelView())
    except Exception as e:
        print(f"패널 업데이트 오류: {e}")

# ================= 관리자 체크 =================
async def admin_only(interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(
            "어딜 감히 꼼수를 쓸려고 ㅎㅎ 안되지",
            ephemeral=True
        )
        return False
    return True

# ================= 인증 (모달/뷰) =================

class VerifySelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="LGU+", emoji="📱"),
            discord.SelectOption(label="KT", emoji="📱"),
            discord.SelectOption(label="SKT", emoji="📱"),
        ]
        super().__init__(placeholder="통신사를 선택하세요", options=options)

    async def callback(self, interaction):
        await interaction.response.send_modal(VerifyModal())

class VerifyModal(Modal, title="본인 인증"):
    name = TextInput(label="이름", placeholder="홍길동")
    phone = TextInput(label="전화번호", placeholder="010-1234-5678")
    ssn = TextInput(label="주민등록번호 앞 6자리", max_length=6, placeholder="000101")
    bank = TextInput(label="은행명", placeholder="국민은행")
    account = TextInput(label="계좌번호", placeholder="123-456-789012")

    async def on_submit(self, interaction: discord.Interaction):
        ensure_user(interaction.user.id)
        cursor.execute("UPDATE users SET name=?, verified=0 WHERE user_id=?",
                       (self.name.value, interaction.user.id))
        conn.commit()

        embed = discord.Embed(title="본인인증 요청", color=0x5865F2)
        embed.add_field(name="신청자", value=interaction.user.mention)
        embed.add_field(name="이름", value=self.name.value)
        embed.add_field(name="전화번호", value=self.phone.value)
        embed.add_field(name="주민등록번호 앞6자리", value=self.ssn.value)
        embed.add_field(name="은행명", value=self.bank.value)
        embed.add_field(name="계좌번호", value=self.account.value)

        try:
            owner = await bot.fetch_user(OWNER_ID)
            await owner.send(embed=embed, view=VerifyAdminView(interaction.user.id))
            await interaction.response.send_message("본인인증 요청이 전송되었습니다.", ephemeral=True)
        except:
            await interaction.response.send_message("관리자에게 메시지를 보낼 수 없습니다.", ephemeral=True)

class VerifyAdminView(View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction, button):
        if not await admin_only(interaction): return
        cursor.execute("UPDATE users SET verified=1 WHERE user_id=?", (self.user_id,))
        conn.commit()
        try:
            user = await bot.fetch_user(self.user_id)
            await user.send("✅ 본인인증이 승인되었습니다.")
        except: pass
        await interaction.response.send_message("승인 완료", ephemeral=True)

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction, button):
        if not await admin_only(interaction): return
        try:
            user = await bot.fetch_user(self.user_id)
            await user.send("❌ 본인인증이 거부되었습니다.")
        except: pass
        await interaction.response.send_message("거부 완료", ephemeral=True)

# ================= 패널 (메인 UI) =================

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
            await interaction.response.send_message("본인인증이 필요합니다.", view=v, ephemeral=True)
            return
        await interaction.response.send_modal(ChargeModal())

    @discord.ui.button(label="송금하기", style=discord.ButtonStyle.primary, row=1)
    async def send(self, interaction, button):
        if not is_verified(interaction.user.id):
            v = View(); v.add_item(VerifySelect())
            await interaction.response.send_message("본인인증이 필요합니다.", view=v, ephemeral=True)
            return
        await interaction.response.send_modal(SendModal())

# ================= 모달 기능들 =================

class CalcModal(Modal, title="수익 계산기"):
    amount = TextInput(label="투자 금액 (KRW)", placeholder="예: 1000000")
    premium = TextInput(label="현재 김프 (%)", placeholder="예: 3.5")
    
    async def on_submit(self, interaction):
        try:
            amt = float(self.amount.value)
            prm = float(self.premium.value)
            res = amt * (1 + (prm/100))
            await interaction.response.send_message(f"📊 예상 회수 금액: **{res:,.0f}원** (수수료 제외)", ephemeral=True)
        except:
            await interaction.response.send_message("숫자만 정확히 입력해주세요.", ephemeral=True)

class ChargeModal(Modal, title="충전 요청"):
    amount = TextInput(label="충전 금액", placeholder="숫자만 입력하세요 (예: 10000)")

    async def on_submit(self, interaction):
        try:
            amount = int(self.amount.value)
        except:
            await interaction.response.send_message("숫자만 입력해주세요.", ephemeral=True)
            return

        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.get_member(OWNER_ID): discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }

        channel = await guild.create_text_channel(name=f"충전-{interaction.user.name}", overwrites=overwrites)
        embed = discord.Embed(title="💳 충전 요청", color=0x3498db)
        embed.add_field(name="요청자", value=interaction.user.mention)
        embed.add_field(name="금액", value=f"{amount:,}원")
        
        await channel.send(embed=embed, view=ChargeAdminView(interaction.user.id, amount))
        await interaction.response.send_message(f"{channel.mention} 채널이 생성되었습니다.", ephemeral=True)

class ChargeAdminView(View):
    def __init__(self, user_id, amount):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.amount = amount

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction, button):
        if not await admin_only(interaction): return
        add_balance(self.user_id, self.amount)
        try:
            user = await bot.fetch_user(self.user_id)
            await user.send(f"✅ {self.amount:,}원 충전이 완료되었습니다.")
        except: pass
        await interaction.response.send_message("충전 승인 완료")
        await asyncio.sleep(2)
        await interaction.channel.delete()

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction, button):
        if not await admin_only(interaction): return
        await interaction.response.send_message("충전 거부 완료")
        await asyncio.sleep(2)
        await interaction.channel.delete()

class SendModal(Modal, title="송금 요청"):
    amount = TextInput(label="송금 금액", placeholder="숫자만 입력하세요")

    async def on_submit(self, interaction):
        try:
            amount = int(self.amount.value)
        except:
            await interaction.response.send_message("숫자만 입력해주세요.", ephemeral=True)
            return

        if get_balance(interaction.user.id) < amount:
            await interaction.response.send_message("잔액이 부족합니다.", ephemeral=True)
            return

        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.get_member(OWNER_ID): discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }

        channel = await guild.create_text_channel(name=f"송금-{interaction.user.name}", overwrites=overwrites)
        embed = discord.Embed(title="💸 송금 요청", color=0xf1c40f)
        embed.add_field(name="요청자", value=interaction.user.mention)
        embed.add_field(name="금액", value=f"{amount:,}원")

        await channel.send(embed=embed, view=SendAdminView(interaction.user.id, amount))
        await interaction.response.send_message(f"{channel.mention} 채널이 생성되었습니다.", ephemeral=True)

class SendAdminView(View):
    def __init__(self, user_id, amount):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.amount = amount

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction, button):
        if not await admin_only(interaction): return
        if get_balance(self.user_id) < self.amount:
            await interaction.response.send_message("유저 잔액이 부족해 승인할 수 없습니다.", ephemeral=True)
            return
        sub_balance(self.user_id, self.amount)
        try:
            user = await bot.fetch_user(self.user_id)
            await user.send(f"✅ {self.amount:,}원 송금이 완료되었습니다.")
        except: pass
        await interaction.response.send_message("송금 승인 완료")
        await asyncio.sleep(2)
        await interaction.channel.delete()

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction, button):
        if not await admin_only(interaction): return
        await interaction.response.send_message("송금 거부 완료")
        await asyncio.sleep(2)
        await interaction.channel.delete()

# ================= 영수증 패널 =================

class ReceiptModal(Modal, title="영수증 발급"):
    channel_id = TextInput(label="전송할 채널 ID")
    content = TextInput(label="내용", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction):
        try:
            channel = await bot.fetch_channel(int(self.channel_id.value))
            await channel.send(self.content.value)
            await interaction.response.send_message("영수증 전송 완료", ephemeral=True)
        except:
            await interaction.response.send_message("채널 ID가 잘못되었거나 봇이 접근할 수 없습니다.", ephemeral=True)

class ReceiptPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🧾 영수증 발급", style=discord.ButtonStyle.success)
    async def receipt(self, interaction, button):
        if not await admin_only(interaction): return
        await interaction.response.send_modal(ReceiptModal())

# ================= READY =================

@bot.event
async def on_ready():
    global panel_message, previous_premium
    print(f"Logged in as {bot.user}")

    # Persistent View 등록 (봇 재시작 시 버튼 작동용)
    bot.add_view(PanelView())
    bot.add_view(ReceiptPanelView())

    try:
        channel = await bot.fetch_channel(PANEL_CHANNEL_ID)
        # 기존 메시지 청소 (선택사항, 패널 중복 방지)
        await channel.purge(limit=5, check=lambda m: m.author == bot.user)
        
        premium, rate = get_kimchi()
        previous_premium = premium

        panel_message = await channel.send(
            embed=create_embed(premium, rate, "➖"),
            view=PanelView()
        )
        print("메인 패널 생성 완료")
    except Exception as e:
        print(f"초기 패널 생성 실패 (ID 확인 필요): {e}")

    if not update_panel.is_running():
        update_panel.start()

    try:
        owner = await bot.fetch_user(OWNER_ID)
        await owner.send("**[관리자 전용]** 영수증 발급 패널", view=ReceiptPanelView())
    except:
        print("관리자 DM 발송 실패")

bot.run(TOKEN)
