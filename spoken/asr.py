"""语音识别（ASR）：sounddevice 录音 + faster-whisper 本地转写。

- 模型首次使用时自动下载（默认 base，约 150MB）到 models/ 目录，之后离线可用。
- 录音直接在内存中采集，停止时返回 16kHz 单声道 float32 波形数组，
  不写临时 WAV 文件。
- 识别时把波形数组直接传给 faster-whisper（其 ndarray 分支会跳过内部
  av 解码）——这是为了绕开 faster-whisper 1.2.1 与 PyAV 19 的兼容问题
  （faster-whisper 调用 av.open(metadata_errors=...) 在 PyAV 19 上会
  抛 TypeError: open() got an unexpected keyword argument 'metadata_errors'）。
- 依赖缺失时相关类不可用，GUI 会降级为纯文字输入，程序不会崩溃。
- 模型从国内镜像 hf-mirror.com 下载（run.bat 默认设置 HF_ENDPOINT），
  并在 spoken 包导入时自动禁用 Xet 下载协议（HF_HUB_DISABLE_XET=1），
  避免镜像站返回 401；也可在 config.yaml 指定 asr_model_local_path
  使用手动下载的本地模型。
"""

from __future__ import annotations

import time
from dataclasses import dataclass


class ASRDownloadError(RuntimeError):
    """faster-whisper 模型下载失败（通常是 Hugging Face 网络超时）。"""

    def __init__(self, original: Exception, model_size: str) -> None:
        self.original = original
        self.model_size = model_size
        hint = (
            "\n\n语音识别模型下载失败。常见原因：当前网络访问镜像站不稳定，"
            "大文件连接被中断。"
            "\n解决方案（任选其一）："
            "\n1. 再次点击麦克风重试——软件会自动断点续传，已下载的部分不会丢失"
            f"\n2. 手动下载模型：访问 https://hf-mirror.com/Systran/faster-whisper-{model_size} "
            f"下载全部文件后放到项目目录的 models/faster-whisper-{model_size} 下，"
            f"然后在 config.yaml 设置 asr_model_local_path: models/faster-whisper-{model_size}"
            "\n3. 暂时用键盘输入文字，不使用麦克风。"
        )
        super().__init__(f"{original}{hint}")


def asr_available() -> bool:
    """faster-whisper 是否可用。"""
    try:
        import faster_whisper  # noqa: F401
    except Exception:
        return False
    return True


def mic_available() -> bool:
    """sounddevice（麦克风采集）是否可用。"""
    try:
        import sounddevice  # noqa: F401
    except Exception:
        return False
    return True


@dataclass
class ASRStatus:
    model_loaded: bool = False
    recording: bool = False


