# -*- coding: utf-8 -*-
"""单色图标渲染：Pillow + 系统符号字体 -> PhotoImage。

背景：tkinter 的 create_text 渲染 emoji 时依赖 Windows 字体回退，
同一字符在「彩色字图 / 文本呈现（U+FE0E）」两种模式下的 ink 位置
不稳定，曾出现个别图标（如 📊）整体偏移到卡片外；位图方案把字形
交给 Pillow/FreeType 排版，再由 Tk 当图片绘制，位置与颜色完全可控。

Pillow 缺失或字体不可用时返回 None，调用方回退 create_text。

缓存说明：PhotoImage 绑定创建时的 Tk interpreter，root 销毁后即成
僵尸，因此缓存按 root 分层（WeakKeyDictionary），取出时做存活检测，
失效则用当前 root 重建。
"""
from __future__ import annotations

import os
import weakref

try:  # Pillow 为软依赖：装不上就走调用方的 create_text 回退路径
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    _PIL = True
except Exception:  # pragma: no cover - 无 Pillow 环境
    _PIL = False

# 符号字体候选（按平台）。Segoe UI Symbol 含全部场景图标的单色字形。
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\seguisym.ttf",
    "/System/Library/Fonts/Apple Symbols.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
    "/usr/share/fonts/truetype/ancient-scripts/Symbols2.ttf",
]

_font_cache: dict[int, "ImageFont.FreeTypeFont"] = {}
_per_root: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def mono(ch: str) -> str:
    """去掉 emoji 变体选择符，得到「文本呈现」码点序列。"""
    return ch.replace("\ufe0f", "").replace("\ufe0e", "")


def _font_path() -> str | None:
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def available() -> bool:
    """位图图标是否可用（Pillow + 符号字体都在）。"""
    return _PIL and _font_path() is not None


def _pil_font(size: int):
    f = _font_cache.get(size)
    if f is None:
        path = _font_path()
        if path is None:
            return None
        f = ImageFont.truetype(path, size)
        _font_cache[size] = f
    return f


def _root_of(master):
    """取控件所属的 root（PhotoImage 要绑到正确的 interpreter）。"""
    if master is None:
        import tkinter as _tk
        return _tk._get_default_root()
    try:
        return master.winfo_toplevel()
    except Exception:
        return None


def _alive(img) -> bool:
    """检测 Tk image 是否还有效（root 销毁后为僵尸）。"""
    try:
        img.tk.call("image", "type", str(img))
        return True
    except Exception:
        return False


def icon(ch: str, size: int, color: str, master=None):
    """把字符渲染为单色 PhotoImage（居中，四周留 2px 呼吸边距）。

    ``master`` 传入调用方控件，保证 image 与其 canvas 处于同一
    Tk interpreter；size 为像素字号；color 为十六进制色。
    失败返回 None。
    """
    if not available():
        return None
    root = _root_of(master)
    if root is None:
        return None
    key = (mono(ch), size, color)
    cache = _per_root.get(root)
    if cache is None:
        cache = _per_root[root] = {}
    img = cache.get(key)
    if img is not None and _alive(img):
        return img
    try:
        f = _pil_font(size)
        if f is None:
            return None
        pad = 2
        im = Image.new("RGBA", (size + pad * 2, size + pad * 2), (0, 0, 0, 0))
        ImageDraw.Draw(im).text(
            (im.width / 2, im.height / 2), key[0],
            font=f, fill=color, anchor="mm")
        img = ImageTk.PhotoImage(im, master=root)
        cache[key] = img
        return img
    except Exception:
        return None
