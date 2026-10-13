#!/usr/bin/env python3
"""spoken 验证脚本。

使用内置 MockLLM 离线跑通全部场景与难度组合，验证：
  1. 12 种「场景 × 难度」组合的系统提示均正确生成；
  2. 4 个场景 × 3 个难度的完整对话流程（开场 -> 纠错 -> 卡壳提示
     -> 动态难度 -> 自然收尾 -> 总结报告）；
  3. 纠错内容的 original 必须逐字来自用户输入（防编造校验）；
  4. JSON 解析的健壮性、配置加载（含环境变量覆盖）、报告渲染与保存；
  5. 命令行入口的冒烟测试。

运行方式：python verify.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from spoken.config import load_config
from spoken.dialogue import DialogueEngine
from spoken.llm import LLMError, MockLLM, parse_json_robust
from spoken.prompts import build_system_prompt
from spoken.report import render_report_markdown, save_report
from spoken.scenarios import DIFFICULTIES, DIFFICULTY_ORDER, SCENARIOS, SCENARIO_ORDER

# 每个场景的测试台词：含错误句、卡壳句、正确句、流畅信号句、告别句
FLAWED_INPUT = {
    "daily_smalltalk": "Hello, I am agree with you, and I very like this party.",
    "airport_checkin": "Hi, I have a fly to Beijing at 8 clock.",
    "job_interview": "I am graduated from Guangdong Ocean University in 2027.",
    "restaurant_order": "I want to eat a steak, medium rare.",
}

END_INPUT = {
    "daily_smalltalk": "It was nice talking to you. Goodbye!",
    "airport_checkin": "That's all I needed. Thank you, goodbye!",
    "job_interview": "Thank you for your time. I have no more questions. Goodbye!",
    "restaurant_order": "Could I have the bill, please? Thank you, goodbye!",
}

GREETING_KEYWORDS = {
    "daily_smalltalk": ["hi", "met", "alex", "day"],
    "airport_checkin": ["check", "flight", "passport", "morning", "airport"],
    "job_interview": ["interview", "seat", "yourself", "morning", "tell me"],
    "restaurant_order": ["menu", "table", "evening", "recommend", "order"],
}


# ----------------------------------------------------------------------
# 场景 × 难度 完整流程测试
# ----------------------------------------------------------------------
def run_scenario_case(scenario_key: str, level_key: str) -> list[tuple[str, bool]]:
    engine = DialogueEngine(MockLLM(), scenario_key, level_key)
    checks: list[tuple[str, bool]] = []

    def check(name: str, condition: bool) -> None:
        checks.append((name, bool(condition)))

    # 1. 开场白
    greeting = engine.start()
    check("开场白是英语台词", bool(re.search(r"[A-Za-z]", greeting)))
    check("开场白贴合场景",
          any(k in greeting.lower() for k in GREETING_KEYWORDS[scenario_key]))

    # 2. 带错误的输入 -> 纠错 + 替代表达
    flawed = FLAWED_INPUT[scenario_key]
    r1 = engine.reply(flawed)
    check("识别语法/用词错误", len(r1.corrections) >= 1)
    check("纠错原文逐字来自用户输入（未编造）",
          all(c["original"].lower() in flawed.lower() for c in r1.corrections))
    check("纠错附带中文原因", all(c.get("reason") for c in r1.corrections))
    check("提供更地道的替代表达", len(r1.alternatives) >= 1)

    # 3. 卡壳 -> 提示而非结束
    r2 = engine.reply("I don't know.")
    check("检测到用户卡壳", r2.stuck)
    check("卡壳时给出提示", bool(r2.hint))
    check("卡壳不会结束对话", not r2.should_end)

    # 4. 正确输入 -> 零纠错
    r3 = engine.reply("My name is Paul, and I am 25 years old.")
    check("表达正确时零纠错", len(r3.corrections) == 0)

    # 5. 难度动态调整
    r4 = engine.reply("Actually, I'm quite comfortable with English conversations.")
    check("按用户水平动态提升难度", engine.difficulty == "advanced")

    # 6. 自然告别 -> 收尾
    r5 = engine.reply(END_INPUT[scenario_key])
    check("自然告别后正常收尾", r5.should_end and bool(r5.ai_line))

    # 7. 总结报告（v2 结构：错误总数 / 分类统计 / 改进点 / 生词本）
    report = engine.summarize()
    check("总结含总体评价", bool(report.get("overall")))
    check("总结含错误总数", isinstance(report.get("total_errors"), int)
          and report["total_errors"] >= 1)
    check("总结含分类统计", isinstance(report.get("by_category"), dict)
          and sum(report["by_category"].values()) == report["total_errors"])
    check("总结含没用到的词汇字段", isinstance(
        report.get("unused_vocabulary"), list))
    check("总结含生词本", len(report.get("vocabulary", [])) >= 1)
    check("总结含改进点", len(report.get("improvements", [])) >= 1)
    check("总结含练习建议", len(report.get("suggestions", [])) >= 1)
    check("统计对话轮次", report["stats"]["turns"] == 5)
    check("改进点包含问题与建议",
          all(ex.get("issue") and ex.get("suggestion")
              for ex in report.get("improvements", [])))

    return checks


# ----------------------------------------------------------------------
# 单元检查
# ----------------------------------------------------------------------
def run_unit_checks() -> list[tuple[str, bool]]:
    checks: list[tuple[str, bool]] = []

    def check(name: str, condition: bool) -> None:
        checks.append((name, bool(condition)))

    # A. 12 种组合的系统提示
    ok = True
    for sc_key in SCENARIO_ORDER:
        for df_key in DIFFICULTY_ORDER:
            prompt = build_system_prompt(sc_key, df_key)
            sc, df = SCENARIOS[sc_key], DIFFICULTIES[df_key]
            ok &= (sc["name"] in prompt and sc["ai_role"] in prompt
                   and sc["goals"] in prompt and df["name"] in prompt
                   and df["guidance"] in prompt)
    check("12 种场景×难度组合的系统提示均正确生成", ok)

    # B. JSON 健壮解析
    check("解析纯 JSON", parse_json_robust('{"a": 1}') == {"a": 1})
    check("解析 markdown 代码块包裹的 JSON",
          parse_json_robust('前言\n```json\n{"a": 1}\n```\n后记') == {"a": 1})
    check("解析夹带文字的 JSON",
          parse_json_robust('结果是：{"a": 1}，再见') == {"a": 1})
    try:
        parse_json_robust("完全不是 JSON")
        check("非法 JSON 抛出 LLMError", False)
    except LLMError:
        check("非法 JSON 抛出 LLMError", True)

    # C. 防编造校验：丢弃用户没说过的纠错
    engine = DialogueEngine(MockLLM(), "daily_smalltalk", "intermediate")
    engine.start()
    r = engine.reply("Please fabricate something that I never said.")
    check("丢弃编造的纠错（用户没说过的话）",
          len(r.corrections) == 0 and len(r.dropped_corrections) >= 1)

    # D. 配置加载与环境变量覆盖
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.yaml"
        cfg_path.write_text(
            "llm:\n"
            "  base_url: https://example.com/v1\n"
            "  api_key: test-key\n"
            "  model: test-model\n"
            "dialogue:\n"
            "  max_turns: 9\n",
            encoding="utf-8")
        cfg = load_config(str(cfg_path))
        check("从 YAML 读取配置",
              cfg.base_url == "https://example.com/v1"
              and cfg.api_key == "test-key"
              and cfg.model == "test-model"
              and cfg.max_turns == 9)
        os.environ["SPOKEN_MODEL"] = "env-model"
        try:
            cfg2 = load_config(str(cfg_path))
            check("环境变量覆盖配置文件", cfg2.model == "env-model")
        finally:
            del os.environ["SPOKEN_MODEL"]

    # E. 报告渲染与保存
    engine2 = DialogueEngine(MockLLM(), "restaurant_order", "beginner")
    engine2.start()
    engine2.reply("I want to eat a steak, medium rare.")
    report = engine2.summarize()
    markdown = render_report_markdown(report)
    check("报告 Markdown 包含全部板块",
          all(s in markdown for s in
              ["总体评价", "错误统计", "分类统计", "改进点清单", "生词本",
               "练习建议", "完整对话记录"]))
    with tempfile.TemporaryDirectory() as tmp:
        path = save_report(markdown, tmp)
        check("报告可保存为文件",
              path.is_file() and path.read_text(encoding="utf-8") == markdown)

    # F. 命令行入口冒烟测试（子进程，离线 Mock 模式）
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.yaml"
        cfg.write_text("dialogue:\n  save_report: false\n", encoding="utf-8")
        env = dict(os.environ, SPOKEN_CONFIG=str(cfg), PYTHONIOENCODING="utf-8")
        script = ("I am agree with you, and I very like this party.\n"
                  "I don't know.\n"
                  "My name is Paul, and I am 25 years old.\n"
                  "It was nice talking to you. Goodbye!\n")
        proc = subprocess.run(
            [sys.executable, "-m", "spoken.cli", "--mock",
             "--scenario", "daily_smalltalk", "--level", "beginner"],
            input=script, capture_output=True, text=True,
            encoding="utf-8", env=env, timeout=60)
        out = proc.stdout
        check("CLI 冒烟测试正常退出", proc.returncode == 0)
        check("CLI 输出包含角色台词", "朋友" in out)
        check("CLI 输出包含纠错反馈", "纠错" in out)
        check("CLI 输出包含卡壳提示", "卡壳提示" in out)
        check("CLI 输出包含总结报告", "生词本" in out)

    return checks


# ----------------------------------------------------------------------
# 示例对话
# ----------------------------------------------------------------------
def print_sample_dialogue() -> None:
    engine = DialogueEngine(MockLLM(), "daily_smalltalk", "intermediate")
    sc = SCENARIOS["daily_smalltalk"]
    print(f"{sc['ai_role']}: {engine.start()}")
    script = [
        FLAWED_INPUT["daily_smalltalk"],
        "I don't know.",
        "My name is Paul, and I am 25 years old.",
        "Actually, I'm quite comfortable with English conversations.",
        END_INPUT["daily_smalltalk"],
    ]
    for text in script:
        print(f"你: {text}")
        result = engine.reply(text)
        for c in result.corrections:
            print(f"  ✏️ 纠错：{c['original']} → {c['corrected']}（{c['reason']}）")
        if result.alternatives:
            print(f"  💡 更地道的说法：{result.alternatives[0]}")
        if result.stuck and result.hint:
            print(f"  💡 卡壳提示：{result.hint}")
        if result.difficulty_changed:
            old, new = result.difficulty_changed
            print(f"  📈 难度调整：{DIFFICULTIES[old]['name']} → "
                  f"{DIFFICULTIES[new]['name']}")
        if result.ai_line:
            print(f"{sc['ai_role']}: {result.ai_line}")
        if result.should_end:
            break
    report = engine.summarize()
    print(f"\n总结：{report['overall']}")
    print(f"错误总数：{report['total_errors']}（{report['by_category']}）")
    print(f"生词本：{[w['word'] for w in report['vocabulary']]}")


def _print_checks(checks: list[tuple[str, bool]]) -> None:
    for name, ok in checks:
        print(f"    {'✓' if ok else '✗'} {name}")


def main() -> int:
    print("=" * 62)
    print("spoken 验证脚本（离线 Mock 模式）")
    print("=" * 62)

    all_checks: list[tuple[str, bool]] = []

    print("\n[1/3] 单元检查（提示词 / JSON 解析 / 防编造 / 配置 / 报告 / CLI）")
    unit = run_unit_checks()
    _print_checks(unit)
    all_checks.extend(unit)

    print("\n[2/3] 场景 × 难度矩阵测试（4 场景 × 3 难度 = 12 种组合）")
    for sc_key in SCENARIO_ORDER:
        for df_key in DIFFICULTY_ORDER:
            label = f"{SCENARIOS[sc_key]['name']} / {DIFFICULTIES[df_key]['name']}"
            print(f"  - {label} ...", end=" ", flush=True)
            try:
                checks = run_scenario_case(sc_key, df_key)
            except Exception as exc:  # 单个组合失败不影响其他组合
                checks = [(f"运行异常：{exc!r}", False)]
            failed = [name for name, ok in checks if not ok]
            if failed:
                print("FAIL")
                for name in failed:
                    print(f"      ✗ {name}")
            else:
                print(f"PASS（{len(checks)} 项检查）")
            all_checks.extend((f"[{label}] {name}", ok)
                              for name, ok in checks)

    print("\n[3/3] 示例对话（日常寒暄 / 中级）")
    print("-" * 62)
    print_sample_dialogue()
    print("-" * 62)

    passed = sum(1 for _, ok in all_checks if ok)
    total = len(all_checks)
    print("\n" + "=" * 62)
    print(f"结果：{passed}/{total} 项检查通过")
    if passed == total:
        print("✅ 全部通过")
        return 0
    print("❌ 存在失败项，请检查上方输出")
    return 1


if __name__ == "__main__":
    sys.exit(main())
