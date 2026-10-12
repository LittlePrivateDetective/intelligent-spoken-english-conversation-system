"""命令行入口：场景/难度选择、对话循环、反馈与报告渲染。"""

from __future__ import annotations

import argparse
import sys

import yaml

from . import __version__
from .config import load_config
from .dialogue import DialogueEngine, TurnResult
from .llm import LLMError, MockLLM, OpenAICompatibleLLM
from .report import render_report_markdown, save_report
from .scenarios import DIFFICULTIES, DIFFICULTY_ORDER, SCENARIOS, SCENARIO_ORDER

HELP_TEXT = """可用命令：
  /quit   结束对话并生成本次总结
  /hint   请求 AI 给一句提示（卡壳时用）
  /level  查看当前难度与练习统计
  /help   显示本帮助"""


def _ensure_utf8_output() -> None:
    """Windows 控制台默认编码可能不支持 emoji，尽量切换到 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def _out(message: str = "") -> None:
    print(message)


def _choose(prompt: str, options: dict, order: list, labels: dict) -> str:
    _out(prompt)
    for index, key in enumerate(order, 1):
        _out(f"  {index}. {labels[key]}")
    while True:
        try:
            choice = input("请输入序号 > ").strip()
        except (EOFError, KeyboardInterrupt):
            _out("")
            raise SystemExit(0) from None
        if choice.isdigit() and 1 <= int(choice) <= len(order):
            return order[int(choice) - 1]
        if choice in options:
            return choice
        _out("  输入无效，请重新输入序号。")


def choose_scenario() -> str:
    labels = {k: f"{v['name']}（{v['name_en']}）—— {v['summary']}"
              for k, v in SCENARIOS.items()}
    return _choose("请选择练习场景：", SCENARIOS, SCENARIO_ORDER, labels)


def choose_difficulty() -> str:
    labels = {k: f"{v['name']}（CEFR {v['cefr']}）"
              for k, v in DIFFICULTIES.items()}
    return _choose("请选择难度等级：", DIFFICULTIES, DIFFICULTY_ORDER, labels)


# ----------------------------------------------------------------------
# 渲染
# ----------------------------------------------------------------------
def _render_feedback(result: TurnResult) -> None:
    if result.corrections or result.alternatives:
        _out("  " + "─" * 52)
        for item in result.corrections:
            _out(f"  ✏️  纠错：{item.get('original', '')}  →  "
                 f"{item.get('corrected', '')}")
            reason = item.get("reason", "")
            if reason:
                _out(f"      原因：{reason}")
        if result.alternatives:
            _out("  💡 更地道的说法：")
            for line in result.alternatives:
                _out(f"      · {line}")
        _out("  " + "─" * 52)
    if result.stuck and result.hint:
        _out(f"  💡 卡壳提示：{result.hint}")
    if result.difficulty_changed:
        old, new = result.difficulty_changed
        _out(f"  📈 难度调整：{DIFFICULTIES[old]['name']} → "
             f"{DIFFICULTIES[new]['name']}")


def _render_report(report: dict) -> None:
    scores = report.get("scores", {}) or {}
    _out("")
    _out("═" * 56)
    _out("📋 本次对话总结")
    _out("═" * 56)
    if report.get("overall"):
        _out(f"\n{report['overall']}")
    if scores:
        _out("\n能力评分：" + "  ".join(
            f"{_SCORE_LABEL.get(key, key)} {value}/10"
            for key, value in scores.items()))
    vocab = report.get("vocabulary") or []
    if vocab:
        _out("\n📚 生词本：")
        for item in vocab:
            _out(f"  · {item.get('word', '')} —— {item.get('meaning_zh', '')}")
            if item.get("example"):
                _out(f"      例句：{item['example']}")
    improvements = report.get("improvements") or []
    if improvements:
        _out("\n🔧 改进点：")
        for index, item in enumerate(improvements, 1):
            _out(f"  {index}. {item.get('issue', '')}：{item.get('suggestion', '')}")
    suggestions = report.get("suggestions") or []
    if suggestions:
        _out("\n🏋️ 练习建议：")
        for tip in suggestions:
            _out(f"  · {tip}")
    if report.get("encouragement"):
        _out(f"\n💪 {report['encouragement']}")
    _out("═" * 56)


_SCORE_LABEL = {
    "fluency": "流利度",
    "grammar": "语法",
    "vocabulary": "词汇",
    "appropriateness": "得体度",
}


# ----------------------------------------------------------------------
# 对话主循环
# ----------------------------------------------------------------------
def _run_dialogue(engine: DialogueEngine, max_turns: int) -> dict | None:
    scenario = SCENARIOS[engine.scenario_key]
    difficulty = DIFFICULTIES[engine.difficulty]
    _out(f"\n场景：{scenario['name']}｜难度：{difficulty['name']}｜"
         f"你的角色：{scenario['user_role']}｜AI 角色：{scenario['ai_role']}")
    _out("输入 /help 查看命令，/quit 结束对话\n")

    try:
        opening = engine.start()
    except LLMError as exc:
        _out(f"⚠️ 模型调用失败：{exc}")
        _out("请检查网络与 API 配置后重试。")
        return None
    _out(f"{scenario['ai_role']}: {opening}")

    while True:
        if engine.turn >= max_turns:
            _out(f"\n（已达到最大对话轮数 {max_turns}，自动收尾）")
            break
        try:
            user_input = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            _out("")
            break

        if not user_input:
            _out("  （输入为空，直接用英语说就好；/help 查看命令）")
            continue

        if user_input.startswith("/"):
            command = user_input.lower()
            if command == "/quit":
                break
            if command == "/help":
                _out(HELP_TEXT)
                continue
            if command == "/level":
                _out(f"  当前难度：{DIFFICULTIES[engine.difficulty]['name']}，"
                     f"已聊 {engine.turn} 轮，纠错 {engine.correction_count} 处")
                continue
            if command == "/hint":
                # 把“请求提示”翻译成一句自然的英语，让 AI 按规则给出提示
                user_input = "Sorry, I'm stuck. Could you give me a hint?"
            else:
                _out("  未知命令，输入 /help 查看可用命令。")
                continue

        try:
            result = engine.reply(user_input)
        except LLMError as exc:
            engine.rollback_last_user()
            _out(f"  ⚠️ 模型调用失败：{exc}")
            _out("  请重试，或输入 /quit 结束对话。")
            continue

        _render_feedback(result)
        _out(f"{scenario['ai_role']}: "
             f"{result.ai_line or '（让我想一下该怎么接这句话……）'}")
        if result.should_end:
            _out(f"\n（{result.end_reason or '场景目标已达成'}）")
            break

    # ---- 总结 ----
    _out("\n正在生成本次练习总结，请稍候 ...")
    try:
        report = engine.summarize()
    except LLMError as exc:
        _out(f"⚠️ 总结生成失败：{exc}")
        _out("以下为本会话收集到的生词：")
        for item in engine.vocabulary.values():
            _out(f"  · {item.get('word', '')} —— {item.get('meaning_zh', '')}")
        return None

    _render_report(report)
    return report


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_output()

    parser = argparse.ArgumentParser(
        prog="spoken",
        description="智能英语口语对话练习程序（命令行）：选择场景和难度，"
                    "AI 扮演角色陪你练英语并实时纠错。")
    parser.add_argument("--config", help="配置文件路径（默认 ./config.yaml）")
    parser.add_argument("--scenario", choices=SCENARIO_ORDER,
                        help="跳过菜单，直接选择场景")
    parser.add_argument("--level", choices=DIFFICULTY_ORDER,
                        help="跳过菜单，直接选择难度")
    parser.add_argument("--mock", action="store_true",
                        help="离线演示模式：使用内置模拟模型，无需 API Key")
    parser.add_argument("--version", action="version",
                        version=f"spoken {__version__}")
    args = parser.parse_args(argv)

    _out("spoken —— 智能英语口语对话练习")
    _out("选择场景和难度后，AI 会扮演对应角色陪你练习英语口语。\n")

    try:
        config = load_config(args.config)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        _out(f"⚠️ 配置文件读取失败：{exc}")
        return 2

    if args.mock:
        llm = MockLLM()
        _out("（离线演示模式：使用内置模拟模型，回复为预设内容）\n")
    else:
        if not config.api_key:
            _out("⚠️ 未检测到 API Key。请先配置：")
            _out("  1. 复制 config.example.yaml 为 config.yaml，"
                 "填入 base_url / api_key / model；")
            _out("  2. 或设置环境变量 SPOKEN_API_KEY"
                 "（可选 SPOKEN_BASE_URL / SPOKEN_MODEL）；")
            _out("  3. 也可以加 --mock 参数先体验离线演示模式。")
            return 2
        llm = OpenAICompatibleLLM(
            base_url=config.base_url,
            api_key=config.api_key,
            model=config.model,
            temperature=config.temperature,
            timeout=config.timeout,
        )

    scenario_key = args.scenario or choose_scenario()
    difficulty_key = args.level or choose_difficulty()

    engine = DialogueEngine(
        llm, scenario_key, difficulty_key,
        feedback_language=config.feedback_language,
        min_turns=config.min_turns,
    )
    report = _run_dialogue(engine, config.max_turns)

    if report is not None and config.save_report:
        try:
            path = save_report(render_report_markdown(report), config.report_dir)
            _out(f"\n📄 报告已保存：{path}")
        except OSError as exc:
            _out(f"\n⚠️ 报告保存失败：{exc}")
    return 0
