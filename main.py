import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
import os
import datetime
import asyncpg

# ====== 설정 (기존 정보 유지) ======
TOKEN = os.getenv("TOKEN")
DATABASE_URL = "postgresql://postgres:ftdLqBhVQzpuEqKhtwUILzuOepuOoMGG@centerbeam.proxy.rlwy.net:30872/railway"

ADMIN_USER_ID = 1472930278874939445  # 관리자 ID
LOG_CHANNEL_ID = 1476976182523068478 # 로그 채널 ID

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.db = await asyncpg.create_pool(DATABASE_URL)
        await create_tables(self.db)
        await self.tree.sync()
        print("✅ 슬래시 명령어 및 최신 도움말 동기화 완료!")

bot = MyBot()

# 실시간 정보 변수
stock_amount = "현재 자판기 미완성"
kimchi_premium = "현재 자판기 미완성"
last_update = "현재 자판기 미완성"

# ================= DB 초기화 =================
async def create_tables(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            balance NUMERIC DEFAULT 0
        );
        """)
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
                        INSERT INTO users (user_id, balance)
                        VALUES ($1, $2::numeric)
                        ON CONFLICT (user_id)
                        DO UPDATE SET balance = users.balance + EXCLUDED.balance
                    """, self.user_id, self.amount)

            target_user = await bot.fetch_user(self.user_id)
            if target_user:
                try:
                    embed = discord.Embed(title="💰 충전 완료 안내", color=discord.Color.green())
                    embed.description = f"신청하신 **{self.amount:,.0f}원**이 성공적으로 충전되었습니다!"
                    await target_user.send(embed=embed)
                except:
                    pass

            await interaction.message.edit(content=f"✅ <@{self.user_id}>님 {self.amount:,.0f}원 승인 완료", embed=None, view=None)
            await interaction.followup.send(f"승인 처리가 완료되었습니다.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"오류 발생: {e}", ephemeral=True)

    @discord.ui.button(label="❌ 거절", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: Button):
        async with bot.db.acquire() as conn:
            await conn.execute("UPDATE deposit_requests SET status='rejected' WHERE user_id=$1 AND amount=$2", self.user_id, self.amount)
        await interaction.response.edit_message(content="❌ 요청이 거절되었습니다.", embed=None, view=None)

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

        await interaction.response.send_message(f"✅ {amount:,.0f}원 충전 신청 완료!\n관리자 확인 후 DM으로 안내됩니다.", ephemeral=True)

        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(title="🔔 충전 요청 발생", color=discord.Color.red())
            embed.add_field(name="신청자", value=f"{interaction.user.mention}")
            embed.add_field(name="금액", value=f"{amount:,.0f}원")
            await log_channel.send(embed=embed, view=ApproveView(interaction.user.id, amount))

# ================= 메인 OTC 뷰 (도움말 완전 수정 버전) =================
class OTCView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary)
    async def charge(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DepositModal())

    @discord.ui.button(label="📤 송금", style=discord.ButtonStyle.primary)
    async def send(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("📤 송금 기능 준비 중입니다.", ephemeral=True)

    @discord.ui.button(label="📊 정보", style=discord.ButtonStyle.secondary)
    async def info(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        async with bot.db.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", interaction.user.id)
            balance = user.get('balance', 0) if user else 0
            if not user:
                await conn.execute("INSERT INTO users (user_id, balance) VALUES ($1, 0)", interaction.user.id)

        embed = discord.Embed(title=f"👤 {interaction.user.display_name}님의 정보", color=discord.Color.blue())
        embed.add_field(name="💰 현재 잔액", value=f"**{balance:,.0f}원**", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="🧮 계산기", style=discord.ButtonStyle.secondary)
    async def calc(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("🧮 계산기 기능은 업데이트 예정입니다.", ephemeral=True)

    @discord.ui.button(label="❓ 도움말", style=discord.ButtonStyle.secondary)
    async def help(self, interaction: discord.Interaction, button: Button):
        # 요청하신 디자인과 상세 문구 반영
        embed = discord.Embed(
            title="신속한 대행 | 레제 코인대행", 
            description="**이용을 위한 간편 도움말**", 
            color=discord.Color.orange()
        )
        # 충전 설명
        embed.add_field(
            name="• (💰) 충전", 
            value="충전 요청을 한 후 관리자를 기다려주시면 관리자가 디엠으로 계좌를 보낼겁니다 그럼 돈을 보내고 이중창을 하시고 기다려주시면 됩니다.", 
            inline=False
        )
        # 정보 설명
        embed.add_field(
            name="• (📊) 정보", 
            value="현재 자신의 금액이 얼마나 있는지 확인할 수 있습니다.", 
            inline=False
        )
        # 송금 설명
        embed.add_field(
            name="• (📤) 송금", 
            value="코인 송금을 할 수 있는 버튼입니다.", 
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= 슬래시 명령어 =================
@bot.tree.command(name="otc", description="레제 코인대행 메뉴를 호출합니다.")
async def otc_slash(interaction: discord.Interaction):
    embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
    embed.add_field(name="💰 실시간 재고", value=stock_amount, inline=False)
    embed.add_field(name="📈 실시간 김프", value=kimchi_premium, inline=False)
    embed.add_field(name="🕒 마지막 갱신", value=last_update, inline=False)
    embed.set_footer(text="신속한 대행 | 레제 코인대행")
    await interaction.response.send_message(embed=embed, view=OTCView())

if TOKEN:
    bot.run(TOKEN)
