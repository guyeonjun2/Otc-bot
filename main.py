import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
import os, asyncpg

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_USER_ID = 1472930278874939445
LOG_CHANNEL_ID = 1476976182523068478

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


# ================= DB 봇 =================

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.db = await asyncpg.create_pool(DATABASE_URL)
        async with self.db.acquire() as conn:
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance BIGINT DEFAULT 0,
                total_spent BIGINT DEFAULT 0,
                is_verified BOOLEAN DEFAULT FALSE
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS verify_requests (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                name TEXT,
                phone TEXT,
                rrn TEXT,
                bank TEXT,
                account TEXT,
                carrier TEXT,
                status TEXT DEFAULT 'pending'
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS deposit_requests (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                sender_name TEXT,
                amount BIGINT,
                status TEXT DEFAULT 'pending'
            );
            """)

        await self.tree.sync()


bot = MyBot()


# ================= 공통 유저 생성 =================

async def ensure_user(user_id):
    async with bot.db.acquire() as conn:
        u = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
        if not u:
            await conn.execute(
                "INSERT INTO users (user_id) VALUES ($1)",
                user_id
            )


# ================= 인증 승인 버튼 =================

class AdminVerifyView(View):
    def __init__(self, req_id, user_id):
        super().__init__(timeout=None)
        self.req_id = req_id
        self.user_id = user_id

    @discord.ui.button(label="✅ 인증 승인", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: Button):
        async with bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET is_verified=TRUE WHERE user_id=$1", self.user_id)
            await conn.execute("UPDATE verify_requests SET status='approved' WHERE id=$1", self.req_id)

        await interaction.response.send_message("✅ 인증 승인 완료", ephemeral=True)
        await interaction.message.delete()

    @discord.ui.button(label="❌ 인증 거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: Button):
        async with bot.db.acquire() as conn:
            await conn.execute("UPDATE verify_requests SET status='rejected' WHERE id=$1", self.req_id)

        await interaction.response.send_message("❌ 인증 거부 완료", ephemeral=True)
        await interaction.message.delete()


# ================= 인증 모달 =================

class VerifyModal(Modal):
    def __init__(self, carrier):
        super().__init__(title="본인 인증 정보 입력")
        self.carrier = carrier

        self.name = TextInput(label="이름")
        self.phone = TextInput(label="전화번호 (- 없이)")
        self.rrn = TextInput(label="주민등록번호 앞 7자리")
        self.bank = TextInput(label="은행명")
        self.account = TextInput(label="계좌번호")

        for i in [self.name, self.phone, self.rrn, self.bank, self.account]:
            self.add_item(i)

    async def on_submit(self, interaction: discord.Interaction):
        await ensure_user(interaction.user.id)

        async with bot.db.acquire() as conn:
            req_id = await conn.fetchval("""
            INSERT INTO verify_requests 
            (user_id, name, phone, rrn, bank, account, carrier)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            RETURNING id
            """,
            interaction.user.id,
            self.name.value,
            self.phone.value,
            self.rrn.value,
            self.bank.value,
            self.account.value,
            self.carrier
            )

        log_ch = await bot.fetch_channel(LOG_CHANNEL_ID)

        embed = discord.Embed(title="🛡️ 본인인증 신청")
        embed.add_field(name="유저", value=interaction.user.mention)
        embed.add_field(name="통신사", value=self.carrier, inline=False)
        embed.add_field(name="정보",
                        value=f"이름:{self.name.value}\n전화:{self.phone.value}\n주민:{self.rrn.value}\n은행:{self.bank.value}\n계좌:{self.account.value}",
                        inline=False)

        await log_ch.send(embed=embed, view=AdminVerifyView(req_id, interaction.user.id))
        await interaction.response.send_message("✅ 인증 신청 완료. 관리자 승인 대기.", ephemeral=True)


# ================= 통신사 선택 =================

class CarrierView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="SKT", style=discord.ButtonStyle.secondary)
    async def skt(self, interaction, button):
        await interaction.response.send_modal(VerifyModal("SKT"))

    @discord.ui.button(label="KT", style=discord.ButtonStyle.secondary)
    async def kt(self, interaction, button):
        await interaction.response.send_modal(VerifyModal("KT"))

    @discord.ui.button(label="LGU+", style=discord.ButtonStyle.secondary)
    async def lgu(self, interaction, button):
        await interaction.response.send_modal(VerifyModal("LGU+"))

    @discord.ui.button(label="알뜰폰", style=discord.ButtonStyle.primary)
    async def mvno(self, interaction, button):
        await interaction.response.send_message("사용 통신사를 선택하세요", view=MVNOView(), ephemeral=True)


class MVNOView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="SKT망", style=discord.ButtonStyle.secondary)
    async def skt(self, interaction, button):
        await interaction.response.send_modal(VerifyModal("알뜰폰-SKT망"))

    @discord.ui.button(label="KT망", style=discord.ButtonStyle.secondary)
    async def kt(self, interaction, button):
        await interaction.response.send_modal(VerifyModal("알뜰폰-KT망"))

    @discord.ui.button(label="LGU+망", style=discord.ButtonStyle.secondary)
    async def lgu(self, interaction, button):
        await interaction.response.send_modal(VerifyModal("알뜰폰-LGU+망"))


# ================= 메인 버튼 =================

class MainView(View):
    def __init__(self):
        super().__init__(timeout=None)

    async def check_verify(self, interaction):
        await ensure_user(interaction.user.id)
        async with bot.db.acquire() as conn:
            u = await conn.fetchrow("SELECT is_verified FROM users WHERE user_id=$1", interaction.user.id)
        return u["is_verified"]

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary)
    async def charge(self, interaction, button):
        if not await self.check_verify(interaction):
            await interaction.response.send_message("🔒 본인 인증이 필요합니다.", view=CarrierView(), ephemeral=True)
            return
        await interaction.response.send_message("충전 기능 준비중", ephemeral=True)

    @discord.ui.button(label="📤 송금", style=discord.ButtonStyle.primary)
    async def transfer(self, interaction, button):
        if not await self.check_verify(interaction):
            await interaction.response.send_message("🔒 본인 인증이 필요합니다.", view=CarrierView(), ephemeral=True)
            return
        await interaction.response.send_message("송금 기능 준비중", ephemeral=True)


# ================= OTC 명령어 =================

@bot.tree.command(name="otc")
async def otc(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_USER_ID:
        return
    await interaction.response.send_message("🪙 OTC 자판기", view=MainView())


if TOKEN:
    bot.run(TOKEN)
