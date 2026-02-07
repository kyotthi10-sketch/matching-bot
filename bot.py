import os
import asyncio
import discord
from discord.ext import commands

from questions import QUESTIONS
from db import (
    init_db, get_state, set_state, save_answer, load_answers, reset_user,
    get_or_create_order, reset_order,
    get_message_id, set_message_id, reset_message_id,
    count_total_users, count_completed_users, count_inprogress_users
)

from collections import defaultdict, Counter
import asyncio

AUTO_CLOSE_SECONDS = 5 * 60  # 15分（好きに変更）

async def schedule_auto_delete(channel: discord.TextChannel, user_id: int, seconds: int):
    await asyncio.sleep(seconds)

    # 念のため、まだ存在しているかチェックして削除
    try:
        await channel.delete(reason=f"Auto close (user:{user_id})")
    except Exception:
        pass


# ===== 環境変数 =====
TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ["GUILD_ID"])
AUTO_CLOSE_SECONDS = int(os.environ.get("AUTO_CLOSE_SECONDS", "300"))
BOTADMIN_ROLE_ID = int(os.environ.get("BOTADMIN_ROLE_ID", "1469582684845113467"))
ADMIN_ROLE_ID = int(os.environ.get("ADMIN_ROLE_ID", "1469624897587118081"))
ADMIN_CHANNEL_ID = int(os.environ.get("ADMIN_CHANNEL_ID", "1469593018637090897"))
WELCOME_CHANNEL_ID = int(os.environ.get("ADMIN_CHANNEL_ID", "1466960571688550537"))
CATEGORY_LABEL = {
    "game_style": "ゲームスタイル",
    "communication": "コミュニケーション",
    "play_time": "プレイ時間・生活",
    "distance": "距離感",
    "money": "お金・課金感覚",
    "future": "将来観・価値観",
}



intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== 共通変数 =====
def has_admin_role(member: discord.Member) -> bool:
    return any(r.name == BOTADMIN_ROLE_NAME for r in member.roles)
    
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
from collections import defaultdict, Counter

# ===== 共通関数 =====
async def post_panel(channel: discord.TextChannel):
    embed = discord.Embed(
        title="🎮 診断スタート",
        description="下のボタンを押すと、あなた専用の診断ルームが作成されます。",
    )
    await channel.send(embed=embed, view=StartRoomView())

# 5段階：A=0, B=25, C=50, D=75, E=100
SCALE = {"A": 0, "B": 25, "C": 50, "D": 75, "E": 100}
VALID_ANS = set(SCALE.keys())
STAR_MAP = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}

def stars(letter: str) -> str:
    n = STAR_MAP.get(letter, 3)
    return "★" * n + "☆" * (5 - n)

def progress_bar(current: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return ""
    filled = int(round((current / total) * width))
    filled = max(0, min(width, filled))
    return "■" * filled + "□" * (width - filled)

def build_question_embed(idx: int, total: int, q: dict) -> discord.Embed:
    embed = discord.Embed(
        title="🎮 ロール診断",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="📊 進捗",
        value=f"{progress_bar(idx + 1, total, 12)}  {idx + 1} / {total}",
        inline=False
    )

    embed.add_field(
        name="❓ 質問",
        value=f"Q{idx + 1}. {q['text']}",
        inline=False
    )

    cat = q.get("category")
    if cat:
        embed.add_field(
            name="🧩 カテゴリ",
            value=CATEGORY_LABEL.get(cat, cat),
            inline=True
        )

    embed.set_footer(text="★が多いほど強い／頻度が高い傾向です")

    return embed
    

def progress_text(idx: int, total: int) -> str:
    # idx は 0始まり。表示は 1/total
    now = min(idx + 1, total)
    bar = progress_bar(now, total, width=12)
    return f"[{bar}] {now}/{total}"

def build_profile(user_id: int):
    """
    returns:
      picks:  dict(category -> "A".."E")  最頻回答
      meters: dict(category -> 0..100)   平均スコア
    """
    answers = load_answers(user_id)
    qid_to_cat = {q["id"]: q.get("category") for q in QUESTIONS}

    by_cat = defaultdict(list)
    for qid, ans in answers:
        cat = qid_to_cat.get(qid)
        if cat and ans in VALID_ANS:
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

async def create_or_open_room_for_member(guild: discord.Guild, member: discord.Member):
    user_id = member.id
    channel_name = f"match-{user_id}"

    # 既存ルームがあれば案内だけ
    for ch in guild.text_channels:
        if is_user_room(ch, user_id):
            try:
                await member.send(f"✅ 既に専用ルームがあります：{ch.mention}")
            except Exception:
                pass
            return ch

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }

    ch = await guild.create_text_channel(
        channel_name,
        topic=f"user:{user_id}",
        overwrites=overwrites
    )

    # 初期化
    reset_user(user_id)
    reset_order(user_id)
    reset_message_id(user_id)

    # 出題順 → 1つの固定メッセージ（Embed）で開始
    order = get_or_create_order(user_id, [q["id"] for q in QUESTIONS])
    await upsert_question_message(ch, user_id, 0, order)

    # 本人にDMで案内（DM拒否されてたら無視）
    try:
        await member.send(f"🎮 診断ルームを作成しました：{ch.mention}")
    except Exception:
        pass

    return ch


