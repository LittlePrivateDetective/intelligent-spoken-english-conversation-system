"""GitHub Release 自动更新检查与一键更新（非阻塞、失败静默）。

启动时向 GitHub API 查询最新 Release，与当前版本比较；若发现更新，
GUI 弹出一个非阻塞横幅，可一键下载并替换安装（仅 exe 冻结态）。

设计要点：
- 走系统代理（requests 自动读取 http_proxy/https_proxy），与项目其它网络一致。
- 限流处理：GitHub API 未认证 60 次/小时；本模块每天最多检查一次，结果缓存到
  用户数据目录的 .update_cache.json。
- 一键更新：下载 Release 附件（zip）→ 解出 spoken.exe 生成 .new →
  写一个 Windows 批处理：等当前进程退出 → 备份旧 exe → 替换 → 重启 →
  自删。任何异常都返回 None / 抛给调用方降级为「手动前往下载页」。
"""

from __future__ import annotations

import json
import os
import sys
import time
import zipfile
from pathlib import Path

try:
    import requests
except ImportError:  # 极端情况下 requests 不可用，直接禁用更新检查
    requests = None

from . import __version__ as CURRENT_VERSION
from .paths import is_frozen, user_data_dir

REPO = "LittlePrivateDetective/intelligent-spoken-english-conversation-system"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CACHE_FILE = ".update_cache.json"
CHECK_INTERVAL = 24 * 3600  # 距上次检查 24 小时内不再联网
# 更新包中的 exe 名（打包产物固定为 spoken.exe）
EXE_NAME = "spoken.exe"


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
    """查询 GitHub 最新 Release，返回 {tag, url, published_at, asset_url} 或 None。"""
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
            "asset_url": _pick_asset_url(data.get("assets") or []),
        }
    except Exception:
        return None


def _pick_asset_url(assets: list, prefer_lite: bool = False) -> str:
    """从 Release 附件里挑 Windows 更新包。

    优先 zip（含 exe），其次裸 exe；``prefer_lite=True`` 时优先名字带
    "lite" 的包（精简版用户保持小体积更新），找不到则回退常规包。
    """
    zips = [a for a in assets
            if str(a.get("name", "")).lower().endswith(".zip")]
    exes = [a for a in assets
            if str(a.get("name", "")).lower() == EXE_NAME]
    pool = zips + exes
    if prefer_lite:
        lite = [a for a in pool if "lite" in str(a.get("name", "")).lower()]
        if lite:
            pool = lite
    for a in pool:
        url = a.get("browser_download_url")
        if url:
            return str(url)
    return ""


def check_for_update() -> dict | None:
    """带缓存与版本比较的更新检查：返回需提示的更新信息或 None。

    仅当距上次检查超过 24h 才联网；发现的新版本更新（比当前版本新）才返回。
    """
    cache = _load_cache()
    if time.time() - int(cache.get("checked_at", 0)) < CHECK_INTERVAL:
        latest = cache.get("latest_tag", "")
        info = None
    else:
        info = check_latest()
        latest = info["tag"] if info else cache.get("latest_tag", "")
        _save_cache(latest)
    if not latest:
        return None
    if not is_newer(latest):
        return None
    # 缓存命中时没有 asset_url，需要现查一次（仅发现新版本时才发生，频率极低）
    if info is None:
        info = check_latest() or {}
    return {
        "tag": latest,
        "url": f"https://github.com/{REPO}/releases/tag/{latest}",
        "published_at": "",
        "asset_url": info.get("asset_url", ""),
    }


# ----------------------------------------------------------------------
# 一键更新：下载 → 解出 exe → 生成替换批处理（仅冻结态可用）
# ----------------------------------------------------------------------
def download_asset(url: str, dest: Path,
                   progress_cb=None, timeout: int = 30) -> Path:
    """流式下载 Release 附件到 dest；progress_cb(done_bytes, total_bytes)。"""
    if requests is None:
        raise RuntimeError("requests 不可用，无法下载更新")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                fh.write(chunk)
                done += len(chunk)
                if progress_cb:
                    try:
                        progress_cb(done, total)
                    except Exception:
                        pass
    return dest


