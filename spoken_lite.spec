# -*- mode: python ; coding: utf-8 -*-
# 纯文字精简版：不打包语音依赖（faster-whisper / sounddevice / pyttsx3 等），
# 体积约为完整版的 1/10；程序自动降级为文字对话模式，功能不受影响。
# 用法：pyinstaller --noconfirm --clean spoken_lite.spec
# 完整版（含本地语音识别与合成）请使用 spoken.spec。

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'faster_whisper', 'ctranslate2', 'tokenizers', 'onnxruntime',
        'sounddevice', 'pyttsx3', 'comtypes', 'torch', 'numpy',
        'PyInstaller', 'pytest',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='spoken',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # upx=False：UPX 压缩的 bootloader 易被杀毒软件误报为木马
    # （用户下载后不敢运行），且 onefile 首次启动需解压反而更慢。
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
