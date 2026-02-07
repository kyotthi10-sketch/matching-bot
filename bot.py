import os
import discord
from discord.ext import commands

from questions import QUESTIONS
from db import init_db, get_state, set_state, save_answer, load_answers, reset_user

TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ.get("GUILD_ID", "1466960571004882967"))  # Railwayに入れるのがおすすめ（後述）

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

def simple_result(user_id: int) -> str:
    answers = load_answers(user_id)
    a = sum(1 for _, v in answers if v == "A")
    b = sum(1 for _, v in answers if v == "B")
    if a >= b:
        typ = "安心重視型"
        tags = "慎重 / 安定志向 / 聞き手寄り"
    else:
        typ = "行動優先型"
        tags = "積極的 / テンポ速め / 外向き"
    return f"**あなたのタイプ：{typ}**\nタグ：{tags}\n(A={a}, B={b})"

class AnswerView(discord.ui.View):
    def __init__(self, user_id: int, q_idx: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.q_idx = q_idx

        q = QUESTIONS[q_idx]
        for key, label in q["choices"]:
            self.add_item(AnswerButton(user_id, q_idx, key, label))

class AnswerButton(discord.ui.Button):
    def __init__(self, user_id: int, q_idx: int, choice_key: str, label: str):
        super().__init__(style=discord.ButtonStyle.primary, label=f"{choice_key}: {label}")
        self.user_id = user_id
        self.q_idx = q_idx
        self.choice_key = choice_key

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("これは他の人の質問です。/start から始めてね。", ephemeral=True)
            return

        q = QUESTIONS[self.q_idx]
        save_answer(self.user_id, q["id"], self.choice_key)

        next_idx = self.q_idx + 1
        set_state(self.user_id, next_idx)

        if next_idx >= len(QUESTIONS):
            msg = "✅ 質問は以上！\n" + simple_result(self.user_id) + "\n\nやり直すなら /reset"
            await interaction.response.edit_message(content=msg, view=None)
        else:
            await send_question(interaction, next_idx, edit=True)

async def send_question(interaction: discord.Interaction, q_idx: int, edit: bool):
    q = QUESTIONS[q_idx]
    content = f"Q{q['id']}. {q['text']}"
    view = AnswerView(user_id=interaction.user.id, q_idx=q_idx)

    if edit:
        await interaction.response.edit_message(content=content, view=view)
    else:
        await interaction.response.send_message(content=content, view=view, ephemeral=True)

@bot.event
async def on_ready():
    init_db()
    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        await bot.tree.sync(guild=guild)
        print(f"Bot起動: {bot.user} (guild synced)")
    else:
        await bot.tree.sync()
        print(f"Bot起動: {bot.user} (global synced)")

@bot.tree.command(name="start", description="質問を開始します", guild=discord.Object(id=GUILD_ID) if GUILD_ID else None)
async def start(interaction: discord.Interaction):
    idx = get_state(interaction.user.id)
    if idx >= len(QUESTIONS):
        await interaction.response.send_message("すでに完了しています！やり直すなら /reset", ephemeral=True)
        return
    await send_question(interaction, idx, edit=False)

@bot.tree.command(name="reset", description="回答をリセットします", guild=discord.Object(id=GUILD_ID) if GUILD_ID else None)
async def reset(interaction: discord.Interaction):
    reset_user(interaction.user.id)
    await interaction.response.send_message("リセットしました！ /start で再開できます。", ephemeral=True)

@bot.tree.command(name="ping", description="動作確認", guild=discord.Object(id=GUILD_ID) if GUILD_ID else None)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong!")

bot.run(TOKEN)

