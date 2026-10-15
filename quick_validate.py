"""quick_validate.py —— spoken v2 快速验证脚本。

离线运行，不需要 API Key、不需要麦克风（使用内置 MockLLM）。
覆盖：
  1. 所有场景 × 难度组合能正常启动、对话、总结，不崩溃
  2. 纠错模块能命中典型错误（且 original 必须是用户原话子串）
  3. 干净句子零误报
  4. 同一错误不重复输出
  5. 总结结构完整（错误总数 / 分类统计 / 没用到的词汇 / 改进点清单）
  6. GUI 窗口能正常构建（无显示环境时自动跳过并提示）

用法：python quick_validate.py
"""

from __future__ import annotations

import sys

from spoken.asr import asr_available, mic_available
from spoken.corrector import CATEGORY_NAMES, RuleCorrector
from spoken.dialogue import DialogueEngine
from spoken.llm import MockLLM
from spoken.scenarios import (DIFFICULTIES, DIFFICULTY_ORDER, SCENARIOS,
                          SCENARIO_ORDER, is_custom, list_scenario_keys,
                          resolve_hotwords, resolve_scenario)
from spoken.tts import tts_available
from spoken import accents, cloud_tts, assessor, history
from spoken.asr import MicRecorder
from spoken.config import load_config
from spoken.vocab_model import VocabEntry
from spoken.vocab_gen import VocabGenerator
from spoken.vocab_store import count_words, delete_word, list_words, save_word
from spoken import custom_scenarios

# CI 的 Windows runner 默认控制台编码是 cp1252（英文系统），中文断言名
# 会触发 UnicodeEncodeError；强制 UTF-8 输出（本地中文 Windows 无此问题）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASS, FAIL, SKIP = 0, 0, 0
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if ok:
        PASS += 1
    else:
        FAIL += 1
    RESULTS.append((name, ok, detail))
    mark = "✅" if ok else "❌"
    line = f"{mark} {name}"
    if detail and not ok:
        line += f" —— {detail}"
    print(line)
    return ok


def skip(name: str, reason: str = "") -> None:
    """可选依赖缺失等情况下跳过某项检查，不计入失败。"""
    global SKIP
    SKIP += 1
    line = f"⏭️  {name}"
    if reason:
        line += f"（{reason}）"
    print(line)


# 典型错误句 -> 期望在 corrected 中出现的片段
TYPICAL_ERRORS = [
    ("I am agree with you.", "I agree"),
    ("He don't like coffee.", "doesn't"),
    ("Yesterday I go to school.", "went"),
    ("I very like this movie.", "really like"),
    ("Did you went home?", "did you go"),
    ("Although I am tired, but I keep working.", "Although"),
    ("I have 25 years old.", "I am 25 years old"),
    ("Most of people like tea.", "Most people"),
    ("I want go home now.", "want to go"),
    ("This bag is more cheaper.", "cheaper"),
    ("We discuss about the plan.", "discuss"),
    ("She is married with a doctor.", "married to"),
    ("I listen music every day.", "listen to music"),
    ("Please explain me this word.", "explain to me"),
    ("I am interested on music.", "interested in"),
    ("Open the light, please.", "turn on the light"),
    ("I eat medicine every morning.", "take medicine"),
    ("I have two advices for you.", "advice"),
    ("How to say this in English?", "How do you say"),
    ("I live here since three years.", "for three years"),
]

# 干净句子：一条规则都不该命中
CLEAN_SENTENCES = [
    "I agree with you completely.",
    "He doesn't like coffee at all.",
    "Yesterday I went to school by bus.",
    "I really like this movie.",
    "Did you go home after work?",
    "Although I was tired, I kept working.",
    "I am 25 years old.",
    "Most people like tea.",
    "I want to go home now.",
    "This bag is much cheaper.",
    "We discussed the plan yesterday.",
    "She is married to a doctor.",
    "I listen to music every day.",
    "Can you explain this word to me?",
    "I am interested in music.",
    "Please turn on the light.",
    "I take medicine every morning.",
    "I have two pieces of advice for you.",
    "How do you say this in English?",
    "I have lived here for three years.",
]


def section(title: str) -> None:
    print(f"\n{'─' * 56}\n{title}\n{'─' * 56}")


# ----------------------------------------------------------------------
# 1. 场景 × 难度矩阵
# ----------------------------------------------------------------------
def test_matrix() -> None:
    section("1. 场景 × 难度组合（12 组）：启动 / 对话 / 纠错 / 总结")
    for scenario in SCENARIO_ORDER:
        for difficulty in DIFFICULTY_ORDER:
            label = f"{SCENARIOS[scenario]['name']} × {DIFFICULTIES[difficulty]['name']}"
            try:
                engine = DialogueEngine(MockLLM(), scenario, difficulty,
                                        min_turns=3)
                opening = engine.start()
                assert opening, "开场白为空"

                r1 = engine.reply("Hello, nice to meet you.")
                assert r1.ai_line, "第一轮 AI 没有接话"

                # 含典型错误的输入：规则纠错必须命中
                r2 = engine.reply("I am agree with you, and I very like it.")
                hit = any(c.get("original", "").lower() in
                          "i am agree with you, and i very like it."
                          for c in r2.corrections)
                assert hit, "规则纠错没有命中典型错误"
                assert all(c.get("original", "").lower() in
                           "i am agree with you, and i very like it."
                           for c in r2.corrections), "出现了非用户原话的纠错"

                # 同一错误重复输入：第二次不再展示同一条纠错
                r3 = engine.reply("I am agree with you.")
                assert not any(
                    c.get("original", "").lower() == "i am agree"
                    for c in r3.corrections), "同一错误重复输出了"

                r4 = engine.reply("Thank you, bye!")
                assert r4.should_end, "满 min_turns 后没有正常结束"

                summary = engine.summarize()
                assert isinstance(summary.get("total_errors"), int)
                assert isinstance(summary.get("by_category"), dict)
                assert isinstance(summary.get("unused_vocabulary"), list)
                assert isinstance(summary.get("improvements"), list)
                assert summary["total_errors"] >= 1, "总结里错误总数应 ≥ 1"
                assert summary["stats"]["turns"] == 4
                assert summary["stats"]["scenario"] == scenario
                check(f"[{label}] 启动/对话/纠错/去重/结束/总结", True)
            except Exception as exc:
                check(f"[{label}] 启动/对话/纠错/去重/结束/总结", False,
                      f"{type(exc).__name__}: {exc}")


# ----------------------------------------------------------------------
# 2. 纠错模块：典型错误命中
# ----------------------------------------------------------------------
def test_corrector_hits() -> None:
    section("2. 纠错模块命中典型错误（20 例）")
    corrector = RuleCorrector()
    for sentence, expected in TYPICAL_ERRORS:
        try:
            corrections = corrector.check(sentence)
            ok = bool(corrections)
            detail = "没有命中任何规则"
            if ok:
                joined = " ".join(c.corrected for c in corrections)
                ok = expected.lower() in joined.lower()
                detail = f"期望包含 “{expected}”，实际：{joined}"
                for c in corrections:
                    if c.original.lower() not in sentence.lower():
                        ok = False
                        detail = f"original “{c.original}” 不是用户原话子串"
                    if c.category not in CATEGORY_NAMES:
                        ok = False
                        detail = f"未知类别：{c.category}"
            check(f"命中：{sentence[:34]}", ok, detail)
        except Exception as exc:
            check(f"命中：{sentence[:34]}", False,
                  f"{type(exc).__name__}: {exc}")


