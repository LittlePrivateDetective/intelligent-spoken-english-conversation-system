# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：spoken-web（Windows 桌面应用，目录分发）。

用法（在 v2-web 目录下）：
    ..\v1-desktop\.venv\Scripts\pyinstaller.exe spoken_web.spec --noconfirm

产物：dist/spoken-web/spoken-web.exe（整个文件夹压缩成 zip 分发）

几点说明：
- 用 onedir 而不是 onefile：这个包里有 ctranslate2 / tokenizers 的原生 DLL，
  打成单文件每次启动都要解压两三百 MB，冷启动要十几秒；目录形态秒开。
- datas 里带 web/（前端）、papers/（题库）、config.example.yaml（配置模板）。
  配置模板绝不能换成真实的 config.yaml —— 那会把开发者自己的 API Key 发出去。
- 语音模型不打包：首次用麦克风时从 HuggingFace 镜像下载（见 spoken/asr.py），
  避免了包体多几百 MB，也方便用户换模型。
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

HERE = Path(SPECPATH).resolve()

# ---------------------------------------------------------------------
# 随包分发的只读资源
# ---------------------------------------------------------------------
datas = [
    (str(HERE / "web"), "web"),
    (str(HERE / "papers"), "papers"),
    (str(HERE / "config.example.yaml"), "."),
]

binaries = []
hiddenimports = []

# 语音识别链路：这几个包含原生 DLL / 数据文件，必须整体收集
for _mod in ("faster_whisper", "ctranslate2", "tokenizers", "av", "huggingface_hub"):
    try:
        _d, _b, _h = collect_all(_mod)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:  # 某个可选依赖没装就跳过，不影响其余部分
        pass

# uvicorn 大量按字符串动态导入协议实现，静态分析抓不到
hiddenimports += collect_submodules("uvicorn")

# Windows 本地 TTS（如果走了 SAPI 回退）需要
hiddenimports += ["pyttsx3.drivers", "pyttsx3.drivers.sapi5", "comtypes", "comtypes.stream"]

a = Analysis(
    [str(HERE / "launcher.py")],
    pathex=[str(HERE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 明显用不到的大件，排除后包体小很多
        "torch", "torchaudio", "torchvision",
        "matplotlib", "pandas", "scipy", "sklearn",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "IPython", "notebook", "jupyter",
        "pytest", "PyInstaller",
        # 内嵌 WebView 不采用（麦克风权限问题），避免误收集
        "webview",
        "spoken.gui", "spoken.cli", "spoken.__main__",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="spoken-web",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # 不开 UPX：压缩过的 bootloader 常被杀毒软件误报，用户不敢运行
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="spoken-web",
)
