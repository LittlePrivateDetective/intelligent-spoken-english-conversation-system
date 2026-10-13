"""生词本本地存储：sqlite3 标准库，零第三方依赖。

记录字段：id、word、word_key（小写，用于去重/排序）、created_at、data（完整 JSON）。
提供：保存（按词 upsert）、列表（时间/字母排序 + 搜索）、删除、计数。
离线可用：所有已收藏词条直接从本地读取，无需联网。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .vocab_model import VocabEntry

# 默认数据库文件放在项目根目录（与练习历史库并列）
DEFAULT_DB = Path(__file__).resolve().parent.parent / "vocab.db"


def _connect(db_path) -> sqlite3.Connection:
    path = str(db_path) if db_path else str(DEFAULT_DB)
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS vocab (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL,
            word_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            data TEXT NOT NULL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_vocab_word_key ON vocab(word_key)")
    return conn


def save_word(db_path, entry: VocabEntry) -> int:
    """写入一条生词；同一单词（大小写不敏感）已存在则更新，返回记录 id。"""
    conn = _connect(db_path)
    key = entry.word.strip().lower()
    data = json.dumps(entry.to_dict(), ensure_ascii=False)
    try:
        row = conn.execute(
            "SELECT id FROM vocab WHERE word_key=?", (key,)).fetchone()
        if row:
            conn.execute(
                "UPDATE vocab SET word=?, created_at=?, data=? WHERE id=?",
                (entry.word, entry.created_at, data, row[0]))
            conn.commit()
            return int(row[0])
        cur = conn.execute(
            "INSERT INTO vocab (word, word_key, created_at, data) "
            "VALUES (?, ?, ?, ?)",
            (entry.word, key, entry.created_at, data))
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_words(db_path, *, sort: str = "time",
               search: str = "") -> list[VocabEntry]:
    """读取生词列表。

    sort: "time"=按收藏时间倒序；"alpha"=按单词字母升序。
    search: 非空时在 word 或完整内容里模糊匹配。
    返回 VocabEntry 列表（已填充 id）。
    """
    conn = _connect(db_path)
    try:
        q = "SELECT id, data FROM vocab"
        params: list = []
        if search:
            like = f"%{search}%"
            q += " WHERE word LIKE ? OR data LIKE ?"
            params = [like, like]
        if sort == "alpha":
            q += " ORDER BY word_key ASC, id ASC"
        else:
            q += " ORDER BY created_at DESC, id DESC"
        rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()

    out: list[VocabEntry] = []
    for row_id, data in rows:
        try:
            entry = VocabEntry.from_dict(json.loads(data))
            entry.id = int(row_id)
            out.append(entry)
        except Exception:
            continue
    return out


def delete_word(db_path, word_id: int) -> None:
    """按 id 删除一条生词。"""
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM vocab WHERE id=?", (word_id,))
        conn.commit()
    finally:
        conn.close()


def count_words(db_path) -> int:
    conn = _connect(db_path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM vocab").fetchone()[0])
    finally:
        conn.close()