# ===== 診断結果（カテゴライズ）=====
def categorized_result(user_id: int) -> str:
    """
    30問 / 6カテゴリ / 5段階（A〜E）
    - 各カテゴリ：文章 + ★表示
    """
    picks, meters = build_profile(user_id)
    # picks : {"game_style": "D", ...}
    # meters: {"game_style": 4.2, ...}  # 1.0〜5.0 の平均想定

    # 表示するカテゴリ（30問構成）
    CATS = [
        "game_style",
        "communication",
        "play_time",
        "distance",
        "money",
        "future",
    ]

    # 日本語ラベル
    LABEL = {
        "game_style": "🎮 ゲームスタイル",
        "communication": "💬 コミュニケーション",
        "play_time": "🕒 プレイ時間・生活",
        "distance": "🧍 距離感",
        "money": "💰 お金・課金感覚",
        "future": "🧭 将来観・価値観",
    }

    # 5段階（A〜E）の意味づけ（カテゴリ別）
    TEXT = {
        "game_style": {
            "A": "エンジョイ重視で気楽に楽しむ",
            "B": "楽しさと勝敗のバランス型",
            "C": "状況次第で本気も出す",
            "D": "勝ちや成長をしっかり求める",
            "E": "かなりガチ志向で突き詰める",
        },
        "communication": {
            "A": "必要最低限・テキスト中心",
            "B": "落ち着いたやり取りが好み",
            "C": "相手に合わせる柔軟タイプ",
            "D": "積極的に会話・連携したい",
            "E": "VCや雑談をかなり重視",
        },
        "play_time": {
            "A": "かなり控えめ・不定期",
            "B": "空いた時間にほどほど",
            "C": "無理のない安定ペース",
            "D": "定期的にしっかり遊ぶ",
            "E": "時間を作ってでも遊ぶ",
        },
        "distance": {
            "A": "干渉少なめ・自立重視",
            "B": "必要な時だけ関わりたい",
            "C": "心地よい距離感を保つ",
            "D": "一緒に過ごす時間を重視",
            "E": "密な関係・頻繁な交流が理想",
        },
        "money": {
            "A": "無課金・超堅実派",
            "B": "基本は節約・慎重",
            "C": "必要なら使うバランス型",
            "D": "体験向上なら課金OK",
            "E": "趣味への投資は惜しまない",
        },
        "future": {
            "A": "流れに任せたい",
            "B": "深く考えすぎない",
            "C": "タイミングを見て考える",
            "D": "早めに方向性を共有したい",
            "E": "最初から価値観を重視",
        },
    }

    lines = []
    for cat in CATS:
        if cat not in picks:
            continue

        letter = picks[cat]          # A〜E
        desc = TEXT[cat].get(letter, letter)
        star = stars(letter)         # ★☆☆☆☆ 表示

        lines.append(
            f"{LABEL.get(cat, cat)}：{desc}\n{star}"
        )

    return "\n\n".join(lines)


    # 「相性％」は /match で相手と比較して出すのが自然なので
    # ここでは “あなたの指標” を％で必ず見せる（要求①）
    header = "🧩 **診断結果**\n"
    footer = "\n\n🔎 相性％（TOP3）は `/match` で表示できます。"
    if shown == 0:
        return "🧩 **診断結果**\n\nデータが不足しています。/start からやり直してください。" + footer

    return header + "\n".join(lines) + footer
