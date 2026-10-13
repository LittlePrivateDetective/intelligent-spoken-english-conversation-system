"""总结报告的渲染与保存。

v2 总结结构（与需求一一对应）：
- total_errors   错误总数
- by_category    分类统计（语法/用词/表达/礼貌得体）
- unused_vocabulary  教了但用户没用上的词汇
- improvements   改进点清单
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .corrector import CATEGORY_NAMES
from .scenarios import DIFFICULTIES, SCENARIOS


def render_report_markdown(report: dict) -> str:
    """把总结 dict 渲染成 Markdown 文本。"""
    stats = report.get("stats", {}) or {}
    scenario = SCENARIOS.get(stats.get("scenario", ""), {})
    difficulty = DIFFICULTIES.get(stats.get("difficulty", ""), {})
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# spoken 口语练习报告",
        "",
        f"- 场景：{scenario.get('name', stats.get('scenario', '未知'))}"
        f"（{scenario.get('name_en', '')}）",
        f"- 难度：{difficulty.get('name', stats.get('difficulty', ''))}"
        f"（CEFR {difficulty.get('cefr', '')}）",
        f"- 时间：{now}",
        f"- 对话轮次：{stats.get('turns', 0)}（卡壳 {stats.get('stuck', 0)} 次）",
        "",
        "## 总体评价",
        "",
        str(report.get("overall") or "（本次未生成总体评价）"),
        "",
        "## 错误统计",
        "",
        f"**错误总数：{report.get('total_errors', 0)}**",
        "",
    ]
    by_category = report.get("by_category") or {}
    if by_category:
        parts = [f"{CATEGORY_NAMES.get(k, k)} {v} 处"
                 for k, v in by_category.items()]
        lines.append("分类统计：" + "；".join(parts))
        lines += ["", "| 类别 | 数量 |", "| --- | --- |"]
        for category, count in by_category.items():
            lines.append(f"| {CATEGORY_NAMES.get(category, category)} | {count} |")
    else:
        lines.append("分类统计：无（本次没有检测到错误）")

    lines += ["", "## 改进点清单", ""]
    improvements = report.get("improvements") or []
    if improvements:
        for index, item in enumerate(improvements, 1):
            lines.append(f"{index}. **{item.get('issue', '')}**")
            if item.get("suggestion"):
                lines.append(f"   - 建议：{item['suggestion']}")
    else:
        lines.append("本次没有检测到明显错误，保持！")

    lines += ["", "## 生词本", ""]
    vocabulary = report.get("vocabulary") or []
    if vocabulary:
        lines += ["| 单词/短语 | 释义 | 状态 | 例句 |", "| --- | --- | --- | --- |"]
        for item in vocabulary:
            status = "已用上" if item.get("used") else "没用上"
            lines.append(
                f"| {item.get('word', '')} "
                f"| {item.get('meaning_zh', '')} "
                f"| {status} "
                f"| {item.get('example', '')} |"
            )
    else:
        lines.append("（本次没有记录新词）")

    unused = report.get("unused_vocabulary") or []
    if unused:
        lines += ["", "### 没用到的词汇（下次练习试着用上）", ""]
        for item in unused:
            lines.append(f"- **{item.get('word', '')}** —— {item.get('meaning_zh', '')}")

    lines += ["", "## 练习建议", ""]
    suggestions = report.get("suggestions") or []
    if suggestions:
        for tip in suggestions:
            lines.append(f"- {tip}")
    else:
        lines.append("- 把生词本中的表达用到下一次练习中")

    if report.get("encouragement"):
        lines += ["", "---", "", f"💪 {report['encouragement']}"]

    transcript = report.get("transcript") or []
    if transcript:
        lines += ["", "## 完整对话记录", ""]
        for speaker, text in transcript:
            label = "你" if speaker == "user" else scenario.get("ai_role", "AI")
            lines.append(f"**{label}**：{text}")
            lines.append("")

    lines.append("")
    return "\n".join(lines)


def render_summary_text(report: dict) -> str:
    """把总结 dict 渲染成纯文本（供 GUI 弹窗直接展示）。"""
    lines = []
    if report.get("overall"):
        lines += [report["overall"], ""]
    lines.append(f"错误总数：{report.get('total_errors', 0)}")
    by_category = report.get("by_category") or {}
    if by_category:
        parts = [f"{CATEGORY_NAMES.get(k, k)} {v} 处"
                 for k, v in by_category.items()]
        lines.append("分类统计：" + "；".join(parts))
    else:
        lines.append("分类统计：无")

    lines += ["", "改进点清单："]
    improvements = report.get("improvements") or []
    if improvements:
        for index, item in enumerate(improvements, 1):
            lines.append(f"  {index}. {item.get('issue', '')}"
                         + (f" — {item['suggestion']}" if item.get("suggestion") else ""))
    else:
        lines.append("  本次没有检测到明显错误，保持！")

    unused = report.get("unused_vocabulary") or []
    lines += ["", "没用到的词汇："]
    if unused:
        for item in unused:
            lines.append(f"  · {item.get('word', '')} —— {item.get('meaning_zh', '')}")
    else:
        lines.append("  无（教的词你都用上了，很棒）")

    if report.get("suggestions"):
        lines += ["", "练习建议："]
        for tip in report["suggestions"]:
            lines.append(f"  · {tip}")

    if report.get("encouragement"):
        lines += ["", report["encouragement"]]
    return "\n".join(lines)


def save_report(markdown: str, report_dir: str) -> Path:
    """把报告 Markdown 保存到 report_dir，返回文件路径。"""
    directory = Path(report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"spoken_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    path.write_text(markdown, encoding="utf-8")
    return path
