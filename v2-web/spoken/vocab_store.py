"""生词本本地存储：sqlite3 标准库，零第三方依赖。

记录字段：id、word、word_key（小写，用于去重/排序）、created_at、data（完整 JSON）。
提供：保存（按词 upsert，保留复习排期）、列表（时间/字母排序 + 搜索）、删除、计数、
今日待复习列表与复习结果回写（SM-2 简化排期）。
离线可用：所有已收藏词条直接从本地读取，无需联网。
"""

from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path

from .paths import data_file
from .vocab_model import VocabEntry

# 默认数据库文件：源码态在项目根，冻结态（exe）在用户数据目录
DEFAULT_DB = data_file("vocab.db")

# 复习质量 → SM-2 简化的连续答对间隔（天）
_REVIEW_INTERVALS = [1, 3, 7, 14, 30, 60, 120]


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
    """写入一条生词；同一单词（大小写不敏感）已存在则更新，返回记录 id。

    更新时保留既有的复习排期（due/interval/reps）——重新生成词条不应
    清空用户的复习进度。
    """
    conn = _connect(db_path)
    key = entry.word.strip().lower()
    data = json.dumps(entry.to_dict(), ensure_ascii=False)
    try:
        row = conn.execute(
            "SELECT id, data FROM vocab WHERE word_key=?", (key,)).fetchone()
        if row:
            try:
                old = json.loads(row[1])
                for f in ("due", "interval", "reps"):
                    if not getattr(entry, f, None) and old.get(f):
                        setattr(entry, f, old[f])
                data = json.dumps(entry.to_dict(), ensure_ascii=False)
            except Exception:
                pass
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


# ----------------------------------------------------------------------
# 复习排期（遗忘曲线，SM-2 简化）
# ----------------------------------------------------------------------
def _today() -> str:
    return datetime.date.today().isoformat()


def due_words(db_path, today: str | None = None) -> list[VocabEntry]:
    """今天到期待复习的生词（从未复习的 due 为空，也算待复习）。"""
    today = today or _today()
    due: list[VocabEntry] = []
    for entry in list_words(db_path, sort="alpha"):
        if not entry.due or entry.due[:10] <= today:
            due.append(entry)
    return due


def update_review(db_path, word_id: int, quality: str) -> str:
    """回写一次复习结果，返回新的到期日（ISO 字符串）。

    quality: "know"（认识，间隔进入下一档）/ "vague"（模糊，间隔不变或压到 1 天）
             / "forgot"（忘记，重新从 1 天开始）。
    """
    today = datetime.date.today()
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT data FROM vocab WHERE id=?",
                           (word_id,)).fetchone()
        if not row:
            raise ValueError(f"生词不存在：id={word_id}")
        data = json.loads(row[0])
        reps = int(data.get("reps", 0) or 0)
        interval = int(data.get("interval", 0) or 0)
        if quality == "forgot":
            # 忘记：当天内会再次出现（间隔 0 天），重新从第一档开始
            reps, interval = 0, 0
        elif quality == "vague":
            interval = 1 if reps == 0 else max(1, interval)
        else:  # know
            reps += 1
            interval = _REVIEW_INTERVALS[min(reps, len(_REVIEW_INTERVALS)) - 1]
        due = (today + datetime.timedelta(days=interval)).isoformat()
        data.update({"due": due, "interval": interval, "reps": reps})
        conn.execute("UPDATE vocab SET data=? WHERE id=?",
                     (json.dumps(data, ensure_ascii=False), word_id))
        conn.commit()
        return due
    finally:
        conn.close()
