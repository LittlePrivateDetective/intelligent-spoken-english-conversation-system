"""apppaths.py —— 应用路径解析（源码运行 / PyInstaller 打包 exe 两态通用）。

两种运行形态：
1. 源码运行（`python launcher.py` 或 `python server.py`）：
   - 只读资源（web/、papers/）就在本目录
   - 可写配置优先复用 ../v1-desktop/config.yaml（开发时的习惯位置）
2. 打包后的 exe：
   - 只读资源在 PyInstaller 解包目录（sys._MEIPASS）
   - 可写配置在 %APPDATA%/spoken-web/config.yaml
     绝不能把开发者自己的 API Key 打进 exe 分发，首次运行从内置模板生成。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "spoken-web"
APP_TITLE = "spoken · 智能英语口语教练"


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包后的可执行文件中。"""
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


def bundle_dir() -> Path:
    """只读资源根目录：web/、papers/、config.example.yaml 等随包分发的文件。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", str(Path(sys.executable).parent)))
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """可写数据目录（config.yaml、数据库、日志）。"""
    if is_frozen():
        if os.name == "nt":
            base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        elif sys.platform == "darwin":
            base = str(Path.home() / "Library" / "Application Support")
        else:
            base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / APP_NAME
    else:
        # 源码态：配置就放 v2-web 目录（与仓库约定一致）
        path = Path(__file__).resolve().parent
    path.mkdir(parents=True, exist_ok=True)
    return path


# 源码开发时，用户真实填过 Key 的配置通常放在上一级目录（v1 桌面版那里）。
# 仓库结构是 v1-desktop/{config.yaml, spoken/, v2-web/}，所以候选两处：
#   ../config.yaml              —— v2-web 与 config.yaml 同级（并入仓库后的布局）
#   ../v1-desktop/config.yaml   —— v2-web 独立放在工作区根时的老布局
_DEV_CONFIG_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "config.yaml",
    Path(__file__).resolve().parent.parent / "v1-desktop" / "config.yaml",
]


def config_file() -> Path:
    """当前生效的配置文件路径。

    - 冻结态：%APPDATA%/spoken-web/config.yaml
    - 源码态：优先 v2-web/config.yaml；没有则沿用上一级已有配置（不复制、不改动，
      避免开发时两份配置打架）。
    """
    own = data_dir() / "config.yaml"
    if own.is_file():
        return own
    if not is_frozen():
        for cand in _DEV_CONFIG_CANDIDATES:
            if cand.is_file():
                return cand
    return own


def ensure_config() -> tuple[Path, bool]:
    """确保配置文件存在；首次运行从内置模板生成。

    返回 (配置文件路径, 是否本次新建)。
    """
    path = config_file()
    if path.is_file():
        return path, False
    template = bundle_dir() / "config.example.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if template.is_file():
        shutil.copyfile(template, path)
    else:
        path.write_text(
            "# spoken 配置（从模板生成失败，请手动填写）\n"
            "base_url: https://dashscope.aliyuncs.com/compatible-mode/v1\n"
            "api_key: \"\"\n"
            "model: qwen-plus\n",
            encoding="utf-8",
        )
    return path, True


def web_dir() -> Path:
    return bundle_dir() / "web"


def papers_dir() -> Path:
    return bundle_dir() / "papers"
