import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
import os
import asyncpg

# ====== [1. 설정 및 ID] ======
TOKEN = os.getenv("TOKEN")
DATABASE_URL = "postgresql://postgres:ftdLqBhVQzpuEqKhtwUILzuOepuOoMGG@centerbeam.proxy.rlwy.net:30872/railway"

ADMIN_USER_ID = 1472930278874939445
LOG_CHANNEL_ID = 1476976182523068478

RANKS = {
    50000000: 1476788776658534501, 10000000: 1476788690696011868, 
    3000000: 1476788607569104946, 1000000: 1476788508076146689,  
    500000: 1476788430850752532, 300000: 1476788381940973741,   
    100000: 1476788291448865019, 0: 1476788194346274936         
}

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
        print("✅ 시스템 가동 준비 완료")

bot = MyBot()

stock_amount = "현재 자판기 미완성"
kimchi_premium = "현재 자판기 미완성"
last_update = "현재 자판기 미완성"

async def create_tables(pool):
    async with pool.acquire() as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance NUMERIC DEFAULT 0, total_spent NUMERIC DEFAULT 0);")
        await conn.execute("CREATE TABLE IF NOT EXISTS deposit_requests (id SERIAL PRIMARY KEY, user_id BIGINT, amount NUMERIC, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT NOW());")

async def update_member_rank(member, total_spent):
    target_role_id = 1476788194346274936
    for amount, role_id in sorted(RANKS.items(), reverse=True):
        if total_spent >= amount:
            target_role_id = role_id
            break
    
    all_rank_ids = list(RANKS.values())
    roles_to_remove = [discord.Object(id=rid) for rid in all_rank_ids if rid != target_role_id and any(r.id == rid for r in member.roles)]
    
    try:
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)
        target_role = member.guild.get_role(target_role_id)
        if target_role and target_role not in member.roles:
            await member.add_roles(target_role)
    except:
        pass

class ApproveView(View):
    def __init__(self, user_id, amount):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.amount = amount

    @discord.ui.button(label="✅ 승인", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        try:
            async with bot.db.acquire() as conn:
                async with conn.transaction():
                    user_data = await conn.fetchrow("""
                        INSERT INTO users (user_id, balance, total_spent) 
                        VALUES ($1, $2::numeric, $2::numeric)
                        ON CONFLICT (user_id) DO UPDATE SET 
                            balance = users.balance + EXCLUDED.balance, 
                            total_spent = users.total_spent + EXCLUDED.total_spent
                        RETURNING total_spent, balance
                    """, self.user_id, self.amount)
                    await conn.execute("UPDATE deposit_requests SET status='approved' WHERE user_id=$1 AND amount=$2::numeric AND status='pending'", self.user_id, self.amount)

            member = interaction.guild.get_member(self.user_id)
            if member:
                await update_member_rank(member, user_data['total_spent'])
                try:
                    embed = discord.Embed(title="💰 충전 완료 안내", color=discord.Color.green())
                    embed.description = f"신청하신 **{self.amount:,.0f}원**이 충전되었습니다.\n현재 잔액: **{user_data['balance']:,.0f}원**"
                    await member.send(embed=embed)
                except: pass

            await interaction.followup.send(f"✅ <@{self.user_id}>님 승인 완료", ephemeral=True)
            await interaction.message.delete()
        except Exception as e:
            await interaction.followup.send(f"❌ 오류: {e}", ephemeral=True)

    @discord.ui.button(label="❌ 거절", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        async with bot.db.acquire() as conn:
            await conn.execute("UPDATE deposit_requests SET status='rejected' WHERE user_id=$1 AND amount=$2::numeric", self.user_id, self.amount)
        await interaction.followup.send("❌ 거절 완료", ephemeral=True)
        await interaction.message.delete()

class OTCView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💰 충전", style=discord.ButtonStyle.primary)
    async def charge(self, interaction: discord.Interaction, button: Button):
        modal = Modal(title="💰 충전 신청")
        amt_input = TextInput(label="충전 금액", placeholder="숫자만 입력하세요")
        modal.add_item(amt_input)
        async def on_modal_submit(intact: discord.Interaction):
            await intact.response.defer(ephemeral=True)
            if not amt_input.value.isdigit(): return await intact.followup.send("숫자만 입력하세요.", ephemeral=True)
            async with bot.db.acquire() as conn:
                await conn.execute("INSERT INTO deposit_requests (user_id, amount) VALUES ($1, $2::numeric)", intact.user.id, int(amt_input.value))
            await intact.followup.send("✅ 충전 신청 완료!", ephemeral=True)
            log_ch = bot.get_channel(LOG_CHANNEL_ID)
            if log_ch: await log_ch.send(f"🔔 **충전 요청**: <@{intact.user.id}>님이 {int(amt_input.value):,}원 요청", view=ApproveView(intact.user.id, int(amt_input.value)))
        modal.on_submit = on_modal_submit
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="📤 송금", style=discord.ButtonStyle.primary)
    async def send(self, interaction: discord.Interaction, button: Button):
        # 아무 반응도 없게 처리 (defer만 하고 아무것도 안 함)
        await interaction.response.defer()

    @discord.ui.button(label="📊 정보", style=discord.ButtonStyle.secondary)
    async def info(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        async with bot.db.acquire() as conn:
            user = await conn.fetchrow("SELECT balance, total_spent FROM users WHERE user_id = $1", interaction.user.id)
        bal = user['balance'] if user else 0
        spent = user['total_spent'] if user else 0
        current_rank = "아이언"
        for amount, role_id in sorted(RANKS.items(), reverse=True):
            if spent >= amount:
                role = interaction.guild.get_role(role_id)
                current_rank = role.name if role else "알 수 없음"
                break
        embed = discord.Embed(title=f"👤 {interaction.user.display_name}님의 정보", color=discord.Color.blue())
        embed.add_field(name="🏆 현재 등급", value=f"**{current_rank}**", inline=True)
        embed.add_field(name="💰 보유 잔액", value=f"**{bal:,.0f}원**", inline=True)
        embed.add_field(name="📈 누적 이용액", value=f"**{spent:,.0f}원**", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="❓ 도움말", style=discord.ButtonStyle.secondary)
    async def help(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(title="신속한 대행 | 레제 코인대행", description="**이용을 위한 간편 도움말**", color=discord.Color.orange())
        embed.add_field(name="• (💰) 충전", value="충전 요청을 한 후 관리자를 기다려주시면 관리자가 디엠으로 계좌를 보낼겁니다 그럼 돈을 보내고 이중창을 하시고 기다려주시면 됩니다.", inline=False)
        embed.add_field(name="• (📊) 정보", value="현재 자신의 금액이 얼마나 있는지 확인할 수 있습니다.", inline=False)
        embed.add_field(name="• (📤) 송금", value="코인 송금을 할 수 있는 버튼입니다.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="otc", description="메뉴 호출")
async def otc_slash(interaction: discord.Interaction):
    embed = discord.Embed(title="🪙 레제 코인대행", color=discord.Color.blue())
    embed.add_field(name="💰 재고", value=stock_amount, inline=True); embed.add_field(name="📈 김프", value=kimchi_premium, inline=True)
    embed.add_field(name="🕒 갱신", value=last_update, inline=False); embed.set_footer(text="신속한 대행 | 레제 코인대행")
    await interaction.response.send_message(embed=embed, view=OTCView())

if TOKEN: bot.run(TOKEN)
