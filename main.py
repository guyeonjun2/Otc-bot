import discord
from discord.ext import commands
import os
import datetime

# ====== 환경변수 & 로그 채널 ======
TOKEN = os.getenv("TOKEN")
LOG_CHANNEL_ID = 1476976182523068478  # ⚠️ 여기를 로그 채널 ID로 바꿔주세요

# ====== 인텐트 설정 ======
intents = discord.Intents.default()
intents.message_content = True  # Prefix 명령어 동작 필수

bot = commands.Bot(command_prefix="!", intents=intents)

# ====== 실시간 값 (예시) ======
stock_amount = "5,000,000원"
kimchi_premium = "1.14%"
last_update = "방금 전"

# ====== 버튼 UI ======
class OTCView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # View 만료 안 됨

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary)
    async def charge(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "✅ 충전 요청이 접수되었습니다. 잠시만 기다려주세요.",
            ephemeral=True
        )

        # 로그 채널 알림
        log_channel = interaction.client.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="💰 충전 요청 알림",
                color=discord.Color.red(),
                timestamp=datetime.datetime.now()
            )
            embed.add_field(
                name="👤 요청자",
                value=f"{interaction.user} ({interaction.user.id})",
                inline=False
            )
            embed.add_field(
                name="📍 서버",
                value=interaction.guild.name,
                inline=False
            )
            await log_channel.send(embed=embed)

    @discord.ui.button(label="📤 송금", style=discord.ButtonStyle.primary)
    async def send(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "📤 송금 접수 요청이 접수되었습니다.",
            ephemeral=True
        )

    @discord.ui.button(label="📊 정보", style=discord.ButtonStyle.secondary)
    async def info(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "📊 OTC 운영 정보입니다.",
            ephemeral=True
        )

    @discord.ui.button(label="🧮 계산기", style=discord.ButtonStyle.secondary)
    async def calc(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "🧮 계산기 기능은 추후 업데이트됩니다.",
            ephemeral=True
        )

    @discord.ui.button(label="❓ 도움말", style=discord.ButtonStyle.secondary)
    async def help(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="❓ OTC 도움말",
            description="레제 코인대행 사용 안내입니다.",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="💰 충전",
            value="충전 버튼을 누른 후 관리자를 기다려주세요 [아마 디엠 올거].",
            inline=False
        )
        embed.add_field(
            name="📤 송금",
            value="입금 확인 후 송금 버튼을 누른 후 코인 선택 후 송금하기 클릭 [현재는 수동].",
            inline=False
        )
        embed.add_field(
            name="🧮 계산기",
            value="계산기 기능은 추후 업데이트 예정입니다.",
            inline=False
        )
        embed.set_footer(text="레제 코인 대행 | 신속한 대행")

        # followup 사용 → Interaction 실패 방지
        await interaction.followup.send(embed=embed, ephemeral=True)

# ====== 봇 시작시 View 등록 ======
@bot.event
async def on_ready():
    print(f"봇 로그인 완료: {bot.user}")
    bot.add_view(OTCView())

# ====== !otc 명령어 ======
@bot.command()
async def otc(ctx):
    embed = discord.Embed(
        title="🪙 레재 코인 대행",
        color=discord.Color.blue()
    )
    embed.add_field(name="💰 실시간 재고", value=stock_amount, inline=False)
    embed.add_field(name="📈 실시간 김프", value=kimchi_premium, inline=False)
    embed.add_field(name="⏰ 마지막 갱신", value=last_update, inline=False)
    embed.set_footer(text="24시간 운영 | 안전 OTC")
    await ctx.send(embed=embed, view=OTCView())

bot.run(TOKEN)