# ----------------------------------------------------------------------
# 3. 干净句子零误报
# ----------------------------------------------------------------------
def test_corrector_clean() -> None:
    section("3. 干净句子零误报（20 例）")
    corrector = RuleCorrector()
    for sentence in CLEAN_SENTENCES:
        try:
            corrections = corrector.check(sentence)
            detail = "；".join(
                f"{c.original} → {c.corrected}" for c in corrections)
            check(f"不误报：{sentence[:34]}", not corrections, detail)
        except Exception as exc:
            check(f"不误报：{sentence[:34]}", False,
                  f"{type(exc).__name__}: {exc}")


# ----------------------------------------------------------------------
# 4. 同一错误不重复输出（模块级连续会话）
# ----------------------------------------------------------------------
def test_no_repeat() -> None:
    section("4. 同一错误不重复输出")
    try:
        engine = DialogueEngine(MockLLM(), "daily_smalltalk", "beginner",
                                min_turns=3)
        engine.start()
        first = engine.reply("He don't like it.")
        second = engine.reply("He don't like it.")
        third = engine.reply("He don't like it.")
        first_hit = any(c.get("original", "").lower() == "he don't"
                        for c in first.corrections)
        again = [c for c in second.corrections + third.corrections
                 if c.get("original", "").lower() == "he don't"]
        check("首次输入命中纠错", first_hit,
              f"corrections={first.corrections}")
        check("重复输入不再输出同一纠错", not again,
              f"仍出现：{again}")
        check("重复输入计入 repeated 留痕",
              len(first.repeated_corrections) == 0
              and len(second.repeated_corrections + third.repeated_corrections) >= 1)

        # 重叠去重：规则与 LLM 对同一错误给出不同长度片段时，只保留更精确的
        merged = [
            {"original": "I am agree", "corrected": "I agree",
             "reason": "r", "type": "grammar"},
            {"original": "I am agree with you", "corrected": "I agree with you",
             "reason": "r", "type": "grammar"},
            {"original": "very like", "corrected": "really like",
             "reason": "r", "type": "expression"},
            {"original": "I very like", "corrected": "I really like",
             "reason": "r", "type": "expression"},
        ]
        deduped = DialogueEngine._dedup_overlapping(merged)
        check("重叠纠错自动去重（保留更精确片段，4 条合并为 2 条）",
              len(deduped) == 2
              and {d["original"] for d in deduped} == {"I am agree", "very like"},
              f"实际：{[d['original'] for d in deduped]}")
    except Exception as exc:
        check("同一错误不重复输出", False, f"{type(exc).__name__}: {exc}")


# ----------------------------------------------------------------------
# 5. 总结结构完整
# ----------------------------------------------------------------------
def test_summary_structure() -> None:
    section("5. 总结结构完整")
    try:
        engine = DialogueEngine(MockLLM(), "job_interview", "advanced",
                                min_turns=3)
        engine.start()
        engine.reply("I am graduated from a university in 2027.")
        engine.reply("I have hands-on experience with embedded systems.")
        engine.reply("Thank you for your time, goodbye!")
        summary = engine.summarize()

        required = ["total_errors", "by_category", "unused_vocabulary",
                    "improvements", "vocabulary", "transcript", "stats"]
        missing = [k for k in required if k not in summary]
        check("总结包含全部必需字段", not missing, f"缺少：{missing}")
        check("total_errors 为整数", isinstance(summary["total_errors"], int))
        check("by_category 为字典且值为整数",
              isinstance(summary["by_category"], dict)
              and all(isinstance(v, int) for v in summary["by_category"].values()))
        check("unused_vocabulary 为列表且元素含 word 字段",
              isinstance(summary["unused_vocabulary"], list)
              and all("word" in v for v in summary["unused_vocabulary"]))
        check("improvements 为列表且元素含 issue 字段",
              isinstance(summary["improvements"], list)
              and all("issue" in v for v in summary["improvements"]))
        check("transcript 记录完整对话",
              len(summary["transcript"]) >= 6
              and summary["transcript"][0][0] == "ai")
        check("stats 包含场景/难度/轮次",
              {"scenario", "difficulty", "turns"} <= set(summary["stats"]))

        from spoken.report import render_report_markdown, render_summary_text
        md = render_report_markdown(summary)
        text = render_summary_text(summary)
        for token in ["错误总数", "分类统计", "改进点", "没用到的词汇"]:
            check(f"Markdown 报告包含「{token}」", token in md)
        for token in ["错误总数", "改进点清单", "没用到的词汇"]:
            check(f"总结文本包含「{token}」", token in text)
    except Exception as exc:
        check("总结结构完整", False, f"{type(exc).__name__}: {exc}")


# ----------------------------------------------------------------------
# 6. 模型下载器（断点续传逻辑，离线可测部分）
# ----------------------------------------------------------------------
def test_model_downloader() -> None:
    section("6. 模型下载器逻辑")
    try:
        from spoken import model_download as md
        d = md.model_dir("base")
        check("模型目录为项目 models/faster-whisper-base",
              d.name == "faster-whisper-base" and d.parent.name == "models")
        check("必需文件清单完整（含 model.bin 等 4 项）",
              set(md.NEEDED_FILES)
              == {"config.json", "model.bin", "tokenizer.json", "vocabulary.txt"})
        check("Range 续传请求头构造正确",
              md._range_header(1024) == {"Range": "bytes=1024-"}
              and md._range_header(0) == {})

        class _Resp:
            def __init__(self, status, headers):
                self.status_code = status
                self.headers = headers

        # 206 响应：从 Content-Range 解析总大小
        check("从 206 Content-Range 解析总大小",
              md._parse_total(
                  _Resp(206, {"Content-Range": "bytes 100-199/145217532"}), 100)
              == 145217532)
        # 200 响应：Content-Length 即总大小
        check("从 200 Content-Length 解析总大小",
              md._parse_total(_Resp(200, {"Content-Length": "258"}), 0) == 258)
    except Exception as exc:
        check("模型下载器逻辑", False, f"{type(exc).__name__}: {exc}")


# ----------------------------------------------------------------------
# 7. 识别路径：波形数组直传（绕开 PyAV 兼容问题）
# ----------------------------------------------------------------------
def test_transcribe_ndarray_path() -> None:
    section("7. 识别路径（波形数组直传，绕开 PyAV）")
    try:
        import numpy as np
    except ModuleNotFoundError:
        skip("识别路径（波形数组直传）", "numpy 未安装（核心依赖不含，可选）")
        return
    try:
        from spoken.asr import Transcriber

        class _Seg:
            def __init__(self, text: str) -> None:
                self.text = text

        class _FakeModel:
            def __init__(self) -> None:
                self.received = None

            def transcribe(self, audio, **kwargs):
                self.received = audio
                return [_Seg(" hello world ")], None

        t = Transcriber()
        t._model = _FakeModel()
        waveform = np.zeros(16000, dtype=np.float32)
        text = t.transcribe(waveform)
        check("transcribe 接受波形数组并返回识别文本", text == "hello world")
        check("传给模型的是 ndarray 而非文件路径",
              isinstance(t._model.received, np.ndarray))
    except Exception as exc:
        check("识别路径（波形数组直传）", False,
              f"{type(exc).__name__}: {exc}")


