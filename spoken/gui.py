"""Windows 桌面 GUI（tkinter，Python 官方自带，零额外依赖）。

界面结构（浅色现代简约风）：
  - 欢迎页：程序标题 + 「开始练习」入口；
  - 设置页：场景卡片 + 难度选择 + 「开始对话」；
  - 对话页：聊天区 / 录音球体动画 / 文字输入 / 总结。
线程模型：录音、识别、LLM 调用、朗读、总结全部在后台线程，
界面更新统一通过 root.after marshalling 回主线程，避免卡界面。
降级策略：语音识别/合成依赖缺失时，程序仍可以纯文字模式完整运行。
圆角与投影：tkinter 原生控件无圆角，用 Canvas 自绘圆角矩形/按钮/卡片。
录音动画：读取 MicRecorder.last_level（实时 RMS 电平），主线程 ~30fps
          驱动球体缩放与波纹扩散，平滑插值保证流畅。
"""

from __future__ import annotations

import math
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .asr import (
    ASRDownloadError, MicRecorder, Transcriber, asr_available, mic_available,
)
from .assessor import Assessor, MockAssessor, float32_to_wav_bytes
from .config import find_config_file, load_config
from .dialogue import DialogueEngine
from .history import add_session, list_sessions, stats as history_stats
from .llm import LLMError, OpenAICompatibleLLM
from .report import render_report_markdown, render_summary_text, save_report
from .scenarios import (
    DIFFICULTIES, DIFFICULTY_ORDER, SCENARIOS, SCENARIO_HOTWORDS, SCENARIO_ORDER,
)
from .tts import Speaker, list_voices as tts_list_voices, tts_available
from .vocab_gen import VocabGenerator
from .vocab_model import VocabEntry
from .vocab_store import delete_word, list_words, save_word
from . import accents, cloud_tts

_FONT = ("Microsoft YaHei UI", 10)
_FONT_SMALL = ("Microsoft YaHei UI", 9)
_FONT_TITLE = ("Microsoft YaHei UI", 26, "bold")
_FONT_H2 = ("Microsoft YaHei UI", 13, "bold")

# ------------------------------------------------------------------
# 浅色调色板
# ------------------------------------------------------------------
C_BG = "#F4F6FA"        # 米白浅灰背景
C_CARD = "#FFFFFF"      # 卡片
C_BORDER = "#E4E9F2"    # 边框
C_SHADOW = "#E8EDF4"    # 卡片投影（偏移矩形模拟）
C_TEXT = "#2E3A4D"      # 主文字（深灰蓝，非纯黑）
C_TEXT2 = "#7C8AA0"     # 次文字
C_TEXT3 = "#AAB6C6"     # 弱文字/禁用
C_ACCENT = "#4C7DFF"    # 主色（淡蓝）
C_ACCENT_D = "#3A6BE0"  # 主色加深（按压）
C_ACCENT_BG = "#ECF2FF"  # 选中卡片底
C_GREEN = "#3FAE85"     # 辅助色（淡绿）
C_REC = "#FF7A6B"       # 录音珊瑚色
C_REC_D = "#F2604F"
C_REC_BG = "#FFEEEB"
C_TAG_AI = "#2B5FD9"
C_TAG_USER = "#2F7D4F"
C_TAG_FEEDBACK = "#B7791F"
C_TAG_HINT = "#C05621"
C_TAG_SYS = "#8A94A6"


# 场景图标（仅展示用，与后端场景数据解耦）
_SCENARIO_ICONS = {
    "daily_smalltalk": "💬",
    "airport_checkin": "✈️",
    "job_interview": "💼",
    "restaurant_order": "🍽️",
}


# ------------------------------------------------------------------
# Canvas 自绘组件
# ------------------------------------------------------------------
def _rr_fill(cv: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
             r: float, **kw) -> None:
    """在 canvas 上画填充圆角矩形。"""
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    cv.create_rectangle(x1 + r, y1, x2 - r, y2, **kw)
    cv.create_rectangle(x1, y1 + r, x2, y2 - r, **kw)
    if r <= 0:
        return
    cv.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90,
                  style="pieslice", **kw)
    cv.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90,
                  style="pieslice", **kw)
    cv.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90,
                  style="pieslice", **kw)
    cv.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90,
                  style="pieslice", **kw)


def rounded_rect(cv: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
                 r: float, fill: str | None = None, outline: str | None = None,
                 width: int = 1) -> None:
    """圆角矩形（outline 用“大底小盖”实现，保证边框也是圆角）。"""
    if outline and width > 0:
        _rr_fill(cv, x1, y1, x2, y2, r, fill=outline, outline="")
        _rr_fill(cv, x1 + width, y1 + width, x2 - width, y2 - width,
                 max(0.0, r - width), fill=fill or C_BG, outline="")
    else:
        _rr_fill(cv, x1, y1, x2, y2, r, fill=fill or C_BG, outline="")


class PillButton(tk.Canvas):
    """圆角按钮：primary / secondary / rec / ghost 四种风格，带悬停按压态。"""

    _STYLES = {
        "primary": (C_ACCENT, C_ACCENT_D, "#FFFFFF"),
        "rec": (C_REC, C_REC_D, "#FFFFFF"),
        "secondary": (C_CARD, "#EEF2F8", C_TEXT),
        "ghost": (C_BG, "#EAEEF5", C_TEXT2),
    }

    def __init__(self, master, text: str, command=None, kind: str = "primary",
                 width: int = 120, height: int = 34, font=_FONT,
                 bg: str = C_BG) -> None:
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0)
        self.text = text
        self.command = command
        self.kind = kind
        self.font = font
        self._bw, self._bh = width, height
        self._enabled = True
        self._hover = False
        self._pressed = False
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._draw()

    # -- 公开 API --------------------------------------------------
    def set_text(self, text: str) -> None:
        self.text = text
        self._draw()

    def set_enabled(self, on: bool) -> None:
        self._enabled = on
        self._draw()

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self._draw()

    # -- 内部 ------------------------------------------------------
    def _on_enter(self, _e):
        self._hover = True
        self._draw()

    def _on_leave(self, _e):
        self._hover = self._pressed = False
        self._draw()

    def _on_press(self, _e):
        self._pressed = True
        self._draw()

    def _on_release(self, e):
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if was_pressed and self._enabled and self.command:
            if 0 <= e.x <= self._bw and 0 <= e.y <= self._bh:
                self.command()

    def _draw(self) -> None:
        self.delete("all")
        if not self._enabled:
            rounded_rect(self, 1, 1, self._bw - 1, self._bh - 1, self._bh / 2,
                         fill="#EDF0F5")
            self.create_text(self._bw / 2, self._bh / 2, text=self.text,
                             font=self.font, fill=C_TEXT3)
            return
        base, pressed, fg = self._STYLES[self.kind]
        fill = pressed if self._pressed else base
        if self.kind == "secondary" and self._hover:
            fill = "#E6ECF6"
        elif self.kind == "primary" and self._hover:
            fill = "#5C89FF"
        elif self.kind == "rec" and self._hover:
            fill = "#FF8F81"
        elif self.kind == "ghost" and self._hover:
            fill = "#E2E8F2"
        # 轻微投影
        _rr_fill(self, 0, 2, self._bw, self._bh, self._bh / 2,
                 fill=C_SHADOW, outline="")
        rounded_rect(self, 0, 0, self._bw, self._bh - 2, self._bh / 2, fill=fill)
        self.create_text(self._bw / 2, (self._bh - 2) / 2, text=self.text,
                         font=self.font, fill=fg)


class ScenarioCard(tk.Canvas):
    """场景选择卡片：emoji + 中文名 + 英文名，选中态高亮。"""

    def __init__(self, master, key: str, index: int, on_select,
                 width: int = 300, height: int = 84) -> None:
        super().__init__(master, width=width, height=height, bg=C_BG,
                         highlightthickness=0, bd=0)
        self.key = key
        self.index = index
        self.on_select = on_select
        self.selected = False
        self._bw, self._bh = width, height
        self.bind("<Enter>", lambda _e: self._draw(hover=True))
        self.bind("<Leave>", lambda _e: self._draw())
        self.bind("<Button-1>", lambda _e: self.on_select(index))
        self._draw()

    def set_selected(self, on: bool) -> None:
        self.selected = on
        self._draw()

    def _draw(self, hover: bool = False) -> None:
        self.delete("all")
        info = SCENARIOS[self.key]
        # 投影
        _rr_fill(self, 0, 2, self._bw, self._bh, 14, fill=C_SHADOW, outline="")
        if self.selected:
            rounded_rect(self, 0, 0, self._bw, self._bh - 2, 14,
                         fill=C_ACCENT_BG, outline=C_ACCENT, width=2)
        else:
            rounded_rect(self, 0, 0, self._bw, self._bh - 2, 14,
                         fill=C_CARD, outline=C_BORDER, width=1)
        self.create_text(34, self._bh / 2 - 2, text=_SCENARIO_ICONS.get(self.key, "🗣"),
                         font=("Segoe UI Emoji", 24))
        self.create_text(70, 26, text=info["name"], anchor="w",
                         font=_FONT_H2, fill=C_TEXT)
        self.create_text(70, 50, text=info["name_en"], anchor="w",
                         font=_FONT_SMALL, fill=C_TEXT2)