class MicRecorder:
    """点击开始 / 点击结束的录音器，停止时返回 float32 波形数组。

    last_level：实时音量电平（0.0~1.0，约每 40ms 刷新一次），
    仅供 UI 录音动画读取；不影响录音数据与识别逻辑。
    """

    def __init__(self, sample_rate: int = 16000, normalize: bool = True) -> None:
        self.sample_rate = sample_rate
        self.normalize = normalize
        self._stream = None
        self._frames: list = []
        self.last_level = 0.0
        self._last_level_t = 0.0

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self.recording:
            return
        import sounddevice as sd

        self._frames = []

        def _callback(indata, frames, time_info, status):  # noqa: ANN001
            # indata: (frames, 1) int16 numpy 数组，必须拷贝（缓冲区会复用）
            self._frames.append(indata.copy())
            # 节流计算 RMS 音量电平，供 UI 动画使用（纯读取，不影响录音）
            now = time.monotonic()
            if now - self._last_level_t >= 0.04:
                self._last_level_t = now
                try:
                    self.last_level = min(
                        1.0, float((indata.astype("float64") ** 2).mean() ** 0.5)
                        / 32768.0 * 6.0)
                except Exception:
                    pass

        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="int16",
            callback=_callback,
        )
        self._stream.start()

    def stop(self) -> "np.ndarray":
        """停止录音，返回 16kHz 单声道 float32 波形（值域 -1.0 ~ 1.0）。"""
        if not self.recording:
            raise RuntimeError("当前没有在录音")
        self._stream.stop()
        self._stream.close()
        self._stream = None
        return self._collect()

    def cancel(self) -> None:
        if self.recording:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._frames = []

    def _collect(self) -> "np.ndarray":
        import numpy as np

        if not self._frames:
            raise RuntimeError("没有录到声音（录音时间太短或麦克风未启用）")
        data = np.concatenate(self._frames, axis=0).reshape(-1)
        self._frames = []
        # int16 -> float32 归一化，whisper 特征提取要求这个格式
        audio = data.astype(np.float32) / 32768.0
        if self.normalize:
            audio = self.normalize_audio(audio)
        return audio

    @staticmethod
    def normalize_audio(audio: "np.ndarray", target_rms: float = 0.15,
                        max_gain: float = 6.0) -> "np.ndarray":
        """轻量录音增强：去直流偏移 + RMS 增益归一化（限幅防削波）。

        - 解决“小声/忽大忽小”导致 faster-whisper 漏字、识别差的问题；
        - 仅做线性增益，不引入额外依赖，保持离线可用；
        - max_gain 防止把本底噪声也放得过大。
        """
        import numpy as np

        audio = np.asarray(audio, dtype=np.float32)
        # 去直流偏移（麦克风偏置/耦合电容残留）
        audio = audio - audio.mean()
        rms = float(np.sqrt((audio ** 2).mean())) if audio.size else 0.0
        if rms < 1e-6:
            return audio
        gain = min(max_gain, target_rms / rms)
        audio = audio * gain
        # 限幅：超过 [-1, 1] 的部分截断，避免爆音/削波
        return np.clip(audio, -1.0, 1.0)


class Transcriber:
    """faster-whisper 转写器：模型懒加载，只加载一次。

    模型来源优先级：
    1. local_path：config.yaml 的 asr_model_local_path 指定的本地目录；
    2. 否则用自带下载器（断点续传 + 重试）从镜像站下载到 models/ 目录。
    """

    def __init__(
        self,
        model_size: str = "base",
        language: str = "en",
        local_path: str | None = None,
        download_progress=None,
    ) -> None:
        self.model_size = model_size
        self.language = language
        self.local_path = local_path
        self.download_progress = download_progress
        self._model = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """下载（首次）并加载模型，可能耗时较久，放后台线程调用。"""
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        if self.local_path:
            model_source = self.local_path
        else:
            # 自带下载器：Range 续传 + 重试，绕开 HF 缓存的
            # "incomplete snapshot" 卡死问题
            from .model_download import ModelDownloadError, ensure_local_model

            try:
                model_source = str(ensure_local_model(
                    self.model_size, progress=self.download_progress))
            except ModelDownloadError as exc:
                raise ASRDownloadError(exc, self.model_size) from exc

        try:
            # int8 量化在 CPU 上速度更快、内存更小
            self._model = WhisperModel(
                model_source, device="cpu", compute_type="int8")
        except Exception as exc:
            msg = str(exc).lower()
            is_network_err = any(
                x in msg
                for x in [
                    "timeout", "connect", "10060", "10061", "hub",
                    "connection", "unreachable", "403", "401", "404",
                ]
            )
            if is_network_err or self.local_path is None:
                raise ASRDownloadError(exc, self.model_size) from exc
            raise

    def transcribe(self, audio: "np.ndarray", hotwords: str | None = None) -> str:
        """识别音频波形（16kHz 单声道 float32），返回英文文本（可能为空串）。

        直接传波形数组而非文件路径：faster-whisper 对 ndarray 输入会跳过
        内部 av 解码，规避 PyAV 19 的 metadata_errors 兼容问题。

        hotwords：场景专有名词/热词（空格分隔），可显著提升生词识别准确率。
        """
        if self._model is None:
            self.load()
        kwargs = dict(language=self.language, beam_size=5, vad_filter=True)
        if hotwords:
            kwargs["hotwords"] = hotwords
        segments, _info = self._model.transcribe(audio, **kwargs)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text
