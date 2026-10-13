"""发音 / 流利度评分：阿里云「智能语音交互」语音评测（口语评测 API）。

- 真正声学打分：参考文本 + 用户音频 -> 准确度(pron) / 完整度(integrity) / 流利度(fluency) / 总分(overall)。
- 与 qwen-plus（文字对话）是两套独立服务：本模块用 nls 的 AppKey + Token 鉴权，
  不共用 DashScope API Key，需单独开通「智能语音交互」项目并获取 AppKey 与 Token。
- 端点：POST https://nls-gateway-<region>.aliyuncs.com/rest/v1/general/SpeechEvaluation
- 音频：16kHz 单声道 16bit PCM 的 WAV，以 base64 内联在 JSON 的 audio 字段；
  若已把音频放到公网可访问地址，也可用 audio_address/file_link 代替。
- 未配置或失败时由调用方决定是否提示用户，不影响练习主流程。
"""

from __future__ import annotations

import base64
import io
import wave
from dataclasses import dataclass

import requests


@dataclass
class ScoreResult:
    overall: float        # 总分 0~100
    accuracy: float       # 准确度（发音）0~100
    integrity: float      # 完整度 0~100
    fluency: float        # 流利度 0~100
    feedback: str = ""    # 简短反馈
    raw: dict = None      # 原始返回，便于调试


def float32_to_wav_bytes(audio, sample_rate: int = 16000) -> bytes:
    """把 faster-whisper 的 float32 波形转成 16bit PCM 单声道 WAV 字节。"""
    import numpy as np

    a = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    pcm = (a * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _feedback_for(s: "ScoreResult") -> str:
    parts = []
    if s.accuracy < 70:
        parts.append("部分单词发音不够准确，注意元音和重音")
    if s.integrity < 70:
        parts.append("有漏读或没读完，尽量把整句读完整")
    if s.fluency < 70:
        parts.append("流利度可提升，减少长停顿、保持语速平稳")
    if not parts:
        parts.append("整体不错，保持节奏多练几次会更自然")
    return "；".join(parts)


class Assessor:
    """阿里云语音评测客户端（en.pred.score 英文段落跟读评测）。"""

    def __init__(self, appkey: str = "", token: str = "",
                 region: str = "cn-shanghai",
                 model_id: str = "en.pred.score", timeout: int = 30) -> None:
        self.appkey = appkey
        self.token = token
        self.region = region
        self.model_id = model_id
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.appkey and self.token)

    def evaluate(self, ref_text: str, wav_bytes: bytes,
                 accent: str | None = None) -> ScoreResult:
        if not self.enabled:
            raise ValueError("语音评测未配置（需要 nls AppKey 与 Token）")
        url = (f"https://nls-gateway-{self.region}.aliyuncs.com"
               f"/rest/v1/general/SpeechEvaluation"
               f"?appkey={self.appkey}&model_id={self.model_id}")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-NLS-Token": self.token,
        }
        body: dict = {
            "ref_text": ref_text,
            "format": "wav",
            "sample_rate": 16000,
            "sample_bytes": 2,
            "audio": base64.b64encode(wav_bytes).decode("ascii"),
        }
        if accent:
            body["accent"] = accent
        resp = requests.post(url, headers=headers, json=body,
                             timeout=self.timeout)
        if resp.status_code != 200:
            raise ValueError(
                f"语音评测返回 HTTP {resp.status_code}：{resp.text[:200]}")
        data = resp.json()
        result = data.get("result") or {}
        if not result:
            err = data.get("error") or data.get("message") or "未知错误"
            raise ValueError(f"语音评测失败：{err}")
        overall = float(result.get("overall", 0))
        accuracy = float(result.get("accuracy") or result.get("pron") or 0)
        integrity = float(result.get("integrity", 0))
        fluency = float(result.get("fluency", 0))
        s = ScoreResult(overall=overall, accuracy=accuracy,
                        integrity=integrity, fluency=fluency, raw=data)
        s.feedback = _feedback_for(s)
        return s


class MockAssessor:
    """离线/测试用的发音评分替身：不联网，返回确定性分数。"""

    def __init__(self, *args, **kwargs) -> None:
        self.enabled = True

    def evaluate(self, ref_text: str, wav_bytes: bytes,
                 accent: str | None = None) -> ScoreResult:
        # 简单确定性：根据参考句长度与音频长度给一个合理的伪分数
        base = 78 + (len(ref_text) % 10) - 4
        s = ScoreResult(
            overall=max(0.0, min(100.0, base)),
            accuracy=max(0.0, min(100.0, base + 2)),
            integrity=max(0.0, min(100.0, base + 4)),
            fluency=max(0.0, min(100.0, base - 3)),
        )
        s.feedback = _feedback_for(s)
        return s
