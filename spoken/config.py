"""配置加载：config.yaml + 环境变量覆盖。

查找顺序：--config 参数 > SPOKEN_CONFIG 环境变量 > ./config.yaml。
环境变量 SPOKEN_BASE_URL / SPOKEN_API_KEY / SPOKEN_MODEL 优先级高于配置文件。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG: dict = {
    "llm": {
        # 任何 OpenAI 兼容接口都可以：OpenAI / DeepSeek / Moonshot / 通义 / Ollama 等
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
        "temperature": 0.7,
        "timeout": 60,
    },
    "dialogue": {
        "max_turns": 25,          # 单次对话最多轮数，到顶自动收尾
        "min_turns": 3,           # 至少聊几轮才允许自然结束
        "feedback_language": "zh",  # 纠错解释语言：zh（中文）/ en（英文）
        "save_report": True,      # 结束后是否把总结存成 Markdown 文件
        "report_dir": "reports",  # 报告保存目录
    },
}


@dataclass
class Config:
    base_url: str
    api_key: str
    model: str
    temperature: float
    timeout: int
    max_turns: int
    min_turns: int
    feedback_language: str
    save_report: bool
    report_dir: str


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
    return data


def find_config_file(explicit: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("SPOKEN_CONFIG"):
        candidates.append(Path(os.environ["SPOKEN_CONFIG"]))
    candidates.append(Path("config.yaml"))
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_config(explicit_path: str | None = None) -> Config:
    path = find_config_file(explicit_path)
    data = DEFAULT_CONFIG
    if path is not None:
        with open(path, "r", encoding="utf-8") as fh:
            user_data = yaml.safe_load(fh) or {}
        data = _deep_merge(DEFAULT_CONFIG, user_data)
    data = _apply_env(data)

    llm, dlg = data["llm"], data["dialogue"]
    return Config(
        base_url=str(llm["base_url"]),
        api_key=str(llm.get("api_key", "")),
        model=str(llm["model"]),
        temperature=float(llm.get("temperature", 0.7)),
        timeout=int(llm.get("timeout", 60)),
        max_turns=int(dlg.get("max_turns", 25)),
        min_turns=int(dlg.get("min_turns", 3)),
        feedback_language=str(dlg.get("feedback_language", "zh")),
        save_report=bool(dlg.get("save_report", True)),
        report_dir=str(dlg.get("report_dir", "reports")),
    )
