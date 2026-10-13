"""faster-whisper 模型下载器：国内镜像 + 断点续传 + 自动重试。

为什么不用 huggingface_hub 自带下载：
1. 经 hf-mirror.com 下载 145MB 大文件时，连接经常被重置
   （WinError 10054 远程主机强迫关闭连接）；
2. 一旦失败，HF 本地缓存会留下 "incomplete snapshot" 状态，
   之后每次重试都被这个状态卡住，必须手动清缓存。

本模块用 requests 直连镜像的 resolve 地址，把文件下载到项目
`models/faster-whisper-<size>/` 目录：
- HTTP Range 断点续传（连接被断后从已下载位置继续）；
- 失败自动重试（指数退避，最多 9 次尝试）；
- 完成后校验文件大小；
- 已完整的文件直接跳过，可反复调用。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import requests

DEFAULT_MIRROR = "https://hf-mirror.com"
REPO_TEMPLATE = "Systran/faster-whisper-{size}"

# WhisperModel 实际加载需要的文件（.gitattributes / README.md 跳过）
NEEDED_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")

# 单次连接/读取超时（秒）：连接 15s，两次数据包之间 60s
_TIMEOUT = (15, 60)
_CHUNK = 1 << 18  # 256KB


class ModelDownloadError(RuntimeError):
    """模型文件下载失败（多次重试后仍无法完成）。"""


def default_model_dir() -> Path:
    """模型存放目录：项目根目录下的 models/（可用 SPOKEN_MODEL_DIR 覆盖）。"""
    env = os.environ.get("SPOKEN_MODEL_DIR")
    if env:
        return Path(env)
    # 本文件位于 <项目根>/spoken/model_download.py，parents[1] 即项目根
    return Path(__file__).resolve().parents[1] / "models"


def model_dir(model_size: str) -> Path:
    """某个模型尺寸的本地目录，如 models/faster-whisper-base。"""
    return default_model_dir() / f"faster-whisper-{model_size}"


def _mirror_base() -> str:
    """下载源：优先 HF_ENDPOINT 环境变量，默认国内镜像。"""
    return (os.environ.get("HF_ENDPOINT") or DEFAULT_MIRROR).rstrip("/")


def _range_header(pos: int) -> dict:
    """构造断点续传请求头（纯函数，便于测试）。"""
    return {"Range": f"bytes={pos}-"} if pos > 0 else {}


def _remote_size(session: requests.Session, url: str) -> int | None:
    """探测远端文件大小；失败返回 None（不阻塞下载流程）。

    不用 HEAD：镜像站 CDN 对 HEAD 不返回 Content-Length。
    改用 GET + Range: bytes=0-0：服务端支持 Range 时返回
    206 和 Content-Range（含总大小），否则退回 200 的 Content-Length。
    """
    try:
        with session.get(
            url, headers={"Range": "bytes=0-0"}, timeout=(15, 30), stream=True
        ) as resp:
            if resp.status_code == 206:
                content_range = resp.headers.get("Content-Range", "")
                if "/" in content_range:
                    try:
                        return int(content_range.rsplit("/", 1)[1])
                    except ValueError:
                        pass
            length = resp.headers.get("Content-Length", "")
            if length.isdigit():
                return int(length)
    except requests.RequestException:
        pass
    return None


def _parse_total(resp: requests.Response, pos: int) -> int | None:
    """从响应头解析文件总大小（206 时用 Content-Range，200 时用 Content-Length）。"""
    if resp.status_code == 206:
        content_range = resp.headers.get("Content-Range", "")
        if "/" in content_range:
            try:
                return int(content_range.rsplit("/", 1)[1])
            except ValueError:
                pass
    length = resp.headers.get("Content-Length", "")
    if length.isdigit():
        return int(length) + (pos if resp.status_code == 206 else 0)
    return None


def _download_one(
    session: requests.Session,
    url: str,
    dest: Path,
    total: int | None,
    name: str,
    progress=None,
    retries: int = 8,
) -> None:
    """下载单个文件（支持续传 + 重试）。全部失败时抛 ModelDownloadError。"""
    part = dest.with_name(dest.name + ".part")
    for attempt in range(1, retries + 2):
        pos = part.stat().st_size if part.exists() else 0
        if total is not None and pos > total:
            part.unlink(missing_ok=True)  # 本地残留比远端还大：损坏，重下
            pos = 0
        try:
            with session.get(
                url, stream=True, headers=_range_header(pos), timeout=_TIMEOUT
            ) as resp:
                if resp.status_code == 416:
                    break  # Range 越界：服务端认为已完整
                if resp.status_code not in (200, 206):
                    # HTTP 层错误（404/403 等）：重试无意义，直接抛出
                    raise ModelDownloadError(
                        f"下载 {name} 时服务器返回 HTTP {resp.status_code}")
                if resp.status_code == 200:
                    pos = 0  # 服务端忽略 Range，从头下载
                if total is None:
                    total = _parse_total(resp, pos)
                mode = "ab" if (resp.status_code == 206 and pos) else "wb"
                with open(part, mode) as fh:
                    for chunk in resp.iter_content(chunk_size=_CHUNK):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        pos += len(chunk)
                        if progress and total:
                            progress(name, pos, total)
        except ModelDownloadError:
            raise
        except (requests.RequestException, OSError) as exc:
            # 连接被重置/超时：保留 .part 进度，退避后重试（自动续传）
            if attempt > retries:
                raise ModelDownloadError(
                    f"下载 {name} 失败（重试 {retries} 次后连接仍中断）：{exc}"
                ) from exc
            time.sleep(min(2 ** attempt, 10))
            continue
        # 一轮传输正常结束：校验大小
        if total is None or part.stat().st_size == total:
            break
        # 大小不匹配：删掉残留重下
        part.unlink(missing_ok=True)
        if attempt > retries:
            raise ModelDownloadError(f"{name} 下载不完整（大小校验失败）")
        time.sleep(min(2 ** attempt, 10))

    if total is not None and part.stat().st_size != total:
        part.unlink(missing_ok=True)
        raise ModelDownloadError(f"{name} 下载不完整（大小校验失败）")
    part.replace(dest)


def _fetch_manifest(session: requests.Session, mirror: str,
                    repo: str) -> dict:
    """从镜像 API 获取仓库文件清单 {文件名: 字节数}；失败返回空 dict。"""
    try:
        resp = session.get(f"{mirror}/api/models/{repo}?blobs=true",
                           timeout=(15, 30))
        if resp.status_code == 200:
            return {
                s["rfilename"]: s["size"]
                for s in resp.json().get("siblings", [])
                if s.get("rfilename") and s.get("size")
            }
    except (requests.RequestException, ValueError):
        pass
    return {}


def ensure_local_model(
    model_size: str,
    progress=None,
    retries: int = 8,
) -> Path:
    """确保模型完整存在于本地 models/faster-whisper-<size>/，返回目录路径。

    progress: 可选回调 progress(filename, done_bytes, total_bytes)。
    已下载且大小正确的文件会跳过，可安全重复调用。
    """
    dest_dir = model_dir(model_size)
    dest_dir.mkdir(parents=True, exist_ok=True)
    base = _mirror_base()
    repo = REPO_TEMPLATE.format(size=model_size)

    with requests.Session() as session:
        # 文件大小以 API 清单为准（小文件不走 LFS，探测不到大小）
        manifest = _fetch_manifest(session, base, repo)
        for name in NEEDED_FILES:
            dest = dest_dir / name
            url = f"{base}/{repo}/resolve/main/{name}"
            total = manifest.get(name) or _remote_size(session, url)
            if total is not None and dest.exists() and dest.stat().st_size == total:
                if progress:
                    progress(name, total, total)
                continue
            _download_one(session, url, dest, total, name, progress, retries)
    return dest_dir
