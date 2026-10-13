"""口音 / 发音人注册表（云端 CosyVoice TTS）。

需求希望可切换「多国口音」：美国、英国、泰国、印度、越南、马来西亚、韩国、
日本、哈萨克斯坦、乌兹别克斯坦。

现实约束（依据阿里云百炼官方 CosyVoice 音色清单，模型 cosyvoice-v3-flash，
2026-10 核对）：
  * 英语口音音色：只有「美式英语」「英式英语」两类（各含若干男女音色）；
  * 另有「日语」「韩语」「印尼语」音色——但只朗读对应语言，不是英语口音；
  * 泰语 / 越南语 / 马来语 / 印度英语 / 哈萨克语 / 乌兹别克语：官方无任何音色。

因此本表如实标注可用性，绝不假装支持：
  available=True  该口音在 CosyVoice 有对应音色；
  english=True    该音色能自然朗读英语（可用于英语练习）。
界面据 available / english 决定可选状态与提示。
需要更多语种口音时，可用「自定义音色 ID」接入声音复刻或后续新增的 voice id。
"""

from __future__ import annotations

# 默认口音（美式英语）
DEFAULT_ACCENT = "en-US"

# 需求中的 10 个口音（按需求原顺序：美、英、泰、印、越、马、韩、日、哈、乌）
ACCENTS: list[dict] = [
    {"key": "en-US", "country": "美国", "label": "美式英语",
     "voice": "loongabby_v3", "language_hint": "en", "gender": "女",
     "available": True, "english": True, "note": ""},
    {"key": "en-GB", "country": "英国", "label": "英式英语",
     "voice": "loongemily_v3", "language_hint": "en", "gender": "女",
     "available": True, "english": True, "note": ""},
    {"key": "th-TH", "country": "泰国", "label": "泰语",
     "voice": "", "language_hint": "th", "gender": "",
     "available": False, "english": False,
     "note": "CosyVoice 暂无泰语音色"},
    {"key": "en-IN", "country": "印度", "label": "印度英语",
     "voice": "", "language_hint": "en", "gender": "",
     "available": False, "english": False,
     "note": "CosyVoice 暂无印度英语音色"},
    {"key": "vi-VN", "country": "越南", "label": "越南语",
     "voice": "", "language_hint": "vi", "gender": "",
     "available": False, "english": False,
     "note": "CosyVoice 暂无越南语音色"},
    {"key": "ms-MY", "country": "马来西亚", "label": "马来语",
     "voice": "", "language_hint": "ms", "gender": "",
     "available": False, "english": False,
     "note": "CosyVoice 暂无马来语音色"},
    {"key": "ko-KR", "country": "韩国", "label": "韩语发音人",
     "voice": "loongkyong_v3", "language_hint": "ko", "gender": "女",
     "available": True, "english": False,
     "note": "该音色只朗读韩语，非英语口音"},
    {"key": "ja-JP", "country": "日本", "label": "日语发音人",
     "voice": "loongriko_v3", "language_hint": "ja", "gender": "女",
     "available": True, "english": False,
     "note": "该音色只朗读日语，非英语口音"},
    {"key": "kk-KZ", "country": "哈萨克斯坦", "label": "哈萨克语",
     "voice": "", "language_hint": "kk", "gender": "",
     "available": False, "english": False,
     "note": "CosyVoice 暂无哈萨克语音色"},
    {"key": "uz-UZ", "country": "乌兹别克斯坦", "label": "乌兹别克语",
     "voice": "", "language_hint": "uz", "gender": "",
     "available": False, "english": False,
     "note": "CosyVoice 暂无乌兹别克语音色"},
]

# 兼容早期配置里的两字母口音键
_LEGACY = {"am": "en-US", "en": "en-GB", "us": "en-US", "uk": "en-GB"}

_BY_KEY = {a["key"]: a for a in ACCENTS}


def get_accent(key: str | None) -> dict:
    """按 key 取口音条目；兼容旧键 am/en；未知键返回默认（美式）。"""
    if not key:
        return _BY_KEY[DEFAULT_ACCENT]
    resolved = _LEGACY.get(str(key), str(key))
    return _BY_KEY.get(resolved, _BY_KEY[DEFAULT_ACCENT])


def is_available(key: str | None) -> bool:
    """该口音在 CosyVoice 是否有音色。"""
    return bool(get_accent(key)["available"])


def resolve_cloud_voice(cloud_cfg: dict | None) -> tuple[str, str]:
    """由 cloud_tts 配置解析出 (voice_id, language_hint)。

    优先「自定义音色 ID」（custom_voice / custom_language_hint），
    否则按选定口音取官方音色；若选中的口音无音色（available=False），
    回退到默认美式，保证合成不报错。
    """
    cfg = cloud_cfg or {}
    custom = str(cfg.get("custom_voice") or "").strip()
    if custom:
        hint = str(cfg.get("custom_language_hint") or "").strip() or "en"
        return custom, hint
    entry = get_accent(cfg.get("accent"))
    if not entry["voice"]:
        entry = _BY_KEY[DEFAULT_ACCENT]
    return entry["voice"], entry["language_hint"]


def assess_accent(key: str | None) -> str | None:
    """语音评测的 accent 参数：仅英语口音返回 'en'，其余返回 None。"""
    entry = get_accent(key)
    return "en" if entry["english"] else None
