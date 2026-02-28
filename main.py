import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput, Select
import os
import asyncpg
import aiohttp
from datetime import datetime, timedelta

# ====== [1. 설정 및 ID] ======
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_USER_ID = 1472930278874939445
LOG_CHANNEL_ID = 1476976182523068478 # 관리자 전용 채널 (인증 로그 및 패널용)

RANKS = {
    50000000: 1476788776658534501, 10000000: 1476788690696011868, 
    3000000: 1476788607569104946, 1000000: 1476788508076146689,  
    500000: 1476788430850752532, 300000: 1476788381940973741,   
    100000: 1476788291448865019, 0: 1476788194346274936         
}

stock_amount = "현재 자판기 미완성"
current_k_premium = "데이터 수집 중..."
last_update_time = "대기 중"
last_otc_message = None 

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 

# ====== [2. 관리자 전용: 인증 대기열 시스템] ======

class VerifyListSelect(Select):
    def __init__(self, bot, pending_users):
        self.bot = bot
        options = [
            discord.SelectOption(label=f"유저: {u['user_id']}", description="이 유저를 선택하여 승인/거절 결정", value=str(u['user_id']))
            for u in pending_users
        ]
        super().__init__(placeholder="인증 대기 중인 유저를 선택하세요", options=options)

    async def callback(self, interaction: discord.Interaction):
        target_id = int(self.values[0])
        embed = discord.Embed(title="🛡️ 선택된 유저 인증 처리", description=f"대상: <@{target_id}>", color=discord.Color.blue())
        view = View()
        
        # 승인 버튼
        btn_approve = Button(label="최종 승인", style=discord.ButtonStyle.green)
        async def approve_cb(intact: discord.Interaction):
            async with self.bot.db.acquire() as conn:
                await conn.execute("UPDATE users SET is_verified = TRUE WHERE user_id = $1", target_id)
            await intact.response.send_message(f"✅ <@{target_id}> 승인 완료", ephemeral=True)
            try: await (await self.bot.fetch_user(target_id)).send("🎊 본인인증이 승인되었습니다!")
            except: pass
        btn_approve.callback = approve_cb

        # 거절 버튼
        btn_reject = Button(label="인증 거절", style=discord.ButtonStyle.red)
        async def reject_cb(intact: discord.Interaction):
            await intact.response.send_message(f"❌ <@{target_id}> 거절 완료", ephemeral=True)
        btn_reject.callback = reject_cb

        view.add_item(btn_approve); view.add_item(btn_reject)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# ====== [3. 관리자 전용: 메인 관리 패널] ======

class AdminPanelView(View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="📦 재고 수정", style=discord.ButtonStyle.primary, row=0)
    async def edit_stock(self, interaction: discord.Interaction, button: Button):
        modal = Modal(title="재고 수정")
        text = TextInput(label="문구", default=stock_amount, style=discord.TextStyle.paragraph)
        modal.add_item(text)
        async def cb(intact):
            global stock_amount; stock_amount = text.value
            await intact.response.send_message("재고 수정 완료", ephemeral=True)
        modal.on_submit = cb
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="💰 잔액 조절", style=discord.ButtonStyle.secondary, row=0)
    async def edit_balance(self, interaction: discord.Interaction, button: Button):
        modal = Modal(title="잔액 조절")
        u_id = TextInput(label="유저 ID"); u_amt = TextInput(label="조절 금액 (+/-)")
        modal.add_item(u_id); modal.add_item(u_amt)
        async def cb(intact):
            async with self.bot.db.acquire() as conn:
                await conn.execute("UPDATE users SET balance = balance + $2 WHERE user_id = $1", int(u_id.value), int(u_amt.value))
            await intact.response.send_message("처리 완료", ephemeral=True)
        modal.on_submit = cb
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="📋 인증 대기목록", style=discord.ButtonStyle.success, row=1)
    async def list_verify(self, interaction: discord.Interaction, button: Button):
        async with self.bot.db.acquire() as conn:
            # 인증 안된 유저 중 최근 활동 유저들 추출
            pending = await conn.fetch("SELECT user_id FROM users WHERE is_verified = FALSE LIMIT 25")
        
        if not pending:
            return await interaction.response.send_message("현재 인증 대기 중인 유저가 없습니다.", ephemeral=True)
        
        view = View(); view.add_item(VerifyListSelect(self.bot, pending))
        await interaction.response.send_message("인증 대기 리스트입니다:", view=view, ephemeral=True)

    @discord.ui.button(label="🔓 인증 초기화", style=discord.ButtonStyle.danger, row=1)
    async def reset_verify(self, interaction: discord.Interaction, button: Button):
        modal = Modal(title="인증 강제 해제")
        u_id = TextInput(label="유저 ID")
        modal.add_item(u_id)
        async def cb(intact):
            async with self.bot.db.acquire() as conn:
                await conn.execute("UPDATE users SET is_verified = FALSE WHERE user_id = $1", int(u_id.value))
            await intact.response.send_message("초기화 완료", ephemeral=True)
        modal.on_submit = cb
        await interaction.response.send_modal(modal)

# ====== [4. 봇 메인 명령어 로직] ======

# (MyBot 클래스 내 setup_hook 등은 기존과 동일하되 명령어 추가)

@bot.tree.command(name="관리자", description="운영진 전용 관리 패널 호출 (지정 채널 전용)")
async def admin_panel(interaction: discord.Interaction):
    # 채널 체크 + 관리자 ID 체크
    if interaction.channel_id != LOG_CHANNEL_ID:
        return await interaction.response.send_message("❌ 이 명령어는 관리자 전용 채널에서만 사용할 수 있습니다.", ephemeral=True)
    if interaction.user.id != ADMIN_USER_ID:
        return await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)
    
    embed = discord.Embed(title="⚙️ 레제 운영진 관리 시스템", color=discord.Color.dark_gray())
    embed.add_field(name="📦 실시간 제어", value="재고 문구 및 시세 갱신 제어", inline=True)
    embed.add_field(name="🛡️ 유저 관리", value="인증 승인/거절 및 잔액 강제 조정", inline=True)
    
    await interaction.response.send_message(embed=embed, view=AdminPanelView(bot), ephemeral=True)

# (기존 /otc 명령어 및 OTCView 인증 체크 로직 포함...)
