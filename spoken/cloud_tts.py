"""云端语音合成（TTS）：DashScope CosyVoice HTTP 接口。

- 与本地 pyttsx3/SAPI 互补：SAPI 离线、零依赖，但只有系统自带少数发音人；
  云端 CosyVoice 支持多语种 / 多口音（language_hints），音色更清晰。
- 接口：POST https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer
- 鉴权：Authorization: Bearer <DashScope API Key>
- 返回 WAV 字节（output.audio.data 的 base64，或 output.audio.url 临时链接）
- 仅依赖 requests（项目已有）；播放交给调用方（winsound / 临时文件）。

未配置或网络失败时，调用方应回退到本地 SAPI，不影响主流程。
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import requests

_CLOUD_TTS_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"


def synthesize(
    text: str,
    *,
    api_key: str,
    model: str = "cosyvoice-v3-flash",
    voice: str = "longanyang",
    language_hint: str = "en",
    speed: float = 1.0,
    volume: int = 50,
    sample_rate: int = 24000,
    timeout: int = 30,
) -> bytes:
    """合成一段英文（或指定语种）语音，返回 WAV 文件字节。

    language_hint：目标语言，en/fr/de/ja/ko/ru/th/vi/ms/...（见 CosyVoice 文档）。
    speed：语速倍率 0.5~2.0；volume：音量 0~100。
    抛出 requests 异常或 ValueError（接口返回错误）由调用方捕获。
    """
    if not api_key:
        raise ValueError("云端 TTS 未配置 API Key")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "input": {
            "text": text,
            "voice": voice,
            "format": "wav",
            "sample_rate": sample_rate,
            "volume": max(0, min(100, int(volume))),
            "rate": max(0.5, min(2.0, float(speed))),
            "language_hints": [language_hint],
        },
    }
    resp = requests.post(_CLOUD_TTS_URL, headers=headers,
                         json=payload, timeout=timeout)
    if resp.status_code != 200:
        raise ValueError(
            f"云端 TTS 返回 HTTP {resp.status_code}：{resp.text[:200]}")
    data = resp.json()
    output = (data.get("output") or {})
    audio = output.get("audio") or {}
    b64 = audio.get("data") or ""
    if b64:
        return base64.b64decode(b64)
    url = audio.get("url") or ""
    if url:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.content
        raise ValueError(f"云端 TTS 音频链接下载失败 HTTP {r.status_code}")
    raise ValueError(f"云端 TTS 未返回音频数据：{str(data)[:200]}")


def save_temp_wav(wav_bytes: bytes) -> str:
    """把 WAV 字节写成临时文件，返回路径（调用方负责播放后清理）。"""
    fd, path = tempfile.mkstemp(prefix="spoken_tts_", suffix=".wav")
    with open(fd, "wb") as f:
        f.write(wav_bytes)
    return path


def play_wav(path: str) -> None:
    """用系统扬声器播放 WAV 文件（Windows winsound，阻塞到播放结束）。"""
    import winsound

    winsound.PlaySound(path, winsound.SND_FILENAME)