# ===== メッセージ固定 =====
async def upsert_question_message(
    channel: discord.TextChannel,
    user_id: int,
    idx: int,
    order: list[int],
):
    qid = order[idx]
    q = q_by_id(qid)

    embed = build_question_embed(idx, len(order), q)
    view = AnswerView(user_id, idx)

    mid = await asyncio.to_thread(get_message_id, user_id)

    if mid is None:
        msg = await channel.send(embed=embed, view=view)
        await asyncio.to_thread(set_message_id, user_id, msg.id)
        return msg

    try:
        msg = await channel.fetch_message(mid)
        await msg.edit(embed=embed, view=view)
        return msg
    except Exception:
        msg = await channel.send(embed=embed, view=view)
        await asyncio.to_thread(set_message_id, user_id, msg.id)
        return msg

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
def q_by_id(qid: int) -> dict:
    # QUESTIONSは小さいので線形でもOK。気になるなら辞書化してもOK。
    for q in QUESTIONS:
        if q["id"] == qid:
            return q
    raise KeyError(f"question id not found: {qid}")

async def send_question_to_channel(channel: discord.TextChannel, user_id: int, idx: int):
    order = get_or_create_order(user_id, [q["id"] for q in QUESTIONS])
    qid = order[idx]
    q = q_by_id(qid)

    header = progress_text(idx, len(order))
    await channel.send(f"{header}\nQ{idx+1}. {q['text']}", view=AnswerView(user_id, idx, order))


# ===== ボタンUI =====
def stars_from_key(key: str) -> str:
    return {"A": "★☆☆☆☆", "B": "★★☆☆☆", "C": "★★★☆☆", "D": "★★★★☆", "E": "★★★★★"}.get(key, "★☆☆☆☆")


class AnswerView(discord.ui.View):
    def __init__(self, user_id: int, idx: int):
        super().__init__(timeout=None)

        for key in ["A", "B", "C", "D", "E"]:
            self.add_item(
                discord.ui.Button(
                    label=stars_from_key(key),
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"ans:{user_id}:{idx}:{key}",
                )
            )


class AnswerButton(discord.ui.Button):
    def __init__(self, user_id: int, idx: int, order: list[int], key: str, label: str):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=f"{key}: {label}"
        )
        self.user_id = user_id
        self.idx = idx
        self.order = order
        self.key = key

class StartRoomView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="診断を始める",
        style=discord.ButtonStyle.success,
        custom_id="start_room_button"
    )
    async def start_room_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で押してください。", ephemeral=True)
            return
        await create_or_open_room(interaction)

