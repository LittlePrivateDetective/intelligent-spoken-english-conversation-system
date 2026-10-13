@echo off
chcp 65001 >nul
cd /d %~dp0
:: 默认使用 HuggingFace 国内镜像，避免 faster-whisper 模型首次下载超时
:: 若你已有稳定代理，可将下面一行删除或改为自己的 HF_ENDPOINT
set HF_ENDPOINT=https://hf-mirror.com
:: 禁用 Xet 下载协议：该协议经镜像站会返回 401，禁用后走普通通道可正常下载
set HF_HUB_DISABLE_XET=1
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m spoken
) else (
    start "" pythonw -m spoken
)
