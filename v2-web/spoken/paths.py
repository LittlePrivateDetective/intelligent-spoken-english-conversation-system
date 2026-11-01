"""可写目录与资源路径解析。

本程序有两种运行形态：
1. 源码运行（`python -m spoken` 或 `run.bat`）：用户数据（config.yaml /
   *.db / reports / models / 自定义场景）写在「当前工作目录」（通常是仓库根）。
2. 打包后的独立 exe（PyInstaller --onedir，分发给无环境的朋友）：
   程序与依赖都在 dist/spoken/ 里，用户数据统一写到「exe 所在目录」，
   整个文件夹拷走即带走全部数据，自包含分发、解压双击即用。
   注意：不要把程序解压到 Program Files 等只读位置（放桌面/文档即可）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """是否运行在 PyInstaller 等打包后的可执行文件中。"""
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


def exe_dir() -> Path:
    """打包后 exe 所在目录（仅 frozen 态有意义）。"""
    return Path(sys.executable).resolve().parent


def app_data_dir() -> Path:
    """返回跨平台「用户数据目录」（备用方案，当前分发策略未启用）。

    Windows: %APPDATA%/spoken
    macOS:   ~/Library/Application Support/spoken
    Linux:   ~/.local/share/spoken
    目录不存在时自动创建。
    """
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    path = Path(base) / "spoken"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_data_dir() -> Path:
    """返回应当写入用户数据的目录。

    - 冻结态（exe）：exe 所在目录（自包含分发，数据跟着文件夹走）。
    - 源码态：当前工作目录（与历史行为一致，config.yaml 等就在仓库根）。
    """
    if is_frozen():
        return exe_dir()
    return Path.cwd()


def resource_path(relative: str) -> Path:
    """解析打包内置资源路径。

    源码态直接按相对仓库根返回；冻结态从 PyInstaller 解包目录查找。
    用于定位随包分发的只读文件（如图标、内置数据）。
    """
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", str(Path.cwd())))
        return base / relative
    return Path(__file__).resolve().parent.parent / relative


def data_file(name: str) -> Path:
    """返回一个应写入的用户数据文件路径（按名称）。

    源码态落在当前工作目录（仓库根），冻结态落在 ``app_data_dir``，
    保证 exe 在 ``Program Files`` 下也能正常读写数据库 / 模型 / 报告等。
    """
    return user_data_dir() / name