class DifficultyPill(tk.Canvas):
    """难度选择胶囊：选中态实心主色。"""

    def __init__(self, master, key: str, index: int, on_select,
                 width: int = 190, height: int = 46) -> None:
        super().__init__(master, width=width, height=height, bg=C_BG,
                         highlightthickness=0, bd=0)
        self.key = key
        self.index = index
        self.on_select = on_select
        self.selected = False
        self._bw, self._bh = width, height
        self._hover = False
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<Button-1>", lambda _e: self.on_select(index))
        self._draw()

    def _set_hover(self, on: bool) -> None:
        self._hover = on
        self._draw()

    def set_selected(self, on: bool) -> None:
        self.selected = on
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        info = DIFFICULTIES[self.key]
        _rr_fill(self, 0, 2, self._bw, self._bh, self._bh / 2,
                 fill=C_SHADOW, outline="")
        if self.selected:
            rounded_rect(self, 0, 0, self._bw, self._bh - 2, self._bh / 2,
                         fill=C_ACCENT)
            name_fg, cefr_fg = "#FFFFFF", "#D8E4FF"
        else:
            rounded_rect(self, 0, 0, self._bw, self._bh - 2, self._bh / 2,
                         fill=C_CARD, outline=C_BORDER, width=1)
            name_fg, cefr_fg = C_TEXT, C_TEXT2
        self.create_text(self._bw / 2 - 18, self._bh / 2 - 1, text=info["name"],
                         font=_FONT, fill=name_fg)
        self.create_text(self._bw / 2 + 26, self._bh / 2 - 1,
                         text=info["cefr"], font=_FONT_SMALL, fill=cefr_fg)


class RecordingOrb(tk.Canvas):
    """录音球体动画：随实时音量缩放 + 波纹扩散。

    - level 平滑插值（~30fps 主线程驱动），音量越大球体越大、波纹越远；
    - 停止录音时整体隐藏，不留残留。
    """

    SIZE = 300

    def __init__(self, master, bg: str = C_BG) -> None:
        super().__init__(master, width=self.SIZE, height=self.SIZE, bg=bg,
                         highlightthickness=0, bd=0)
        self.level = 0.0          # 平滑后的电平
        self._target = 0.0
        self._phase = 0.0         # 波纹相位
        self._visible = False
        self._started_at = 0.0
        self._timer_text = "00:00"

    # -- 公开 API --------------------------------------------------
    def start(self) -> None:
        self.level = 0.0
        self._target = 0.0
        self._phase = 0.0
        self._visible = True
        self._started_at = time.monotonic()
        self._timer_text = "00:00"

    def stop(self) -> None:
        self._visible = False

    @property
    def visible(self) -> bool:
        return self._visible

    def set_level(self, value: float) -> None:
        self._target = max(0.0, min(1.0, value))

    def tick(self) -> None:
        """推进一帧动画（由主线程定时调用）。"""
        if not self._visible:
            return
        # 平滑插值：大权重趋向目标，保证跟手又不抖动
        self.level += (self._target - self.level) * 0.32
        self._phase += 0.055
        if self._started_at:
            secs = int(time.monotonic() - self._started_at)
            self._timer_text = f"{secs // 60:02d}:{secs % 60:02d}"
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        cx = cy = self.SIZE / 2
        lv = self.level
        # 待机呼吸：静音时也有轻微脉动，避免"死球"
        breath = 0.05 + 0.025 * math.sin(self._phase * 1.6)
        energy = max(breath, lv)

        # ---- 波纹扩散圈（音量越大扩散越远） ----------------------
        for i in range(3):
            p = (self._phase * 0.9 + i / 3.0) % 1.0
            ring_r = 52 + p * (46 + lv * 60)
            tint = ("#D9E5FF", "#C6D8FF", "#B3CBFF")[i]
            self.create_oval(cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r,
                             outline=tint, width=2)
        # ---- 球体（同心圆模拟径向渐变） --------------------------
        r = 44 + lv * 26
        self.create_oval(cx - r, cy - r, cx + r, cy + r,
                         fill="#B9CFFF", outline="")
        self.create_oval(cx - r * 0.74, cy - r * 0.74,
                         cx + r * 0.74, cy + r * 0.74,
                         fill="#7FA5FF", outline="")
        self.create_oval(cx - r * 0.48, cy - r * 0.48,
                         cx + r * 0.48, cy + r * 0.48,
                         fill=C_ACCENT, outline="")
        # 中心图标
        self.create_text(cx, cy, text="🎙", font=("Segoe UI Emoji", 20),
                         fill="#FFFFFF")
        # ---- 状态文字 --------------------------------------------
        self.create_text(cx, cy + r + 26, text="正在聆听 …",
                         font=_FONT_H2, fill=C_REC)
        self.create_text(cx, cy + r + 50, text=self._timer_text,
                         font=_FONT_SMALL, fill=C_TEXT2)