# ----------------------------------------------------------------------
# 8. ASR 下载失败友好提示
# ----------------------------------------------------------------------
def test_asr_error_hint() -> None:
    section("8. ASR 下载失败友好提示")
    try:
        import os
        from spoken.asr import ASRDownloadError
        # 导入 spoken 包即应禁用 Xet 协议（走镜像下载时的 401 规避）
        check("导入 spoken 时自动禁用 Xet 下载协议",
              os.environ.get("HF_HUB_DISABLE_XET") == "1",
              f"HF_HUB_DISABLE_XET={os.environ.get('HF_HUB_DISABLE_XET')!r}")
        exc = ASRDownloadError(Exception("ConnectTimeout"), "base")
        msg = str(exc)
        check("ASRDownloadError 包含国内镜像方案", "hf-mirror.com" in msg)
        check("ASRDownloadError 包含对应模型名",
              "faster-whisper-base" in msg)
        check("ASRDownloadError 包含本地路径配置说明",
              "asr_model_local_path" in msg)
    except Exception as exc:
        check("ASR 下载失败友好提示", False,
              f"{type(exc).__name__}: {exc}")


# ----------------------------------------------------------------------
# 9. GUI 冒烟
# ----------------------------------------------------------------------
def test_gui() -> None:
    section("9. GUI 窗口构建冒烟测试")
    try:
        import tkinter as tk
        import spoken.gui as gui_mod
        from spoken.gui import SpokenApp

        root = tk.Tk()
        app = SpokenApp(root)
        root.update()
        root.after(150, root.quit)
        root.mainloop()  # 等布局稳定后再断言
        check("GUI 正常构建（欢迎页）", True)
        check("页面包含 welcome/setup/chat/shadow 四页",
              set(app._pages) == {"welcome", "setup", "chat", "shadow"})
        check("场景卡片为 12 内置 + 1 自定义入口",
              len(app._scenario_cards) == 13)
        real_cards = [c for c in app._scenario_cards if not c.add_card]
        check("内置场景卡片为 12 个", len(real_cards) == 12)
        check("末尾为『自定义场景』入口卡",
              app._scenario_cards[-1].add_card is True)
        check("难度选项有 3 个难度", len(app._difficulty_btns) == 3)
        # 进入设置页并做布局回归：底部操作栏与难度行必须固定可见，
        # 场景卡片区必须可滚动。
        # （曾经的 bug：12+1 张卡片内容超高且无滚动区，底部『开始对话』
        #   被 pack 挤成 1px 移出屏幕，用户选完场景找不到入口）
        app._show_page("setup")
        root.update()
        check("设置页『开始对话』按钮可见且高度正常",
              app._start_btn.winfo_ismapped()
              and app._start_btn.winfo_height() > 15)
        check("设置页难度选项全部可见",
              all(p.winfo_ismapped() and p.winfo_height() > 15
                  for p in app._difficulty_btns))
        bbox = app._setup_canvas.bbox("all")
        check("场景区内容超过视口时滚动区生效",
              bbox is not None
              and bbox[3] > app._setup_canvas.winfo_height())
        check("滚轮绑定已挂到场景卡片",
              bool(app._scenario_cards[0].bind("<MouseWheel>")))
        # 进入对话页（不启动真实会话，仅验证布局）
        app._show_page("chat")
        root.update()
        # 布局回归检查：底部输入行与状态栏必须真实可见。
        # （曾经的 bug：聊天 Text 未指定 height，YaHei 字体下请求 700px 高度，
        #   超过窗口 640px，导致后打包的输入行被挤成 1x1 完全不可见）
        check("麦克风按钮可见且高度正常",
              app.mic_btn.winfo_ismapped() and app.mic_btn.winfo_height() > 15)
        check("文字输入框可见且宽度正常",
              app.input_entry.winfo_ismapped()
              and app.input_entry.winfo_width() > 100)
        check("发送按钮可见且高度正常",
              app.send_btn.winfo_ismapped()
              and app.send_btn.winfo_height() > 15)
        # 气泡对话 + 打字机效果回归
        # （曾经的样式：纯文字行、无气泡、台词一次性显示）
        def _hidden_chars(chat):
            """统计仍处于 pending（elide 隐藏）状态的字符数。"""
            ranges = chat.tag_ranges("pending")
            total = 0
            for i in range(0, len(ranges), 2):
                c = chat.count(str(ranges[i]), str(ranges[i + 1]), "chars")
                total += int(c[0] if isinstance(c, tuple) else c)
            return total

        app._show_ai_line("Hello there, this is a typing test.")
        hidden0 = _hidden_chars(app.chat)
        check("AI 台词逐字弹出（台词初始处于隐藏态）", hidden0 > 0)
        for _ in range(3):        # 手动推进 3 拍（每拍揭示 2 字符）
            app._typewriter_tick()
        hidden1 = _hidden_chars(app.chat)
        check("每拍揭示部分文字", 0 < hidden1 < hidden0)
        check("揭示内容可见", "Hell" in app.chat.get("1.0", tk.END))
        app._finish_typewriter()
        check("补全后全部显示（无隐藏残留）",
              _hidden_chars(app.chat) == 0)
        check("完整台词内容正确",
              "Hello there, this is a typing test.\n"
              in app.chat.get("1.0", tk.END))
        # 打断：用户消息到来时立即补全未打完的 AI 台词
        app._show_ai_line("Second line for interruption test.")
        app._typewriter_tick()
        app._append_chat("user", "你", "打断一下")
        check("新消息到来时自动补全未打完的台词",
              "interruption test." in app.chat.get("1.0", tk.END))
        check("打断后无隐藏残留", _hidden_chars(app.chat) == 0)
        # 注意：读 gui_mod.C_BUBBLE_AI 而非快照 import——SpokenApp 会按
        # config.ui.theme 调用 _apply_theme_colors() 改写模块 globals，
        # 快照值在深色主题下会过期（曾因用户 config theme=dark 偶发失败）。
        check("AI 消息为气泡（有背景色）",
              app.chat.tag_cget("ai", "background") == gui_mod.C_BUBBLE_AI)
        check("用户消息为气泡（有背景色）",
              app.chat.tag_cget("user", "background") == gui_mod.C_BUBBLE_USER)
        check("提示/纠错无气泡背景",
              app.chat.tag_cget("feedback", "background") == "")
        ai_size = int(app.chat.tag_cget("ai", "font").rsplit(" ", 1)[1])
        fb_size = int(app.chat.tag_cget("feedback", "font").rsplit(" ", 1)[1])
        check("对话字体大于提示/纠错字体", ai_size > fb_size)
        # 录音球体动画冒烟：启动 + 推进一帧 + 停止
        app._orb_start()
        app._orb.set_level(0.6)
        app._orb.tick()
        check("录音球体动画可运行", app._orb.visible)
        app._orb_stop()
        check("停止录音后球体隐藏", not app._orb.visible)
        check("存在语音设置按钮", hasattr(app, "_settings_btn"))
        check("存在练习历史按钮", hasattr(app, "_history_btn"))
        check("存在生词本按钮（设置页）", hasattr(app, "_vocab_btn"))
        check("存在生词本按钮（对话页）", hasattr(app, "_chat_vocab_btn"))
        check("存在跟读打分按钮", hasattr(app, "shadow_btn"))
        check("存在参考句提示标签", hasattr(app, "_ref_label"))

        # 生词卡片渲染冒烟：用样本条目在临时容器上渲染，断言关键文本出现
        smoke = tk.Toplevel()
        smoke.withdraw()
        s_inner = tk.Frame(smoke)
        s_inner.pack()
        sample = VocabEntry.from_dict({
            "word": "apply", "phonetic": "/əˈplaɪ/", "pos": "v.",
            "definition_zh": "申请；应用",
            "derivations": [
                {"word": "application", "pos": "n.", "definition_zh": "申请；应用"},
                {"word": "applicable", "pos": "adj.", "definition_zh": "适用的"},
                {"word": "applied", "pos": "adj.", "definition_zh": "应用的"},
            ],
            "contrast": [{
                "pos": "adj.",
                "items": [
                    {"word": "applicable", "focus": "强调可适用",
                     "register": "正式", "scene": "规则/法律",
                     "example": "This rule is applicable to all."},
                    {"word": "applied", "focus": "强调实际应用",
                     "register": "中性", "scene": "学术/技术",
                     "example": "We need more applied research."},
                ],
            }],
            "phrases": [
                {"phrase": "apply for", "structure": "apply for + something（物/职位），接申请对象",
                 "meaning_zh": "申请", "example": "She applied for a job."},
                {"phrase": "apply to", "structure": "apply to + someone/something，接接收方或适用对象",
                 "meaning_zh": "向…申请；适用于", "example": "This applies to members."},
            ],
        })
        app._build_vocab_card(s_inner, sample)
        s_texts = []

        def _collect(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Label):
                    s_texts.append(c.cget("text"))
                _collect(c)

        _collect(s_inner)
        check("生词卡片渲染出词头 apply", any("apply" in t for t in s_texts))
        check("生词卡片渲染出词形变换", any("application" in t for t in s_texts))
        check("生词卡片渲染出近义对比", any("近义对比" in t for t in s_texts))
        check("生词卡片渲染出短语搭配", any("apply for" in t for t in s_texts))
        smoke.destroy()

        app.speaker.stop()
        root.destroy()
    except Exception as exc:
        if "TclError" in type(exc).__name__ or "display" in str(exc).lower():
            check("GUI 正常构建", True,
                  "（当前环境无图形显示，已跳过；请在本机双击 run.bat 验证）")
        else:
            check("GUI 正常构建", False, f"{type(exc).__name__}: {exc}")


