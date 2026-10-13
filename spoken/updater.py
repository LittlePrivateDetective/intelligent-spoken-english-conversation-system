"""GitHub Release 自动更新检查（非阻塞、失败静默）。

启动时向 GitHub API 查询最新 Release，与当前版本比较；若发现更新，
GUI 弹出一个非阻塞横幅，点击可前往下载页。

设计要点：
- 走系统代理（requests 自动读取 http_proxy/https_proxy），与项目其它网络一致。
- 限流处理：GitHub API 未认证 60 次/小时；本模块每天最多检查一次，结果缓存到
  用户数据目录的 .update_cache.json。
- 任何异常（无网 / 超时 / 限流 / 解析失败）都返回 None，调用方据此静默跳过。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

try:
    import requests
except ImportError:  # 极端情况下 requests 不可用，直接禁用更新检查
    requests = None

from . import __version__ as CURRENT_VERSION
from .paths import user_data_dir

REPO = "LittlePrivateDetective/intelligent-spoken-english-conversation-system"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CACHE_FILE = ".update_cache.json"
CHECK_INTERVAL = 24 * 3600  # 距上次检查 24 小时内不再联网


def _cache_path() -> Path:
    return user_data_dir() / CACHE_FILE


def _load_cache() -> dict:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(latest_tag: str) -> None:
    try:
        _cache_path().write_text(
            json.dumps({"checked_at": int(time.time()), "latest_tag": latest_tag},
                      ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass


def parse_version(tag: str) -> tuple:
    """把 'v1.2.3' / '1.2.3' 解析成 (1, 2, 3) 用于比较；解析失败返回空元组。"""
    s = tag.lstrip("vV").strip()
    parts: list[int] = []
    for piece in s.split("."):
        if piece.isdigit():
            parts.append(int(piece))
        else:
            break
    return tuple(parts)


def is_newer(latest_tag: str, current: str = CURRENT_VERSION) -> bool:
    """判断 latest_tag 是否比 current 新（按语义化版本号逐段比较）。"""
    a, b = parse_version(latest_tag), parse_version(current)
    if not a:
        return False
    # 长度不等时补齐 0
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


def check_latest(timeout: int = 5) -> dict | None:
    """查询 GitHub 最新 Release，返回 {tag, url, published_at} 或 None。"""
    if requests is None:
        return None
    try:
        resp = requests.get(API_URL, timeout=timeout,
                            headers={"Accept": "application/vnd.github+json"})
        if resp.status_code != 200:
            return None
        data = resp.json()
        tag = data.get("tag_name")
        if not tag:
            return None
        return {
            "tag": tag,
            "url": data.get("html_url", f"https://github.com/{REPO}/releases"),
            "published_at": data.get("published_at", ""),
        }
    except Exception:
        return None


def check_for_update() -> dict | None:
    """带缓存与版本比较的更新检查：返回需提示的更新信息或 None。

    仅当距上次检查超过 24h 才联网；发现的新版本更新（比当前版本新）才返回。
    """
    cache = _load_cache()
    if time.time() - int(cache.get("checked_at", 0)) < CHECK_INTERVAL:
        latest = cache.get("latest_tag", "")
    else:
        info = check_latest()
        latest = info["tag"] if info else cache.get("latest_tag", "")
        _save_cache(latest)
    if not latest:
        return None
    if not is_newer(latest):
        return None
    return {
        "tag": latest,
        "url": f"https://github.com/{REPO}/releases/tag/{latest}",
        "published_at": "",
    }
