"""生词本数据模型：词头 / 词形变换 / 近义对比 / 短语搭配。

纯标准库 dataclass，便于复用与本地序列化（存 SQLite / JSON）。
字段容错：from_dict 对模型返回做规范化，缺字段补默认、坏条目跳过，
避免单条脏数据拖垮整页渲染。
"""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field


@dataclass
class Derivation:
    """词形变换（派生词）：一个衍生词形 + 词性 + 中文释义。"""

    word: str
    pos: str
    definition_zh: str


@dataclass
class ContrastItem:
    """近义对比中的一项：含义侧重 / 语体正式度 / 使用场景 / 例句。"""

    word: str
    focus: str        # 含义侧重（它强调什么）
    register: str     # 语体正式度（正式 / 中性 / 口语）
    scene: str        # 典型使用场景
    example: str      # 英文例句


@dataclass
class ContrastGroup:
    """一组同词性的近义对比（至少两个词）。"""

    pos: str                    # 被对比的词性，如 adj. / v.
    words: list[str]            # 参与对比的词
    items: list[ContrastItem]


@dataclass
class Phrase:
    """相关短语 + 搭配说明。"""

    phrase: str
    structure: str   # 搭配结构说明（接 -ing / to do / 宾语类型等）
    meaning_zh: str
    example: str     # 英文例句


@dataclass
class VocabEntry:
    """一条完整的生词卡片。"""

    word: str
    phonetic: str
    pos: str
    definition_zh: str
    derivations: list[Derivation] = field(default_factory=list)
    contrast: list[ContrastGroup] = field(default_factory=list)
    phrases: list[Phrase] = field(default_factory=list)
    created_at: str = ""
    # 复习排期（遗忘曲线，SM-2 简化）：due=下次复习日期(ISO)，
    # interval=当前间隔天数，reps=已连续答对次数。空 due 表示从未复习。
    due: str = ""
    interval: int = 0
    reps: int = 0
    id: int = 0    # 本地数据库主键（未入库时为 0）

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict) -> "VocabEntry":
        raw = raw or {}

        # 词形变换（派生词）
        derivations: list[Derivation] = []
        for d in (raw.get("derivations") or []):
            if not isinstance(d, dict):
                continue
            w = (d.get("word") or "").strip()
            if not w:
                continue
            derivations.append(Derivation(
                word=w,
                pos=(d.get("pos") or "").strip(),
                definition_zh=(d.get("definition_zh") or "").strip(),
            ))

        # 近义 / 同词性对比（防御：同词性至少 2 项才保留）
        contrast: list[ContrastGroup] = []
        for g in (raw.get("contrast") or []):
            if not isinstance(g, dict):
                continue
            items: list[ContrastItem] = []
            for it in (g.get("items") or []):
                if not isinstance(it, dict):
                    continue
                w = (it.get("word") or "").strip()
                if not w:
                    continue
                items.append(ContrastItem(
                    word=w,
                    focus=(it.get("focus") or "").strip(),
                    register=(it.get("register") or "").strip(),
                    scene=(it.get("scene") or "").strip(),
                    example=(it.get("example") or "").strip(),
                ))
            if len(items) >= 2:
                contrast.append(ContrastGroup(
                    pos=(g.get("pos") or "").strip(),
                    words=[i.word for i in items],
                    items=items,
                ))

        # 短语搭配
        phrases: list[Phrase] = []
        for p in (raw.get("phrases") or []):
            if not isinstance(p, dict):
                continue
            ph = (p.get("phrase") or "").strip()
            if not ph:
                continue
            phrases.append(Phrase(
                phrase=ph,
                structure=(p.get("structure") or "").strip(),
                meaning_zh=(p.get("meaning_zh") or "").strip(),
                example=(p.get("example") or "").strip(),
            ))

        created = (raw.get("created_at")
                   or datetime.datetime.now().isoformat(timespec="seconds"))
        return VocabEntry(
            word=(raw.get("word") or "").strip(),
            phonetic=(raw.get("phonetic") or "").strip(),
            pos=(raw.get("pos") or "").strip(),
            definition_zh=(raw.get("definition_zh") or "").strip(),
            derivations=derivations,
            contrast=contrast,
            phrases=phrases,
            created_at=created,
            due=str(raw.get("due") or ""),
            interval=int(raw.get("interval", 0) or 0),
            reps=int(raw.get("reps", 0) or 0),
            id=int(raw.get("id", 0) or 0),
        )