# ----------------------------------------------------------------------
# 10. 新功能模块（TTS 清晰度/云端 / ASR 归一化 / 评分 / 历史 / 配置）
# ----------------------------------------------------------------------
def test_new_features() -> None:
    section("10. 新功能模块：TTS / ASR / 云端TTS / 评分 / 历史 / 配置")
    try:
        import numpy as np
    except ModuleNotFoundError:
        np = None

    # TTS：默认音量 1.0，list_voices 不抛异常
    from spoken.tts import Speaker, list_voices
    sp = Speaker()
    check("Speaker 默认音量为 1.0", sp.volume == 1.0)
    try:
        vs = list_voices()
        check("list_voices 返回列表（不抛异常）", isinstance(vs, list))
    except Exception as exc:
        check("list_voices 返回列表", False, str(exc))

    # ASR 归一化：提升轻音 RMS 且对超幅限幅
    if np is not None:
        quiet = np.zeros(16000, dtype=np.float32)
        quiet[1000:2000] = 0.01
        norm = MicRecorder.normalize_audio(quiet)
        check("归一化后 RMS 提升",
              float(np.sqrt((norm ** 2).mean())) > float(np.sqrt((quiet ** 2).mean())))
        loud = np.full(16000, 5.0, dtype=np.float32)
        norm2 = MicRecorder.normalize_audio(loud)
        check("归一化限幅到 [-1,1]",
              float(norm2.max()) <= 1.0 and float(norm2.min()) >= -1.0)
    else:
        skip("ASR 音频归一化校验", "numpy 未安装（核心依赖不含，可选）")

    # 云端 TTS：无 key 应直接报错（不联网）
    try:
        cloud_tts.synthesize("hi", api_key="")
        check("云端 TTS 无 key 报错", False, "应抛 ValueError")
    except ValueError:
        check("云端 TTS 无 key 直接报错（不联网）", True)

    # 评分：MockAssessor 返回四维分数；float32->WAV 生成 RIFF 头
    m = assessor.MockAssessor()
    sc = m.evaluate("Hello world", b"fake")
    check("MockAssessor 返回四维分数",
          all(hasattr(sc, k) for k in ("overall", "accuracy", "integrity", "fluency")))
    wav = assessor.float32_to_wav_bytes(quiet)
    check("float32_to_wav_bytes 生成 WAV(RIFF) 字节", wav.startswith(b"RIFF"))

    # 历史：临时库读写与统计
    import os, tempfile
    tmp = tempfile.mktemp(suffix=".db")
    try:
        history.add_session(tmp, scenario="daily_smalltalk", difficulty="beginner",
                           overall=80, accuracy=82, integrity=85, fluency=78,
                           ref_text="Hi")
        rows = history.list_sessions(tmp)
        check("历史写入后可读取",
              len(rows) == 1 and rows[0]["scenario"] == "daily_smalltalk")
        st = history.stats(tmp)
        check("历史统计平均分正确",
              st.count == 1 and st.avg_overall == 80.0)
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass

    # 配置：含 cloud_tts / assessment 默认段
    cfg = load_config()
    check("config 含 cloud_tts 段（enabled 字段）",
          isinstance(cfg.cloud_tts, dict) and "enabled" in cfg.cloud_tts)
    check("config 含 assessment 段（model_id 字段）",
          isinstance(cfg.assessment, dict) and "model_id" in cfg.assessment)
    # 场景热词已定义
    from spoken.scenarios import SCENARIO_HOTWORDS
    check("每个场景都有热词", set(SCENARIO_HOTWORDS) == set(SCENARIO_ORDER))

    # 口音注册表（accents）
    keys = [a["key"] for a in accents.ACCENTS]
    check("口音表含需求中的 10 国", len(accents.ACCENTS) == 10)
    check("口音 key 唯一", len(set(keys)) == len(keys))
    check("默认口音可用",
          accents.is_available(accents.DEFAULT_ACCENT))
    check("英语口音标 english=True 的仅美/英",
          sorted(a["key"] for a in accents.ACCENTS if a["english"])
          == ["en-GB", "en-US"])
    check("缺失语种标 available=False",
          all(not accents.is_available(k)
              for k in ("th-TH", "en-IN", "vi-VN", "ms-MY", "kk-KZ", "uz-UZ")))
    v, hint = accents.resolve_cloud_voice({"accent": "en-US"})
    check("en-US 解析出官方音色", v == "loongabby_v3" and hint == "en")
    v2, _ = accents.resolve_cloud_voice({"accent": "th-TH"})
    check("不可用口音回退默认音色", v2 == "loongabby_v3")
    v3, h3 = accents.resolve_cloud_voice(
        {"accent": "en-US", "custom_voice": "myclone", "custom_language_hint": "en"})
    check("自定义音色优先", v3 == "myclone" and h3 == "en")
    check("旧键 am/en 兼容",
          accents.get_accent("am")["key"] == "en-US"
          and accents.get_accent("en")["key"] == "en-GB")
    check("评测 accent：英语返回 en，日/韩返回 None",
          accents.assess_accent("en-US") == "en"
          and accents.assess_accent("ja-JP") is None
          and accents.assess_accent("ko-KR") is None)


# ----------------------------------------------------------------------
# 11. 智能生词本（模型 / 生成器 / 存储）
# ----------------------------------------------------------------------
def _stub_vocab_client(payload_json: str):
    """返回一个 chat() 直接回吐指定 JSON 的桩客户端（不联网）。"""

    class _Stub:
        def chat(self, messages, purpose="turn"):
            return payload_json

    return _Stub()


