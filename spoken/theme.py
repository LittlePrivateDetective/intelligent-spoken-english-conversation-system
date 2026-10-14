"""界面主题：浅色 / 深色两套调色板。

GUI 的颜色常量（C_BG / C_CARD / C_TEXT …）在 gui.py 中以模块级变量
存在，``apply_theme(name)`` 会把选定调色板写入这些变量，随后重建界面
即可整体换肤。新增颜色时两个调色板都要补，缺色会回退到浅色值。
"""

from __future__ import annotations

# 调色板键名与 gui.py 中的颜色常量一一对应
PALETTE_KEYS = (
    "bg", "card", "border", "shadow", "text", "text2", "text3",
    "accent", "accent_d", "accent_bg", "accent_hover",
    "bubble_ai", "bubble_user", "green", "rec", "rec_d", "rec_bg",
    "tag_ai", "tag_user", "tag_feedback", "tag_hint", "tag_sys",
    "btn_disabled", "btn_secondary", "btn_secondary_hover",
    "btn_ghost_hover", "rec_hover",
    "deco_1", "deco_2", "deco_3",          # 欢迎页装饰色块
    "orb_ring_1", "orb_ring_2", "orb_ring_3",  # 录音球波纹
    "orb_body", "orb_body_hi",
    "pill_selected_cefr",                    # 难度胶囊选中态 CEFR 文字
)

_LIGHT = {
    "bg": "#F4F6FA", "card": "#FFFFFF", "border": "#E4E9F2",
    "shadow": "#E8EDF4", "text": "#2E3A4D", "text2": "#7C8AA0",
    "text3": "#AAB6C6", "accent": "#4C7DFF", "accent_d": "#3A6BE0",
    "accent_bg": "#ECF2FF", "accent_hover": "#5C89FF",
    "bubble_ai": "#ECF2FF", "bubble_user": "#E9F7F0", "green": "#3FAE85",
    "rec": "#FF7A6B", "rec_d": "#F2604F", "rec_bg": "#FFEEEB",
    "tag_ai": "#2B5FD9", "tag_user": "#2F7D4F", "tag_feedback": "#B7791F",
    "tag_hint": "#C05621", "tag_sys": "#8A94A6",
    "btn_disabled": "#EDF0F5", "btn_secondary": "#EEF2F8",
    "btn_secondary_hover": "#E6ECF6", "btn_ghost_hover": "#E2E8F2",
    "rec_hover": "#FF8F81",
    "deco_1": "#E9F0FE", "deco_2": "#E6F6F0", "deco_3": "#EAF1FE",
    "orb_ring_1": "#D9E5FF", "orb_ring_2": "#C6D8FF", "orb_ring_3": "#B3CBFF",
    "orb_body": "#B9CFFF", "orb_body_hi": "#7FA5FF",
    "pill_selected_cefr": "#D8E4FF",
}

_DARK = {
    "bg": "#1B2333", "card": "#242E42", "border": "#37425A",
    "shadow": "#151C29", "text": "#E8EDF5", "text2": "#9AA7BD",
    "text3": "#6B7A93", "accent": "#6B96FF", "accent_d": "#517FEE",
    "accent_bg": "#2C3A57", "accent_hover": "#82A8FF",
    "bubble_ai": "#2C3A57", "bubble_user": "#26402F", "green": "#4FC39B",
    "rec": "#FF8F81", "rec_d": "#F2604F", "rec_bg": "#4A2B27",
    "tag_ai": "#8FB2FF", "tag_user": "#7CCBA4", "tag_feedback": "#E3B659",
    "tag_hint": "#F0916B", "tag_sys": "#8A94A6",
    "btn_disabled": "#2E3950", "btn_secondary": "#2E3950",
    "btn_secondary_hover": "#3A4661", "btn_ghost_hover": "#31405C",
    "rec_hover": "#FFA79B",
    "deco_1": "#233049", "deco_2": "#1F3534", "deco_3": "#243349",
    "orb_ring_1": "#3A4E7E", "orb_ring_2": "#32456E", "orb_ring_3": "#2B3C5E",
    "orb_body": "#3D5CA8", "orb_body_hi": "#5B82D6",
    "pill_selected_cefr": "#B9CCFF",
}

THEMES: dict[str, dict[str, str]] = {"light": _LIGHT, "dark": _DARK}

DEFAULT_THEME = "light"


def available_themes() -> tuple[str, ...]:
    """可用主题键名（顺序即设置页展示顺序）。"""
    return tuple(THEMES.keys())


def palette(name: str) -> dict[str, str]:
    """取调色板；未知主题名回退浅色。"""
    return THEMES.get(name, _LIGHT)
