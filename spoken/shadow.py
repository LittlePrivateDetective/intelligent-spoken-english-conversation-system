"""跟读专项练习：句子队列 + 低分自动重练 + 汇总。

与自由对话（DialogueEngine）解耦：本模块只管理「练习哪些句子、当前练到
哪句、低分是否重练、结束时的统计」，识别/评分/播放由 GUI 层驱动。

流程：生成 N 句 → 逐句（播放参考 → 录音 → 评分）→ 总分低于
``RETRY_THRESHOLD`` 的句子自动插回队尾重练（每句最多重练
``MAX_RETRIES`` 次）→ 队列耗尽输出汇总。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .llm import LLMError, parse_json_robust
from .prompts import (SHADOW_SENTENCES_INSTRUCTION, SHADOW_SENTENCES_SYSTEM)
from .scenarios import DIFFICULTIES, resolve_scenario

RETRY_THRESHOLD = 70.0   # 总分低于此值进入重练队列
MAX_RETRIES = 2          # 每句最多重练次数（含首次共练习 3 次）


def generate_sentences(llm, scenario_key: str, difficulty_key: str,
                       count: int = 5) -> list[str]:
    """让 LLM 按场景与难度生成跟读句子；失败或空结果抛 LLMError。"""
    scn = resolve_scenario(scenario_key)
    diff = DIFFICULTIES[difficulty_key]
    system = (
        SHADOW_SENTENCES_SYSTEM
        + f"\n\n【当前场景】{scn['name']}（{scn['name_en']}）："
        + str(scn.get("summary", ""))
        + f"\n【难度】{diff['name']}（{diff['cefr']}）"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user",
         "content": SHADOW_SENTENCES_INSTRUCTION.format(count=count)},
    ]
    raw = llm.chat(messages, purpose="shadow")
    try:
        data = parse_json_robust(raw)
    except LLMError:
        raise LLMError("跟读句子生成失败：模型没有返回有效的 JSON")
    sentences = [str(s).strip() for s in (data.get("sentences") or [])
                 if str(s).strip()]
    if not sentences:
        raise LLMError("跟读句子生成失败：句子列表为空")
    return sentences[:count]


@dataclass
class ShadowSession:
    """一次跟读练习的队列状态机。"""

    scenario_key: str
    difficulty_key: str
    sentences: list[str]
    retry_threshold: float = RETRY_THRESHOLD
    max_retries: int = MAX_RETRIES

    _queue: list[str] = field(default_factory=list, init=False)
    _done: list[tuple[str, object | None]] = field(default_factory=list,
                                                   init=False)
    _attempts: dict[str, int] = field(default_factory=dict, init=False)
    retry_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._queue = list(self.sentences)

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    @property
    def current(self) -> str | None:
        """当前待练句子；队列耗尽返回 None。"""
        return self._queue[0] if self._queue else None

    @property
    def finished(self) -> bool:
        return not self._queue

    @property
    def progress(self) -> tuple[int, int]:
        """(已完成句数, 队列剩余句数)。"""
        return len(self._done), len(self._queue)

    @property
    def total_attempts(self) -> int:
        """累计练习次数（含重练）。"""
        return len(self._done) + len(self._queue)

    # ------------------------------------------------------------------
    # 推进
    # ------------------------------------------------------------------
    def submit(self, score) -> str:
        """提交当前句的评分（score 可为 None = 未配置评分）。

        返回 "retry"（已插入队尾重练）/ "next"（进入下一句）/
        "finished"（练习全部完成）。
        """
        sentence = self._queue.pop(0)
        self._done.append((sentence, score))
        attempts = self._attempts.get(sentence, 0) + 1
        self._attempts[sentence] = attempts
        overall = getattr(score, "overall", None) if score is not None else None
        if (overall is not None and overall < self.retry_threshold
                and attempts <= self.max_retries):
            self._queue.append(sentence)
            self.retry_count += 1
            return "retry"
        if self._queue:
            return "next"
        return "finished"

    def skip(self) -> str:
        """跳过当前句（不评分）。返回同 submit 的状态词。"""
        sentence = self._queue.pop(0)
        self._done.append((sentence, None))
        if self._queue:
            return "next"
        return "finished"

    def requeue(self, sentence: str) -> bool:
        """把已练过的句子插到队首重练（用户主动「再练一次」）。

        超过 max_retries 上限时返回 False（UI 可禁用该按钮）。
        """
        attempts = self._attempts.get(sentence, 0)
        if attempts > self.max_retries:
            return False
        self._queue.insert(0, sentence)
        self.retry_count += 1
        return True

    def requeue_possible(self, sentence: str) -> bool:
        """该句子是否还能再练一次（未超重练上限）。"""
        return self._attempts.get(sentence, 0) <= self.max_retries

    # ------------------------------------------------------------------
    # 汇总
    # ------------------------------------------------------------------
    def summary(self) -> dict:
        """结束时的统计：平均分（仅统计有评分的次数）、练习/重练次数。"""
        scored = [s for _, s in self._done if s is not None]
        n = len(scored)
        avg = lambda attr: (round(sum(getattr(s, attr) for s in scored) / n, 1)
                            if n else 0.0)
        return {
            "scenario": self.scenario_key,
            "difficulty": self.difficulty_key,
            "sentence_count": len(self.sentences),
            "attempts": len(self._done),
            "retry_count": self.retry_count,
            "scored_count": n,
            "avg_overall": avg("overall"),
            "avg_accuracy": avg("accuracy"),
            "avg_integrity": avg("integrity"),
            "avg_fluency": avg("fluency"),
            "records": [(text, getattr(s, "overall", None) if s else None)
                        for text, s in self._done],
        }
