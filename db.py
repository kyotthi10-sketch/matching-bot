import sqlite3
from typing import List, Tuple

DB_PATH = "app.db"

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_state (
            user_id INTEGER PRIMARY KEY,
            idx INTEGER NOT NULL DEFAULT 0
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS answers (
            user_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            answer TEXT NOT NULL,
            PRIMARY KEY (user_id, question_id)
        )
        """)
        con.commit()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS question_order (
            user_id INTEGER PRIMARY KEY,
            order_json TEXT NOT NULL
        )
        """)

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
        cur.execute("""
        INSERT INTO answers(user_id, question_id, answer) VALUES(?, ?, ?)
        ON CONFLICT(user_id, question_id) DO UPDATE SET answer=excluded.answer
        """, (user_id, question_id, answer))
        con.commit()

def load_answers(user_id: int) -> List[Tuple[int, str]]:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("SELECT question_id, answer FROM answers WHERE user_id=? ORDER BY question_id", (user_id,))
        return [(int(qid), ans) for (qid, ans) in cur.fetchall()]

def reset_user(user_id: int) -> None:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("DELETE FROM answers WHERE user_id=?", (user_id,))
        cur.execute("DELETE FROM user_state WHERE user_id=?", (user_id,))
        con.commit()
import sqlite3

DB_PATH = "app.db"  # 既にある場合は不要

def count_total_users() -> int:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM user_state")
        return int(cur.fetchone()[0])

def count_completed_users(total_questions: int) -> int:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM user_state WHERE idx >= ?",
            (total_questions,)
        )
        return int(cur.fetchone()[0])

def count_inprogress_users(total_questions: int) -> int:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM user_state WHERE idx < ?",
            (total_questions,)
        )
        return int(cur.fetchone()[0])

import json
import random

def get_or_create_order(user_id: int, question_ids: list[int]) -> list[int]:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("SELECT order_json FROM question_order WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row:
            return json.loads(row[0])

        ids = question_ids[:]  # copy
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