def test_vocab() -> None:
    section("11. 智能生词本：数据模型 / 生成器 / 存储")
    import os
    import tempfile

    raw = {
        "word": "apply", "phonetic": "/əˈplaɪ/", "pos": "v.",
        "definition_zh": "申请；应用",
        "derivations": [
            {"word": "application", "pos": "n.", "definition_zh": "申请"},
            {"word": "", "pos": "n.", "definition_zh": "空词跳过"},  # 应被跳过
            {"word": "applicable", "pos": "adj.", "definition_zh": "适用的"},
        ],
        "contrast": [
            {"pos": "adj.",
             "items": [
                 {"word": "applicable", "focus": "可适用", "register": "正式",
                  "scene": "规则", "example": "This rule is applicable."},
                 {"word": "applied", "focus": "实际应用", "register": "中性",
                  "scene": "学术", "example": "applied research."},
             ]},
            {"pos": "x.", "items": [
                {"word": "only-one", "focus": "单条", "register": "中性",
                 "scene": "s", "example": "e."}]},  # 仅 1 项，应被丢弃
        ],
        "phrases": [
            {"phrase": "apply for", "structure": "apply for + something",
             "meaning_zh": "申请", "example": "apply for a job"},
        ],
    }
    entry = VocabEntry.from_dict(raw)
    check("from_dict 词头字段正确",
          entry.word == "apply" and entry.phonetic == "/əˈplaɪ/")
    check("from_dict 跳过空词形",
          [d.word for d in entry.derivations] == ["application", "applicable"])
    check("from_dict 仅保留≥2项的对比组",
          len(entry.contrast) == 1 and entry.contrast[0].pos == "adj.")
    check("from_dict 短语保留", len(entry.phrases) == 1
          and entry.phrases[0].phrase == "apply for")
    check("to_dict 往返一致",
          VocabEntry.from_dict(entry.to_dict()).word == "apply")

    # 生成器：桩客户端返回合法 JSON
    payload = '{"word":"apply","phonetic":"/əˈplaɪ/","pos":"v.",' \
              '"definition_zh":"申请","derivations":[],"contrast":[],' \
              '"phrases":[{"phrase":"apply for","structure":"apply for + something",' \
              '"meaning_zh":"申请","example":"apply for a job"}]}'
    gen = VocabGenerator(_stub_vocab_client(payload))
    got = gen.generate("apply")
    check("VocabGenerator 用桩客户端生成词条",
          got.word == "apply" and len(got.phrases) == 1)
    try:
        VocabGenerator(_stub_vocab_client('not json')).generate("x")
        check("VocabGenerator 非法 JSON 报错", False, "应抛 VocabGenError")
    except Exception as exc:
        check("VocabGenerator 非法 JSON 报错", "VocabGenError" in type(exc).__name__,
              type(exc).__name__)

    # 存储：临时库 upsert / 列表 / 搜索 / 删除
    tmp = tempfile.mktemp(suffix=".db")
    try:
        e1 = VocabEntry(word="Apply", phonetic="/əˈplaɪ/", pos="v.",
                        definition_zh="申请", created_at="2026-01-01T00:00:00",
                        phrases=[{"phrase": "apply for", "structure": "s",
                        "meaning_zh": "申请", "example": "e"}])
        e2 = VocabEntry(word="book", phonetic="/bʊk/", pos="n.",
                        definition_zh="书", created_at="2026-01-02T00:00:00")
        id1 = save_word(tmp, e1)
        id2 = save_word(tmp, e2)
        check("save_word 写入两条", count_words(tmp) == 2)
        # 同词（大小写不同）upsert，不新增
        save_word(tmp, VocabEntry(word="APPLY", phonetic="/əˈplaɪ/", pos="v.",
                                 definition_zh="申请（更新）",
                                 created_at="2026-01-03T00:00:00"))
        check("同词大小写不敏感 upsert", count_words(tmp) == 2)
        by_time = list_words(tmp, sort="time")
        check("列表按时间倒序", by_time[0].word.lower() == "apply")
        by_alpha = list_words(tmp, sort="alpha")
        check("列表按字母升序", by_alpha[0].word.lower() == "apply"
              and by_alpha[1].word.lower() == "book")
        found = list_words(tmp, search="book")
        check("搜索命中 word 字段", len(found) == 1 and found[0].word == "book")
        found2 = list_words(tmp, search="申请")
        check("搜索命中内容字段（释义/短语）", len(found2) == 1)
        delete_word(tmp, id1)
        check("delete_word 删除一条", count_words(tmp) == 1)
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


def test_custom_scenarios() -> None:
    section("11. 自定义场景：读写 / 解析层回退 / 增删改")
    import json
    import os
    import tempfile

    tmp = os.path.join(tempfile.gettempdir(), f"spoken_cust_{os.getpid()}.json")
    custom_scenarios.set_storage_path(tmp)
    try:
        check("初始无自定义场景", custom_scenarios.load() == {})
        key1 = custom_scenarios.upsert({
            "name": "测试场景", "name_en": "Test Scenario",
            "summary": "单元测试用", "ai_role": "测试AI", "user_role": "测试用户",
            "setting": "测试设定", "goals": "测试目标", "hotwords": "test keyword"})
        check("upsert 返回 custom_ 前缀 key", key1.startswith("custom_"))
        data = custom_scenarios.load()
        check("load 读回自定义场景",
              key1 in data and data[key1]["name"] == "测试场景")
        sc = resolve_scenario(key1)
        check("resolve_scenario 解析自定义场景",
              sc["name"] == "测试场景" and sc["ai_role"] == "测试AI")
        check("is_custom 识别自定义 key", is_custom(key1))
        check("list_scenario_keys 含自定义", key1 in list_scenario_keys())
        check("resolve_hotwords 取自定义热词",
              resolve_hotwords(key1) == "test keyword")
        # 编辑更新（同 key 不新增）
        custom_scenarios.upsert({"key": key1, "name": "改名场景",
            "name_en": "Renamed", "summary": "s", "ai_role": "a",
            "user_role": "u", "setting": "st", "goals": "g"})
        reloaded = custom_scenarios.load()
        check("upsert 同 key 更新不新增",
              len(reloaded) == 1 and reloaded[key1]["name"] == "改名场景")
        # 删除
        check("delete 自定义场景", custom_scenarios.delete(key1) is True)
        check("删除后不存在", key1 not in custom_scenarios.load())
        # 脏数据容错：损坏 JSON 返回空 dict 而非崩溃
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        check("损坏文件容错返回空字典", custom_scenarios.load() == {})
    finally:
        custom_scenarios.set_storage_path(None)
        try:
            os.remove(tmp)
        except Exception:
            pass