# ------------------------------------------------------------------
# 主应用
# ------------------------------------------------------------------
class SpokenApp:
    """spoken 桌面应用主类。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("spoken — 智能英语口语教练")
        self.root.geometry("960x720")
        self.root.minsize(860, 600)
        self.root.configure(bg=C_BG)

        self.cfg = load_config()
        self.engine: DialogueEngine | None = None
        self.session_active = False
        self.busy = False            # 后台任务进行中（识别/LLM/总结）
        self.recorder: MicRecorder | None = None
        self.recording = False
        self._last_dl_pct = -1        # 模型下载进度节流
        self._last_dl_t = 0.0
        self._scenario_idx = 0
        self._difficulty_idx = 0

        # 语音组件（缺失时自动降级）
        self._last_ai_line = ""
        self._ref_text = ""          # 跟读参考句（最近一次 AI 台词）
        self._rec_mode = "chat"      # 录音模式：chat=对话轮 / shadow=跟读打分
        self._speed_rate = {"slow": 140, "medium": 175, "fast": 215}
        self._speed_mult = {"slow": 0.8, "medium": 1.0, "fast": 1.3}
        speed = (self.cfg.tts_speed or "medium")
        sapi_rate = self._speed_rate.get(speed, 175)
        # 云端 TTS（可选）：配置后优先用 CosyVoice，失败自动回退本地 SAPI
        self.speaker = Speaker(
            rate=sapi_rate, voice=self.cfg.tts_voice,
            volume=max(0.0, min(1.0, self.cfg.tts_volume / 100.0)),
            on_error=self._on_tts_error, cloud_synth=self._make_cloud_synth())
        # 发音评分（可选）：配置 nls AppKey/Token 后用真实声学打分；否则留空
        assess_cfg = self.cfg.assessment or {}
        if (assess_cfg.get("enabled") and assess_cfg.get("appkey")
                and assess_cfg.get("token")):
            self.assessor = Assessor(
                appkey=assess_cfg["appkey"], token=assess_cfg["token"],
                region=assess_cfg.get("region", "cn-shanghai"),
                model_id=assess_cfg.get("model_id", "en.pred.score"))
        else:
            self.assessor = None
        self.history_db = Path("practice_history.db")
        local_path = self.cfg.asr_model_local_path or None
        self.transcriber = (
            Transcriber(self.cfg.asr_model, self.cfg.asr_language,
                        local_path=local_path,
                        download_progress=self._asr_download_progress)
            if asr_available() else None)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _make_cloud_synth(self):
        """按当前配置构造云端 TTS 合成函数；未启用或无 key 时返回 None。

        音色/语言由 spoken.accents.resolve_cloud_voice 解析：
        优先自定义音色 id，其次按选定口音取官方音色。
        """
        cloud_cfg = self.cfg.cloud_tts or {}
        if not (cloud_cfg.get("enabled") and cloud_cfg.get("api_key")):
            return None
        voice, language_hint = accents.resolve_cloud_voice(cloud_cfg)
        speed = self.cfg.tts_speed or "medium"
        mult = self._speed_mult.get(speed, 1.0)
        volume = max(0, min(100, int(self.cfg.tts_volume)))
        api_key = cloud_cfg.get("api_key", "")
        model = cloud_cfg.get("model", "cosyvoice-v3-flash")
        return lambda text: cloud_tts.synthesize(
            text, api_key=api_key, model=model, voice=voice,
            language_hint=language_hint, speed=mult, volume=volume)

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self._pages: dict[str, tk.Frame] = {}
        self._build_welcome_page()
        self._build_setup_page()
        self._build_chat_page()
        self._show_page("welcome")

        # 启动 1 秒后做一次语音自检，让"没声音"问题当场可见
        if self.speaker.available:
            self.root.after(1000, self._voice_selfcheck)

    def _show_page(self, name: str) -> None:
        for page in self._pages.values():
            page.pack_forget()
        self._pages[name].pack(fill=tk.BOTH, expand=True)
        self._page = name

    # -- 欢迎页 -------------------------------------------------------
    def _build_welcome_page(self) -> None:
        page = tk.Frame(self.root, bg=C_BG)
        self._pages["welcome"] = page

        # 装饰性柔和色块（浅蓝 / 浅绿，部分出血到屏幕外）
        deco = tk.Canvas(page, bg=C_BG, highlightthickness=0, bd=0)
        deco.place(relx=0, rely=0, relwidth=1, relheight=1)
        deco.create_oval(-160, -180, 260, 240, fill="#E9F0FE", outline="")
        deco.create_oval(760, 480, 1180, 900, fill="#E6F6F0", outline="")
        deco.create_oval(880, -120, 1080, 80, fill="#EAF1FE", outline="")

        card = tk.Canvas(page, width=460, height=380, bg=C_BG,
                         highlightthickness=0, bd=0)
        card.place(relx=0.5, rely=0.44, anchor="center")
        _rr_fill(card, 4, 8, 456, 372, 24, fill=C_SHADOW, outline="")
        rounded_rect(card, 4, 4, 456, 368, 24, fill=C_CARD,
                     outline=C_BORDER, width=1)

        # 顶部圆形图标
        card.create_oval(190, 52, 270, 132, fill=C_ACCENT_BG, outline="")
        card.create_text(230, 92, text="🎓", font=("Segoe UI Emoji", 30))
        card.create_text(230, 176, text="口语练习助手",
                         font=_FONT_TITLE, fill=C_TEXT)
        card.create_text(230, 216, text="AI 陪你每天练英语口语 · 实时纠错 · 语音陪练",
                         font=_FONT_SMALL, fill=C_TEXT2)
        card.create_text(230, 246, text="本地模型驱动，离线也能练",
                         font=_FONT_SMALL, fill=C_TEXT2)

        self._welcome_btn = PillButton(
            card, text="开始练习", command=lambda: self._show_page("setup"),
            kind="primary", width=200, height=44,
            font=("Microsoft YaHei UI", 11, "bold"))
        card.create_window(230, 306, window=self._welcome_btn)
        card.create_text(230, 344, text="spoken v1.0.0",
                         font=_FONT_SMALL, fill=C_TEXT3)

    # -- 设置页 -------------------------------------------------------
    def _build_setup_page(self) -> None:
        page = tk.Frame(self.root, bg=C_BG)
        self._pages["setup"] = page

        # 顶部标题
        header = tk.Frame(page, bg=C_BG)
        header.pack(fill=tk.X, padx=48, pady=(36, 12))
        tk.Label(header, text="练习设置", font=_FONT_TITLE, bg=C_BG,
                 fg=C_TEXT).pack(anchor="w")
        tk.Label(header, text="选一个场景和难度，随时可以重新开始",
                 font=_FONT_SMALL, bg=C_BG, fg=C_TEXT2).pack(anchor="w", pady=(4, 0))
        # 右上角工具按钮：生词本 / 练习历史 / 语音设置
        toolbar = tk.Frame(header, bg=C_BG)
        toolbar.pack(side=tk.RIGHT, anchor="e")
        self._vocab_btn = PillButton(
            toolbar, text="📚 生词本", command=self._open_vocab,
            kind="ghost", width=104, height=30, bg=C_BG)
        self._vocab_btn.pack(side=tk.RIGHT, padx=(0, 8))
        self._history_btn = PillButton(
            toolbar, text="📊 练习历史", command=self._open_history,
            kind="ghost", width=116, height=30, bg=C_BG)
        self._history_btn.pack(side=tk.RIGHT, padx=(0, 8))
        self._settings_btn = PillButton(
            toolbar, text="⚙ 语音设置", command=self._open_voice_settings,
            kind="ghost", width=116, height=30, bg=C_BG)
        self._settings_btn.pack(side=tk.RIGHT)

        # 场景卡片区
        tk.Label(page, text="选择场景", font=_FONT_H2, bg=C_BG,
                 fg=C_TEXT).pack(anchor="w", padx=48, pady=(10, 8))
        grid = tk.Frame(page, bg=C_BG)
        grid.pack(anchor="w", padx=48)
        self._scenario_cards: list[ScenarioCard] = []
        for i, key in enumerate(SCENARIO_ORDER):
            card = ScenarioCard(grid, key, i, self._select_scenario)
            card.grid(row=i // 2, column=i % 2, padx=(0, 16), pady=(0, 14))
            self._scenario_cards.append(card)
        self._scenario_cards[0].set_selected(True)

        # 难度选择区
        tk.Label(page, text="选择难度", font=_FONT_H2, bg=C_BG,
                 fg=C_TEXT).pack(anchor="w", padx=48, pady=(6, 8))
        pill_row = tk.Frame(page, bg=C_BG)
        pill_row.pack(anchor="w", padx=48)
        self._difficulty_btns: list[DifficultyPill] = []
        for i, key in enumerate(DIFFICULTY_ORDER):
            pill = DifficultyPill(pill_row, key, i, self._select_difficulty)
            pill.grid(row=0, column=i, padx=(0, 14))
            self._difficulty_btns.append(pill)
        self._difficulty_btns[0].set_selected(True)

        # 底部操作行
        bottom = tk.Frame(page, bg=C_BG)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=48, pady=24)
        back = PillButton(bottom, text="← 返回", command=self._back_to_welcome,
                          kind="ghost", width=96, height=38)
        back.pack(side=tk.LEFT)
        self._start_btn = PillButton(
            bottom, text="开始对话", command=self._start_session,
            kind="primary", width=160, height=38,
            font=("Microsoft YaHei UI", 11, "bold"))
        self._start_btn.pack(side=tk.RIGHT)

        self._setup_status_var = tk.StringVar(value=self._initial_status())
        tk.Label(page, textvariable=self._setup_status_var, font=_FONT_SMALL,
                 bg=C_BG, fg=C_TEXT2, anchor="w").pack(
                     side=tk.BOTTOM, fill=tk.X, padx=48, pady=(0, 10))

    # -- 对话页 -------------------------------------------------------
    def _build_chat_page(self) -> None:
        page = tk.Frame(self.root, bg=C_BG)
        self._pages["chat"] = page

        # 顶部：会话信息 + 结束对话
        header = tk.Frame(page, bg=C_BG)
        header.pack(fill=tk.X, padx=20, pady=(14, 8))
        self._session_var = tk.StringVar(value="")
        tk.Label(header, textvariable=self._session_var, font=_FONT_H2,
                 bg=C_BG, fg=C_TEXT).pack(side=tk.LEFT)
        self._chat_vocab_btn = PillButton(
            header, text="📚 生词本", command=self._open_vocab,
            kind="ghost", width=110, height=32, bg=C_BG)
        self._chat_vocab_btn.pack(side=tk.RIGHT, padx=(0, 8))
        self._end_btn = PillButton(header, text="结束对话",
                                   command=self._end_session, kind="rec",
                                   width=110, height=32, bg=C_BG)
        self._end_btn.pack(side=tk.RIGHT)

        # 聊天区（Text 指定 height，避免 YaHei 字体请求过高挤占输入行）
        chat_frame = tk.Frame(page, bg=C_CARD, padx=2, pady=2)
        chat_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 8))
        self.chat = tk.Text(chat_frame, wrap=tk.WORD, state=tk.DISABLED,
                            font=_FONT, spacing1=4, spacing3=6, height=14,
                            bg=C_CARD, relief=tk.FLAT, bd=0)
        scrollbar = ttk.Scrollbar(chat_frame, command=self.chat.yview)
        self.chat.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(2, 0))
        self.chat.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.chat.tag_config("ai", foreground=C_TAG_AI,
                             font=("Microsoft YaHei UI", 10, "bold"))
        self.chat.tag_config("user", foreground=C_TAG_USER)
        self.chat.tag_config("feedback", foreground=C_TAG_FEEDBACK)
        self.chat.tag_config("hint", foreground=C_TAG_HINT)
        self.chat.tag_config("system", foreground=C_TAG_SYS,
                             font=("Microsoft YaHei UI", 9, "italic"))

        # 参考句 / 关键词提示（跟读辅助，始终可见）
        self._ref_frame = tk.Frame(page, bg=C_BG)
        self._ref_frame.pack(fill=tk.X, padx=20, pady=(0, 4))
        self._ref_label = tk.Label(
            self._ref_frame, text="", font=_FONT_SMALL, bg=C_BG, fg=C_TEXT2,
            anchor="w", justify="left", wraplength=900)
        self._ref_label.pack(fill=tk.X)

        # 录音球体（覆盖在聊天区中央，默认隐藏）
        self._orb = RecordingOrb(page, bg=C_BG)
        self._orb_timer = None

        # 底部输入行
        bottom = tk.Frame(page, bg=C_BG)
        bottom.pack(fill=tk.X, padx=20, pady=(0, 10))
        self.mic_btn = PillButton(bottom, text="🎤 点击说话",
                                  command=self._toggle_mic, kind="primary",
                                  width=128, height=34, bg=C_BG)
        self.mic_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.input_var = tk.StringVar()
        self._entry_bg = tk.Canvas(bottom, height=34, bg=C_BG,
                                   highlightthickness=0, bd=0)
        self._entry_bg.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.input_entry = tk.Entry(
            self._entry_bg, textvariable=self.input_var, font=_FONT,
            bg=C_CARD, relief=tk.FLAT, bd=0, insertbackground=C_TEXT,
            fg=C_TEXT)
        self.input_entry.bind("<Return>", lambda _e: self._send_from_box())
        self._entry_bg.bind("<Configure>", self._redraw_entry_bg)
        self._redraw_entry_bg()

        self.send_btn = PillButton(bottom, text="发送",
                                   command=self._send_from_box,
                                   kind="secondary", width=72, height=34,
                                   bg=C_BG)
        self.send_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.shadow_btn = PillButton(bottom, text="🎯 跟读打分",
                                     command=self._start_shadow,
                                     kind="ghost", width=120, height=34,
                                     bg=C_BG)
        self.shadow_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.replay_btn = PillButton(bottom, text="🔊 重播",
                                     command=self._replay_last,
                                     kind="ghost", width=96, height=34,
                                     bg=C_BG)
        self.replay_btn.set_enabled(False)
        self.replay_btn.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value=self._initial_status())
        tk.Label(page, textvariable=self.status_var, font=_FONT_SMALL,
                 bg=C_BG, fg=C_TEXT2, anchor="w").pack(
                     side=tk.BOTTOM, fill=tk.X, padx=20, pady=(0, 10))

    def _redraw_entry_bg(self, _e=None) -> None:
        self._entry_bg.delete("all")
        w = self._entry_bg.winfo_width() or 300
        h = self._entry_bg.winfo_height() or 34
        _rr_fill(self._entry_bg, 0, 2, w, h, h / 2, fill=C_SHADOW, outline="")
        rounded_rect(self._entry_bg, 0, 0, w, h - 2, h / 2,
                     fill=C_CARD, outline=C_BORDER, width=1)
        # 注意：delete("all") 会连窗口项一起删掉，必须重新挂载 Entry
        self.input_entry_window = self._entry_bg.create_window(
            12, (h - 2) / 2, window=self.input_entry, anchor="w")

    # ------------------------------------------------------------------
    # 语音自检 / TTS 错误
    # ------------------------------------------------------------------
    def _voice_selfcheck(self) -> None:
        self._append_system("语音自检：现在应该播放一句英文。"
                            "如果没听到，请检查系统音量/输出设备（聊天区会提示错误）。")
        self.speaker.speak("Voice ready. Let's practice English!")

    def _on_tts_error(self, message: str) -> None:
        self._ui(self._append_system, f"语音合成出错：{message}")

    def _replay_last(self) -> None:
        if self._last_ai_line and self.speaker.available:
            self.speaker.speak(self._last_ai_line)

    # ------------------------------------------------------------------
    # 录音球体动画
    # ------------------------------------------------------------------
    def _orb_start(self) -> None:
        self._orb.start()
        self._orb.place(relx=0.5, rely=0.46, anchor="center")
        self._orb_tick()

    def _orb_stop(self) -> None:
        self._orb.stop()
        self._orb.place_forget()
        if self._orb_timer is not None:
            self.root.after_cancel(self._orb_timer)
            self._orb_timer = None

    def _orb_tick(self) -> None:
        if not self._orb.visible:
            self._orb_timer = None
            return
        if self.recorder is not None:
            self._orb.set_level(getattr(self.recorder, "last_level", 0.0))
        self._orb.tick()
        # ~30fps：足够流畅且开销极小
        self._orb_timer = self.root.after(33, self._orb_tick)

    # ------------------------------------------------------------------
    # 线程工具：后台执行 + 界面更新 marshalling
    # ------------------------------------------------------------------
    def _run_worker(self, fn, *args) -> None:
        threading.Thread(target=self._worker_guard, args=(fn, *args),
                         daemon=True).start()

    def _worker_guard(self, fn, *args) -> None:
        try:
            fn(*args)
        except Exception as exc:  # 兜底：任何后台异常都不许拖垮界面
            self._ui(self._append_system, f"出现错误：{exc}")
            self._ui(self._finish_busy)

    def _ui(self, fn, *args) -> None:
        """把界面更新请求抛回主线程执行。"""
        self.root.after(0, lambda: fn(*args))

    def _set_status(self, text: str) -> None:
        self._ui(self.status_var.set, text)

    # ------------------------------------------------------------------
    # 聊天区输出
    # ------------------------------------------------------------------
    def _append_chat(self, tag: str, speaker: str, text: str) -> None:
        self.chat.configure(state=tk.NORMAL)
        if speaker:
            self.chat.insert(tk.END, f"{speaker}：", tag)
        self.chat.insert(tk.END, f"{text}\n", tag)
        self.chat.configure(state=tk.DISABLED)
        self.chat.see(tk.END)

    def _append_system(self, text: str) -> None:
        self._append_chat("system", "", text)

    def _render_feedback(self, result) -> None:
        """渲染纠错与更地道表达；没有错误时什么都不输出（不硬凑）。"""
        for item in result.corrections:
            self._append_chat(
                "feedback", "💡 纠错",
                f"“{item.get('original', '')}” → “{item.get('corrected', '')}”"
                f"（{item.get('reason', '')}）")
        if result.alternatives:
            self._append_chat(
                "feedback", "🗣 更地道",
                " / ".join(result.alternatives))

    # ------------------------------------------------------------------
    # 会话控制
    # ------------------------------------------------------------------
    def _selected_keys(self) -> tuple[str, str]:
        scenario = SCENARIO_ORDER[self._scenario_idx]
        difficulty = DIFFICULTY_ORDER[self._difficulty_idx]
        return scenario, difficulty

    def _select_scenario(self, index: int) -> None:
        self._scenario_idx = index
        for i, card in enumerate(self._scenario_cards):
            card.set_selected(i == index)

    def _select_difficulty(self, index: int) -> None:
        self._difficulty_idx = index
        for i, pill in enumerate(self._difficulty_btns):
            pill.set_selected(i == index)

    def _back_to_welcome(self) -> None:
        self._show_page("welcome")

    def _initial_status(self) -> str:
        parts = [f"模型：{self.cfg.model}"]
        parts.append("语音识别：" + ("就绪（首次说话时加载）" if self.transcriber
                                    else "不可用（可打字）"))
        parts.append("语音合成：" + ("就绪" if self.speaker.available else "不可用"))
        return "｜".join(parts)

    def _build_llm(self) -> OpenAICompatibleLLM:
        return OpenAICompatibleLLM(
            base_url=self.cfg.base_url,
            api_key=self.cfg.api_key,
            model=self.cfg.model,
            temperature=self.cfg.temperature,
            timeout=self.cfg.timeout,
            think=self.cfg.think,
        )

    def _start_session(self) -> None:
        if self.session_active:
            return
        scenario, difficulty = self._selected_keys()
        self.engine = DialogueEngine(
            self._build_llm(), scenario, difficulty,
            feedback_language=self.cfg.feedback_language,
            min_turns=self.cfg.min_turns)
        self.session_active = True
        self.busy = True
        self._start_btn.set_enabled(False)
        self._end_btn.set_enabled(True)
        for card in self._scenario_cards:
            card.set_selected(False)
        self._show_page("chat")
        self._session_var.set(
            f"{SCENARIOS[scenario]['name']}｜难度：{DIFFICULTIES[difficulty]['name']}")
        self._ref_text = ""
        self._set_reference()
        self.chat.configure(state=tk.NORMAL)
        self.chat.delete("1.0", tk.END)
        self.chat.configure(state=tk.DISABLED)
        self.replay_btn.set_enabled(False)
        self._append_system(
            f"会话开始：{SCENARIOS[scenario]['name']}｜难度：{DIFFICULTIES[difficulty]['name']}")
        self._set_status("AI 正在开口 …")
        if self.transcriber and not self.transcriber.loaded:
            self._run_worker(self._load_asr_worker)
        self._run_worker(self._opening_worker)

    def _load_asr_worker(self) -> None:
        self._set_status("正在准备语音识别模型（首次需下载，约 150MB）…")
        self.transcriber.load()
        self._set_status("语音识别模型就绪")

    def _asr_download_progress(self, filename: str, done: int,
                               total: int) -> None:
        """模型下载进度回调（下载线程调用，节流后 marshalling 回主线程）。"""
        if total <= 0:
            return
        now = time.monotonic()
        pct = int(done * 100 / total)
        if pct == self._last_dl_pct and now - self._last_dl_t < 2.0:
            return  # 节流：进度变化 <2 秒或不足 1% 不刷新
        self._last_dl_pct, self._last_dl_t = pct, now
        mb_done, mb_total = done / 1e6, total / 1e6
        self._set_status(
            f"正在下载语音识别模型 {filename}：{pct}%"
            f"（{mb_done:.0f}/{mb_total:.0f} MB）")

    def _opening_worker(self) -> None:
        try:
            line = self.engine.start()
        except LLMError as exc:
            self._append_system(f"AI 开口失败：{exc}")
            self._append_system("请检查 config.yaml 里的 API Key 与网络，然后重试。")
            self._ui(self._reset_after_failed_start)
            return
        self._ui(self._show_ai_line, line)
        if self.cfg.auto_speak:
            self.speaker.speak(line)
        self._ui(self._finish_busy)

    def _show_ai_line(self, line: str) -> None:
        scenario, _ = self._selected_keys()
        role = SCENARIOS[scenario]["ai_role"]
        self._append_chat("ai", role, line)
        self._last_ai_line = line
        self._ref_text = line      # 最近 AI 台词作为跟读参考句
        self._set_reference()
        self.replay_btn.set_enabled(True)

    def _end_session(self) -> None:
        if not self.session_active or self.busy:
            return
        self.busy = True
        self._end_btn.set_enabled(False)
        self.mic_btn.set_enabled(False)
        self._set_status("正在生成本次练习总结 …")
        self._run_worker(self._summary_worker)

    def _summary_worker(self) -> None:
        report_path = None
        try:
            summary = self.engine.summarize()
            if self.cfg.save_report:
                report_path = save_report(
                    render_report_markdown(summary), self.cfg.report_dir)
        except Exception as exc:
            self._ui(self._append_system, f"总结生成失败：{exc}")
            self._ui(self._reset_ui_after_session)
            return
        self._ui(self._show_summary_dialog, summary, str(report_path or ""))

    # ------------------------------------------------------------------
    # 用户输入：麦克风 / 文字
    # ------------------------------------------------------------------
    def _toggle_mic(self) -> None:
        if not self.session_active or self.busy:
            return
        if not self.recording:
            if self.recorder is None:
                self.recorder = MicRecorder(self.cfg.sample_rate)
            try:
                self.recorder.start()
            except Exception as exc:
                self._append_system(f"无法开始录音：{exc}")
                self._append_system("请检查麦克风是否连接、是否被其他程序占用。")
                return
            self.recording = True
            self.mic_btn.set_text("⏹ 停止并发送")
            self.mic_btn.set_kind("rec")
            self._set_status("录音中……说完再点一次按钮")
            self._orb_start()
        else:
            self.recording = False
            self.mic_btn.set_text("🎤 点击说话")
            self.mic_btn.set_kind("primary")
            self.mic_btn.set_enabled(False)
            self.busy = True
            self._set_status("识别中……")
            self._orb_stop()
            if self._rec_mode == "shadow":
                self._run_worker(self._shadow_worker)
            else:
                self._run_worker(self._transcribe_worker)

    def _transcribe_worker(self) -> None:
        text = ""
        try:
            audio = self.recorder.stop()
            if self.transcriber is None:
                raise RuntimeError("语音识别组件不可用（未安装 faster-whisper）")
            if not self.transcriber.loaded:
                self._set_status("正在加载语音识别模型（首次需下载，约 150MB）…")
                self.transcriber.load()
            text = self.transcriber.transcribe(audio)
        except Exception as exc:
            self._ui(self._append_system, f"识别失败：{exc}")
            self._ui(self._finish_busy)
            return
        self._ui(self._on_recognized, text)

    def _on_recognized(self, text: str) -> None:
        self.mic_btn.set_enabled(True)
        self.busy = False
        text = (text or "").strip()
        if not text:
            self._set_status("没有识别到内容，请再试一次")
            return
        self.input_var.set(text)
        self._send(text)

    def _send_from_box(self) -> None:
        self._send(self.input_var.get())

    def _send(self, text: str) -> None:
        text = (text or "").strip()
        if not text or not self.session_active or self.busy:
            return
        self.input_var.set("")
        self._append_chat("user", "你", text)
        self.busy = True
        self._set_status("AI 思考中 …")
        self._run_worker(self._turn_worker, text)

    def _turn_worker(self, text: str) -> None:
        try:
            result = self.engine.reply(text)
        except LLMError as exc:
            self.engine.rollback_last_user()
            self._ui(self._append_system, f"模型调用失败：{exc}（请重试或结束对话）")
            self._ui(self._finish_busy)
            return
        self._ui(self._show_turn_result, result)

    def _show_turn_result(self, result) -> None:
        self.busy = False
        if result.difficulty_changed:
            old, new = result.difficulty_changed
            self._append_system(
                f"难度调整：{DIFFICULTIES[old]['name']} → {DIFFICULTIES[new]['name']}")
        self._render_feedback(result)
        if result.stuck:
            self._append_chat("hint", "💡 卡壳提示",
                              result.hint or "别急，试着用一个简单的句子回答。")
        if result.ai_line:
            self._show_ai_line(result.ai_line)
            if self.cfg.auto_speak:
                self.speaker.speak(result.ai_line)
        if result.should_end:
            self._append_system(f"（{result.end_reason or '场景目标已达成'}）")
            self._end_session()
            return
        self._set_status("就绪 — 点击麦克风说话，或输入文字")

    # ------------------------------------------------------------------
    # 状态复位
    # ------------------------------------------------------------------
    def _finish_busy(self) -> None:
        self.busy = False
        if self.session_active:
            self.mic_btn.set_enabled(True)
            self._set_status("就绪 — 点击麦克风说话，或输入文字")

    def _reset_ui_after_session(self) -> None:
        self.session_active = False
        self.busy = False
        self._start_btn.set_enabled(True)
        self._end_btn.set_enabled(False)
        self.mic_btn.set_enabled(True)
        self.mic_btn.set_text("🎤 点击说话")
        self.mic_btn.set_kind("primary")
        self._orb_stop()
        self._show_page("setup")
        self._set_status(self._initial_status())

    def _reset_after_failed_start(self) -> None:
        self._reset_ui_after_session()

    # ------------------------------------------------------------------
    # 总结弹窗
    # ------------------------------------------------------------------
    def _show_summary_dialog(self, summary: dict, report_path: str) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("本次练习总结")
        dialog.geometry("560x480")
        dialog.transient(self.root)
        dialog.configure(bg=C_BG)

        frame = tk.Frame(dialog, bg=C_BG, padx=14, pady=14)
        frame.pack(fill=tk.BOTH, expand=True)
        text = tk.Text(frame, wrap=tk.WORD, font=_FONT, spacing1=3, spacing3=5,
                       height=12, bg=C_CARD, relief=tk.FLAT, bd=0)
        bar = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=bar.set)
        bar.pack(side=tk.RIGHT, fill=tk.Y, padx=(2, 0))
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        text.insert(tk.END, render_summary_text(summary))
        if report_path:
            text.insert(tk.END, f"\n\n📄 报告已保存：{report_path}")
        text.configure(state=tk.DISABLED)

        ok = PillButton(dialog, text="好的", width=110, height=36,
                        command=lambda: (dialog.destroy(),
                                         self._reset_ui_after_session()),
                        bg=C_BG)
        ok.pack(pady=(10, 12))
        dialog.protocol("WM_DELETE_WINDOW",
                        lambda: (dialog.destroy(), self._reset_ui_after_session()))

    # ------------------------------------------------------------------
    # 参考句 / 关键词提示
    # ------------------------------------------------------------------
    def _set_reference(self) -> None:
        parts = []
        if self._ref_text:
            parts.append("📖 参考句：" + self._ref_text)
        sc = SCENARIO_ORDER[self._scenario_idx]
        kw = SCENARIO_HOTWORDS.get(sc, "")
        if kw:
            parts.append("🔑 关键词：" + kw)
        if parts and getattr(self, "_ref_label", None) is not None:
            self._ref_label.config(text="\n".join(parts))

    # ------------------------------------------------------------------
    # 跟读打分（录音 -> 识别字幕 + 声学评分 + 存历史）
    # ------------------------------------------------------------------
    def _start_shadow(self) -> None:
        if not self.session_active or self.busy:
            return
        if self.recorder is None:
            self.recorder = MicRecorder(self.cfg.sample_rate)
        try:
            self.recorder.start()
        except Exception as exc:
            self._append_system(f"无法开始录音：{exc}")
            return
        self._rec_mode = "shadow"
        self.recording = True
        self.mic_btn.set_text("⏹ 停止并评分")
        self.mic_btn.set_kind("rec")
        self._set_status("跟读录音中……读完参考句再点一次按钮")
        self._orb_start()

    def _shadow_worker(self) -> None:
        try:
            audio = self.recorder.stop()
            hotwords = SCENARIO_HOTWORDS.get(self._selected_keys()[0], "")
            recognized = ""
            if self.transcriber is not None:
                if not self.transcriber.loaded:
                    self.transcriber.load()
                recognized = self.transcriber.transcribe(audio, hotwords=hotwords)
            recognized = (recognized or "").strip()
            ref = self._ref_text or self._last_ai_line
            score = None
            if self.assessor is not None and ref:
                try:
                    wav = float32_to_wav_bytes(audio, self.cfg.sample_rate)
                    accent = accents.assess_accent(
                        (self.cfg.cloud_tts or {}).get("accent"))
                    score = self.assessor.evaluate(ref, wav, accent=accent)
                except Exception as exc:
                    self._ui(self._append_system, f"发音评分失败：{exc}")
            elif ref and self.assessor is None:
                self._ui(self._append_system,
                         "（未配置发音评分：在 config.yaml 的 assessment 填入 "
                         "nls AppKey/Token 后可用真实声学打分）")
        except Exception as exc:
            self._ui(self._append_system, f"跟读识别失败：{exc}")
            self._ui(self._finish_busy)
            self._rec_mode = "chat"
            return
        self._ui(self._show_shadow_result, recognized, score)

    def _show_shadow_result(self, recognized: str, score) -> None:
        self._rec_mode = "chat"
        self.mic_btn.set_enabled(True)
        self.busy = False
        if recognized:
            self._append_chat("user", "你（跟读）", recognized)
        else:
            self._append_system("没有识别到内容")
        if score is not None:
            scenario, difficulty = self._selected_keys()
            try:
                add_session(
                    self.history_db, scenario=scenario, difficulty=difficulty,
                    overall=score.overall, accuracy=score.accuracy,
                    integrity=score.integrity, fluency=score.fluency,
                    ref_text=self._ref_text or self._last_ai_line or "")
            except Exception:
                pass
            self._ui(self._show_score_dialog, score)
            self._set_status(
                f"跟读评分：总分 {score.overall:.0f}｜准确度 {score.accuracy:.0f}｜"
                f"完整度 {score.integrity:.0f}｜流利度 {score.fluency:.0f}")
        else:
            self._set_status("就绪 — 点击麦克风说话，或输入文字")

    def _show_score_dialog(self, score) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("跟读评分")
        dialog.geometry("460x380")
        dialog.transient(self.root)
        dialog.configure(bg=C_BG)
        frame = tk.Frame(dialog, bg=C_BG, padx=16, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(frame, text="发音评分结果", font=_FONT_H2, bg=C_BG,
                 fg=C_TEXT).pack(anchor="w")
        rows = [("总分", score.overall), ("准确度", score.accuracy),
                ("完整度", score.integrity), ("流利度", score.fluency)]
        for name, val in rows:
            r = tk.Frame(frame, bg=C_BG)
            r.pack(fill=tk.X, pady=4)
            tk.Label(r, text=name, width=8, anchor="w", bg=C_BG,
                     fg=C_TEXT).pack(side=tk.LEFT)
            tk.Label(r, text=f"{val:.0f}", width=6, anchor="w", bg=C_BG,
                     fg=C_ACCENT, font=_FONT_H2).pack(side=tk.LEFT)
            bar = tk.Canvas(r, height=14, bg=C_BG, highlightthickness=0)
            bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
            pct = max(0.0, min(100.0, val)) / 100.0
            bar.create_rectangle(0, 2, 200 * pct, 12, fill=C_ACCENT, outline="")
            bar.create_rectangle(0, 2, 200, 12, outline=C_BORDER, fill=C_CARD)
        tk.Label(frame, text="建议：" + score.feedback, font=_FONT_SMALL, bg=C_BG,
                 fg=C_TEXT2, wraplength=420, justify="left").pack(
                     anchor="w", pady=(10, 0))
        ok = PillButton(dialog, text="好的", width=110, height=36,
                        command=dialog.destroy, bg=C_BG)
        ok.pack(pady=(12, 14))

    # ------------------------------------------------------------------
    # 语音设置窗口（发音人 / 语速 / 音量 / 云端 TTS）
    # ------------------------------------------------------------------
    def _open_voice_settings(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("语音设置")
        dialog.geometry("480x760")
        dialog.transient(self.root)
        dialog.configure(bg=C_BG)

        tk.Label(dialog, text="发音人（本地 SAPI）", font=_FONT_H2, bg=C_BG,
                 fg=C_TEXT).pack(anchor="w", padx=16, pady=(14, 4))
        voices = tts_list_voices()
        voice_names = ["（系统默认 / 自动选英文）"] + [
            v.get("name", "?") for v in voices]
        voice_ids = [""] + [v.get("id", "") for v in voices]
        voice_var = tk.StringVar(value=self.cfg.tts_voice or voice_names[0])
        ttk.Combobox(dialog, textvariable=voice_var, values=voice_names,
                     state="readonly", width=42).pack(
                         anchor="w", padx=16, pady=(0, 8))

        tk.Label(dialog, text="语速", font=_FONT_H2, bg=C_BG,
                 fg=C_TEXT).pack(anchor="w", padx=16, pady=(4, 2))
        speed_var = tk.StringVar(value=self.cfg.tts_speed or "medium")
        for s in ("slow", "medium", "fast"):
            tk.Radiobutton(dialog, text={"slow": "慢", "medium": "中",
                            "fast": "快"}[s], variable=speed_var, value=s,
                            bg=C_BG).pack(anchor="w", padx=24)

        tk.Label(dialog, text="音量", font=_FONT_H2, bg=C_BG,
                 fg=C_TEXT).pack(anchor="w", padx=16, pady=(6, 2))
        vol_var = tk.IntVar(value=self.cfg.tts_volume)
        tk.Scale(dialog, from_=0, to=100, orient=tk.HORIZONTAL,
                 variable=vol_var, bg=C_BG).pack(
                     anchor="w", padx=16, fill=tk.X)

        tk.Label(dialog, text="云端 TTS（CosyVoice，可选）", font=_FONT_H2,
                 bg=C_BG, fg=C_TEXT).pack(anchor="w", padx=16, pady=(8, 2))
        cloud_cfg = self.cfg.cloud_tts or {}
        cloud_on = tk.BooleanVar(value=bool(cloud_cfg.get("enabled")))
        tk.Checkbutton(dialog, text="启用云端 TTS（音色更清晰）",
                       variable=cloud_on, bg=C_BG).pack(anchor="w", padx=16)

        tk.Label(dialog, text="口音 / 发音人（CosyVoice 官方音色）", bg=C_BG,
                 fg=C_TEXT, font=_FONT_SMALL).pack(anchor="w", padx=16,
                                                   pady=(4, 0))
        accent_key = accents.get_accent(cloud_cfg.get("accent"))["key"]
        if not accents.is_available(accent_key):
            accent_key = accents.DEFAULT_ACCENT
        accent_var = tk.StringVar(value=accent_key)
        acc_frame = tk.Frame(dialog, bg=C_BG)
        acc_frame.pack(anchor="w", padx=24, fill=tk.X)
        for a in accents.ACCENTS:
            usable = a["available"] and a["english"]
            if usable:
                text = f"{a['label']}（{a['country']}）"
                fg = C_TEXT
            elif a["available"]:
                text = f"{a['label']}（{a['country']}）· 非英语口音"
                fg = C_TEXT2
            else:
                text = f"{a['label']}（{a['country']}）· 暂不支持"
                fg = C_TEXT3
            tk.Radiobutton(
                acc_frame, text=text, variable=accent_var, value=a["key"],
                bg=C_BG, font=_FONT_SMALL, selectcolor=C_BG, anchor="w",
                state=(tk.NORMAL if a["available"] else tk.DISABLED),
                fg=fg).pack(anchor="w")
        tk.Label(dialog, text="· 泰/印/越/马/哈/乌：CosyVoice 官方暂无音色；"
                 "日/韩音色只朗读对应语言。缺少的口音可在下方自定义音色 ID 接入。",
                 bg=C_BG, fg=C_TEXT2, font=_FONT_SMALL, wraplength=440,
                 justify="left").pack(anchor="w", padx=16, pady=(2, 0))
        tk.Label(dialog, text="自定义音色 ID（可选，填了则忽略上面的选择）",
                 bg=C_BG, fg=C_TEXT2, font=_FONT_SMALL).pack(
                     anchor="w", padx=16, pady=(6, 0))
        custom_var = tk.StringVar(value=cloud_cfg.get("custom_voice", ""))
        tk.Entry(dialog, textvariable=custom_var, width=42).pack(
            anchor="w", padx=16, pady=(0, 2))

        def _save():
            selected = voice_var.get()
            idx = voice_names.index(selected) if selected in voice_names else 0
            new_voice = voice_ids[idx]
            accent_val = accent_var.get()
            custom = custom_var.get().strip()
            patch = {
                "voice": {"tts_voice": new_voice, "tts_speed": speed_var.get(),
                          "tts_volume": vol_var.get()},
                "cloud_tts": {"enabled": bool(cloud_on.get()),
                              "accent": accent_val,
                              "custom_voice": custom},
            }
            self._save_config_patch(patch)
            self._apply_voice_settings(
                new_voice, speed_var.get(), vol_var.get(),
                cloud_on.get(), accent_val, custom)
            dialog.destroy()

        save_btn = PillButton(dialog, text="保存", width=110, height=36,
                              command=_save, bg=C_BG)
        save_btn.pack(pady=(10, 14))

    def _save_config_patch(self, patch: dict) -> None:
        """把语音设置合并写回 config.yaml（gitignored，仅本地生效）。"""
        try:
            import yaml

            path = find_config_file() or Path("config.yaml")
            data: dict = {}
            if path.is_file():
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            for section, kv in patch.items():
                data.setdefault(section, {})
                data[section].update(kv)
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        except Exception as exc:
            self._append_system(f"保存语音设置失败：{exc}")

    def _apply_voice_settings(self, voice, speed, volume, cloud_on,
                              accent, custom_voice="") -> None:
        self.cfg.tts_voice = voice
        self.cfg.tts_speed = speed
        self.cfg.tts_volume = int(volume)
        if self.cfg.cloud_tts is None:
            self.cfg.cloud_tts = {}
        self.cfg.cloud_tts["enabled"] = bool(cloud_on)
        self.cfg.cloud_tts["accent"] = accent
        self.cfg.cloud_tts["custom_voice"] = custom_voice
        sapi_rate = self._speed_rate.get(speed, 175)
        self.speaker.stop()
        self.speaker = Speaker(
            rate=sapi_rate, voice=voice,
            volume=max(0.0, min(1.0, int(volume) / 100.0)),
            on_error=self._on_tts_error, cloud_synth=self._make_cloud_synth())
        if self.speaker.available and self.cfg.auto_speak:
            self.speaker.speak("Voice settings updated.")

    # ------------------------------------------------------------------
    # 练习历史窗口
    # ------------------------------------------------------------------
    def _open_history(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("练习历史")
        dialog.geometry("560x540")
        dialog.transient(self.root)
        dialog.configure(bg=C_BG)
        s = history_stats(self.history_db)
        tk.Label(dialog, text=f"练习历史（共 {s.count} 次）", font=_FONT_H2,
                 bg=C_BG, fg=C_TEXT).pack(anchor="w", padx=14, pady=(12, 4))
        tk.Label(dialog, text=f"平均分 —— 总分 {s.avg_overall}｜准确度 "
                 f"{s.avg_accuracy}｜完整度 {s.avg_integrity}｜流利度 "
                 f"{s.avg_fluency}", font=_FONT_SMALL, bg=C_BG,
                 fg=C_TEXT2).pack(anchor="w", padx=14, pady=(0, 6))
        canvas = tk.Canvas(dialog, height=140, bg=C_CARD, highlightthickness=0)
        canvas.pack(fill=tk.X, padx=14, pady=(0, 8))
        self._draw_trend(canvas, s.trend)
        listbox = tk.Text(dialog, wrap=tk.WORD, font=_FONT_SMALL, bg=C_CARD,
                          relief=tk.FLAT, bd=0, height=10)
        listbox.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 12))
        for item in list_sessions(self.history_db, 200)[::-1]:
            sc = SCENARIOS.get(item["scenario"], {}).get("name", item["scenario"])
            diff = DIFFICULTIES.get(item["difficulty"], {}).get(
                "name", item["difficulty"])
            listbox.insert(tk.END,
                           f"{item['ts']}  {sc}/{diff}  总分 {item['overall']}\n")
        listbox.configure(state=tk.DISABLED)

    @staticmethod
    def _draw_trend(canvas, trend) -> None:
        w, h = 520, 130
        canvas.config(width=w, height=h)
        if not trend:
            canvas.create_text(w / 2, h / 2, text="暂无数据", fill=C_TEXT3)
            return
        n = len(trend)
        xs = [i / max(1, n - 1) * (w - 40) + 20 for i in range(n)]
        vals = [v for _, v in trend]
        ys = [h - 20 - (v / 100.0) * (h - 40) for v in vals]
        canvas.create_line(20, h - 20, w - 20, h - 20, fill=C_BORDER)
        canvas.create_line(20, 20, 20, h - 20, fill=C_BORDER)
        if n > 1:
            pts = []
            for x, y in zip(xs, ys):
                pts.extend((x, y))
            canvas.create_line(*pts, fill=C_ACCENT, width=2)
        for x, y, v in zip(xs, ys, vals):
            canvas.create_oval(x - 3, y - 3, x + 3, y + 3,
                               fill=C_ACCENT, outline="")
            canvas.create_text(x, y - 10, text=f"{v:.0f}", font=_FONT_SMALL,
                               fill=C_TEXT2)
        canvas.create_text(xs[0], h - 8, text=trend[0][0][5:],
                           font=_FONT_SMALL, fill=C_TEXT3)
        if n > 1:
            canvas.create_text(xs[-1], h - 8, text=trend[-1][0][5:],
                               font=_FONT_SMALL, fill=C_TEXT3)

    # ------------------------------------------------------------------
    # 智能生词本（查询收藏 / 卡片列表 / 搜索 / 排序 / 删除）
    # ------------------------------------------------------------------
    def _open_vocab(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("智能生词本")
        dialog.geometry("700x660")
        dialog.transient(self.root)
        dialog.configure(bg=C_BG)

        self._vocab_dialog = dialog
        self._vocab_db = Path("vocab.db")

        # 标题 + 计数
        tk.Label(dialog, text="智能生词本", font=_FONT_TITLE, bg=C_BG,
                 fg=C_TEXT).pack(anchor="w", padx=18, pady=(16, 2))
        self._vocab_count_var = tk.StringVar(value="")
        tk.Label(dialog, textvariable=self._vocab_count_var, font=_FONT_SMALL,
                 bg=C_BG, fg=C_TEXT2).pack(anchor="w", padx=18, pady=(0, 6))

        # 查询并收藏
        lookup = tk.Frame(dialog, bg=C_BG)
        lookup.pack(fill=tk.X, padx=18, pady=(0, 4))
        self._vocab_lookup_var = tk.StringVar()
        ent = tk.Entry(lookup, textvariable=self._vocab_lookup_var,
                       font=_FONT, bg=C_CARD, relief=tk.FLAT, bd=0,
                       insertbackground=C_TEXT, fg=C_TEXT)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)
        qbtn = PillButton(lookup, text="🔍 查询并收藏",
                          command=self._vocab_lookup, kind="primary",
                          width=132, height=34, bg=C_BG)
        qbtn.pack(side=tk.LEFT, padx=(8, 0))
        self._vocab_status_var = tk.StringVar(value="")
        tk.Label(dialog, textvariable=self._vocab_status_var, font=_FONT_SMALL,
                 bg=C_BG, fg=C_TEXT2, anchor="w").pack(
                     fill=tk.X, padx=18, pady=(0, 4))

        # 搜索 + 排序
        ctrl = tk.Frame(dialog, bg=C_BG)
        ctrl.pack(fill=tk.X, padx=18, pady=(0, 4))
        tk.Label(ctrl, text="搜索", bg=C_BG, fg=C_TEXT2,
                 font=_FONT_SMALL).pack(side=tk.LEFT)
        self._vocab_search_var = tk.StringVar()
        self._vocab_search_var.trace_add(
            "write", lambda *_: self._render_vocab_list())
        se = tk.Entry(ctrl, textvariable=self._vocab_search_var,
                      font=_FONT_SMALL, bg=C_CARD, relief=tk.FLAT, bd=0,
                      fg=C_TEXT)
        se.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3, padx=(6, 12))
        self._vocab_sort_var = tk.StringVar(value="time")
        tk.Radiobutton(ctrl, text="按时间", variable=self._vocab_sort_var,
                       value="time", bg=C_BG, font=_FONT_SMALL,
                       command=self._render_vocab_list).pack(side=tk.LEFT)
        tk.Radiobutton(ctrl, text="按字母", variable=self._vocab_sort_var,
                       value="alpha", bg=C_BG, font=_FONT_SMALL,
                       command=self._render_vocab_list).pack(
                           side=tk.LEFT, padx=(8, 0))

        # 卡片滚动区
        self._vocab_canvas = tk.Canvas(dialog, bg=C_BG, highlightthickness=0)
        self._vocab_scroll = ttk.Scrollbar(
            dialog, orient=tk.VERTICAL, command=self._vocab_canvas.yview)
        self._vocab_canvas.configure(yscrollcommand=self._vocab_scroll.set)
        self._vocab_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 12))
        self._vocab_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                                padx=(12, 0))
        self._vocab_inner = tk.Frame(self._vocab_canvas, bg=C_BG)
        self._vocab_canvas.create_window(
            (0, 0), window=self._vocab_inner, anchor="nw")
        self._vocab_inner.bind(
            "<Configure>",
            lambda e: self._vocab_canvas.configure(
                scrollregion=self._vocab_canvas.bbox("all")))

        self._render_vocab_list()

    def _vocab_alive(self) -> bool:
        dlg = getattr(self, "_vocab_dialog", None)
        return dlg is not None and dlg.winfo_exists()

    def _render_vocab_list(self) -> None:
        if not self._vocab_alive():
            return
        try:
            for child in self._vocab_inner.winfo_children():
                child.destroy()
            entries = list_words(
                self._vocab_db, sort=self._vocab_sort_var.get(),
                search=self._vocab_search_var.get().strip())
            self._vocab_count_var.set(f"共 {len(entries)} 个生词")
            if not entries:
                tk.Label(
                    self._vocab_inner,
                    text="还没有生词。在上方输入单词/短语，点击「查询并收藏」即可添加；"
                         "离线也能查看已收藏的词条。",
                    bg=C_BG, fg=C_TEXT2, font=_FONT, wraplength=620,
                    justify="left", padx=6, pady=24).pack(anchor="w")
                return
            for entry in entries:
                self._build_vocab_card(self._vocab_inner, entry)
            self._vocab_canvas.configure(
                scrollregion=self._vocab_canvas.bbox("all"))
        except Exception as exc:
            tk.Label(self._vocab_inner, text=f"读取生词本失败：{exc}",
                     bg=C_BG, fg=C_REC, font=_FONT, padx=6, pady=24
                     ).pack(anchor="w")

    def _build_vocab_card(self, parent, entry: VocabEntry) -> None:
        """渲染一张生词卡片：词头 → 词形变换 → 近义对比 → 短语搭配。"""
        card = tk.Frame(parent, bg=C_CARD, highlightbackground=C_BORDER,
                        highlightthickness=1)
        card.pack(fill=tk.X, padx=2, pady=6, ipadx=14, ipady=12)

        # 词头行：词 / 音标 / 词性 / 释义 + 删除
        head = tk.Frame(card, bg=C_CARD)
        head.pack(fill=tk.X, padx=4, pady=(0, 6))
        tk.Label(head, text=entry.word, font=("Microsoft YaHei UI", 16, "bold"),
                 bg=C_CARD, fg=C_ACCENT).pack(side=tk.LEFT)
        sub = "   ".join(
            x for x in (entry.phonetic, entry.pos, entry.definition_zh) if x)
        tk.Label(head, text=sub, font=_FONT, bg=C_CARD, fg=C_TEXT2
                 ).pack(side=tk.LEFT, padx=(10, 0))
        del_btn = PillButton(
            head, text="🗑 删除", command=lambda eid=entry.id:
            self._delete_vocab(eid), kind="ghost", width=80, height=28,
            bg=C_CARD)
        del_btn.pack(side=tk.RIGHT)

        # 词形变换
        if entry.derivations:
            body = "\n".join(
                f"• {d.word}  [{d.pos}]  {d.definition_zh}"
                for d in entry.derivations)
            self._vocab_section(card, "词形变换", body)

        # 近义 / 同词性对比
        for g in entry.contrast:
            lines = []
            for it in g.items:
                lines.append(f"【{it.word}】（{g.pos}）")
                lines.append(f"    侧重：{it.focus}")
                lines.append(f"    语体：{it.register}　场景：{it.scene}")
                lines.append(f"    例：{it.example}")
            self._vocab_section(card, f"近义对比（{g.pos}）", "\n".join(lines))

        # 短语搭配
        if entry.phrases:
            lines = []
            for p in entry.phrases:
                lines.append(f"【{p.phrase}】{p.meaning_zh}")
                lines.append(f"    搭配：{p.structure}")
                lines.append(f"    例：{p.example}")
            self._vocab_section(card, "短语搭配", "\n".join(lines))

    def _vocab_section(self, parent, title: str, body: str) -> None:
        sec = tk.Frame(parent, bg=C_CARD)
        sec.pack(fill=tk.X, padx=4, pady=(2, 6))
        tk.Label(sec, text=title, font=_FONT_H2, bg=C_CARD,
                 fg=C_TEXT).pack(anchor="w")
        tk.Label(sec, text=body, font=_FONT, bg=C_CARD, fg=C_TEXT,
                 justify="left", wraplength=620, anchor="w"
                 ).pack(anchor="w", pady=(2, 0))

    def _delete_vocab(self, word_id: int) -> None:
        try:
            delete_word(self._vocab_db, word_id)
        except Exception as exc:
            if self._vocab_alive():
                self._vocab_status_var.set(f"删除失败：{exc}")
            return
        self._render_vocab_list()

    def _vocab_lookup(self) -> None:
        word = self._vocab_lookup_var.get().strip()
        if not word:
            self._vocab_status_var.set("请输入要查询的单词或短语")
            return
        if self.busy:
            return
        self._vocab_status_var.set(
            f"正在查询「{word}」…（需联网 / 通义 Key）")
        self._run_worker(self._vocab_lookup_worker, word)

    def _vocab_lookup_worker(self, word: str) -> None:
        try:
            client = self._build_llm()
            gen = VocabGenerator(client)
            entry = gen.generate(word)
        except Exception as exc:
            if self._vocab_alive():
                self._vocab_status_var.set(f"查询失败：{exc}")
            return
        try:
            save_word(self._vocab_db, entry)
        except Exception as exc:
            if self._vocab_alive():
                self._vocab_status_var.set(f"保存失败：{exc}")
            return
        self._ui(self._vocab_lookup_done, entry)

    def _vocab_lookup_done(self, entry: VocabEntry) -> None:
        if not self._vocab_alive():
            return
        self._vocab_lookup_var.set("")
        self._vocab_status_var.set(f"已收藏「{entry.word}」")
        self._vocab_sort_var.set("time")
        self._render_vocab_list()

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------
    def _on_close(self) -> None:
        if self.recording:
            try:
                self.recorder.cancel()
            except Exception:
                pass
        self._orb_stop()
        self.speaker.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    SpokenApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
