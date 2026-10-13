"""用户自定义场景：读写 ``custom_scenarios.json``。

与内置 ``SCENARIOS`` 不同，自定义场景保存在「用户数据目录」
（源码态为当前目录，exe 态为 ``%APPDATA%/spoken``），不进入仓库，
随用户机器持久化。每个场景是一个 dict，字段与内置场景一致：

    {
      "key": "custom_xxx",          # 以 custom_ 前缀唯一标识
      "name": "商务谈判",
      "name_en": "Business Negotiation",
      "summary": "…",
      "ai_role": "…",
      "user_role": "…",
      "setting": "…",
      "goals": "…",
      "hotwords": "negotiate contract …",   # 可选，提升识别准确率
      "created_at": "2026-10-13T17:00:00"
    }
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .paths import user_data_dir

KEY_PREFIX = "custom_"

# 自定义场景必须提供的字段（缺省时用占位值，保证程序不崩）
_REQUIRED = ("name", "name_en", "summary", "ai_role", "user_role", "setting", "goals")

# 测试时可临时覆盖存储路径，避免污染真实用户数据目录。
_FILE_OVERRIDE: "Path | None" = None


def set_storage_path(path) -> None:
    """覆盖自定义场景文件的存储位置（主要用于测试）。传 None 恢复默认。"""
    global _FILE_OVERRIDE
    _FILE_OVERRIDE = Path(path) if path else None


def file_path() -> Path:
    """自定义场景 JSON 文件位置（可被 set_storage_path 覆盖）。"""
    if _FILE_OVERRIDE is not None:
        return _FILE_OVERRIDE
    return user_data_dir() / "custom_scenarios.json"


def load() -> dict:
    """读取全部自定义场景，返回 ``{key: scenario}``。

    文件不存在或损坏时返回空字典（不抛错，保证首次使用顺畅）。
    """
    path = file_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    # 仅保留结构合法的项，脏数据不拖垮整份文件
    clean: dict = {}
    for key, scn in raw.items():
        if isinstance(scn, dict) and scn.get("name"):
            scn.setdefault("key", key)
            _fill_defaults(scn)
            clean[key] = scn
    return clean


def _fill_defaults(scn: dict) -> None:
    for field in _REQUIRED:
        scn.setdefault(field, "")
    scn.setdefault("hotwords", "")
    scn.setdefault("created_at", "")


def save_all(data: dict) -> None:
    """整体写回自定义场景文件。"""
    path = file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def new_key() -> str:
    """生成一个未占用的自定义场景 key。"""
    existing = load()
    while True:
        key = f"{KEY_PREFIX}{uuid.uuid4().hex[:8]}"
        if key not in existing:
            return key


def upsert(scn: dict) -> str:
    """新增或更新一个自定义场景，返回其 key。

    ``scn`` 需含 ``name`` 等必填字段；若未带 ``key`` 视为新增并分配 key。
    """
    data = load()
    key = scn.get("key")
    if not key or not str(key).startswith(KEY_PREFIX):
        key = new_key()
    scn["key"] = key
    _fill_defaults(scn)
    scn["created_at"] = scn.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%S")
    data[key] = scn
    save_all(data)
    return key


def delete(key: str) -> bool:
    """删除指定 key 的自定义场景，返回是否真的删掉了。"""
    if not str(key).startswith(KEY_PREFIX):
        return False
    data = load()
    if key in data:
        del data[key]
        save_all(data)
        return True
    return False


def ordered_keys(data: dict | None = None) -> list:
    """按创建时间排序的自定义场景 key 列表。"""
    data = load() if data is None else data
    items = list(data.items())
    items.sort(key=lambda kv: kv[1].get("created_at", ""))
    return [k for k, _ in items]
