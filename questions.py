# 質問はここに追加していくだけでOK
# questions.py
# 30問 / 6カテゴリ（各5問）
# 回答は A〜E の5段階（★☆☆☆☆〜★★★★★）

CHOICES_5 = [
    ("A", "まったく当てはまらない"),
    ("B", "あまり当てはまらない"),
    ("C", "どちらとも言えない"),
    ("D", "やや当てはまる"),
    ("E", "とても当てはまる"),
]

QUESTIONS = [
    # --- game_style（ゲームスタイル） ---
    {"id": 1, "category": "game_style", "text": "勝敗には強くこだわる方だ。", "choices": CHOICES_5},
    {"id": 2, "category": "game_style", "text": "負けた時もすぐ切り替えられる。", "choices": CHOICES_5},
    {"id": 3, "category": "game_style", "text": "攻略情報（Wiki/動画）をよく調べる。", "choices": CHOICES_5},
    {"id": 4, "category": "game_style", "text": "効率重視でプレイすることが多い。", "choices": CHOICES_5},
    {"id": 5, "category": "game_style", "text": "ひとつのゲームを長く続けるタイプだ。", "choices": CHOICES_5},

    # --- communication（コミュニケーション） ---
    {"id": 6, "category": "communication", "text": "VC（ボイスチャット）で話しながら遊ぶのが好きだ。", "choices": CHOICES_5},
    {"id": 7, "category": "communication", "text": "連携が必要な場面では自分から指示や提案を出す。", "choices": CHOICES_5},
    {"id": 8, "category": "communication", "text": "無言で一緒に遊んでも気にならない。", "choices": CHOICES_5},
    {"id": 9, "category": "communication", "text": "初対面の人とも比較的すぐに打ち解けられる。", "choices": CHOICES_5},
    {"id": 10, "category": "communication", "text": "ゲーム中の雑談やノリの共有は大事だと思う。", "choices": CHOICES_5},

    # --- play_time（プレイ時間・生活リズム） ---
    {"id": 11, "category": "play_time", "text": "平日でも定期的にゲームをする。", "choices": CHOICES_5},
    {"id": 12, "category": "play_time", "text": "深夜帯にプレイすることが多い。", "choices": CHOICES_5},
    {"id": 13, "category": "play_time", "text": "予定があっても、ついゲームを優先しがちだ。", "choices": CHOICES_5},
    {"id": 14, "category": "play_time", "text": "生活リズムは比較的安定している。", "choices": CHOICES_5},
    {"id": 15, "category": "play_time", "text": "ゲーム以外の趣味や時間も大切にしている。", "choices": CHOICES_5},

    # --- distance（距離感・人間関係） ---
    {"id": 16, "category": "distance", "text": "毎日こまめに連絡を取りたいタイプだ。", "choices": CHOICES_5},
    {"id": 17, "category": "distance", "text": "束縛や干渉が強い関係は苦手だ。", "choices": CHOICES_5},
    {"id": 18, "category": "distance", "text": "一人の時間は多めに必要だ。", "choices": CHOICES_5},
    {"id": 19, "category": "distance", "text": "トラブルや誤解があれば話し合って解決したい。", "choices": CHOICES_5},
    {"id": 20, "category": "distance", "text": "フレンド関係でも、プライベートの境界は分けたい。", "choices": CHOICES_5},

    # --- money（お金・課金感覚） ---
    {"id": 21, "category": "money", "text": "課金（スキン/バトルパス等）に抵抗は少ない。", "choices": CHOICES_5},
    {"id": 22, "category": "money", "text": "ゲームにお金をかけるのは“体験への投資”だと思う。", "choices": CHOICES_5},
    {"id": 23, "category": "money", "text": "趣味の出費は計画的に管理している。", "choices": CHOICES_5},
    {"id": 24, "category": "money", "text": "ガチャや限定品に熱くなりやすい。", "choices": CHOICES_5},
    {"id": 25, "category": "money", "text": "コスパ（費用対効果）を重視する。", "choices": CHOICES_5},

    # --- future（将来観・価値観） ---
    {"id": 26, "category": "future", "text": "ゲームは人生の中でかなり大きな存在だ。", "choices": CHOICES_5},
    {"id": 27, "category": "future", "text": "新しいことに挑戦するのが好きだ。", "choices": CHOICES_5},
    {"id": 28, "category": "future", "text": "安定よりも刺激や変化を求めることが多い。", "choices": CHOICES_5},
    {"id": 29, "category": "future", "text": "将来の目標や計画を立てる方だ。", "choices": CHOICES_5},
    {"id": 30, "category": "future", "text": "相手とは早めに価値観をすり合わせたい。", "choices": CHOICES_5},
]
