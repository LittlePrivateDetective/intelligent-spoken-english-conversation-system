"""语音合成（TTS）。

两种后端，由调用方选择：
1. 本地 SAPI（pyttsx3）：离线、零额外依赖，但只有系统自带少数发音人；
2. 云端 CosyVoice（spoken.cloud_tts）：多语种/多口音、更清晰，需联网+Key。

Speaker 的设计：
- 异步队列：speak() 只入队不阻塞，后台线程按顺序播放；
- 本地后端每句话新建 SAPI 引擎实例，规避 Windows 上“第二次 runAndWait 不发声”的已知 bug；
- 若传入 cloud_synth（一个“text -> wav bytes”的已配置闭包），优先走云端播放，
  失败自动回退本地 SAPI，保证主流程不中断；
- 全程写 tts_debug.log，无声问题时可回放现场。
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
from pathlib import Path
from typing import Callable, Optional

from .cloud_tts import play_wav, save_temp_wav

_LOG_PATH = Path(__file__).resolve().parent.parent / "tts_debug.log"


def _log(msg: str) -> None:
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def tts_available() -> bool:
    try:
        import pyttsx3  # noqa: F401
    except Exception:
        return False
    return True


def list_voices() -> list[dict]:
    """枚举本机 SAPI 发音人（id / name / languages），供 GUI 让用户选择。

    返回空列表表示无 pyttsx3 或无法枚举；不抛异常。
    """
    try:
        import pyttsx3
    except Exception:
        return []
    try:
        engine = pyttsx3.init()
        out = []
        for v in engine.getProperty("voices"):
            langs = getattr(v, "languages", None) or []
            out.append({
                "id": getattr(v, "id", ""),
                "name": getattr(v, "name", ""),
                "languages": list(langs),
            })
        del engine
        return out
    except Exception:
        return []


class Speaker:
    """异步朗读队列：AI 台词入队后按顺序播放。"""

    def __init__(self, rate: int = 175, voice: str = "",
                 volume: float = 1.0, on_error=None,
                 cloud_synth: Optional[Callable[[str], bytes]] = None) -> None:
        self.rate = rate
        self.voice = voice
        self.volume = max(0.0, min(1.0, float(volume)))
        self.available = tts_available()
        self.last_error = ""     # 最近一次 TTS 错误（供界面显示）
        self._on_error = on_error  # 出错回调（调用方负责线程安全）
        self._cloud_synth = cloud_synth  # text -> wav bytes；None=只用本地
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        _log(f"Speaker 初始化: available={self.available}, rate={rate}, "
             f"voice={voice!r}, volume={self.volume}, cloud="
             f"{self._cloud_synth is not None}, log={_LOG_PATH}")

    def start(self) -> None:
        """启动播放线程（幂等）。"""
        if self._thread is not None or not self.available:
            return
        self._thread = threading.Thread(
            target=self._loop, name="spoken-tts", daemon=True)
        self._thread.start()
        _log("播放线程已启动")

    def speak(self, text: str) -> None:
        """把一段文本加入播放队列（非阻塞）。"""
        if not self.available or not text or not text.strip():
            _log(f"speak() 被跳过: available={self.available}, text={text[:40]!r}")
            return
        self.start()
        self._queue.put(text)
        _log(f"speak() 入队: {text[:60]!r}")

    def stop(self) -> None:
        """停止播放线程。"""
        if self._thread is not None:
            self._queue.put(None)
            self._thread = None
            _log("播放线程请求停止")

    def _loop(self) -> None:
        try:
            import pyttsx3

            probe = pyttsx3.init()
            picked = self.voice or self._pick_voice(probe)
            _log(f"pyttsx3 可用，语速={self.rate}, 音量={self.volume}, 语音={picked!r}")
            del probe

            from pyttsx3.engine import Engine

            while True:
                text = self._queue.get()
                if text is None:
                    _log("收到停止信号，播放线程退出")
                    break
                t0 = time.time()
                _log(f"开始播放: {text[:50]!r}")
                # 优先云端；云端失败则回退本地 SAPI（保证出声）
                if self._cloud_synth is not None:
                    try:
                        self._play_cloud(text)
                        dt = time.time() - t0
                        _log(f"云端播放完成，耗时 {dt:.2f}s")
                        continue
                    except Exception as exc:
                        _log("云端播放失败，回退 SAPI:\n" + traceback.format_exc())
                        self.last_error = f"云端 TTS 失败，已回退本地：{exc}"
                        self._report_error()
                # 本地 SAPI 播放
                try:
                    engine = Engine("sapi5")
                    engine.setProperty("rate", self.rate)
                    engine.setProperty("volume", self.volume)
                    engine.setProperty("voice", picked)
                    engine.say(text)
                    engine.runAndWait()
                    dt = time.time() - t0
                    if dt < min(0.8, 0.05 * len(text)):
                        _log(f"警告：仅 {dt:.2f}s 完成，疑似静音快速返回")
                    else:
                        _log(f"播放完成，耗时 {dt:.2f}s")
                except Exception as exc:
                    self.last_error = f"播放失败：{exc}"
                    _log("runAndWait 异常:\n" + traceback.format_exc())
                    self._report_error()
                    continue
        except Exception as exc:
            self.available = False
            self.last_error = f"TTS 引擎初始化失败：{exc!r}"
            _log("初始化异常:\n" + traceback.format_exc())
            self._report_error()

    def _play_cloud(self, text: str) -> None:
        wav = self._cloud_synth(text)
        if not wav:
            raise ValueError("云端返回空音频")
        path = save_temp_wav(wav)
        try:
            play_wav(path)
        finally:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass

    @staticmethod
    def _pick_voice(engine) -> str:
        """未配置 voice 时优先选英文语音（英语练习默认用英文发音）。"""
        try:
            for v in engine.getProperty("voices"):
                label = f"{getattr(v, 'id', '')} {getattr(v, 'name', '')}".lower()
                if "en-us" in label or "en-gb" in label or "english" in label:
                    return v.id
        except Exception:
            pass
        return ""  # 找不到就用系统默认

    def _report_error(self) -> None:
        if self._on_error is not None:
            try:
                self._on_error(self.last_error)
            except Exception:
                pass
