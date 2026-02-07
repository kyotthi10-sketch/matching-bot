import os
import asyncio
import discord
from discord.ext import commands

from questions import QUESTIONS
from db import (
    init_db, get_state, set_state, save_answer, load_answers, reset_user,
    count_total_users, count_completed_users, count_inprogress_users
)
from collections import defaultdict, Counter

# ===== 環境変数 =====
TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ["1466960571004882967"])
AUTO_CLOSE_SECONDS = int(os.environ.get("AUTO_CLOSE_SECONDS", "300"))
ADMIN_ROLE_NAME = os.environ.get("ADMIN_ROLE_NAME", "Bot-管理者")


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== 共通変数 =====
def has_admin_role(member: discord.Member) -> bool:
    return any(r.name == ADMIN_ROLE_NAME for r in member.roles)
def compatibility_percent(picks_a: dict, picks_b: dict, categories: list[str]) -> int:
    usable = [c for c in categories if c in picks_a and c in picks_b]
    if not usable:
        return 0
    same = sum(1 for c in usable if picks_a[c] == picks_b[c])
    return int(round(same / len(usable) * 100))

def compatibility_points(picks_a: dict, picks_b: dict, categories: list[str]) -> int:
    # A案：0〜100pt（％と同じスケール）
    return compatibility_percent(picks_a, picks_b, categories)


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
SCALE = {"A": 0, "B": 50, "C": 100}

def build_profile(user_id: int):
    """
    returns:
      picks: dict(category -> "A"/"B"/"C")  最頻回答
      meters: dict(category -> 0..100)      平均％（A=0,B=50,C=100）
    """
    answers = load_answers(user_id)
    qid_to_cat = {q["id"]: q.get("category") for q in QUESTIONS}

    by_cat = defaultdict(list)
    for qid, ans in answers:
        cat = qid_to_cat.get(qid)
        if cat and ans in ("A", "B", "C"):
            by_cat[cat].append(ans)

    picks = {}
    meters = {}
    for cat, lst in by_cat.items():
        c = Counter(lst)
        picks[cat] = c.most_common(1)[0][0]
        meters[cat] = int(round(sum(SCALE[x] for x in lst) / len(lst)))

    return picks, meters

def compatibility_points(picks_a: dict, picks_b: dict, categories: list[str]) -> int:
    usable = [c for c in categories if c in picks_a and c in picks_b]
    if not usable:
        return 0
    same = sum(1 for c in usable if picks_a[c] == picks_b[c])
    # 0〜100pt
    return int(round(same / len(usable) * 100))

# ===== 診断結果（カテゴライズ）=====
def categorized_result(user_id: int) -> str:
    picks, meters = build_profile(user_id)

    # 表示したいカテゴリ（あなたの questions.py の category 名に合わせて）
    # ここに無いカテゴリは表示されません（増やしたらここに追加）
    CATS = ["game_style", "communication", "real_priority", "distance", "money", "play_time", "future"]

    # 日本語ラベル
    LABEL = {
        "game_style": "🎮 ゲーム志向",
        "communication": "💬 コミュニケーション",
        "real_priority": "🏠 リアル優先度",
        "distance": "🧍 距離感",
        "money": "💰 お金/課金感覚",
        "play_time": "🕒 プレイ頻度/時間帯",
        "future": "🧭 将来観",
    }

    # A/B/Cの意味（カテゴリごとに微調整したい場合はここをいじる）
    TEXT = {
        "game_style": {"A":"エンジョイ寄り", "B":"バランス", "C":"ガチ志向"},
        "communication": {"A":"テキスト派", "B":"状況次第", "C":"VC重視"},
        "real_priority": {"A":"リアル優先", "B":"両立型", "C":"ゲームも重視"},
        "distance": {"A":"自立距離", "B":"バランス", "C":"密接"},
        "money": {"A":"堅実派", "B":"バランス", "C":"体験/課金OK"},
        "play_time": {"A":"控えめ", "B":"中くらい", "C":"多め"},
        "future": {"A":"自然に", "B":"早めに相談", "C":"最初から擦り合わせ"},
    }

    lines = []
    shown = 0
    for cat in CATS:
        if cat in picks:
            shown += 1
            pct = meters.get(cat, 50)
            lines.append(f"{LABEL.get(cat, cat)}：{TEXT.get(cat, {}).get(picks[cat], picks[cat])}（{pct}%）")

    # 「相性％」は /match で相手と比較して出すのが自然なので
    # ここでは “あなたの指標” を％で必ず見せる（要求①）
    header = "🧩 **診断結果（ゲーム × リアル）**\n"
    footer = "\n\n🔎 相性％（TOP3）は `/match` で表示できます。"
    if shown == 0:
        return "🧩 **診断結果**\n\nデータが不足しています。/start からやり直してください。" + footer

    return header + "\n".join(lines) + footer


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
                + categorized_result(self.user_id)
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

@bot.tree.command(name="match", description="相性TOP3（任意表示）", guild=discord.Object(id=GUILD_ID))
async def match(interaction: discord.Interaction):
    # 専用ルーム以外は拒否（あなたの方針）
    if not is_user_room(interaction.channel, interaction.user.id):
        await interaction.response.send_message("専用ルーム内で実行してください。", ephemeral=True)
        return

    # 診断完了してないなら拒否
    if get_state(interaction.user.id) < len(QUESTIONS):
        await interaction.response.send_message("診断が完了していません。先に質問に回答してください。", ephemeral=True)
        return

    me_picks, _ = build_profile(interaction.user.id)

    # 比較するカテゴリ（結果表示と同じにする）
    CATS = ["game_style", "communication", "real_priority", "distance", "money", "play_time", "future"]

    # 全ユーザー候補（answersテーブルから拾う：参加者のみ）
    # ※ db.pyの追加なしで動く簡易版
    import sqlite3
    from db import DB_PATH  # db.pyにDB_PATHがある前提（無ければ追記が必要）

    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("SELECT DISTINCT user_id FROM answers")
        user_ids = [int(r[0]) for r in cur.fetchall()]

    results = []
    for uid in user_ids:
        if uid == interaction.user.id:
            continue
        if get_state(uid) < len(QUESTIONS):  # 未完了は除外
            continue
        other_picks, _ = build_profile(uid)
        pct = compatibility_percent(me_picks, other_picks, CATS)
        results.append((pct, uid))

    if not results:
        await interaction.response.send_message("比較できる相手がまだいません。", ephemeral=True)
        return

    results.sort(reverse=True, key=lambda x: x[0])
    top = results[:3]

    lines = ["🏆 **相性TOP3（カテゴリ一致率）**"]
    for i, (pct, uid) in enumerate(top, start=1):
        lines.append(f"{i}位：<@{uid}>  **{pct}%**")

    await interaction.response.send_message("\n".join(lines))


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