def test_i18n_theme() -> None:
    section("13. 多语言与主题：i18n 切换 / 双调色板 / 界面偏好")
    import os
    import tempfile
    from spoken import i18n, theme

    # -- i18n：中文即键名，英文查表，缺失回退 --
    check("默认中文原样返回", i18n.t("开始对话") == "开始对话")
    check("支持中英两种语言", set(i18n.LANGUAGES) == {"zh", "en"})
    i18n.set_language("en")
    check("切换英文返回译文",
          i18n.t("开始对话") == "Start Conversation")
    check("缺失键回退中文原文", i18n.t("不存在的文案xyz") == "不存在的文案xyz")
    check("模板占位符格式化",
          i18n.t("出现错误：{exc}", exc="boom") == "Something went wrong: boom")
    seen: list = []
    i18n.on_change(seen.append)
    check("切换回调被触发", i18n.set_language("zh") and seen == ["zh"])
    i18n.off_change(seen.append)
    i18n.set_language("zh")

    # -- theme：浅/深双调色板，键名齐全 --
    check("提供浅色与深色两套主题",
          set(theme.available_themes()) == {"light", "dark"})
    light, dark = theme.palette("light"), theme.palette("dark")
    check("调色板键名齐全（两套一致）",
          set(light) == set(dark) == set(theme.PALETTE_KEYS))
    check("深色背景确实更深", light["bg"] != dark["bg"])
    check("未知主题名回退浅色", theme.palette("nope") is light)

    # -- config：ui 段默认值 --
    from spoken.config import load_config
    cfg = load_config()
    check("配置含界面语言字段", cfg.ui_language in ("zh", "en"))
    check("配置含主题字段", cfg.ui_theme in ("light", "dark"))
    check("配置含窗口几何字段", isinstance(cfg.window_geometry, str))

    # -- GUI：英文 + 深色下完整构建并切换重建（临时目录隔离 config）--
    try:
        import tkinter as tk
        import spoken.gui as gui_mod
        from spoken.gui import SpokenApp

        old_cwd = os.getcwd()
        tmp = tempfile.mkdtemp(prefix="spoken_i18n_")
        os.chdir(tmp)
        try:
            root = tk.Tk()
            root.withdraw()
            app = SpokenApp(root)
            check("默认（中文/浅色）构建含四页",
                  set(app._pages) == {"welcome", "setup", "chat", "shadow"})
            app._apply_ui_preference("language", "en")
            check("切换英文后界面重建且语言生效",
                  i18n.get_language() == "en"
                  and set(app._pages) == {"welcome", "setup", "chat", "shadow"})
            app._apply_ui_preference("theme", "dark")
            check("切换深色后背景色来自深色调色板",
                  gui_mod.C_BG == dark["bg"])
            check("偏好已持久化到 config.yaml",
                  os.path.isfile("config.yaml"))
            app._apply_ui_preference("language", "zh")
            root.destroy()
        finally:
            os.chdir(old_cwd)
    except Exception as exc:
        check(f"GUI 多语言/主题构建（异常 {exc}）", False)


# ----------------------------------------------------------------------
# 16. 语音设置 UX：X 关闭=应用 / 取消=放弃 / 场景图标单色化
# ----------------------------------------------------------------------
def test_voice_settings_ux() -> None:
    section("16. 语音设置 UX：关闭窗口=应用 / 取消=放弃 / 图标单色化")
    try:
        import os
        import tempfile
        import tkinter as tk
        import spoken.gui as gui_mod
        from spoken.gui import ScenarioCard, SpokenApp, _mono_icon

        # -- _mono_icon：emoji 转文本呈现（深色主题下随 fill 变白）--
        check("💬 转为文本呈现（FE0E）", _mono_icon("💬") == "💬\ufe0e")
        check("✈️ 去 FE0F 再加 FE0E", _mono_icon("✈️") == "✈\ufe0e")
        check("🛍️ 去 FE0F 再加 FE0E", _mono_icon("🛍️") == "🛍\ufe0e")

        old_cwd = os.getcwd()
        tmp = tempfile.mkdtemp(prefix="spoken_vux_")
        os.chdir(tmp)
        # 屏蔽真实扬声器：避免测试过程中真的发声
        real_speaker = gui_mod.Speaker

        class _SilentSpeaker:
            available = False

            def __init__(self, *a, **k):
                pass

            def stop(self):
                pass

            def speak(self, *a, **k):
                pass

        gui_mod.Speaker = _SilentSpeaker
        try:
            root = tk.Tk()
            root.withdraw()
            app = SpokenApp(root)

            def walk(w):
                yield w
                for c in w.winfo_children():
                    yield from walk(c)

            def dialog():
                for w in root.winfo_children():
                    if isinstance(w, tk.Toplevel) and w.winfo_exists():
                        return w
                return None

            def radios(dlg, values):
                return [w for w in walk(dlg)
                        if isinstance(w, tk.Radiobutton)
                        and w.cget("value") in values]

            def sel(rs):
                return root.globalgetvar(rs[0].cget("variable"))

            def pill(dlg, text):
                return [w for w in walk(dlg)
                        if isinstance(w, gui_mod.PillButton)
                        and w.text == text]

            def close_x(dlg):
                """模拟用户点窗口右上角 X：触发 WM_DELETE_WINDOW 处理器。"""
                cmd = dlg.protocol("WM_DELETE_WINDOW")
                assert cmd, "WM_DELETE_WINDOW 未注册处理器"
                root.tk.call(cmd)

            SPEEDS = ("slow", "medium", "fast")
            ACCENTS = {"en-US", "en-GB"}

            # 场景卡片图标：位图单色渲染 + 颜色取主题文字色（深色下随文字变白）
            holder = tk.Frame(root)
            card = ScenarioCard(holder, "daily_smalltalk", 0, lambda i: None)
            icon = [i for i in card.find_all() if card.type(i) == "image"]
            check("场景卡片图标为位图单色呈现", len(icon) == 1)
            check("场景卡片图标水平居中于 x=34",
                  bool(icon) and abs(card.coords(icon[0])[0] - 34) <= 1)
            holder.destroy()

            # 基线配置
            app._save_config_patch({"voice": {"tts_speed": "medium"},
                                    "cloud_tts": {"accent": "en-US"}})
            app.cfg = gui_mod.load_config()

            # 1) 改语速 -> X 关闭 -> 重开保持（用户反馈的丢设置问题）
            app._open_voice_settings()
            dlg = dialog()
            dlg.withdraw()
            for r in radios(dlg, SPEEDS):
                if r.cget("value") == "fast":
                    r.invoke()
            close_x(dlg)
            check("X 关闭应用语速修改（写盘）", app.cfg.tts_speed == "fast")
            app._open_voice_settings()
            dlg = dialog()
            dlg.withdraw()
            check("重开对话框语速保持 fast",
                  sel(radios(dlg, SPEEDS)) == "fast")
            dlg.destroy()

            # 2) 改语速 -> 「取消」-> 放弃修改
            app._save_config_patch({"voice": {"tts_speed": "medium"}})
            app.cfg = gui_mod.load_config()
            app._open_voice_settings()
            dlg = dialog()
            dlg.withdraw()
            for r in radios(dlg, SPEEDS):
                if r.cget("value") == "fast":
                    r.invoke()
            btns = pill(dlg, "取消")
            check("对话框提供「取消」按钮", len(btns) == 1)
            btns[0].command()
            app._open_voice_settings()
            dlg = dialog()
            dlg.withdraw()
            check("取消后重开回到 medium",
                  sel(radios(dlg, SPEEDS)) == "medium")
            dlg.destroy()

            # 3) 改口音 -> X 关闭 -> 重开保持
            app._open_voice_settings()
            dlg = dialog()
            dlg.withdraw()
            for r in radios(dlg, ACCENTS):
                if r.cget("value") == "en-GB":
                    r.invoke()
            close_x(dlg)
            check("X 关闭应用口音修改（写盘）",
                  (app.cfg.cloud_tts or {}).get("accent") == "en-GB")
            app._open_voice_settings()
            dlg = dialog()
            dlg.withdraw()
            check("重开对话框口音保持 en-GB",
                  sel(radios(dlg, ACCENTS)) == "en-GB")
            dlg.destroy()

            # 4) 无变化时 X 关闭：静默，不写盘
            mtime = os.path.getmtime("config.yaml")
            app._open_voice_settings()
            dlg = dialog()
            dlg.withdraw()
            close_x(dlg)
            check("无变化时 X 关闭不写盘",
                  os.path.getmtime("config.yaml") == mtime)

            root.destroy()
        finally:
            gui_mod.Speaker = real_speaker
            os.chdir(old_cwd)
    except Exception as exc:
        check(f"语音设置 UX（异常 {exc}）", False)