async def create_or_open_room(interaction: discord.Interaction):
    guild = interaction.guild
    user_id = interaction.user.id
    channel_name = f"match-{user_id}"

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

    reset_user(user_id)
    reset_order(user_id)
    reset_message_id(user_id)

    order = get_or_create_order(user_id, [q["id"] for q in QUESTIONS])
    await upsert_question_message(ch, user_id, 0, order)

    await interaction.response.send_message(f"専用ルームを作成しました：{ch.mention}", ephemeral=True)
   
    async def callback(self, interaction: discord.Interaction):
        # ✅ 3秒制限対策：とにかく最初にACK（ここが最重要）
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
            # 他人の操作は followup で返す（responseはもう使わない）
        if interaction.user.id != self.user_id:
            await interaction.followup.send("これはあなたの診断ではありません。", ephemeral=True)
            return

    try:
        # --- 回答保存（sqlite等はブロックするので別スレッド） ---
        q = q_by_id(self.order[self.idx])
        await asyncio.to_thread(save_answer, self.user_id, q["id"], self.key)

        next_idx = self.idx + 1
        await asyncio.to_thread(set_state, self.user_id, next_idx)

        # --- 完了 ---
        if next_idx >= len(self.order):
            result_text = "✅ **診断完了！**\n\n" + categorized_result(self.user_id)

            mid = get_message_id(self.user_id)
            msg = None
            if mid:
                try:
                    msg = await interaction.channel.fetch_message(mid)
                except Exception:
                    msg = None

            notice = f"\n\n⏳ {AUTO_CLOSE_SECONDS//60}分後にこのルームは自動削除されます。"

            if msg:
                await msg.edit(content=result_text + notice, embed=None, view=None)
            else:
                await interaction.followup.send(result_text + notice, ephemeral=True)

            asyncio.create_task(schedule_auto_delete(interaction.channel, self.user_id, AUTO_CLOSE_SECONDS))
            return

        # --- 次の質問へ（固定メッセージを更新） ---
        await upsert_question_message(interaction.channel, self.user_id, next_idx, self.order)

    except Exception as e:
        await interaction.followup.send(f"⚠️ エラー：{type(e).__name__}", ephemeral=True)
        raise





# ===== イベント =====
@bot.event
async def on_ready():
    init_db()
    bot.add_view(StartRoomView())  # ボタンを永続化している場合
    guild = discord.Object(id=GUILD_ID)
    await bot.tree.sync(guild=guild)
    print(f"Bot起動: {bot.user}")

@bot.event
async def on_member_join(member: discord.Member):
    # Botが入ってきた時は無視
    if member.bot:
        return

    await create_or_open_room_for_member(member.guild, member)

@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return
    await create_or_open_room_for_member(member.guild, member)
    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if channel is None:
        return

    # メンバー歓迎（任意）
    await channel.send(f"👋 {member.mention} さん、ようこそ！ボタンを押して診断スタート")

    # 診断パネルを自動設置
    await post_panel(channel)
    
    @bot.event
    async def on_interaction(interaction: discord.Interaction):
    # ボタン以外は無視
      if interaction.type != discord.InteractionType.component:
        return

    data = interaction.data or {}
    cid = data.get("custom_id", "")
    if not isinstance(cid, str) or not cid.startswith("ans:"):
        return

    # ✅ 3秒制限回避：即ACK
      if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

      try:
        # ans:{user_id}:{idx}:{key}
        _, uid_s, idx_s, key = cid.split(":")
        user_id = int(uid_s)
        idx = int(idx_s)

        # 他人操作拒否
        if interaction.user.id != user_id:
            await interaction.followup.send(
                "これはあなたの診断ではありません。",
                ephemeral=True
            )
            return

        # order取得
        order = await asyncio.to_thread(
            get_or_create_order,
            user_id,
            [q["id"] for q in QUESTIONS]
        )

        # state補正
        cur_idx = await asyncio.to_thread(get_state, user_id)
        if isinstance(cur_idx, int) and 0 <= cur_idx < len(order):
            idx = cur_idx

        # 保存（DBは別スレッド）
        q = q_by_id(order[idx])
        await asyncio.to_thread(save_answer, user_id, q["id"], key)

        next_idx = idx + 1
        await asyncio.to_thread(set_state, user_id, next_idx)

        # --- 完了 ---
        if next_idx >= len(order):
            result_text = "✅ **診断完了！**\n\n" + categorized_result(user_id)
            notice = f"\n\n⏳ {AUTO_CLOSE_SECONDS//60}分後にこのルームは自動削除されます。"

            mid = await asyncio.to_thread(get_message_id, user_id)
            msg = None
            if mid:
                try:
                    msg = await interaction.channel.fetch_message(mid)
                except Exception:
                    msg = None

            if msg:
                await msg.edit(
                    content=result_text + notice,
                    embed=None,
                    view=None
                )
            else:
                await interaction.followup.send(
                    result_text + notice,
                    ephemeral=True
                )

            asyncio.create_task(
                schedule_auto_delete(
                    interaction.channel,
                    user_id,
                    AUTO_CLOSE_SECONDS
                )
            )
            return

        # --- 次の質問 ---
        await upsert_question_message(
            interaction.channel,
            user_id,
            next_idx,
            order
        )

    except Exception as e:
        await interaction.followup.send(
            f"⚠️ エラー：{type(e).__name__}",
            ephemeral=True
        )
        raise


    
