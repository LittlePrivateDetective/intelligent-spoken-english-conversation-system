"""生词生成：复用通义 Plus（任意 OpenAI 兼容 /chat/completions）生成结构化词条。

只新增「查词 / 生词生成」这一调用场景，不重写现有通义接入逻辑：
直接用 spoken.llm.OpenAICompatibleLLM（或任意提供 chat(messages)->str 的客户端）。
"""

from __future__ import annotations

from .llm import LLMError, parse_json_robust
from .prompts import build_vocab_messages
from .vocab_model import VocabEntry


class VocabGenError(LLMError):
    """生词生成失败（网络 / 解析 / 内容不完整）。"""


class VocabGenerator:
    """给定英文单词或短语，调用模型生成结构化生词卡片。"""

    def __init__(self, client) -> None:
        # client 只需提供 chat(messages, purpose="vocab") -> str
        self.client = client

    def generate(self, word: str) -> VocabEntry:
        word = (word or "").strip()
        if not word:
            raise VocabGenError("查询词为空")

        try:
            raw_text = self.client.chat(build_vocab_messages(word),
                                        purpose="vocab")
        except LLMError as exc:
            raise VocabGenError(f"模型调用失败：{exc}") from exc

        try:
            data = parse_json_robust(raw_text)
        except LLMError as exc:
            raise VocabGenError(f"无法解析模型返回的 JSON：{exc}") from exc

        entry = VocabEntry.from_dict(data)
        # 模型偶尔不回写 word 字段，用查询词兜底
        if not entry.word:
            entry.word = word
        # 内容完整性兜底：至少要有释义或词形或短语，否则视为无效
        if (not entry.definition_zh and not entry.derivations
                and not entry.phrases and not entry.contrast):
            raise VocabGenError("模型返回的内容不完整，请重试")
        return entry
