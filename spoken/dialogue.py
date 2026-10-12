"""对话引擎：单轮问答、纠错校验、动态难度、卡壳提示、总结生成。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .llm import LLMError, parse_json_robust
from .prompts import (JSON_REPAIR_INSTRUCTION, OPENING_INSTRUCTION,
                      SUMMARY_INSTRUCTION, build_system_prompt)
from .scenarios import DIFFICULTIES, get_difficulty, get_scenario


@dataclass
class TurnResult:
    """一轮对话的结构化结果。"""

    ai_line: str = ""
    corrections: list = field(default_factory=list)
    alternatives: list = field(default_factory=list)
    new_words: list = field(default_factory=list)
    stuck: bool = False
    hint: str | None = None
    difficulty: str = ""
    should_end: bool = False
    end_reason: str | None = None
    difficulty_changed: tuple | None = None
    dropped_corrections: list = field(default_factory=list)


def _dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


class DialogueEngine:
    """驱动一次完整的口语练习会话。"""

    def __init__(self, llm, scenario_key: str, difficulty_key: str,
                 feedback_language: str = "zh", min_turns: int = 3) -> None:
        get_scenario(scenario_key)    # 校验存在性
        get_difficulty(difficulty_key)
        self.llm = llm
        self.scenario_key = scenario_key
        self.difficulty = difficulty_key
        self.feedback_language = feedback_language
        self.min_turns = min_turns

        self.messages: list[dict] = [
            {"role": "system", "content": build_system_prompt(
                scenario_key, difficulty_key, feedback_language)}
        ]
        self.transcript: list[tuple[str, str]] = []  # ("ai"|"user", 文本)
        self.vocabulary: dict[str, dict] = {}        # 生词本（按单词去重）
        self.turn = 0
        self.correction_count = 0
        self.stuck_count = 0

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

    def _collect_words(self, words) -> list:
        """把新词并入生词本（按单词去重），返回本轮真正新增的词条。"""
        collected = []
        for item in words or []:
            if not isinstance(item, dict):
                continue
            word = str(item.get("word", "")).strip()
            if not word:
                continue
            if word.lower() not in self.vocabulary:
                self.vocabulary[word.lower()] = item
                collected.append(item)
        return collected

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

        data = self._chat_json("turn")
        self.messages.append({"role": "assistant", "content": _dump(data)})

        result = TurnResult()
        result.corrections, result.dropped_corrections = self._validate_corrections(
            user_input, data.get("corrections") or [])
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

        self.correction_count += len(result.corrections)
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

    def summarize(self) -> dict:
        """生成本次练习的总结报告（结构化 dict）。"""
        self.messages.append({"role": "user", "content": SUMMARY_INSTRUCTION})
        data = self._chat_json("summary")
        self._collect_words(data.get("vocabulary"))
        data["vocabulary"] = list(self.vocabulary.values())
        data["transcript"] = list(self.transcript)
        data["stats"] = {
            "scenario": self.scenario_key,
            "difficulty": self.difficulty,
            "turns": self.turn,
            "corrections": self.correction_count,
            "stuck": self.stuck_count,
        }
        return data