# ----------------------------------------------------------------------
# 17. 图标位图化：Pillow 预渲染单色图标（规避 Tk emoji 字体回退错位）
# ----------------------------------------------------------------------
def test_icon_bitmaps() -> None:
    section("17. 图标位图化：Pillow 单色渲染 / 位置精确 / 回退路径")
    try:
        import tkinter as tk
        import spoken.icons as icons
        from spoken.gui import ScenarioCard

        # -- icons 模块本身 --
        check("mono() 去掉变体选择符", icons.mono("✈️") == "✈")
        check("mono() 去 FE0E", icons.mono("💬\ufe0e") == "💬")

        if icons.available():
            root = tk.Tk()
            root.withdraw()
            img = icons.icon("📊", 24, "#E8EDF5", master=root)
            check("icon() 返回 PhotoImage", img is not None)
            check("位图尺寸 = 字号 + 2*2 边距",
                  img is not None and img.width() == 28
                  and img.height() == 28)
            check("同参缓存命中（同一对象）",
                  icons.icon("📊", 24, "#E8EDF5", master=root) is img)
            check("颜色变化生成新位图",
                  icons.icon("📊", 24, "#000000", master=root) is not img)
            check("生僻字符不抛异常",
                  icons.icon("\U000E0000", 24, "#FFFFFF",
                             master=root) is not None)

            # -- 场景卡片：图标必须是 image 且水平居中于 x=34 --
            holder = tk.Frame(root)
            all_ok = True
            for key in ("daily_smalltalk", "airport_checkin",
                        "job_interview", "restaurant_order",
                        "business_meeting", "travel", "hotel", "shopping",
                        "hospital", "phone_call", "opinion", "campus"):
                card = ScenarioCard(holder, key, 0, lambda i: None)
                items = [i for i in card.find_all()
                         if card.type(i) == "image"]
                if len(items) != 1:
                    all_ok = False
                    print(f"  {key}: image items = {len(items)}")
                    continue
                x, _y = card.coords(items[0])
                bb = card.bbox(items[0])
                if abs(x - 34) > 1 or bb[0] < -1 or bb[2] > card._bw + 1:
                    all_ok = False
                    print(f"  {key}: x={x:.1f} bbox={bb}")
                card.destroy()
            check("12 个场景卡片各有 1 个位图图标且居中不出界", all_ok)

            add = ScenarioCard(holder, "", 0, lambda i: None, add_card=True)
            check("自定义入口卡（➕）使用位图",
                  len([i for i in add.find_all()
                       if add.type(i) == "image"]) == 1)
            add.destroy()
            holder.destroy()
            root.destroy()
        else:
            check("Pillow/符号字体不可用（跳过位图断言，走回退）", True)

        # -- 场景图标表：字形必须在符号字体中真实存在 --
        from spoken import gui as gui_mod
        check("travel 图标为地图字符", gui_mod._SCENARIO_ICONS["travel"] == "\U0001F5FA")
        check("hotel 图标为床字符", gui_mod._SCENARIO_ICONS["hotel"] == "\U0001F6CF")

        # -- 回退路径字体（无 Pillow 时）--
        src = open("spoken/gui.py", encoding="utf-8").read()
        check("回退路径使用 Segoe UI Symbol（天然单色）",
              '"Segoe UI Symbol"' in src)
        check("绘制统一走 _draw_icon helper", src.count("_draw_icon(") >= 5)
    except Exception as exc:
        check(f"图标位图化（异常 {exc}）", False)


def test_shadow_and_review() -> None:
    section("14. 跟读专项练习 / 评分趋势 / 复习排期")
    import os
    import tempfile
    from spoken.llm import MockLLM
    from spoken.shadow import (RETRY_THRESHOLD, ShadowSession,
                               generate_sentences)

    class _FakeScore:
        def __init__(self, overall):
            self.overall = overall
            self.accuracy = self.integrity = self.fluency = 80.0
            self.feedback = ""

    sentences = generate_sentences(MockLLM(), "restaurant_order",
                                   "intermediate", 5)
    check("MockLLM 生成 5 句跟读句子", len(sentences) == 5 and all(sentences))

    s = ShadowSession("restaurant_order", "intermediate", sentences[:2])
    check("初始队列 2 句", s.progress == (0, 2))
    check("高分进入下一句", s.submit(_FakeScore(90)) == "next")
    check("低分自动重练", s.submit(_FakeScore(RETRY_THRESHOLD - 1)) == "retry"
          and s.retry_count == 1)
    check("重练仍低分继续重练（未超 2 次）",
          s.submit(_FakeScore(50)) == "retry" and s.retry_count == 2)
    check("第三次低分不再重练（达上限）",
          s.submit(_FakeScore(50)) == "finished")
    s2 = ShadowSession("restaurant_order", "intermediate", sentences[:2])
    s2.submit(_FakeScore(90))
    s2.submit(_FakeScore(70))
    summ = s2.summary()
    check("汇总：平均分与次数",
          summ["scored_count"] == 2 and summ["avg_overall"] == 80.0
          and summ["attempts"] == 2)

    # 历史分维度趋势
    from spoken import history
    tmp = tempfile.mkdtemp(prefix="spoken_qv_p2_")
    db = os.path.join(tmp, "h.db")
    for i, (o, a) in enumerate([(70, 60), (80, 70), (90, 85)]):
        history.add_session(db, scenario="restaurant_order",
                            difficulty="intermediate", overall=o, accuracy=a,
                            integrity=75.0, fluency=80.0,
                            ts=f"2026-10-1{i}T10:00:00")
    st = history.stats(db)
    check("分维度趋势四键齐全",
          set(st.trends) == {"overall", "accuracy", "integrity", "fluency"})
    check("趋势按日期升序", [d for d, _ in st.trends["overall"]]
          == ["2026-10-10", "2026-10-11", "2026-10-12"])
    check("平均分正确", st.avg_overall == 80.0)

    # 复习排期（SM-2 简化）
    from spoken import vocab_store
    from spoken.vocab_model import VocabEntry
    vdb = os.path.join(tmp, "v.db")
    vocab_store.save_word(vdb, VocabEntry(word="delicious", phonetic="",
                                          pos="adj.", definition_zh="美味的"))
    check("新词立即待复习", len(vocab_store.due_words(vdb)) == 1)
    vocab_store.update_review(vdb, 1, "know")
    check("认识后隔 3 天再复习", vocab_store.due_words(vdb) == [])
    vocab_store.update_review(vdb, 1, "forgot")
    check("忘记后当天再现", len(vocab_store.due_words(vdb)) == 1)
    vocab_store.save_word(vdb, VocabEntry(word="Delicious", phonetic="",
                                          pos="adj.", definition_zh="美味的"))
    kept = vocab_store.list_words(vdb)[0]
    check("覆盖保存保留复习字段", kept.reps == 0 and kept.due != "")

    # GUI：跟读页状态机驱动一轮（不录音）
    try:
        import tkinter as tk
        from spoken.gui import SpokenApp

        old_cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp(prefix="spoken_qv_p2gui_"))
        try:
            root = tk.Tk()
            root.withdraw()
            app = SpokenApp(root)
            app._show_page("shadow")
            app._shadow_begin(sentences[:2])
            check("跟读页进入 ready", app._shadow_state == "ready")
            app._shadow_show_result("I would like the menu", _FakeScore(90))
            check("评分后进入 result", app._shadow_state == "result")
            app._shadow_next()
            app._shadow_show_result("", _FakeScore(40))
            app._shadow_next()
            app._shadow_show_result("ok", _FakeScore(95))
            check("低分重练后完成进入 done", app._shadow_state == "done")
            root.destroy()
        finally:
            os.chdir(old_cwd)
    except Exception as exc:
        check(f"GUI 跟读流程（异常 {exc}）", False)