# ===== ボタンで開始 =====   
async def create_or_open_room(interaction: discord.Interaction):
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

    # 初期化
    reset_user(user_id)
    reset_order(user_id)
    reset_message_id(user_id)

    # 出題順
    order = get_or_create_order(user_id, [q["id"] for q in QUESTIONS])
    await upsert_question_message(ch, user_id, 0, order)

    await interaction.response.send_message(f"専用ルームを作成しました：{ch.mention}", ephemeral=True)



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

    # 初期化
    reset_user(user_id)
    reset_order(user_id)
    reset_message_id(user_id)

    # 出題順を作って、固定メッセージ（Embed）で開始
    order = get_or_create_order(user_id, [q["id"] for q in QUESTIONS])
    await upsert_question_message(ch, user_id, 0, order)



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

# ===== 管理者用 =====
@bot.tree.command(name="ping", description="動作確認（運営専用）")
async def ping(interaction: discord.Interaction):

    # ロールチェック
    if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
        await interaction.response.send_message(
            "このコマンドは運営専用です。",
            ephemeral=True
        )
        return

    await interaction.response.send_message("🏓 pong!", ephemeral=True)

@bot.tree.command(name="sync", description="コマンドを同期（管理者用）", guild=discord.Object(id=GUILD_ID))
async def sync_cmd(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
        return

       # ロールチェック
    if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
        await interaction.response.send_message(
            "このコマンドは運営専用です。",
            ephemeral=True
        )
        return

    guild = discord.Object(id=GUILD_ID)
    await bot.tree.sync(guild=guild)
    await interaction.response.send_message("✅ 同期しました。/panel を確認してください。", ephemeral=True)


@bot.tree.command(name="panel", description="診断開始ボタンを設置（指定ロール専用）")
async def panel(interaction: discord.Interaction):

    # ロールチェック
    if not any(role.id == BOTADMIN_ROLE_ID for role in interaction.user.roles):
        await interaction.response.send_message(
            "このコマンドは運営専用です。",
            ephemeral=True
        )
        return

    await post_panel(interaction.channel)
    await interaction.response.send_message("✅ 設置しました。", ephemeral=True)




@bot.tree.command(name="logs", description="管理者用：利用状況を表示（Embed）", guild=discord.Object(id=GUILD_ID))
async def logs(interaction: discord.Interaction):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
        return

    # ✅ 管理者チャンネル限定
    if ADMIN_CHANNEL_ID and interaction.channel_id != ADMIN_CHANNEL_ID:
        await interaction.response.send_message(
            "このコマンドは管理者チャンネルでのみ使用できます。",
            ephemeral=False
        )
        return

    # ✅ 管理者ロール限定
    if not has_admin_role(interaction.user):
        await interaction.response.send_message(
            f"権限がありません（`{ADMIN_ROLE_ID}` ロールが必要です）。",
            ephemeral=True
        )
        return

    total = count_total_users()
    completed = count_completed_users(len(QUESTIONS))
    inprogress = count_inprogress_users(len(QUESTIONS))
    rooms = [ch for ch in interaction.guild.text_channels if ch.name.startswith("match-")]

    # Embed作成
    embed = discord.Embed(
        title="📊 診断Bot 利用状況",
        description="管理者向けの集計情報です。",
    )
    embed.add_field(name="総ユーザー数", value=str(total), inline=True)
    embed.add_field(name="診断完了", value=str(completed), inline=True)
    embed.add_field(name="診断途中", value=str(inprogress), inline=True)
    embed.add_field(name="専用ルーム数", value=str(len(rooms)), inline=True)

    embed.add_field(name="質問数", value=str(len(QUESTIONS)), inline=True)
    embed.add_field(name="管理者ロール", value=f"`{ADMIN_ROLE_NAME}`", inline=True)

    # どのチャンネルで実行されたか等（任意）
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.run(TOKEN)















