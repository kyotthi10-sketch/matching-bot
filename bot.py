import os
import asyncio
import discord
from discord.ext import commands

from questions import QUESTIONS
from db import (
    init_db, get_state, set_state, save_answer, load_answers, reset_user,
    count_total_users, count_completed_users, count_inprogress_users
)

# ===== 環境変数 =====
TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ["GUILD_ID"])
AUTO_CLOSE_SECONDS = int(os.environ.get("AUTO_CLOSE_SECONDS", "300"))
ADMIN_ROLE_NAME = os.environ.get("ADMIN_ROLE_NAME", "Bot-管理者")


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== 共通変数 =====
def has_admin_role(member: discord.Member) -> bool:
    return any(r.name == ADMIN_ROLE_NAME for r in member.roles)

# ===== 集計変数 =====
def count_total_users() -> int:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM user_state")
        return int(cur.fetchone()[0])

def count_completed_users(total_questions: int) -> int:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM user_state WHERE idx >= ?", (total_questions,))
        return int(cur.fetchone()[0])

def count_inprogress_users(total_questions: int) -> int:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM user_state WHERE idx < ?", (total_questions,))
        return int(cur.fetchone()[0])

# ===== 共通判定 =====
def is_user_room(channel: discord.TextChannel, user_id: int) -> bool:
    return (
        isinstance(channel, discord.TextChannel)
        and channel.name == f"match-{user_id}"
        and channel.topic == f"user:{user_id}"
    )

# ===== 診断結果（簡易）=====
def simple_result(user_id: int) -> str:
    answers = load_answers(user_id)
    a = sum(1 for _, v in answers if v == "A")
    b = sum(1 for _, v in answers if v == "B")
    if a >= b:
        return "🧠 **安心重視型**\n慎重・安定志向・聞き手タイプ"
    else:
        return "🔥 **行動優先型**\n積極的・テンポ速め・外向きタイプ"

# ===== 自動削除 =====
async def schedule_auto_delete(channel: discord.TextChannel, user_id: int, seconds: int):
    await asyncio.sleep(seconds)
    try:
        ch = await channel.guild.fetch_channel(channel.id)
    except Exception:
        return

    if is_user_room(ch, user_id):
        try:
            await ch.delete(reason="Auto close after diagnosis")
        except Exception:
            pass

# ===== 質問送信 =====
async def send_question_to_channel(channel: discord.TextChannel, user_id: int, q_idx: int):
    q = QUESTIONS[q_idx]
    view = AnswerView(user_id, q_idx)
    await channel.send(f"Q{q['id']}. {q['text']}", view=view)

# ===== ボタンUI =====
class AnswerView(discord.ui.View):
    def __init__(self, user_id: int, q_idx: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.q_idx = q_idx
        q = QUESTIONS[q_idx]
        for key, label in q["choices"]:
            self.add_item(AnswerButton(user_id, q_idx, key, label))

class AnswerButton(discord.ui.Button):
    def __init__(self, user_id: int, q_idx: int, key: str, label: str):
        super().__init__(style=discord.ButtonStyle.primary, label=f"{key}: {label}")
        self.user_id = user_id
        self.q_idx = q_idx
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("これはあなたの診断ではありません。", ephemeral=True)
            return

        save_answer(self.user_id, QUESTIONS[self.q_idx]["id"], self.key)
        next_idx = self.q_idx + 1
        set_state(self.user_id, next_idx)

        # 最終質問
        if next_idx >= len(QUESTIONS):
            # ロック解除
            if is_user_room(interaction.channel, self.user_id):
                await interaction.channel.set_permissions(interaction.user, send_messages=True)

            msg = (
                "✅ **診断完了！**\n\n"
                + simple_result(self.user_id)
                + f"\n\n⏳ このルームは {AUTO_CLOSE_SECONDS//60} 分後に自動削除されます。\n"
                  "すぐ消す場合は `/close`"
            )
            await interaction.response.edit_message(content=msg, view=None)

            # 自動削除予約
            asyncio.create_task(
                schedule_auto_delete(interaction.channel, self.user_id, AUTO_CLOSE_SECONDS)
            )
        else:
            await interaction.response.edit_message(
                content=f"Q{QUESTIONS[next_idx]['id']}. {QUESTIONS[next_idx]['text']}",
                view=AnswerView(self.user_id, next_idx)
            )

# ===== イベント =====
@bot.event
async def on_ready():
    init_db()
    guild = discord.Object(id=GUILD_ID)
    await bot.tree.sync(guild=guild)
    print(f"Bot起動: {bot.user}")

# ===== コマンド =====
@bot.tree.command(name="room", description="専用診断ルームを作成し自動で開始", guild=discord.Object(id=GUILD_ID))
async def room(interaction: discord.Interaction):
    guild = interaction.guild
    user_id = interaction.user.id
    channel_name = f"match-{user_id}"

    # 既存ルーム再利用
    for ch in guild.text_channels:
        if is_user_room(ch, user_id):
            await interaction.response.send_message(f"既にあります：{ch.mention}", ephemeral=True)
            return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }

    ch = await guild.create_text_channel(
        channel_name,
        topic=f"user:{user_id}",
        overwrites=overwrites
    )

    await interaction.response.send_message(f"専用ルームを作成しました：{ch.mention}", ephemeral=True)
    await ch.send("📝 このルームは診断専用です。ボタンで回答してください。")

    reset_user(user_id)
    await send_question_to_channel(ch, user_id, 0)

@bot.tree.command(name="start", description="診断開始", guild=discord.Object(id=GUILD_ID))
async def start(interaction: discord.Interaction):
    if not is_user_room(interaction.channel, interaction.user.id):
        await interaction.response.send_message("ここでは開始できません。/room を使ってください。", ephemeral=True)
        return

    idx = get_state(interaction.user.id)
    await send_question_to_channel(interaction.channel, interaction.user.id, idx)

@bot.tree.command(name="close", description="自分の診断ルームを削除", guild=discord.Object(id=GUILD_ID))
async def close(interaction: discord.Interaction):
    if is_user_room(interaction.channel, interaction.user.id):
        await interaction.response.send_message("このルームを削除します。", ephemeral=True)
        await interaction.channel.delete()
    else:
        await interaction.response.send_message("この部屋は削除できません。", ephemeral=True)

@bot.tree.command(name="stats", description="管理者用：利用状況を表示", guild=discord.Object(id=GUILD_ID))
async def stats(interaction: discord.Interaction):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
        return

    # ✅ 管理者ロール限定
    if not has_admin_role(interaction.user):
        await interaction.response.send_message("権限がありません（管理者ロールが必要です）。", ephemeral=True)
        return

    total = count_total_users()
    completed = count_completed_users(len(QUESTIONS))
    inprogress = count_inprogress_users(len(QUESTIONS))

    # 専用ルーム数（サーバー内の match-xxx を数える）
    rooms = [ch for ch in interaction.guild.text_channels if ch.name.startswith("match-")]

    msg = (
        "📊 **診断Bot 利用状況**\n\n"
        f"・総ユーザー数：{total}\n"
        f"・診断完了：{completed}\n"
        f"・診断途中：{inprogress}\n"
        f"・現在の専用ルーム数：{len(rooms)}\n\n"
        f"管理者ロール：`{ADMIN_ROLE_NAME}`"
    )
    await interaction.response.send_message(msg, ephemeral=True)


bot.run(TOKEN)
