"""对话引擎：单轮问答、纠错（规则+LLM 双通道）、动态难度、卡壳提示、总结生成。

v2 变化：
- 纠错改为「规则引擎 + LLM」双通道：规则保证确定性和可测试性，LLM 补充规则外的错误；
  两者都会做「original 必须是用户原话子串」校验，同一错误全局只输出一次。
- 跟踪生词使用情况，总结中区分「已掌握」和「没用到的词汇」。
- 总结结构固定为：错误总数 / 分类统计 / 没用到的词汇 / 改进点清单（LLM 只做增强，缺失也能出总结）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .corrector import CATEGORY_NAMES, Correction, RuleCorrector
from .llm import LLMError, parse_json_robust
from .prompts import (JSON_REPAIR_INSTRUCTION, OPENING_INSTRUCTION,
                      SUMMARY_INSTRUCTION, build_system_prompt)
from .scenarios import DIFFICULTIES, get_difficulty, get_scenario


@dataclass
class TurnResult:
    """一轮对话的结构化结果。"""

    ai_line: str = ""
    corrections: list = field(default_factory=list)      # 本轮实际输出的纠错（dict）
    alternatives: list = field(default_factory=list)
    new_words: list = field(default_factory=list)
    stuck: bool = False
    hint: str | None = None
    difficulty: str = ""
    should_end: bool = False
    end_reason: str | None = None
    difficulty_changed: tuple | None = None
    dropped_corrections: list = field(default_factory=list)
    repeated_corrections: list = field(default_factory=list)  # 命中但已输出过、本次不再展示


def _dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


class DialogueEngine:
    """驱动一次完整的口语练习会话。"""

    def __init__(self, llm, scenario_key: str, difficulty_key: str,
                 feedback_language: str = "zh", min_turns: int = 3,
                 use_rules: bool = True) -> None:
        get_scenario(scenario_key)    # 校验存在性
        get_difficulty(difficulty_key)
        self.llm = llm
        self.scenario_key = scenario_key
        self.difficulty = difficulty_key
        self.feedback_language = feedback_language
        self.min_turns = min_turns
        self.corrector = RuleCorrector() if use_rules else None

        self.messages: list[dict] = [
            {"role": "system", "content": build_system_prompt(
                scenario_key, difficulty_key, feedback_language)}
        ]
        self.transcript: list[tuple[str, str]] = []   # ("ai"|"user", 文本)
        self.vocabulary: dict[str, dict] = {}         # 生词本（按单词去重，含 used 标记）
        self.turn = 0
        self.stuck_count = 0
        self.total_corrections = 0                     # 本会话实际输出的纠错总数（去重后）
        self.by_category: dict[str, int] = {}          # 分类统计
        self._fired_pairs: set[tuple[str, str]] = set()  # 已输出过的 (original, corrected)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _refresh_system_prompt(self) -> None:
        self.messages[0] = {
            "role": "system",
            "content": build_system_prompt(
                self.scenario_key, self.difficulty, self.feedback_language),
        }

    def _chat_json(self, purpose: str) -> dict:
        """调用模型并解析 JSON；解析失败时自动请求修复一次。"""
        raw = self.llm.chat(self.messages, purpose=purpose)
        try:
            return parse_json_robust(raw)
        except LLMError:
            self.messages.append(
                {"role": "user", "content": JSON_REPAIR_INSTRUCTION})
            raw = self.llm.chat(self.messages, purpose=purpose)
            return parse_json_robust(raw)

    @staticmethod
    def _validate_corrections(user_input: str,
                              corrections: list) -> tuple[list, list]:
        """防编造校验：original 必须是用户原话中逐字出现的片段，否则丢弃。"""
        valid: list = []
        dropped: list = []
        lowered = user_input.lower()
        for item in corrections:
            if not isinstance(item, dict):
                dropped.append(item)
                continue
            original = str(item.get("original", "")).strip()
            if original and original.lower() in lowered:
                valid.append(item)
            else:
                dropped.append(item)
        return valid, dropped

    @staticmethod
    def _dedup_overlapping(corrections: list[dict]) -> list[dict]:
        """原话片段存在包含关系的纠错只保留更精确的（更短的）那一条。

        规则纠错通常片段更短更精准；LLM 可能返回覆盖同一错误的更长片段，
        两者只需展示一条，避免用户觉得“同一个错说了好几遍”。
        """
        accepted: list[dict] = []
        for item in sorted(corrections,
                           key=lambda c: len(str(c.get("original", "")))):
            original = str(item.get("original", "")).lower().strip()
            if not original:
                continue
            if any(original in str(k.get("original", "")).lower().strip()
                   or str(k.get("original", "")).lower().strip() in original
                   for k in accepted):
                continue
            accepted.append(item)
        return accepted

    def _register(self, corrections: list[dict]) -> tuple[list, list]:
        """登记本轮纠错：同一错误（original+corrected）只输出一次。

        返回 (本轮展示的条目, 命中但已输出过故不再展示的条目)。
        """
        shown: list[dict] = []
        repeated: list[dict] = []
        for item in corrections:
            key = (str(item.get("original", "")).lower(),
                   str(item.get("corrected", "")).lower())
            if key in self._fired_pairs:
                repeated.append(item)
                continue
            self._fired_pairs.add(key)
            shown.append(item)
            self.total_corrections += 1
            category = str(item.get("type", "grammar"))
            self.by_category[category] = self.by_category.get(category, 0) + 1
        return shown, repeated

    def _collect_words(self, words) -> list:
        """把新词并入生词本（按单词去重），返回本轮真正新增的词条。"""
        collected = []
        for item in words or []:
            if not isinstance(item, dict):
                continue
            word = str(item.get("word", "")).strip()
            if not word:
                continue
            key = word.lower()
            if key not in self.vocabulary:
                self.vocabulary[key] = {
                    "word": word,
                    "meaning_zh": str(item.get("meaning_zh", "")),
                    "example": str(item.get("example", "")),
                    "used": False,
                }
                collected.append(self.vocabulary[key])
        return collected

    def _mark_used_words(self, user_input: str) -> None:
        """用户本轮说过的词标记为已掌握（用于总结里的“没用到的词汇”）。"""
        lowered = user_input.lower()
        for entry in self.vocabulary.values():
            if not entry["used"] and entry["word"].lower() in lowered:
                entry["used"] = True

    def _sync_difficulty(self, suggested) -> tuple | None:
        """模型评估的用户水平发生变化时，刷新系统提示并返回 (旧, 新)。"""
        if suggested in DIFFICULTIES and suggested != self.difficulty:
            old, self.difficulty = self.difficulty, suggested
            self._refresh_system_prompt()
            return old, suggested
        return None

    # ------------------------------------------------------------------
    # 对外流程
    # ------------------------------------------------------------------
    def start(self) -> str:
        """让 AI 说出开场白，返回台词文本。"""
        self.messages.append({"role": "user", "content": OPENING_INSTRUCTION})
        data = self._chat_json("open")
        self.messages.append({"role": "assistant", "content": _dump(data)})
        line = str(data.get("next_line", "")).strip()
        if not line:
            raise LLMError("模型没有返回开场台词")
        self.transcript.append(("ai", line))
        self._sync_difficulty(data.get("difficulty"))
        return line

    def reply(self, user_input: str) -> TurnResult:
        """处理用户一轮输入，返回结构化结果。"""
        user_input = user_input.strip()
        if not user_input:
            raise ValueError("用户输入不能为空")
        self.turn += 1
        self.messages.append({"role": "user", "content": user_input})
        self.transcript.append(("user", user_input))
        self._mark_used_words(user_input)

        # 通道一：规则纠错（确定性、离线）
        rule_corrections: list[dict] = []
        if self.corrector is not None:
            rule_corrections = [c.as_dict()
                                for c in self.corrector.check(user_input)]

        # 通道二：LLM 纠错（经防编造校验）
        data = self._chat_json("turn")
        self.messages.append({"role": "assistant", "content": _dump(data)})
        llm_corrections, dropped = self._validate_corrections(
            user_input, data.get("corrections") or [])
        for item in llm_corrections:
            item.setdefault("rule_id", "")

        result = TurnResult()
        result.dropped_corrections = dropped
        merged = self._dedup_overlapping(rule_corrections + llm_corrections)
        result.corrections, result.repeated_corrections = self._register(merged)
        result.alternatives = [
            str(a).strip() for a in (data.get("alternatives") or [])
            if str(a).strip()
        ][:3]
        result.new_words = self._collect_words(data.get("new_words"))
        result.ai_line = str(data.get("next_line", "")).strip()
        result.stuck = bool(data.get("stuck"))
        hint = data.get("hint")
        result.hint = str(hint).strip() if hint else None
        result.should_end = bool(data.get("should_end"))
        result.end_reason = data.get("end_reason") or None
        result.difficulty_changed = self._sync_difficulty(data.get("difficulty"))
        result.difficulty = self.difficulty

        if result.stuck:
            self.stuck_count += 1

        # 至少聊满 min_turns 轮才允许自然结束，避免刚开口就散场
        if result.should_end and self.turn < self.min_turns:
            result.should_end = False

        if result.ai_line:
            self.transcript.append(("ai", result.ai_line))
        return result

    def rollback_last_user(self) -> None:
        """模型调用失败时回滚用户输入，避免污染对话历史。"""
        if self.messages and self.messages[-1]["role"] == "user":
            self.messages.pop()
        if self.transcript and self.transcript[-1][0] == "user":
            self.transcript.pop()
        self.turn = max(0, self.turn - 1)

    # ------------------------------------------------------------------
    # 总结
    # ------------------------------------------------------------------
    def _base_summary(self) -> dict:
        """不依赖 LLM 的确定性总结骨架。"""
        improvements = []
        for category, count in sorted(self.by_category.items(),
                                      key=lambda kv: (-kv[1], kv[0])):
            improvements.append({
                "issue": f"{CATEGORY_NAMES.get(category, category)}问题 {count} 处",
                "suggestion": _category_advice(category),
                "count": count,
            })
        unused = [dict(item) for item in self.vocabulary.values()
                  if not item["used"]]
        return {
            "overall": "",
            "total_errors": self.total_corrections,
            "by_category": dict(self.by_category),
            "unused_vocabulary": unused,
            "vocabulary": [dict(item) for item in self.vocabulary.values()],
            "improvements": improvements,
            "suggestions": [],
            "encouragement": "",
            "transcript": list(self.transcript),
            "stats": {
                "scenario": self.scenario_key,
                "difficulty": self.difficulty,
                "turns": self.turn,
                "corrections": self.total_corrections,
                "stuck": self.stuck_count,
            },
        }

    def summarize(self) -> dict:
        """生成本次练习的总结报告（结构化 dict）。

        结构固定包含：total_errors / by_category / unused_vocabulary /
        improvements；LLM 只负责增强 overall / suggestions / encouragement，
        调用失败也不影响总结产出。
        """
        summary = self._base_summary()
        try:
            self.messages.append(
                {"role": "user", "content": SUMMARY_INSTRUCTION})
            data = self._chat_json("summary")
        except LLMError:
            return summary

        if isinstance(data.get("overall"), str):
            summary["overall"] = data["overall"].strip()
        suggestions = [str(s).strip() for s in (data.get("suggestions") or [])
                       if str(s).strip()]
        summary["suggestions"] = suggestions[:5]
        if isinstance(data.get("encouragement"), str):
            summary["encouragement"] = data["encouragement"].strip()
        for item in data.get("improvements") or []:
            if isinstance(item, dict) and str(item.get("issue", "")).strip():
                summary["improvements"].append({
                    "issue": str(item.get("issue", "")).strip(),
                    "suggestion": str(item.get("suggestion", "")).strip(),
                    "count": 0,
                })
        # LLM 可能补充新词（防御性处理，不影响主流程）
        self._collect_words(data.get("vocabulary"))
        summary["vocabulary"] = [dict(item) for item in self.vocabulary.values()]
        summary["unused_vocabulary"] = [
            dict(item) for item in self.vocabulary.values() if not item["used"]]
        return summary


_CATEGORY_ADVICE = {
    "grammar": "重点复习动词形式（时态、主谓一致、非谓语）和句子结构。",
    "word": "注意近义词辨析和固定搭配，宁可多用简单正确的词。",
    "expression": "多积累完整句型，避免把中文逐字直译成英语。",
    "politeness": "正式或服务场合多用 I'd like ... / Could you ... 等委婉表达。",
}


def _category_advice(category: str) -> str:
    return _CATEGORY_ADVICE.get(category, "针对该类错误做专项句型练习。")
