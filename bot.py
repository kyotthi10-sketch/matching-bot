import os
import re
import json
import random
import asyncio
import sqlite3
from collections import defaultdict, Counter
from typing import List, Tuple, Optional

import discord
from discord.ext import commands

from questions import QUESTIONS
from db import (
    init_db,
    get_state, set_state,
    save_answer, load_answers, reset_user,
    get_or_create_order, reset_order,
    get_message_id, set_message_id, reset_message_id,
    count_total_users, count_completed_users, count_inprogress_users,
)

# =========================================================
# 環境変数
# =========================================================
TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ.get("GUILD_ID", "0"))

AUTO_CLOSE_SECONDS = int(os.environ.get("AUTO_CLOSE_SECONDS", "300"))  # 既定: 5分
BOTADMIN_ROLE_ID = int(os.environ.get("BOTADMIN_ROLE_ID", "1469582684845113467"))        # /panel など
ADMIN_ROLE_ID = int(os.environ.get("ADMIN_ROLE_ID", "1469624897587118081"))              # /sync /ping など
ADMIN_CHANNEL_ID = int(os.environ.get("ADMIN_CHANNEL_ID", "1469593018637090897"))        # /logs などに使う（任意）
WELCOME_CHANNEL_ID = int(os.environ.get("WELCOME_CHANNEL_ID", "1466960571688550537"))    # join時にパネルを置く場所

# db.py のDBパスと合わせる（db.pyが "app.db" の想定）
DB_PATH = os.environ.get("DB_PATH", "app.db")

CATEGORY_LABEL = {
    "game_style": "ゲームスタイル",
    "communication": "コミュニケーション",
    "play_time": "プレイ時間・生活",
    "distance": "距離感",
    "money": "お金・課金感覚",
    "future": "将来観・価値観",
}

# =========================================================
# Bot
# =========================================================
intents = discord.Intents.default()
intents.members = True  # on_member_join 用
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================================================
# 共通ユーティリティ
# =========================================================
async def unlock_chat_after_done(channel: discord.TextChannel, member: discord.Member):
    """診断完了後に /match を打てるように送信権限を付与"""
    try:
        await channel.set_permissions(
            member,
            view_channel=True,
            send_messages=True,
            send_messages_in_threads=True,
        )
    except Exception:
        pass

def safe_channel_name(name: str) -> str:
    """
    Discordチャンネル名は英小文字/数字/ハイフンが安全
    """
    name = name.lower()
    name = re.sub(r"[^a-z0-9]", "-", name)
    name = re.sub(r"-+", "-", name)
    name = name.strip("-")
    return name or "user"

def has_role_id(member: discord.Member, role_id: int) -> bool:
    if role_id <= 0:
        return False
    return any(r.id == role_id for r in member.roles)

def is_user_room(channel: discord.abc.GuildChannel, user_id: int) -> bool:
    """
    ルーム名が変わっても壊れないよう topic で判定
    topic: "user:{id} ..."
    """
    if not isinstance(channel, discord.TextChannel):
        return False
    return (channel.topic or "").startswith(f"user:{user_id}")

# 5段階：A=★1〜E=★5
STAR_MAP = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
VALID_ANS = set(STAR_MAP.keys())

def stars(letter: str) -> str:
    n = STAR_MAP.get(letter, 3)
    return "★" * n + "☆" * (5 - n)

def progress_bar(current: int, total: int, width: int = 12) -> str:
    if total <= 0:
        return ""
    filled = int(round((current / total) * width))
    filled = max(0, min(width, filled))
    return "■" * filled + "□" * (width - filled)

def q_by_id(qid: int) -> dict:
    for q in QUESTIONS:
        if q["id"] == qid:
            return q
    raise KeyError(f"question id not found: {qid}")

# =========================================================
# Embed（質問表示）
# =========================================================
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