def extract_exe(zip_path: Path, dest_dir: Path) -> Path:
    """从更新 zip 中解出 spoken.exe 到 dest_dir，返回其路径。"""
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist()
                 if n.rsplit("/", 1)[-1].lower() == EXE_NAME]
        if not names:
            raise RuntimeError(f"更新包中未找到 {EXE_NAME}")
        target = dest_dir / (EXE_NAME + ".new")
        with zf.open(names[0]) as src, open(target, "wb") as dst:
            dst.write(src.read())
    return target


def build_update_script(script_path: Path, new_exe: Path,
                        pid: int | None = None) -> Path:
    """生成「等进程退出 → 备份替换 → 重启 → 自删」的 Windows 批处理。

    必须在退出程序前用 Popen 启动它；批处理通过 tasklist 等待旧进程消失，
    因此对 onefile exe（单文件整体替换）安全。
    """
    pid = pid or os.getpid()
    exe_dir = new_exe.parent
    bat = "\n".join([
        "@echo off",
        "setlocal",
        f'set "PID={pid}"',
        ":wait",
        f'tasklist /FI "PID eq %PID%" 2>nul | find /i "{EXE_NAME}" >nul',
        "if not errorlevel 1 (",
        "    timeout /t 1 /nobreak >nul",
        "    goto wait",
        ")",
        f'if exist "{exe_dir / (EXE_NAME + ".bak")}" del /f /q "{exe_dir / (EXE_NAME + ".bak")}"',
        f'if exist "{exe_dir / EXE_NAME}" ren "{exe_dir / EXE_NAME}" "{EXE_NAME}.bak"',
        f'move /y "{new_exe}" "{exe_dir / EXE_NAME}" >nul',
        f'if exist "{exe_dir / (EXE_NAME + ".bak")}" del /f /q "{exe_dir / (EXE_NAME + ".bak")}"',
        f'start "" "{exe_dir / EXE_NAME}"',
        f'del /f /q "%~f0"',
        "",
    ])
    script_path.write_text(bat, encoding="gbk")
    return script_path


def prepare_update(progress_cb=None) -> Path:
    """一键更新的完整准备流程，返回待执行的批处理路径。

    步骤：查最新版 → 下载 zip 到用户数据目录 → 解出 spoken.exe.new
    （放在当前 exe 旁）→ 写更新批处理。非冻结态直接抛 RuntimeError。
    精简版用户（无语音依赖）优先下载 lite 包，保持小体积更新。
    """
    if not is_frozen():
        raise RuntimeError("仅打包后的 exe 支持一键更新")
    from .asr import asr_available
    prefer_lite = not asr_available()
    info = check_for_update() or {}
    asset_url = _pick_asset_url(
        _release_assets(info.get("tag", "")), prefer_lite=prefer_lite) \
        if info.get("tag") else ""
    if not asset_url:
        raise RuntimeError("最新版本没有可下载的 Windows 附件")
    updates_dir = user_data_dir() / "updates"
    zip_path = updates_dir / f"spoken_{info.get('tag', 'latest')}.zip"
    download_asset(asset_url, zip_path, progress_cb=progress_cb)
    new_exe = extract_exe(zip_path, Path(sys.executable).parent)
    script = Path(sys.executable).parent / "spoken_update.bat"
    return build_update_script(script, new_exe)


def _release_assets(tag: str) -> list:
    """按 tag 查 Release 附件列表（check_latest 只返回 latest，这里按需补查）。"""
    if not tag:
        return []
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{REPO}/releases/tags/{tag}",
            timeout=10, headers={"Accept": "application/vnd.github+json"})
        if resp.status_code != 200:
            return []
        return resp.json().get("assets") or []
    except Exception:
        return []
