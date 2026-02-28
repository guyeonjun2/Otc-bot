import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
import os
import datetime
import asyncpg

# ====== 설정 ======
TOKEN = os.getenv("TOKEN")
DATABASE_URL = "postgresql://postgres:ftdLqBhVQzpuEqKhtwUILzuOepuOoMGG@centerbeam.proxy.rlwy.net:30872/railway"

ADMIN_USER_ID = 1472930278874939445  # 관리자 ID
LOG_CHANNEL_ID = 1476976182523068478 # 로그 채널 ID
ALLOWED_GUILD_IDS = [1476576109436076085, 1476258189740867728]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True # DM 발송 및 유저 정보를 위해 필수
bot = commands.Bot(command_prefix="!", intents=intents)

# 실시간 정보
stock_amount = "현재 자판기 미완성"
kimchi_premium = "현재 자판기 미완성"

# ================= DB 초기화 =================
async def create_tables():
    async with bot.db.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            balance NUMERIC DEFAULT 0,
            total_spent NUMERIC DEFAULT 0
        );
        """)
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN total_spent NUMERIC DEFAULT 0;")
        except:
            pass
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS deposit_requests (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            amount NUMERIC,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

# ================= 관리자 승인 뷰 (DM 발송 추가) =================
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
        await interaction.response.defer(ephemeral=True) 
        
        try:
            async with bot.db.acquire() as conn:
                async with conn.transaction():
                    record = await conn.fetchrow("""
                        SELECT id FROM deposit_requests 
                        WHERE user_id=$1 AND amount=$2 AND status='pending' 
                        ORDER BY id DESC LIMIT 1
                    """, self.user_id, self.amount)

                    if not record:
                        await interaction.followup.send("❌ 이미 처리된 요청입니다.", ephemeral=True)
                        return

                    await conn.execute("UPDATE deposit_requests SET status='approved' WHERE id=$1", record["id"])
                    await conn.execute("""
                        INSERT INTO users (user_id, balance, total_spent)
                        VALUES ($1, $2::numeric, $2::numeric)
                        ON CONFLICT (user_id)
                        DO UPDATE SET 
                            balance = users.balance + EXCLUDED.balance,
                            total_spent = users.total_spent + EXCLUDED.total_spent
                    """, self.user_id, self.amount)

            # --- [DM 발송 로직 추가] ---
            target_user = await bot.fetch_user(self.user_id)
            if target_user:
                try:
                    dm_embed = discord.Embed(
                        title="💰 충전 완료 안내",
                        description=f"안녕하세요, **{target_user.name}**님!\n신청하신 충전 요청이 승인되었습니다.",
                        color=discord.Color.green(),
                        timestamp=datetime.datetime.now()
                    )
                    dm_embed.add_field(name="💵 충전 금액", value=f"**{self.amount:,.0f}원**", inline=True)
                    dm_embed.add_field(name="✅ 처리 상태", value="승인 완료 (즉시 이용 가능)", inline=True)
                    dm_embed.set_footer(text="레제 코인 대행 | 이용해 주셔서 감사합니다.")
                    
                    await target_user.send(embed=dm_embed)
                    dm_status = " (DM 발송 성공)"
                except:
                    dm_status = " (DM 발송 실패 - 차단됨)"
            # ---------------------------

            await interaction.message.edit(content=f"✅ <@{self.user_id}>님 {self.amount:,.0f}원 승인 완료{dm_status}", embed=None, view=None)
            await interaction.followup.send(f"✅ 승인 및 DM 발송을 완료했습니다.", ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"❌ 오류 발생: {e}", ephemeral=True)

    @discord.ui.button(label="❌ 거절", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: Button):
        async with bot.db.acquire() as conn:
            await conn.execute("UPDATE deposit_requests SET status='rejected' WHERE user_id=$1 AND amount=$2", self.user_id, self.amount)
        
        # 거절 시에도 DM 알림 (선택사항)
        try:
            target_user = await bot.fetch_user(self.user_id)
            await target_user.send(f"❌ 신청하신 {self.amount:,.0f}원 충전 요청이 거절되었습니다. 고객센터로 문의해주세요.")
        except:
            pass

        await interaction.response.edit_message(content="❌ 거절 처리됨", embed=None, view=None)

# ================= 충전 모달 =================
class DepositModal(Modal, title="💰 충전 신청"):
    amount = TextInput(label="충전 금액", placeholder="숫자만 입력 (예: 10000)")

    async def on_submit(self, interaction: discord.Interaction):
        if not self.amount.value.isdigit():
            await interaction.response.send_message("숫자만 입력해주세요.", ephemeral=True)
            return

        amount = int(self.amount.value)
        async with bot.db.acquire() as conn:
            await conn.execute("INSERT INTO deposit_requests (user_id, amount) VALUES ($1, $2)", interaction.user.id, amount)

        await interaction.response.send_message(f"✅ {amount:,.0f}원 충전 신청이 완료되었습니다!\n관리자가 확인 후 DM으로 알려드릴게요.", ephemeral=True)

        log_channel = interaction.client.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(title="🔔 충전 요청", color=discord.Color.red())
            embed.add_field(name="신청자", value=f"{interaction.user.mention} ({interaction.user.id})")
            embed.add_field(name="금액", value=f"{amount:,.0f}원")
            await log_channel.send(embed=embed, view=ApproveView(interaction.user.id, amount))

# ================= 메인 메뉴 (OTCView) =================
class OTCView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary)
    async def charge(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DepositModal())

    @discord.ui.button(label="📤 송금", style=discord.ButtonStyle.primary)
    async def send(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("📤 송금은 준비 중입니다.", ephemeral=True)

    @discord.ui.button(label="📊 정보", style=discord.ButtonStyle.secondary)
    async def info(self, interaction: discord.Interaction, button: Button):
        async with bot.db.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", interaction.user.id)
            if not user:
                await conn.execute("INSERT INTO users (user_id, balance, total_spent) VALUES ($1, 0, 0)", interaction.user.id)
                balance, total_spent = 0, 0
            else:
                balance = user.get('balance', 0)
                total_spent = user.get('total_spent', 0)

        embed = discord.Embed(title=f"👤 {interaction.user.display_name}님의 정보", color=discord.Color.blue())
        embed.add_field(name="💰 현재 잔액", value=f"**{balance:,.0f}원**", inline=False)
        embed.add_field(name="📊 누적 이용액", value=f"**{total_spent:,.0f}원**", inline=False)
        embed.set_footer(text="레제 코인 대행 | 신속한 대행")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🧮 계산기", style=discord.ButtonStyle.secondary)
    async def calc(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("🧮 계산기 기능은 추후 업데이트됩니다.", ephemeral=True)

    @discord.ui.button(label="❓ 도움말", style=discord.ButtonStyle.secondary)
    async def help(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("도움말: 충전 후 관리자 승인을 기다리세요!", ephemeral=True)

# ================= 실행부 =================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        bot.db = await asyncpg.create_pool(DATABASE_URL)
        await create_tables()
        bot.add_view(OTCView())
        print("DB 및 메뉴 초기화 완료")
    except Exception as e:
        print(f"Error: {e}")

@bot.command()
async def otc(ctx):
    embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
    embed.add_field(name="💰 실시간 재고", value=stock_amount, inline=False)
    embed.add_field(name="📈 실시간 김프", value=kimchi_premium, inline=False)
    await ctx.send(embed=embed, view=OTCView())

if TOKEN:
    bot.run(TOKEN)
