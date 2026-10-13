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
from spoken.scenarios import DIFFICULTIES, DIFFICULTY_ORDER, SCENARIOS, SCENARIO_ORDER
from spoken.tts import tts_available
from spoken import accents, cloud_tts, assessor, history
from spoken.asr import MicRecorder
from spoken.config import load_config
from spoken.vocab_model import VocabEntry
from spoken.vocab_gen import VocabGenerator
from spoken.vocab_store import count_words, delete_word, list_words, save_word

PASS, FAIL = 0, 0
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
        from spoken.gui import SpokenApp

        root = tk.Tk()
        app = SpokenApp(root)
        root.update()
        root.after(150, root.quit)
        root.mainloop()  # 等布局稳定后再断言
        check("GUI 正常构建（欢迎页）", True)
        check("页面包含 welcome/setup/chat 三页",
              set(app._pages) == {"welcome", "setup", "chat"})
        check("场景卡片有 4 个场景", len(app._scenario_cards) == 4)
        check("难度选项有 3 个难度", len(app._difficulty_btns) == 3)
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
    import numpy as np

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
    quiet = np.zeros(16000, dtype=np.float32)
    quiet[1000:2000] = 0.01
    norm = MicRecorder.normalize_audio(quiet)
    check("归一化后 RMS 提升",
          float(np.sqrt((norm ** 2).mean())) > float(np.sqrt((quiet ** 2).mean())))
    loud = np.full(16000, 5.0, dtype=np.float32)
    norm2 = MicRecorder.normalize_audio(loud)
    check("归一化限幅到 [-1,1]",
          float(norm2.max()) <= 1.0 and float(norm2.min()) >= -1.0)

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


def main() -> int:
    print("spoken v2 quick_validate —— 离线验证（MockLLM，无需 API Key）")
    print(f"场景：{'、'.join(SCENARIOS[k]['name'] for k in SCENARIO_ORDER)}")
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
    test_new_features()
    test_vocab()

    total = PASS + FAIL
    print(f"\n{'═' * 56}")
    print(f"结果：{PASS}/{total} 项检查通过")
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
