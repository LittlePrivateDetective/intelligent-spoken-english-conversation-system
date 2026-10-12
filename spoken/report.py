"""总结报告的渲染与保存。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .scenarios import DIFFICULTIES, SCENARIOS

_SCORE_NAMES = {
    "fluency": "流利度",
    "grammar": "语法",
    "vocabulary": "词汇",
    "appropriateness": "得体度",
}


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
        f"- 对话轮次：{stats.get('turns', 0)}"
        f"（纠错 {stats.get('corrections', 0)} 处，卡壳 {stats.get('stuck', 0)} 次）",
        "",
        "## 总体评价",
        "",
        str(report.get("overall", "")),
        "",
        "## 能力评分",
        "",
        "| 维度 | 分数（0-10） |",
        "| --- | --- |",
    ]
    scores = report.get("scores", {}) or {}
    for key, name in _SCORE_NAMES.items():
        lines.append(f"| {name} | {scores.get(key, '-')} |")

    lines += ["", "## 生词本", ""]
    vocab = report.get("vocabulary") or []
    if vocab:
        lines += ["| 单词/短语 | 释义 | 例句 |", "| --- | --- | --- |"]
        for item in vocab:
            lines.append(
                f"| {item.get('word', '')} "
                f"| {item.get('meaning_zh', '')} "
                f"| {item.get('example', '')} |"
            )
    else:
        lines.append("（本次没有记录新词）")

    lines += ["", "## 改进点", ""]
    improvements = report.get("improvements") or []
    if improvements:
        for index, item in enumerate(improvements, 1):
            lines.append(f"{index}. **{item.get('issue', '')}**")
            if item.get("example_from_conversation"):
                lines.append(f"   - 对话实例：{item['example_from_conversation']}")
            if item.get("suggestion"):
                lines.append(f"   - 建议：{item['suggestion']}")
    else:
        lines.append("（没有明显需要改进的地方，保持！）")

    lines += ["", "## 练习建议", ""]
    for tip in report.get("suggestions") or []:
        lines.append(f"- {tip}")

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


def save_report(markdown: str, report_dir: str) -> Path:
    """把报告 Markdown 保存到 report_dir，返回文件路径。"""
    directory = Path(report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"spoken_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    path.write_text(markdown, encoding="utf-8")
    return path
