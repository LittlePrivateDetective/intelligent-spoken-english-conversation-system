"""规则纠错模块：常见中式英语错误的确定性检测。

设计要点：
- 每条规则对应一个正则，命中后 original 直接取 match.group(0)，
  天然保证是用户原话中逐字出现的片段（防编造）。
- 干净句子不命中任何规则 -> 零反馈，绝不硬凑。
- 规则只覆盖高频、明确的错误模式；LLM 纠错作为补充（见 dialogue.py）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CATEGORY_NAMES = {
    "grammar": "语法",
    "word": "用词",
    "expression": "表达",
    "politeness": "礼貌得体",
}

CATEGORY_ADVICE = {
    "grammar": "重点复习动词形式（时态、主谓一致、非谓语）和句子结构。",
    "word": "注意近义词辨析和固定搭配，宁可多用简单正确的词。",
    "expression": "多积累完整句型，避免把中文逐字直译成英语。",
    "politeness": "正式或服务场合多用 I'd like ... / Could you ... 等委婉表达。",
}

# 常见动词的过去式（用于 yesterday/last ... 时态规则）
_PAST = {
    "go": "went", "eat": "ate", "see": "saw", "do": "did", "take": "took",
    "come": "came", "get": "got", "make": "made", "have": "had",
    "buy": "bought", "meet": "met", "run": "ran", "write": "wrote",
    "speak": "spoke", "give": "gave", "find": "found",
}
_BASE = {v: k for k, v in _PAST.items()}


@dataclass
class Correction:
    """一条纠错反馈。original 一定是用户原话的逐片子串。"""

    original: str
    corrected: str
    reason: str
    category: str
    rule_id: str = ""

    def as_dict(self) -> dict:
        return {
            "original": self.original,
            "corrected": self.corrected,
            "reason": self.reason,
            "type": self.category,
            "rule_id": self.rule_id,
        }


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    pattern: re.Pattern
    fix: object  # callable(match) -> tuple[str, str] | None
    category: str


def _compile(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


def _fix_am_agree(m: re.Match) -> tuple[str, str]:
    return "I agree", "agree 本身就是动词，前面不需要再加 am；I agree 就是完整说法"


def _fix_very_verb(m: re.Match) -> tuple[str, str]:
    return (f"really {m.group(1)}",
            "汉语的“很”不能直译成 very 修饰动词，英语用 really，"
            "或把 very much 放到句尾")


def _fix_third_person_dont(m: re.Match) -> tuple[str, str]:
    return (f"{m.group(1)} doesn't",
            "he/she/it 是第三人称单数，否定形式要用 doesn't，而不是 don't")


def _fix_past_tense(m: re.Match) -> tuple[str, str] | None:
    verb = m.group(2).lower()
    past = _PAST.get(verb)
    if not past:
        return None
    return (f"{m.group(1)} I {past}",
            "描述昨天/过去发生的事要用一般过去时，动词换成过去式")


def _fix_did_base(m: re.Match) -> tuple[str, str] | None:
    base = _BASE.get(m.group(1).lower())
    if not base:
        return None
    return (f"did you {base}",
            "did 已经表示过去，后面的动词要用原形")


def _fix_drop_trailing(m: re.Match, drop: str, reason: str) -> tuple[str, str]:
    text = m.group(0)
    fixed = re.sub(drop, "", text, flags=re.IGNORECASE)
    return fixed, reason


def _fix_although_but(m: re.Match) -> tuple[str, str]:
    return _fix_drop_trailing(m, r",\s*but\b",
                              "although 和 but 都表示转折，英语里只能用一个")


def _fix_because_so(m: re.Match) -> tuple[str, str]:
    return _fix_drop_trailing(m, r",\s*so\b",
                              "because 和 so 都表示因果，英语里只能用一个")


def _fix_married(m: re.Match) -> tuple[str, str]:
    return "married to", "表示“与某人结婚”用 be married to，是固定搭配"


def _fix_listen(m: re.Match) -> tuple[str, str]:
    return f"listen to {m.group(1)}", "listen 是不及物动词，接宾语时要加 to"


def _fix_age(m: re.Match) -> tuple[str, str]:
    return (f"I am {m.group(1)} years old",
            "表达年龄用 be 动词（I am ... years old）；have 表示“拥有”")


def _fix_most(m: re.Match) -> tuple[str, str]:
    return (f"most {m.group(1)}",
            "most 可以直接接复数名词；most of 后面必须接 the/these/my 等限定词")


def _fix_uncountable(word: str):
    def fix(m: re.Match) -> tuple[str, str]:
        return word, f"{word} 是不可数名词，没有复数形式"
    return fix


def _fix_arrive(m: re.Match) -> tuple[str, str]:
    return "arrive at", "arrive 后面接小地点用 at、接大地点用 in，不用 to"


def _fix_preposition(replacement: str, reason: str):
    def fix(m: re.Match) -> tuple[str, str]:
        return replacement, reason
    return fix


def _fix_weekday(m: re.Match) -> tuple[str, str]:
    return f"on {m.group(1)}", "具体某一天（星期几）前面用介词 on"


def _fix_according(m: re.Match) -> tuple[str, str]:
    return ("in my opinion",
            "according to 表示“根据……”；表达“我认为”要用 in my opinion")


def _fix_want_to(m: re.Match) -> tuple[str, str]:
    return f"I want to {m.group(1)}", "want 后面接动词时要加 to（want to do）"


def _fix_more_comparative(m: re.Match) -> tuple[str, str]:
    return m.group(1), "这是比较级形容词，前面不能再加 more（双重比较）"


def _fix_one_of(m: re.Match) -> tuple[str, str]:
    return (f"{m.group(0)}s",
            "one of 后面接复数名词：……之一")


def _fix_how_to_say(m: re.Match) -> tuple[str, str]:
    return "How do you say", "“这个怎么说”要用完整问句 How do you say ...?"


def _fix_turn_on(m: re.Match) -> tuple[str, str]:
    return f"turn on the {m.group(1)}", "灯、电视等电器用 turn on；open 用于门窗、书本"


def _fix_turn_off(m: re.Match) -> tuple[str, str]:
    return f"turn off the {m.group(1)}", "灯、电视等电器用 turn off；close 用于门窗"


def _fix_eat_medicine(m: re.Match) -> tuple[str, str]:
    return "take medicine", "“吃药”的固定搭配是 take medicine"


def _fix_do_research(m: re.Match) -> tuple[str, str]:
    return "do research", "“做研究”的固定搭配是 do research"


def _fix_since_for(m: re.Match) -> tuple[str, str]:
    num, unit = m.group(1), m.group(2)
    return (f"for {num} {unit}s",
            "since 接时间点（since 2020），for 接时间段（for three years）")


_RULES: list[_Rule] = [
    _Rule("be_agree", _compile(r"\b(?:i\s+am|i'm)\s+agree\b"),
          _fix_am_agree, "grammar"),
    _Rule("very_verb", _compile(r"\bvery\s+(like|enjoy|love|miss|hate|want|need)\b"),
          _fix_very_verb, "expression"),
    _Rule("third_person_dont", _compile(r"\b(he|she|it)\s+don'?t\b"),
          _fix_third_person_dont, "grammar"),
    _Rule("past_tense", _compile(
        r"\b(yesterday|last\s+(?:night|week|month|year)|this\s+morning)\s+i\s+"
        r"(go|eat|see|do|take|come|get|make|have|meet|buy|run|write|speak|give|find)\b"),
        _fix_past_tense, "grammar"),
    _Rule("did_base", _compile(
        r"\bdid\s+you\s+(went|ate|saw|did|took|came|got|made|had|met|bought|ran|wrote|spoke|gave|found)\b"),
        _fix_did_base, "grammar"),
    _Rule("although_but", _compile(r"\balthough\b[^.?!]{1,80}?,\s*but\b"),
          _fix_although_but, "grammar"),
    _Rule("because_so", _compile(r"\bbecause\b[^.?!]{1,80}?,\s*so\b"),
          _fix_because_so, "grammar"),
    _Rule("discuss_about", _compile(r"\bdiscuss\s+about\b"),
          _fix_preposition("discuss", "discuss 是及物动词，直接接宾语，不需要 about"), "word"),
    _Rule("married_with", _compile(r"\bmarried\s+with\b"),
          _fix_married, "word"),
    _Rule("listen_to", _compile(r"\blisten\s+(music|the\s+music|english|radio)\b"),
          _fix_listen, "expression"),
    _Rule("look_at", _compile(r"\blook\s+(this|that|it)\b"),
          _fix_preposition("look at", "表示“看某物”用 look at；单独 look 是不及物动词"), "expression"),
    _Rule("age_have", _compile(r"\bi\s+have\s+(\d{1,3})\s+years?\s+old\b"),
          _fix_age, "grammar"),
    _Rule("most_of_noun", _compile(r"\bmost\s+of\s+(people|students|teachers|my\s+friends|chinese\s+people)\b"),
          _fix_most, "grammar"),
    _Rule("uncountable", _compile(r"\b(advices|informations|homeworks|equipments|furnitures)\b"),
          lambda m: (m.group(1).rstrip("s") if not m.group(1).endswith("ces")
                     else m.group(1)[:-2] + "e",
                     f"{m.group(1).rstrip('s')} 类名词多为不可数，没有复数形式"),
          "word"),
    _Rule("arrive_to", _compile(r"\barrive\s+to\b"), _fix_arrive, "word"),
    _Rule("good_in", _compile(r"\b(good|bad)\s+in\b"),
          _fix_preposition("good at", "“擅长/不擅长”是 be good at / bad at，固定搭配"), "word"),
    _Rule("interested_on", _compile(r"\binterested\s+on\b"),
          _fix_preposition("interested in", "“对……感兴趣”是 be interested in，固定搭配"), "word"),
    _Rule("afraid_from", _compile(r"\bafraid\s+from\b"),
          _fix_preposition("afraid of", "“害怕……”是 be afraid of，固定搭配"), "word"),
    _Rule("depend_of", _compile(r"\bdepends?\s+of\b"),
          _fix_preposition("depend on", "“取决于”是 depend on，固定搭配"), "word"),
    _Rule("weekday_in", _compile(r"\bin\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"),
          _fix_weekday, "grammar"),
    _Rule("according_to_me", _compile(r"\baccording\s+to\s+me\b"),
          _fix_according, "expression"),
    _Rule("want_to_do", _compile(r"\bi\s+want\s+(go|play|eat|sleep|buy|visit|watch|learn|study)\b"),
          _fix_want_to, "grammar"),
    _Rule("more_comparative", _compile(
        r"\bmore\s+(easier|better|faster|cheaper|higher|lower|older|younger|bigger|smaller)\b"),
        _fix_more_comparative, "grammar"),
    _Rule("one_of_plural", _compile(
        r"\bone\s+of\s+the\s+\w+\s+(student|teacher|player|friend|book|city|country|company)\b"),
        _fix_one_of, "grammar"),
    _Rule("how_to_say", _compile(r"\bhow\s+to\s+say\b"), _fix_how_to_say, "expression"),
    _Rule("explain_me", _compile(r"\bexplain\s+me\b"),
          _fix_preposition("explain to me", "explain 接人作宾语时要加 to（explain sth to me）"), "word"),
    _Rule("turn_on", _compile(r"\bopen\s+the\s+(light|tv|radio|computer)\b"),
          _fix_turn_on, "word"),
    _Rule("turn_off", _compile(r"\bclose\s+the\s+(light|tv|radio|computer)\b"),
          _fix_turn_off, "word"),
    _Rule("eat_medicine", _compile(r"\beat\s+(?:the\s+)?medicine\b"),
          _fix_eat_medicine, "word"),
    _Rule("do_research", _compile(r"\bmake\s+(?:a\s+)?research\b"),
          _fix_do_research, "word"),
    _Rule("since_for", _compile(r"\bsince\s+(\d+|two|three|five|ten)\s+(year|month|week|day)s?\b"),
          _fix_since_for, "grammar"),
]


class RuleCorrector:
    """基于规则表的确定性纠错器。"""

    def __init__(self, rules: list[_Rule] | None = None) -> None:
        self.rules = rules if rules is not None else _RULES

    def check(self, text: str) -> list[Correction]:
        """返回用户输入中所有命中的纠错（同一文本内按规则去重）。"""
        if not text or not text.strip():
            return []
        results: list[Correction] = []
        seen: set[str] = set()
        for rule in self.rules:
            for match in rule.pattern.finditer(text):
                if rule.rule_id in seen:
                    continue
                outcome = rule.fix(match)
                if not outcome:
                    continue
                corrected, reason = outcome
                original = match.group(0).strip()
                if not corrected or not original:
                    continue
                seen.add(rule.rule_id)
                results.append(Correction(
                    original=original,
                    corrected=corrected,
                    reason=reason,
                    category=rule.category,
                    rule_id=rule.rule_id,
                ))
        return results
