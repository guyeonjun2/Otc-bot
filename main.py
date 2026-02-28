import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
import os
import datetime
import asyncpg

# ====== 설정 (주신 ID 반영) ======
TOKEN = os.getenv("TOKEN")
# 데이터베이스 주소 (전달해주신 주소 유지)
DATABASE_URL = "postgresql://postgres:ftdLqBhVQzpuEqKhtwUILzuOepuOoMGG@centerbeam.proxy.rlwy.net:30872/railway"

# 관리자 및 로그 채널 설정
ADMIN_USER_ID = 1472930278874939445  # 알려주신 ID 적용
LOG_CHANNEL_ID = 1476976182523068478 # 기존 로그 채널 ID

# 허용된 서버 ID
ALLOWED_GUILD_IDS = [1476576109436076085, 1476258189740867728]

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# 실시간 정보 (임시값)
stock_amount = "현재 자판기 미완성"
kimchi_premium = "현재 자판기 미완성"

# ================= DB 초기화 함수 =================
async def create_tables():
    async with bot.db.acquire() as conn:
        # 유저 테이블 (누적 금액 포함)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            balance NUMERIC DEFAULT 0,
            total_spent NUMERIC DEFAULT 0
        );
        """)
        # 기존 테이블에 컬럼이 없을 경우를 대비한 안전 코드
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN total_spent NUMERIC DEFAULT 0;")
        except:
            pass

        # 충전 요청 테이블
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS deposit_requests (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            amount NUMERIC,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

# ================= 관리자 승인 뷰 =================
class ApproveView(View):
    def __init__(self, user_id, amount):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.amount = amount

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != ADMIN_USER_ID:
            await interaction.response.send_message("❌ 관리자만 승인할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ 승인", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: Button):
        # 상호작용 실패 방지 (지연 응답)
        await interaction.response.defer(ephemeral=True)
        
        try:
            async with bot.db.acquire() as conn:
                async with conn.transaction():
                    # 대기 중인 요청 확인
                    record = await conn.fetchrow("""
                        SELECT id FROM deposit_requests 
                        WHERE user_id=$1 AND amount=$2 AND status='pending' 
                        ORDER BY id DESC LIMIT 1
                    """, self.user_id, self.amount)

                    if not record:
                        await interaction.followup.send("이미 처리된 요청입니다.", ephemeral=True)
                        return

                    # 상태 변경 및 유저 잔액/누적액 동시 업데이트
                    await conn.execute("UPDATE deposit_requests SET status='approved' WHERE id=$1", record["id"])
                    await conn.execute("""
                        INSERT INTO users (user_id, balance, total_spent)
                        VALUES ($1, $2, $2)
                        ON CONFLICT (user_id)
                        DO UPDATE SET 
                            balance = users.balance + EXCLUDED.balance,
                            total_spent = users.total_spent + EXCLUDED.total_spent
                    """, self.user_id, self.amount)

            await interaction.message.edit(content=f"✅ <@{self.user_id}>님 {self.amount:,.0f}원 승인 완료", embed=None, view=None)
            await interaction.followup.send("성공적으로 승인되었습니다.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"오류 발생: {e}", ephemeral=True)

    @discord.ui.button(label="❌ 거절", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: Button):
        async with bot.db.acquire() as conn:
            await conn.execute("UPDATE deposit_requests SET status='rejected' WHERE user_id=$1 AND amount=$2", self.user_id, self.amount)
        await interaction.response.edit_message(content="❌ 거절됨", embed=None, view=None)

# ================= 충전 입력 창 =================
class DepositModal(Modal, title="💰 충전 신청"):
    amount = TextInput(label="충전 금액", placeholder="숫자만 입력 (예: 10000)")

    async def on_submit(self, interaction: discord.Interaction):
        if not self.amount.value.isdigit():
            await interaction.response.send_message("숫자만 입력 가능합니다.", ephemeral=True)
            return

        amount = float(self.amount.value)
        async with bot.db.acquire() as conn:
            await conn.execute("INSERT INTO deposit_requests (user_id, amount) VALUES ($1, $2)", interaction.user.id, amount)

        await interaction.response.send_message(f"✅ {amount:,.0f}원 충전 신청 완료!", ephemeral=True)

        log_channel = interaction.client.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(title="🔔 충전 요청 발생", color=discord.Color.red())
            embed.add_field(name="신청자", value=f"{interaction.user.mention}")
            embed.add_field(name="금액", value=f"{amount:,.0f}원")
            await log_channel.send(embed=embed, view=ApproveView(interaction.user.id, amount))

# ================= 메인 버튼 메뉴 =================
class OTCView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary)
    async def charge(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DepositModal())

    @discord.ui.button(label="📊 정보", style=discord.ButtonStyle.secondary)
    async def info(self, interaction: discord.Interaction, button: Button):
        async with bot.db.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", interaction.user.id)
            if not user:
                # 유저 데이터가 없으면 새로 생성
                await conn.execute("INSERT INTO users (user_id, balance, total_spent) VALUES ($1, 0, 0)", interaction.user.id)
                balance, total_spent = 0, 0
            else:
                balance = user.get('balance', 0)
                total_spent = user.get('total_spent', 0)

        # 정보 임베드 (사진 스타일)
        embed = discord.Embed(title=f"👤 {interaction.user.display_name}님의 정보", color=discord.Color.blue())
        embed.add_field(name="💰 현재 잔액", value=f"**{balance:,.0f}원**", inline=False)
        embed.add_field(name="📊 누적 이용액", value=f"**{total_spent:,.0f}원**", inline=False)
        embed.set_footer(text="레제 코인 대행 | 신속한 대행")
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= 실행부 =================
@bot.event
async def on_ready():
    print(f"Logged in: {bot.user}")
    try:
        bot.db = await asyncpg.create_pool(DATABASE_URL)
        await create_tables()
        bot.add_view(OTCView()) # 봇이 꺼졌다 켜져도 버튼 작동 유지
        print("DB 및 버튼 초기화 완료")
    except Exception as e:
        print(f"초기화 에러: {e}")

@bot.command()
async def otc(ctx):
    embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
    embed.add_field(name="💰 실시간 재고", value=stock_amount, inline=False)
    embed.add_field(name="📈 실시간 김프", value=kimchi_premium, inline=False)
    await ctx.send(embed=embed, view=OTCView())

if TOKEN:
    bot.run(TOKEN)
