"""练习历史 / 进度记录：用标准库 sqlite3 把每次练习存到本地数据库。

记录字段：日期、场景、难度、发音总分、准确度、完整度、流利度、参考句。
提供历史列表与统计（平均分、按日期的平均分趋势），供 GUI 展示。
不引入任何第三方依赖。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .paths import data_file


# 默认数据库文件：源码态在项目根，冻结态（exe）在用户数据目录
DEFAULT_DB = data_file("practice_history.db")


def _connect(db_path) -> sqlite3.Connection:
    path = str(db_path) if db_path else str(DEFAULT_DB)
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            scenario TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            overall REAL, accuracy REAL, integrity REAL, fluency REAL,
            ref_text TEXT
        )"""
    )
    return conn


def add_session(db_path, *, scenario: str, difficulty: str,
                overall: float, accuracy: float, integrity: float,
                fluency: float, ref_text: str = "",
                ts: str | None = None) -> int:
    """写入一条练习记录，返回新记录 id。"""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO sessions
               (ts, scenario, difficulty, overall, accuracy, integrity, fluency, ref_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts or datetime.now().isoformat(timespec="seconds"),
             scenario, difficulty, overall, accuracy, integrity, fluency,
             ref_text or ""),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_sessions(db_path, limit: int = 200) -> list[dict]:
    """最近的练习记录（按时间倒序）。"""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, ts, scenario, difficulty, overall, accuracy, "
            "integrity, fluency, ref_text FROM sessions "
            "ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "ts": r[1], "scenario": r[2], "difficulty": r[3],
            "overall": r[4], "accuracy": r[5], "integrity": r[6],
            "fluency": r[7], "ref_text": r[8],
        })
    return out


@dataclass
class Stats:
    count: int
    avg_overall: float
    avg_accuracy: float
    avg_integrity: float
    avg_fluency: float
    trend: list  # [(date_str, avg_overall), ...] 按日期升序（兼容旧字段）
    trends: dict = field(default_factory=dict)
    # trends: {"overall": [(day, val)], "accuracy": [...], "integrity": [...],
    #          "fluency": [...]} 分维度趋势，供多折线图使用


def stats(db_path) -> Stats:
    """统计：总次数、各维度平均分、按日期的平均分趋势（总分 + 三个分维度）。"""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT overall, accuracy, integrity, fluency FROM sessions"
        ).fetchall()
        trend_rows = conn.execute(
            "SELECT substr(ts, 1, 10) AS day, AVG(overall) "
            "FROM sessions GROUP BY day ORDER BY day ASC"
        ).fetchall()
        dim_rows = {}
        for dim in ("overall", "accuracy", "integrity", "fluency"):
            dim_rows[dim] = conn.execute(
                f"SELECT substr(ts, 1, 10) AS day, AVG({dim}) "
                "FROM sessions GROUP BY day ORDER BY day ASC"
            ).fetchall()
    finally:
        conn.close()

    n = len(rows)
    if n == 0:
        return Stats(0, 0.0, 0.0, 0.0, 0.0, [], {k: [] for k in dim_rows})
    avg_overall = sum(r[0] or 0 for r in rows) / n
    avg_accuracy = sum(r[1] or 0 for r in rows) / n
    avg_integrity = sum(r[2] or 0 for r in rows) / n
    avg_fluency = sum(r[3] or 0 for r in rows) / n
    trend = [(day, round(avg, 1)) for day, avg in trend_rows]
    trends = {dim: [(day, round(avg, 1)) for day, avg in rows_]
              for dim, rows_ in dim_rows.items()}
    return Stats(n, round(avg_overall, 1), round(avg_accuracy, 1),
                 round(avg_integrity, 1), round(avg_fluency, 1), trend, trends)
