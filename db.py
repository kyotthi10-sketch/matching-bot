import sqlite3
import json
import random
from typing import List, Tuple, Optional

DB_PATH = "app.db"


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()

        # --- tables ---
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_state (
            user_id INTEGER PRIMARY KEY,
            idx INTEGER NOT NULL
        )
        """)

        # いまのコードが期待する正式スキーマ（question_id / answer）
        cur.execute("""
        CREATE TABLE IF NOT EXISTS answers (
            user_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            answer TEXT NOT NULL,
            PRIMARY KEY (user_id, question_id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS question_order (
            user_id INTEGER PRIMARY KEY,
            order_json TEXT NOT NULL
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_msg (
            user_id INTEGER PRIMARY KEY,
            message_id INTEGER NOT NULL
        )
        """)

        # --- migration: old schema (qid/ans) -> new schema (question_id/answer) ---
        _migrate_answers_table(cur)

        con.commit()


def _table_columns(cur: sqlite3.Cursor, table: str) -> list[str]:
    cur.execute(f"PRAGMA table_info({table})")
    return [r[1] for r in cur.fetchall()]


def _add_column_if_missing(cur: sqlite3.Cursor, table: str, col: str, coldef: str) -> None:
    cols = _table_columns(cur, table)
    if col not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coldef}")


def _migrate_answers_table(cur: sqlite3.Cursor) -> None:
    """
    旧 answers: (user_id, qid, ans) PRIMARY KEY(user_id, qid)
    新 answers: (user_id, question_id, answer) PRIMARY KEY(user_id, question_id)

    旧列が存在していた場合は新列へコピーし、以後は新列で運用。
    """
    cols = _table_columns(cur, "answers")

    # もし旧スキーマで作られてしまっている場合、列を追加してデータをコピーする
    if "qid" in cols and "ans" in cols:
        _add_column_if_missing(cur, "answers", "question_id", "INTEGER")
        _add_column_if_missing(cur, "answers", "answer", "TEXT")

        # まだコピーしていない行だけコピー（question_idがNULLのもの）
        cur.execute("""
        UPDATE answers
        SET question_id = qid
        WHERE question_id IS NULL
        """)
        cur.execute("""
        UPDATE answers
        SET answer = ans
        WHERE answer IS NULL
        """)

        # PRIMARY KEYが旧(user_id,qid)のままでも、
        # 保存/参照は question_id/answer を使える状態になる。
        # （完全にPKを変更したいならテーブル作り直しが必要だが、まず動かすことを優先）


def get_state(user_id: int) -> int:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("SELECT idx FROM user_state WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row is None:
            cur.execute("INSERT INTO user_state(user_id, idx) VALUES(?, 0)", (user_id,))
            con.commit()
            return 0
        return int(row[0])


def set_state(user_id: int, idx: int) -> None:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("""
        INSERT INTO user_state(user_id, idx) VALUES(?, ?)
        ON CONFLICT(user_id) DO UPDATE SET idx=excluded.idx
        """, (user_id, idx))
        con.commit()


def save_answer(user_id: int, question_id: int, answer: str) -> None:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()

        # 旧DBで PRIMARY KEY(user_id,qid) のままでも動くように両対応
        cols = _table_columns(cur, "answers")
        if "question_id" in cols and "answer" in cols:
            cur.execute("""
            INSERT INTO answers(user_id, question_id, answer) VALUES(?, ?, ?)
            ON CONFLICT(user_id, question_id) DO UPDATE SET answer=excluded.answer
            """, (user_id, question_id, answer))
        else:
            # 念のためのフォールバック（基本ここには来ない）
            cur.execute("""
            INSERT INTO answers(user_id, qid, ans) VALUES(?, ?, ?)
            ON CONFLICT(user_id, qid) DO UPDATE SET ans=excluded.ans
            """, (user_id, question_id, answer))

        con.commit()


def load_answers(user_id: int) -> List[Tuple[int, str]]:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cols = _table_columns(cur, "answers")

        if "question_id" in cols and "answer" in cols:
            cur.execute("""
            SELECT question_id, answer
            FROM answers
            WHERE user_id=?
            ORDER BY question_id
            """, (user_id,))
            return [(int(qid), ans) for (qid, ans) in cur.fetchall()]

        # 旧形式フォールバック
        cur.execute("""
        SELECT qid, ans
        FROM answers
        WHERE user_id=?
        ORDER BY qid
        """, (user_id,))
        return [(int(qid), ans) for (qid, ans) in cur.fetchall()]


def reset_user(user_id: int) -> None:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("DELETE FROM answers WHERE user_id=?", (user_id,))
        cur.execute("DELETE FROM user_state WHERE user_id=?", (user_id,))
        con.commit()


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


def get_or_create_order(user_id: int, question_ids: list[int]) -> list[int]:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("SELECT order_json FROM question_order WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row:
            return json.loads(row[0])

        ids = question_ids[:]
        random.shuffle(ids)
        cur.execute(
            "INSERT OR REPLACE INTO question_order(user_id, order_json) VALUES(?, ?)",
            (user_id, json.dumps(ids))
        )
        con.commit()
        return ids


def reset_order(user_id: int) -> None:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("DELETE FROM question_order WHERE user_id=?", (user_id,))
        con.commit()


def get_message_id(user_id: int) -> Optional[int]:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("SELECT message_id FROM user_msg WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return int(row[0]) if row else None


def set_message_id(user_id: int, message_id: int) -> None:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("""
        INSERT INTO user_msg(user_id, message_id) VALUES(?, ?)
        ON CONFLICT(user_id) DO UPDATE SET message_id=excluded.message_id
        """, (user_id, message_id))
        con.commit()


def reset_message_id(user_id: int) -> None:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("DELETE FROM user_msg WHERE user_id=?", (user_id,))
        con.commit()