# =========================================================
# プロフィール集計
# =========================================================
def build_profile(user_id: int):
    """
    picks:  dict(category -> "A".."E")  最頻回答
    meters: dict(category -> 1..5       平均星）
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
        meters[cat] = int(round(sum(STAR_MAP[x] for x in lst) / len(lst)))

    return picks, meters

def categorized_result(user_id: int) -> str:
    picks, meters = build_profile(user_id)

    CATS = ["game_style", "communication", "play_time", "distance", "money", "future"]

    LABEL = {
        "game_style": "🎮 ゲームスタイル",
        "communication": "💬 コミュニケーション",
        "play_time": "🕒 プレイ時間・生活",
        "distance": "🧍 距離感",
        "money": "💰 お金・課金感覚",
        "future": "🧭 将来観・価値観",
    }

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
        letter = picks[cat]
        desc = TEXT[cat].get(letter, letter)
        lines.append(f"{LABEL.get(cat, cat)}：{desc}\n{stars(letter)}")

    header = "🧩 **診断結果**\n\n"
    footer = "\n\n🔎 相性％（TOP3）は `/match` で表示できます。"

    if not lines:
        return header + "データが不足しています。/room からやり直してください。" + footer

    return header + "\n\n".join(lines) + footer

# =========================================================
# ボタンUI
# =========================================================
def stars_from_key(key: str) -> str:
    return {"A": "★☆☆☆☆", "B": "★★☆☆☆", "C": "★★★☆☆", "D": "★★★★☆", "E": "★★★★★"}.get(key, "★☆☆☆☆")

class AnswerView(discord.ui.View):
    """
    custom_id: ans:{user_id}:{idx}:{key}
    """
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

class StartRoomView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="診断を始める",
        style=discord.ButtonStyle.success,
        custom_id="start_room_button",
    )
    async def start_room_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("サーバー内で押してください。", ephemeral=True)
            return
        await create_or_open_room(interaction)

async def post_panel(channel: discord.TextChannel):
    embed = discord.Embed(
        title="🎮 診断スタート",
        description="下のボタンを押すと、あなた専用の診断ルームが作成されます。",
    )
    await channel.send(embed=embed, view=StartRoomView())

# =========================================================
# 固定メッセージ更新（質問Embed）
# =========================================================
async def upsert_question_message(channel: discord.TextChannel, user_id: int, idx: int, order: List[int]):
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

# =========================================================
# ルーム自動削除
# =========================================================
async def schedule_auto_delete(channel: discord.TextChannel, user_id: int, seconds: int):
    await asyncio.sleep(seconds)
    try:
        # 念のためまだ存在するか
        _ = await channel.guild.fetch_channel(channel.id)
    except Exception:
        return

    if is_user_room(channel, user_id):
        try:
            await channel.delete(reason=f"Auto close after diagnosis (user:{user_id})")
        except Exception:
            pass

# =========================================================
# ルーム作成・開始
# =========================================================
async def create_or_open_room(interaction: discord.Interaction):
    guild = interaction.guild
    assert guild is not None

    member = interaction.user
    assert isinstance(member, discord.Member)

    user_id = member.id
    safe_name = safe_channel_name(member.display_name)
    channel_name = f"診断-{safe_name}-{user_id % 10000}"

    # 既存ルーム再利用
    for ch in guild.text_channels:
        if is_user_room(ch, user_id):
            await interaction.response.send_message(f"既にあります：{ch.mention}", ephemeral=True)
            return

    if guild.me is None:
        await interaction.response.send_message("Bot情報の取得に失敗しました。少し待ってから再度お試しください。", ephemeral=True)
        return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }

    ch = await guild.create_text_channel(
        channel_name,
        topic=f"user:{user_id} name:{member.display_name}",
        overwrites=overwrites
    )

    await interaction.response.send_message(f"専用ルームを作成しました：{ch.mention}", ephemeral=True)
    await ch.send("📝 このルームは診断専用です。ボタンで回答してください。")

    # 初期化（sqliteはブロックするので to_thread）
    await asyncio.to_thread(reset_user, user_id)
    await asyncio.to_thread(reset_order, user_id)
    await asyncio.to_thread(reset_message_id, user_id)
    await asyncio.to_thread(set_state, user_id, 0)

    order = await asyncio.to_thread(get_or_create_order, user_id, [q["id"] for q in QUESTIONS])
    await upsert_question_message(ch, user_id, 0, order)

# =========================================================
# イベント
# =========================================================
@bot.event
async def on_ready():
    init_db()
    try:
        bot.add_view(StartRoomView())  # 永続ボタン
    except Exception as e:
        print("add_view failed:", repr(e))

    print("commands:", [c.name for c in bot.tree.get_commands()])
    print(f"Bot起動: {bot.user}")

@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return
    if WELCOME_CHANNEL_ID <= 0:
        return
    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if channel is None or not isinstance(channel, discord.TextChannel):
        return

    await channel.send(f"👋 {member.mention} さん、ようこそ！ボタンを押して診断スタート")
    await post_panel(channel)

@bot.event
async def on_interaction(interaction: discord.Interaction):
    # ボタン以外は無視（slash等はdiscord.pyが処理する）
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
            await interaction.followup.send("これはあなたの診断ではありません。", ephemeral=True)
            return

        # order取得
        order = await asyncio.to_thread(get_or_create_order, user_id, [q["id"] for q in QUESTIONS])

        # idxがズレていたら現在stateを優先
        cur_idx = await asyncio.to_thread(get_state, user_id)
        if isinstance(cur_idx, int) and 0 <= cur_idx < len(order):
            idx = cur_idx

        # 保存
        q = q_by_id(order[idx])
        await asyncio.to_thread(save_answer, user_id, q["id"], key)

        next_idx = idx + 1
        await asyncio.to_thread(set_state, user_id, next_idx)

        # 完了
        if next_idx >= len(order):
            result_text = "✅ **診断完了！**\n\n" + categorized_result(user_id)
            notice = f"\n\n⏳ {AUTO_CLOSE_SECONDS//10}分後にこのルームは自動削除されます。" 
            
        # ✅ 完了したらチャット解放（/match を打てるように）
        if isinstance(interaction.user, discord.Member):
            await unlock_chat_after_done(interaction.channel, interaction.user)

        mid = await asyncio.to_thread(get_message_id, user_id)
        if mid:
            try:
                msg = await interaction.channel.fetch_message(mid)
                await msg.edit(content=result_text + notice, embed=None, view=None)
            except Exception:
                    await interaction.followup.send(result_text + notice, ephemeral=True)
            else:
                await interaction.followup.send(result_text + notice, ephemeral=True)

            asyncio.create_task(schedule_auto_delete(interaction.channel, user_id, AUTO_CLOSE_SECONDS))
            return

        # 次の質問へ（固定メッセージ更新）
        await upsert_question_message(interaction.channel, user_id, next_idx, order)

    except Exception as e:
        await interaction.followup.send(f"⚠️ エラー：{type(e).__name__}", ephemeral=True)
        raise

# =========================================================
# コマンド
# =========================================================
@bot.tree.command(name="room", description="専用診断ルームを作成し自動で開始")
async def room(interaction: discord.Interaction):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
        return
    await create_or_open_room(interaction)

@bot.tree.command(name="panel", description="診断開始ボタンを設置（運営専用）")
async def panel(interaction: discord.Interaction):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
        return

    if not has_role_id(interaction.user, BOTADMIN_ROLE_ID):
        await interaction.response.send_message("権限がありません。", ephemeral=True)
        return

    await post_panel(interaction.channel)  # どこでも実行可
    await interaction.response.send_message("✅ 設置しました。", ephemeral=True)

@bot.tree.command(name="ping", description="動作確認（運営専用）")
async def ping(interaction: discord.Interaction):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
        return

    if not has_role_id(interaction.user, ADMIN_ROLE_ID):
        await interaction.response.send_message("このコマンドは運営専用です。", ephemeral=True)
        return

    await interaction.response.send_message("🏓 pong!", ephemeral=True)

@bot.tree.command(
    name="sync",
    description="コマンドを同期（運営専用）",
    guild=discord.Object(id=GUILD_ID) if GUILD_ID > 0 else None
)
async def sync_cmd(interaction: discord.Interaction):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
        return

    if not has_role_id(interaction.user, ADMIN_ROLE_ID):
        await interaction.response.send_message("権限がありません。", ephemeral=True)
        return

    # ✅ 3秒制限回避：先にACK
    await interaction.response.defer(ephemeral=True)

    # ✅ B案：グローバルコマンドをこのサーバーへコピーして即反映
    bot.tree.copy_global_to(guild=interaction.guild)

    synced = await bot.tree.sync(guild=interaction.guild)
    await interaction.followup.send(
        f"✅ 同期しました（{len(synced)}件）。`コマンド` が出るか確認してください。",
        ephemeral=True
    )

@bot.tree.command(name="logs", description="管理者用：利用状況を表示（Embed）")
async def logs(interaction: discord.Interaction):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
        return

    # 任意：管理チャンネル固定にしたいなら
    if ADMIN_CHANNEL_ID > 0 and interaction.channel_id != ADMIN_CHANNEL_ID:
        await interaction.response.send_message("このコマンドは管理者チャンネルでのみ使用できます。", ephemeral=True)
        return

    if not has_role_id(interaction.user, ADMIN_ROLE_ID):
        await interaction.response.send_message("権限がありません。", ephemeral=True)
        return

    total = count_total_users()
    completed = count_completed_users(len(QUESTIONS))
    inprogress = count_inprogress_users(len(QUESTIONS))
    rooms = [ch for ch in interaction.guild.text_channels if ch.name.startswith("match-")]

    embed = discord.Embed(
        title="📊 診断Bot 利用状況",
        description="管理者向けの集計情報です。",
    )
    embed.add_field(name="総ユーザー数", value=str(total), inline=True)
    embed.add_field(name="診断完了", value=str(completed), inline=True)
    embed.add_field(name="診断途中", value=str(inprogress), inline=True)
    embed.add_field(name="専用ルーム数", value=str(len(rooms)), inline=True)
    embed.add_field(name="質問数", value=str(len(QUESTIONS)), inline=True)
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed, ephemeral=True)

def compatibility_percent(picks_a: dict, picks_b: dict, categories: List[str]) -> int:
    usable = [c for c in categories if c in picks_a and c in picks_b]
    if not usable:
        return 0
    same = sum(1 for c in usable if picks_a[c] == picks_b[c])
    return int(round(same / len(usable) * 100))

@bot.tree.command(name="match", description="相性TOP3（任意表示）")
async def match(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
        return

    # 専用ルーム以外は拒否
    if not is_user_room(interaction.channel, interaction.user.id):
        await interaction.response.send_message("専用ルーム内で実行してください。", ephemeral=True)
        return

    # 診断完了チェック
    if get_state(interaction.user.id) < len(QUESTIONS):
        await interaction.response.send_message("診断が完了していません。先に質問に回答してください。", ephemeral=True)
        return

    me_picks, _ = build_profile(interaction.user.id)

    CATS = ["game_style", "communication", "play_time", "distance", "money", "future"]

    # 全ユーザー候補（answersテーブルから拾う）
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("SELECT DISTINCT user_id FROM answers")
        user_ids = [int(r[0]) for r in cur.fetchall()]

    results = []
    for uid in user_ids:
        if uid == interaction.user.id:
            continue
        if get_state(uid) < len(QUESTIONS):
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

    await interaction.response.send_message("\n".join(lines), ephemeral=True)

@bot.tree.command(name="close", description="自分の診断ルームを削除")
async def close(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
        return

    if is_user_room(interaction.channel, interaction.user.id):
        await interaction.response.send_message("このルームを削除します。", ephemeral=True)
        try:
            await interaction.channel.delete(reason="User requested close")
        except Exception:
            pass
    else:
        await interaction.response.send_message("この部屋は削除できません。", ephemeral=True)

# =========================================================
# 起動
# =========================================================
bot.run(TOKEN)