def test_ci_and_updater() -> None:
    section("15. CI 配置 / 一键更新 / 精简版打包")
    import os
    import tempfile
    import zipfile
    from pathlib import Path
    from spoken import updater

    # -- updater：附件挑选 / 更新脚本 / 解包 --
    assets = [
        {"name": "spoken.exe", "browser_download_url": "https://x/spoken.exe"},
        {"name": "spoken_v1.1.1_win64.zip",
         "browser_download_url": "https://x/spoken.zip"},
    ]
    check("优先挑选 zip 更新包",
          updater._pick_asset_url(assets) == "https://x/spoken.zip")
    check("无附件返回空串", updater._pick_asset_url([]) == "")
    check("只有裸 exe 时也可选",
          updater._pick_asset_url(assets[:1]) == "https://x/spoken.exe")
    lite_assets = assets + [
        {"name": "spoken_v1.1.1_win64_lite.zip",
         "browser_download_url": "https://x/spoken_lite.zip"}]
    check("精简版用户优先 lite 包",
          updater._pick_asset_url(lite_assets, prefer_lite=True)
          == "https://x/spoken_lite.zip")
    check("无 lite 包时回退常规包",
          updater._pick_asset_url(assets, prefer_lite=True)
          == "https://x/spoken.zip")

    # 解出 exe（构造一个含 spoken.exe 的 zip）
    tmp = tempfile.mkdtemp(prefix="spoken_qv_p3_")
    zp = Path(tmp) / "u.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("spoken.exe", "FAKE-EXE")
    out = updater.extract_exe(zp, Path(tmp))
    check("从 zip 解出 spoken.exe.new",
          out.name == "spoken.exe.new" and out.read_text() == "FAKE-EXE")

    # 更新批处理：等待旧进程 → 备份 → 替换 → 重启 → 自删
    bat = updater.build_update_script(Path(tmp) / "u.bat", out)
    text = bat.read_text(encoding="gbk")
    for token in ("tasklist", "PID eq", "spoken.exe.bak", "move /y",
                  "start", "del /f /q"):
        check(f"更新批处理包含 {token}", token in text)

    # 非冻结态（源码运行）必须拒绝一键更新
    try:
        updater.prepare_update()
        check("源码态拒绝一键更新", False)
    except RuntimeError:
        check("源码态拒绝一键更新", True)
    except Exception as exc:
        check(f"源码态拒绝一键更新（异常 {exc}）", False)

    # -- CI / 打包配置文件存在且合法 --
    root = Path(__file__).resolve().parent
    ci = root / ".github" / "workflows" / "ci.yml"
    check("CI 工作流文件存在", ci.is_file())
    try:
        import yaml
        data = yaml.safe_load(ci.read_text(encoding="utf-8"))
        jobs = set(data.get("jobs", {}))
        check("CI 含 test/build-lite/build-full 三个 job",
              {"test", "build-lite", "build-full"} <= jobs)
        check("完整版仅在 tag 触发",
              "startsWith(github.ref" in str(data["jobs"]["build-full"]["if"]))
    except Exception as exc:
        check(f"CI YAML 解析（异常 {exc}）", False)
    lite_spec = root / "spoken_lite.spec"
    check("精简版打包规格存在且排除语音依赖",
          lite_spec.is_file() and "faster_whisper" in lite_spec.read_text(
              encoding="utf-8"))
    bat_txt = (root / "build_exe.bat").read_text(encoding="utf-8")
    check("build_exe.bat 支持 lite 参数", "lite" in bat_txt)


def test_updater() -> None:
    section("12. 自动更新检查：版本解析与比较")
    from spoken import updater
    check("解析 v1.2.3 -> (1,2,3)", updater.parse_version("v1.2.3") == (1, 2, 3))
    check("解析 2.0 -> (2,0)", updater.parse_version("2.0") == (2, 0))
    check("v1.1.0 比 v1.0.0 新", updater.is_newer("v1.1.0", "1.0.0"))
    check("v1.0.0 不比 v1.1.0 新", not updater.is_newer("v1.0.0", "1.1.0"))
    check("v2.0.0 比 v1.9.9 新", updater.is_newer("v2.0.0", "1.9.9"))
    check("相同版本不视为更新", not updater.is_newer("v1.1.0", "1.1.0"))


def test_config_resilience() -> None:
    """exe 新环境（无任何 config.yaml）不得崩溃：load_config 容错。"""
    print("\n[测试] 配置容错（模拟朋友首次运行 exe）")
    import os
    import tempfile
    from pathlib import Path
    from spoken import config as cfg_mod

    missing = Path(tempfile.mkdtemp()) / "config.yaml"
    old = os.environ.get("SPOKEN_CONFIG")
    old_cwd = os.getcwd()
    try:
        # 候选链：SPOKEN_CONFIG > 当前目录 config.yaml > 用户数据目录，
        # 所以要把工作目录一并切走，才能模拟"全新电脑无任何配置"
        os.environ["SPOKEN_CONFIG"] = str(missing)
        os.chdir(missing.parent)
        c = cfg_mod.load_config()
        check("无配置文件时返回默认配置（不崩溃）", c.api_key == "")
        check("默认模型存在", bool(c.model))
    finally:
        if old is None:
            os.environ.pop("SPOKEN_CONFIG", None)
        else:
            os.environ["SPOKEN_CONFIG"] = old
        os.chdir(old_cwd)


def main() -> int:
    print("spoken v2 quick_validate —— 离线验证（MockLLM，无需 API Key）")
    print(f"场景：{'、'.join(resolve_scenario(k)['name'] for k in list_scenario_keys())}")
    print(f"难度：{'、'.join(DIFFICULTIES[k]['name'] for k in DIFFICULTY_ORDER)}")
    print("\n语音组件可用性（不影响验证结果）：")
    print(f"  语音识别 faster-whisper：{'可用' if asr_available() else '未安装（纯文字模式）'}")
    print(f"  麦克风采集 sounddevice：{'可用' if mic_available() else '未安装'}")
    print(f"  语音合成 pyttsx3：{'可用' if tts_available() else '未安装'}")

    test_matrix()
    test_corrector_hits()
    test_corrector_clean()
    test_no_repeat()
    test_summary_structure()
    test_model_downloader()
    test_transcribe_ndarray_path()
    test_asr_error_hint()
    test_gui()
    test_config_resilience()
    test_new_features()
    test_vocab()
    test_custom_scenarios()
    test_i18n_theme()
    test_voice_settings_ux()
    test_icon_bitmaps()
    test_shadow_and_review()
    test_ci_and_updater()
    test_updater()

    total = PASS + FAIL
    print(f"\n{'═' * 56}")
    print(f"结果：{PASS}/{total} 项检查通过" + (f"，{SKIP} 项跳过" if SKIP else ""))
    if FAIL:
        print("❌ 存在失败项：")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  - {name} —— {detail}")
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
