@echo off
REM ============================================================
REM  把 spoken 打包成独立 Windows exe（双击即用，无需 Python 环境）
REM ------------------------------------------------------------
REM  前置：已在项目根目录创建 .venv 并安装完整依赖：
REM      python -m venv .venv
REM      .venv\Scripts\pip install -e ".[voice,packaging]"
REM  产物：dist\spoken.exe
REM  说明：faster-whisper 走 ctranslate2 推理，不需要 torch；
REM        体积约 400~700MB，首次打包耗时较长。
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo 未找到 .venv，请先创建并安装依赖：
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -e ".[voice,packaging]"
    exit /b 1
)

echo 开始打包（可能需要 5-20 分钟，请耐心等待）...
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name spoken ^
    --collect-all faster_whisper ^
    --collect-all ctranslate2 ^
    --collect-all tokenizers ^
    --collect-all sounddevice ^
    --collect-all pyttsx3 ^
    --hidden-import pyttsx3.drivers ^
    --hidden-import pyttsx3.drivers.sapi5 ^
    --hidden-import comtypes ^
    --hidden-import comtypes.stream ^
    --exclude-module PyInstaller ^
    --exclude-module pytest ^
    run_app.py

if exist "dist\spoken.exe" (
    echo.
    echo 打包完成：dist\spoken.exe
    echo 提示：首次运行会弹出 API 配置窗口（填 Key 即用），
    echo       配置与数据库保存在 %%APPDATA%%\spoken，
    echo       语音识别模型会在首次语音输入时自动下载到该目录。
) else (
    echo 打包失败，请查看上方输出。
    exit /b 1
)
endlocal
