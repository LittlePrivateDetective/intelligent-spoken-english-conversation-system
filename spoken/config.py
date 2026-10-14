"""配置加载：config.yaml + 环境变量覆盖。

查找顺序：--config 参数 > SPOKEN_CONFIG 环境变量 > ./config.yaml。
环境变量 SPOKEN_BASE_URL / SPOKEN_API_KEY / SPOKEN_MODEL 优先级高于配置文件。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from .paths import is_frozen, user_data_dir

DEFAULT_CONFIG: dict = {
    "llm": {
        # 任何 OpenAI 兼容接口都可以：OpenAI / DeepSeek / Moonshot / 通义 / Ollama 等
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
        "temperature": 0.7,
        "timeout": 60,
        # 思考模式开关：None = 不下发（绝大多数服务商）；False = 关闭 Ollama
        # qwen3 等思考模型的推理过程，显著提速
        "think": None,
    },
    "dialogue": {
        "max_turns": 25,          # 单次对话最多轮数，到顶自动收尾
        "min_turns": 3,           # 至少聊几轮才允许自然结束
        "feedback_language": "zh",  # 纠错解释语言：zh（中文）/ en（英文）
        "save_report": True,      # 结束后是否把总结存成 Markdown 文件
        "report_dir": "reports",  # 报告保存目录
    },
    "voice": {
        "asr_model": "base",      # faster-whisper 模型：tiny / base / small / medium
        "asr_model_local_path": "",  # 本地模型目录；为空则自动从 HuggingFace 下载
        "asr_language": "en",     # 识别语言（练习英语就固定 en）
        "sample_rate": 16000,     # 录音采样率（Hz）
        "tts_rate": 175,          # AI 朗读语速（词/分钟，本地 SAPI 用）
        "tts_voice": "",          # 留空 = 自动选英文语音；或填 SAPI 语音 id
        "tts_volume": 100,        # 音量 0~100（SAPI 会归一化到 0~1；云端用 0~100）
        "tts_speed": "medium",    # 语速档位：slow / medium / fast
        "auto_speak": True,       # AI 台词自动朗读（纠错反馈不朗读）
    },
    # 云端 TTS（可选）：开启后用 DashScope CosyVoice 合成，支持多语种/多口音、更清晰。
    # 未开启或失败会自动回退本地 SAPI。需单独在百炼控制台开通并获取 API Key。
    "cloud_tts": {
        "enabled": False,
        "api_key": "",
        "model": "cosyvoice-v3-flash",
        # 口音 / 发音人 key，见 spoken/accents.py：
        #   en-US 美式英语 / en-GB 英式英语（可用）
        #   ja-JP 日语 / ko-KR 韩语（音色只朗读对应语言，非英语口音）
        #   th-TH / en-IN / vi-VN / ms-MY / kk-KZ / uz-UZ（CosyVoice 暂无音色）
        "accent": "en-US",
        # 自定义音色 id：填了则忽略上面的 accent，直接用该音色（可接声音复刻）
        "custom_voice": "",
        "custom_language_hint": "",   # 自定义音色的语言，留空默认 en
    },
    # 界面偏好：语言（zh/en）、主题（light/dark）、窗口几何记忆
    "ui": {
        "language": "zh",       # 界面语言：zh（中文）/ en（English）
        "theme": "light",       # 主题：light（浅色）/ dark（深色）
        "window_geometry": "",  # 窗口位置与大小，如 960x720+100+50；空=默认
    },
    # 发音/流利度评分（可选）：阿里云「智能语音交互」语音评测，真正声学打分。
    # 与 qwen-plus / 云端 TTS 是独立服务，需单独开通并获取 AppKey 与 Token。
    "assessment": {
        "enabled": False,
        "appkey": "",
        "token": "",
        "region": "cn-shanghai",
        "model_id": "en.pred.score",
    },
}


@dataclass
class Config:
    base_url: str
    api_key: str
    model: str
    temperature: float
    timeout: int
    think: bool | None
    max_turns: int
    min_turns: int
    feedback_language: str
    save_report: bool
    report_dir: str
    asr_model: str = "base"
    asr_model_local_path: str = ""
    asr_language: str = "en"
    sample_rate: int = 16000
    tts_rate: int = 175
    tts_voice: str = ""
    tts_volume: int = 100
    tts_speed: str = "medium"
    auto_speak: bool = True
    cloud_tts: dict = None
    assessment: dict = None
    ui_language: str = "zh"
    ui_theme: str = "light"
    window_geometry: str = ""


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_env(data: dict) -> dict:
    """环境变量覆盖，方便临时切换服务商而不改配置文件。"""
    llm = data["llm"]
    if os.environ.get("SPOKEN_BASE_URL"):
        llm["base_url"] = os.environ["SPOKEN_BASE_URL"]
    if os.environ.get("SPOKEN_API_KEY"):
        llm["api_key"] = os.environ["SPOKEN_API_KEY"]
    if os.environ.get("SPOKEN_MODEL"):
        llm["model"] = os.environ["SPOKEN_MODEL"]
    if os.environ.get("SPOKEN_ASR_MODEL"):
        data["voice"]["asr_model"] = os.environ["SPOKEN_ASR_MODEL"]
    return data


def find_config_file(explicit: str | None = None) -> Path | None:
    """定位 config.yaml。

    优先级：--config 参数 > SPOKEN_CONFIG 环境变量 > 当前目录 config.yaml >
    冻结态（exe）下的用户数据目录 config.yaml。返回值要么是已存在的文件，
    要么是推荐写入路径（用户数据目录），保证 exe 在 Program Files 下也能配置。
    """
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("SPOKEN_CONFIG"):
        candidates.append(Path(os.environ["SPOKEN_CONFIG"]))
    candidates.append(Path("config.yaml"))
    if is_frozen():
        candidates.append(user_data_dir() / "config.yaml")
    for path in candidates:
        if path.is_file():
            return path
    # 没有已存在的文件时，返回推荐写入位置（冻结态 → 用户数据目录）
    return user_data_dir() / "config.yaml" if is_frozen() else Path("config.yaml")


def load_config(explicit_path: str | None = None) -> Config:
    path = find_config_file(explicit_path)
    data = DEFAULT_CONFIG
    # find_config_file 找不到任何已存在文件时会返回"推荐写入路径"（文件尚不存在，
    # 例如朋友第一次运行 exe），此时直接用默认配置，绝不能 open() 否则崩溃。
    if path is not None and path.is_file():
        with open(path, "r", encoding="utf-8") as fh:
            user_data = yaml.safe_load(fh) or {}
        data = _deep_merge(DEFAULT_CONFIG, user_data)
    data = _apply_env(data)

    llm, dlg = data["llm"], data["dialogue"]
    voice = data.get("voice", {})
    think_raw = llm.get("think", None)
    think = None if think_raw is None else bool(think_raw)
    return Config(
        base_url=str(llm["base_url"]),
        api_key=str(llm.get("api_key", "")),
        model=str(llm["model"]),
        temperature=float(llm.get("temperature", 0.7)),
        timeout=int(llm.get("timeout", 60)),
        think=think,
        max_turns=int(dlg.get("max_turns", 25)),
        min_turns=int(dlg.get("min_turns", 3)),
        feedback_language=str(dlg.get("feedback_language", "zh")),
        save_report=bool(dlg.get("save_report", True)),
        report_dir=str(dlg.get("report_dir", "reports")),
        asr_model=str(voice.get("asr_model", "base")),
        asr_model_local_path=str(voice.get("asr_model_local_path", "")),
        asr_language=str(voice.get("asr_language", "en")),
        sample_rate=int(voice.get("sample_rate", 16000)),
        tts_rate=int(voice.get("tts_rate", 175)),
        tts_voice=str(voice.get("tts_voice", "")),
        tts_volume=int(voice.get("tts_volume", 100)),
        tts_speed=str(voice.get("tts_speed", "medium")),
        auto_speak=bool(voice.get("auto_speak", True)),
        cloud_tts=dict(data.get("cloud_tts", {})),
        assessment=dict(data.get("assessment", {})),
        ui_language=str(data.get("ui", {}).get("language", "zh")),
        ui_theme=str(data.get("ui", {}).get("theme", "light")),
        window_geometry=str(data.get("ui", {}).get("window_geometry", "")),
    )
