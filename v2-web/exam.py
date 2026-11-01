"""exam.py —— CET-SET4 / CET-SET6 四六级口语考试仿真引擎。

官方结构（全国大学英语四、六级考试委员会，机考）：
  CET-SET4（约 15 分钟，5 个任务）
    Part1 自我介绍        每位 20 秒
    Part2 短文朗读        准备 45 秒，朗读 120 词短文，1 分钟
    Part3 简短回答        回答 2 个与短文相关的问题，40 秒
    Part4 个人陈述        准备 45 秒，陈述 1 分钟
    Part5 两人互动        准备 1 分钟，交谈 3 分钟
  CET-SET6（约 30 分钟，3 个部分）
    Part1 自我介绍 + 问答  自我介绍 20 秒，回答提问 30 秒
    Part2 陈述 + 讨论     准备 1 分钟，陈述 1 分 30 秒，讨论 3 分钟
    Part3 问答            回答一个问题，45 秒

评分采用官方六维标准：准确性、语言范围、话语长短、连贯性、灵活性、适切性。

两个设计取舍：
  1. 题目默认取自 papers/*.json 的仿真题库（四级 12 套 / 六级 10 套），
     秒开、可复现、离线可用；LLM 不可用时评分退化为规则计算，整套流程照样跑通。
  2. 朗读题不让模型"凭感觉"打准确度——本地做词级 Levenshtein 对齐算 WER，
     模型只负责流利度与表达层面的判断，避免打分幻觉。
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

# 复用 v1-desktop 里的 spoken 包（JSON 解析 / LLM 客户端）
_ROOT = Path(__file__).resolve().parent
_V1 = _ROOT.parent / "v1-desktop"
if _V1.is_dir() and str(_V1) not in sys.path:
    sys.path.insert(0, str(_V1))

from spoken.llm import LLMError, parse_json_robust  # noqa: E402

# ---------------------------------------------------------------------
# 官方六维评分维度
# ---------------------------------------------------------------------
DIMENSIONS: list[tuple[str, str, str]] = [
    ("accuracy", "准确性", "语音语调、语法与用词"),
    ("range", "语言范围", "词汇与句式的丰富度"),
    ("discourse", "话语长短", "展开是否充分、信息量是否够"),
    ("coherence", "连贯性", "逻辑层次与衔接手段"),
    ("flexibility", "灵活性", "临场应变、换个说法"),
    ("appropriateness", "适切性", "是否切题、符合身份场景"),
]

# ---------------------------------------------------------------------
# 考试结构（文案与时长全部对照官方表格）
# ---------------------------------------------------------------------
EXAM_SPECS: dict = {
    "cet4": {
        "key": "cet4",
        "name": "四级口语",
        "full_name": "大学英语四级口语考试",
        "code": "CET-SET4",
        "minutes": 15,
        "blurb": "5 个任务：自我介绍 → 短文朗读 → 简短回答 → 个人陈述 → 两人互动",
        "parts": [
            {"no": 1, "name": "自我介绍", "name_en": "Self-introduction", "span": "20 秒"},
            {"no": 2, "name": "短文朗读", "name_en": "Reading Aloud", "span": "45 秒准备 + 1 分钟"},
            {"no": 3, "name": "简短回答", "name_en": "Question & Answer", "span": "40 秒 / 2 题"},
            {"no": 4, "name": "个人陈述", "name_en": "Individual Presentation", "span": "45 秒准备 + 1 分钟"},
            {"no": 5, "name": "两人互动", "name_en": "Pair Interaction", "span": "1 分钟准备 + 3 分钟"},
        ],
        "tasks": [
            {
                "index": 0, "part": 1, "part_name": "自我介绍", "kind": "self_intro",
                "label": "自我介绍", "prep": 0, "answer": 20,
                "tip": "姓名、学校专业、一个爱好。一句话讲一件事，别背长句——20 秒只够说三句。",
            },
            {
                "index": 1, "part": 2, "part_name": "短文朗读", "kind": "reading",
                "label": "朗读短文", "prep": 45, "answer": 60,
                "tip": "准备时间先通读一遍，标出句子断点和生词；朗读时宁可慢一点，也别在中途反复重读。",
            },
            {
                "index": 2, "part": 3, "part_name": "简短回答", "kind": "qa",
                "label": "回答 2 个问题", "prep": 0, "answer": 40,
                "tip": "两题共 40 秒，每题两句话：先给立场，再给一个理由或例子。",
            },
            {
                "index": 3, "part": 4, "part_name": "个人陈述", "kind": "presentation",
                "label": "个人陈述", "prep": 45, "answer": 60,
                "tip": "按提示卡逐条覆盖，开头一句总起，结尾一句收口；不要只讲一个点。",
            },
            {
                "index": 4, "part": 5, "part_name": "两人互动", "kind": "interaction",
                "label": "与 AI 搭档互动", "prep": 60, "answer": 180,
                "tip": "AI 扮演你的搭档。真实考试里互动分看的是「有没有来回」——主动提问、回应对方、一起做决定。",
            },
        ],
    },
    "cet6": {
        "key": "cet6",
        "name": "六级口语",
        "full_name": "大学英语六级口语考试",
        "code": "CET-SET6",
        "minutes": 30,
        "blurb": "3 个部分：自我介绍与问答 → 陈述与讨论 → 追问，考深度表达与互动",
        "parts": [
            {"no": 1, "name": "自我介绍与问答", "name_en": "Self-introduction & Q&A", "span": "20 秒 + 30 秒"},
            {"no": 2, "name": "陈述和讨论", "name_en": "Presentation & Discussion", "span": "1 分钟准备 + 90 秒 + 3 分钟"},
            {"no": 3, "name": "问答", "name_en": "Follow-up Questions", "span": "45 秒"},
        ],
        "tasks": [
            {
                "index": 0, "part": 1, "part_name": "自我介绍与问答", "kind": "self_intro",
                "label": "自我介绍", "prep": 0, "answer": 20,
                "tip": "六级不只看信息，还看表达质量。一句身份 + 一句与考试相关的动机，比流水账更好。",
            },
            {
                "index": 1, "part": 1, "part_name": "自我介绍与问答", "kind": "exam_qa",
                "label": "回答考官提问", "prep": 0, "answer": 30,
                "tip": "30 秒只够 3 句：观点 + 理由 + 一个具体例子。六级考官只读一遍问题，注意听关键词。",
            },
            {
                "index": 2, "part": 2, "part_name": "陈述和讨论", "kind": "presentation",
                "label": "个人陈述", "prep": 60, "answer": 90,
                "tip": "90 秒要有结构：立场 → 两个理由（各带例子）→ 一句让步或总结。六级最忌只有观点没有支撑。",
            },
            {
                "index": 3, "part": 2, "part_name": "陈述和讨论", "kind": "discussion",
                "label": "与 AI 搭档讨论", "prep": 0, "answer": 180,
                "tip": "讨论不是各说各话：要接住搭档的观点、提出分歧、最后一起给结论。",
            },
            {
                "index": 4, "part": 3, "part_name": "问答", "kind": "followup",
                "label": "回答追问", "prep": 0, "answer": 45,
                "tip": "追问通常更深、更具体。45 秒给一个有层次的回答：承认复杂性，再给出你的判断。",
            },
        ],
    },
}

# ---------------------------------------------------------------------
# 内置题库（LLM 不可用 / 出题失败时兜底；也用于离线演示）
# ---------------------------------------------------------------------
# ---------------------------------------------------------------------
# 题库：papers/cet4.json / papers/cet6.json
# ---------------------------------------------------------------------
# 出题策略：题库优先（离线可复现、点开即用），想要新题时再让模型现出一套。
# 题库放在独立 JSON 里，方便持续扩充——加一套卷子只需往 JSON 的 papers 里追加一项，
# 不用改任何 Python 代码（字段格式见 papers/README 或本文件 _paper_ok）。
PAPERS_DIR = _ROOT / "papers"

# 题库文件缺失或损坏时的最小兜底，保证离线也能完整跑一场
_FALLBACK_PAPERS: dict = {
    "cet4": [
        {
            "id": "fallback-cet4",
            "title": "Reading Before Bed",
            "tags": ["学习"],
            "reading": {
                "title": "Reading Before Bed",
                "passage": (
                    "Many students say they have no time to read. Yet reading for "
                    "fifteen minutes before bed can change more than you expect. "
                    "Unlike a phone screen, a printed page does not keep sending "
                    "you alerts, so your mind slows down and your thoughts settle. "
                    "A story also gives your brain something to build, and over a "
                    "term that quiet habit adds up to thousands of new words. You "
                    "do not need a reading list. Pick one book and open it tonight."
                ),
                "questions": [
                    "Why does the speaker compare reading with looking at a phone screen?",
                    "What does the speaker suggest you do to start the habit?",
                ],
            },
            "presentation": {
                "topic": "A skill you would like to learn",
                "points": [
                    "What the skill is and why it interests you",
                    "How you would go about learning it",
                    "How it might help you in the future",
                ],
                "prompt": "Describe a skill you would like to learn. You have one minute.",
            },
            "interaction": {
                "situation": "Your class is planning a one-day trip before graduation.",
                "task": "Decide where to go, how to get there, and what to bring.",
                "partner_role": "a classmate who is helping you organize the trip",
            },
        }
    ],
    "cet6": [
        {
            "id": "fallback-cet6",
            "title": "AI and the Job Market",
            "tags": ["科技", "就业"],
            "exam_qa": [
                "Some people worry that artificial intelligence will take away many jobs. What is your opinion?",
                "How should university students prepare for a job market shaped by AI?",
            ],
            "presentation": {
                "topic": "Will AI create more jobs than it destroys?",
                "points": [
                    "Your overall position",
                    "Which kinds of jobs are most likely to change",
                    "What individuals and schools should do about it",
                ],
                "prompt": "Give a one-and-a-half-minute presentation on the topic. You have one minute to prepare.",
            },
            "discussion": {
                "task": "Discuss with your partner how universities should change what they teach because of AI.",
                "partner_role": "another candidate who partly disagrees with you",
            },
            "followup": [
                "If you could design one course about AI for all students, what would it cover and why?",
            ],
        }
    ],
}


def _paper_ok(paper, level: str) -> bool:
    """题库单套的结构校验：不合格的卷子直接跳过，不让它把考试搞崩。"""
    try:
        if not isinstance(paper.get("presentation", {}).get("topic"), str):
            return False
        if level == "cet4":
            reading = paper["reading"]
            return (isinstance(reading.get("passage"), str)
                    and len(tokenize_words(reading["passage"])) >= 60
                    and len(reading.get("questions") or []) >= 2
                    and isinstance(paper.get("interaction"), dict))
        return (len(paper.get("exam_qa") or []) >= 1
                and isinstance(paper.get("discussion"), dict)
                and len(paper.get("followup") or []) >= 1)
    except (KeyError, TypeError, AttributeError):
        return False


def load_bank(level: str) -> list[dict]:
    """读取某级别的题库。文件缺失/损坏时退回最小兜底卷。

    不做缓存：文件只有几 KB，每次读一次的开销可忽略，
    换来的是「改完 JSON 刷新页面就生效」，方便自己加题。
    """
    path = PAPERS_DIR / f"{level}.json"
    papers: list[dict] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("papers", []) if isinstance(data, dict) else data
        if isinstance(raw, list):
            papers = [p for p in raw if isinstance(p, dict) and _paper_ok(p, level)]
    except (OSError, ValueError, TypeError):
        papers = []
    return papers or [dict(p) for p in _FALLBACK_PAPERS.get(level, [])]


def list_papers(level: str) -> list[dict]:
    """题库目录（给前端选题用）：套号、标题、话题标签。"""
    items = []
    for paper in load_bank(level):
        if level == "cet4":
            title = paper.get("reading", {}).get("title") or paper.get("title", "")
            summary = paper.get("reading", {}).get("passage", "")[:96]
        else:
            title = paper.get("presentation", {}).get("topic") or paper.get("title", "")
            summary = (paper.get("exam_qa") or [""])[0]
        items.append({
            "id": str(paper.get("id") or ""),
            "title": title,
            "tags": list(paper.get("tags") or []),
            "summary": summary,
        })
    return items


def find_paper(level: str, paper_id: str) -> dict | None:
    for paper in load_bank(level):
        if str(paper.get("id")) == str(paper_id):
            return paper
    return None


def bank_size(level: str) -> int:
    return len(load_bank(level))


# ---------------------------------------------------------------------
# 文本处理与朗读客观比对
# ---------------------------------------------------------------------
_WORD_RE = re.compile(r"[a-z0-9']+")
_SENT_SPLIT = re.compile(r"[.!?]+")
_LINKERS = (
    "because", "however", "although", "though", "therefore", "instead",
    "actually", "for example", "for instance", "in addition",
    "on the other hand", "as a result", "what's more", "what is more",
    "in other words", "that is why", "all in all", "to be honest",
    "first of all", "first", "second", "finally", "besides", "whereas",
    "nevertheless", "in fact", "of course", "so",
)


def tokenize_words(text: str) -> list[str]:
    """切词：小写、只保留字母数字与撇号。用于 WER 与语速统计。"""
    return _WORD_RE.findall((text or "").lower())


def word_error_rate(reference: str, hypothesis: str) -> dict:
    """词级 Levenshtein 对齐，返回 WER 及读错/漏读/多读的词。

    WER = (替换 + 删除 + 插入) / 参考词数。朗读题用它给「准确度」客观分，
    避免让语言模型猜考生的发音。
    """
    ref = tokenize_words(reference)
    hyp = tokenize_words(hypothesis)
    n, m = len(ref), len(hyp)
    if n == 0:
        return {"wer": 1.0, "accuracy": 0.0, "ref_words": 0, "errors": 0,
                "substitutions": 0, "deletions": 0, "insertions": 0,
                "missed": [], "extra": [], "matched": 0}

    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        ri = ref[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ri == hyp[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j - 1] + cost,
                           dp[i - 1][j] + 1,
                           dp[i][j - 1] + 1)

    i, j = n, m
    sub = dele = ins = 0
    missed: list[str] = []
    extra: list[str] = []
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            if dp[i][j] == dp[i - 1][j - 1] + cost:
                if cost:
                    sub += 1
                    missed.append(ref[i - 1])
                    extra.append(hyp[j - 1])
                i, j = i - 1, j - 1
                continue
        if i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            dele += 1
            missed.append(ref[i - 1])
            i -= 1
        else:
            ins += 1
            extra.append(hyp[j - 1])
            j -= 1

    errors = sub + dele + ins
    wer = errors / n
    return {
        "wer": round(wer, 4),
        "accuracy": round(max(0.0, 1 - wer), 4),
        "ref_words": n,
        "errors": errors,
        "substitutions": sub,
        "deletions": dele,
        "insertions": ins,
        "matched": n - sub - dele,
        "missed": missed[:12],
        "extra": extra[:12],
    }


def _wer_to_score(wer: float) -> int:
    """WER → 1-5 分。错 0% 得 5 分，错 10% 得 4.2，错 50% 得 1 分。"""
    return max(1, min(5, round(5 - wer * 8)))


def _count_linkers(words: list[str]) -> int:
    text = " " + " ".join(words) + " "
    return sum(text.count(f" {l} ") for l in _LINKERS)


def _strip_speaker_tags(text: str) -> str:
    """去掉互动任务里的 Candidate / Partner 角色标签，避免污染词数统计。"""
    return re.sub(r"(?i)\b(candidate|partner)\s*:", " ", text or "").strip()


# ---------------------------------------------------------------------
# 生成题目
# ---------------------------------------------------------------------
_PAPER_PROMPT = {
    "cet4": """你是 CET-SET4（大学英语四级口语）的命题人。请生成一套完整考题，严格只输出 JSON：
{
  "reading": {
    "title": "英文短标题（4 词以内）",
    "passage": "约 120 个英文单词的短文，3-4 段合并成一段连续文本",
    "questions": ["与短文相关的问题 1", "与短文相关的问题 2"]
  },
  "presentation": {
    "topic": "个人陈述主题（一个短语）",
    "points": ["提示点 1", "提示点 2", "提示点 3"],
    "prompt": "一句话英文指令"
  },
  "interaction": {
    "situation": "两人互动的情景（英文，1-2 句）",
    "task": "两人需要共同完成的任务（英文，1 句）",
    "partner_role": "搭档身份（英文短语，如 a classmate）"
  }
}
要求：
- 话题贴近四六级常考范围：校园生活、科技、环境、健康、文化、旅行、职场
- 短文 110-130 词，难度相当于四级阅读，不要出现生僻专有名词
- 两个问题分别考查「细节理解」和「观点延伸」，都能用一两句话回答
- 个人陈述给 3 个提示点，像真实考试的提示卡
- 全部用英文，不要中文解释""",
    "cet6": """你是 CET-SET6（大学英语六级口语）的命题人。请生成一套完整考题，严格只输出 JSON：
{
  "exam_qa": ["考官问题 1（社会话题，有讨论空间）", "考官问题 2（与问题 1 相关但更具体）"],
  "presentation": {
    "topic": "个人陈述主题（一个英文短语）",
    "points": ["提示点 1", "提示点 2", "提示点 3"],
    "prompt": "一句话英文指令，注明 1 分 30 秒"
  },
  "discussion": {
    "task": "两人讨论需要共同达成的结论（英文，1 句）",
    "partner_role": "搭档立场（英文短语，如 a candidate who partly disagrees with you）"
  },
  "followup": ["一个更深的追问（英文）"]
}
要求：
- 话题要有思辨空间：AI 与就业、教育公平、城市生活、媒体素养、职业选择等
- 问题不能是「是/否」就能答完的，要能引出理由与例子
- 陈述的 3 个提示点要有递进：立场 → 支撑 → 对策
- 全部用英文，不要中文解释""",
}


class ExamEngine:
    """一场口语考试。一个实例 = 一张卷子 + 逐步作答记录。"""

    def __init__(self, llm, level: str = "cet4", seed: int | None = None,
                 paper_id: str | None = None, source: str = "auto") -> None:
        if level not in EXAM_SPECS:
            raise ValueError(f"不支持的考试级别：{level}")
        self.llm = llm
        self.level = level
        self.spec = EXAM_SPECS[level]
        self.tasks: list[dict] = [dict(t) for t in self.spec["tasks"]]
        self.rng = random.Random(seed)
        self.paper_id = paper_id
        # auto：模型现出优先，失败回退题库；bank：直接抽题库；ai：只用模型
        self.source = source if source in ("auto", "bank", "ai") else "auto"
        self.paper: dict = {}
        self.paper_source = "bank"
        self.paper_meta: dict = {}
        self.results: dict[int, dict] = {}   # index -> 评分结果
        self.answers: dict[int, dict] = {}   # index -> {text, duration}
        # 两人互动类任务额外产生的对话记录（AI 搭档台词）
        self.dialogue: dict[int, list[dict]] = {}

    # -- 内部：调用模型并解析 JSON -------------------------------------
    def _chat_json(self, system: str, user: str, purpose: str = "exam") -> dict:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        raw = self.llm.chat(messages, purpose=purpose)
        try:
            return parse_json_robust(raw)
        except LLMError:
            messages.append({
                "role": "user",
                "content": "上一次输出不是合法 JSON。请只输出一个 JSON 对象，"
                           "不要解释文字，不要 markdown 代码块。",
            })
            raw = self.llm.chat(messages, purpose=purpose)
            return parse_json_robust(raw)

    # -- 出题 ---------------------------------------------------------
    def prepare(self) -> None:
        """出卷，优先级：指定套号 > 模型现出（source=auto/ai）> 题库随机。

        题库模式（默认）秒开、可复现、离线可用；想要没见过的新题时用 source=ai。
        """
        if self.paper_id:
            paper = find_paper(self.level, self.paper_id)
            if paper is not None:
                self._adopt(paper, "bank")
                return
        if self.source in ("auto", "ai"):
            try:
                paper = self._chat_json(_PAPER_PROMPT[self.level],
                                        f"请生成一套 {self.spec['code']} 考题。")
                if self._paper_valid(paper):
                    self._adopt(paper, "llm")
                    return
            except Exception:  # noqa: BLE001
                pass
        self._adopt(self.rng.choice(load_bank(self.level)), "bank")

    def _adopt(self, paper: dict, source: str) -> None:
        """把一张卷子挂到本次考试上，并记下它的元信息（套号/标题/标签）。"""
        self.paper = paper
        self.paper_source = source
        title = ((paper.get("reading") or {}).get("title")
                 or paper.get("title")
                 or (paper.get("presentation") or {}).get("topic", ""))
        self.paper_meta = {
            "id": str(paper.get("id") or ""),
            "title": title,
            "tags": list(paper.get("tags") or []),
        }

    def _paper_valid(self, paper: dict) -> bool:
        return _paper_ok(paper, self.level)

    # -- 题目载荷（给前端渲染） ---------------------------------------
    def payload(self, index: int) -> dict:
        task = self.tasks[index]
        kind = task["kind"]
        prompt = ""
        detail: dict = {}

        if kind == "self_intro":
            if self.level == "cet4":
                prompt = "Please introduce yourself briefly: your name, your school or major, and what you like doing in your free time."
            else:
                prompt = "Please introduce yourself briefly, and say why you are taking the CET-SET6 test."
            detail = {"hints": ["name", "school / major", "interest or reason"]}
        elif kind == "reading":
            reading = self.paper["reading"]
            prompt = "Read the passage below aloud. You have 45 seconds to prepare."
            detail = {"title": reading.get("title", ""),
                      "passage": reading.get("passage", "")}
        elif kind == "qa":
            prompt = "Answer the two questions about the passage you have just read."
            detail = {"questions": self.paper["reading"].get("questions", [])}
        elif kind == "presentation":
            pres = self.paper["presentation"]
            prompt = pres.get("prompt") or "Give a short presentation on the topic below."
            detail = {"topic": pres.get("topic", ""),
                      "points": pres.get("points", [])}
        elif kind == "interaction":
            inter = self.paper["interaction"]
            prompt = "Talk with your partner and complete the task together."
            detail = {"situation": inter.get("situation", ""),
                      "task": inter.get("task", ""),
                      "partner_role": inter.get("partner_role", "your partner")}
        elif kind == "exam_qa":
            prompt = "Listen to the examiner's question and answer it."
            detail = {"questions": self.paper.get("exam_qa", [])[:1]}
        elif kind == "discussion":
            disc = self.paper["discussion"]
            prompt = "Discuss the task with your partner and reach a conclusion together."
            detail = {"task": disc.get("task", ""),
                      "partner_role": disc.get("partner_role", "your partner")}
        elif kind == "followup":
            prompt = "Answer the examiner's follow-up question."
            detail = {"questions": self.paper.get("followup", [])[:1]}

        return {
            "index": index,
            "total": len(self.tasks),
            "part": task["part"],
            "part_name": task["part_name"],
            "label": task["label"],
            "kind": kind,
            "prep": task["prep"],
            "answer": task["answer"],
            "tip": task["tip"],
            "prompt": prompt,
            "detail": detail,
            "source": self.paper_source,
        }

    # -- 评分 ---------------------------------------------------------
    def submit(self, index: int, text: str, duration: float) -> dict:
        """记录一次作答并评分。返回 {result, next, finished}。"""
        task = self.tasks[index]
        text = (text or "").strip()
        duration = max(1.0, float(duration or task["answer"]))
        self.answers[index] = {"text": text, "duration": duration}

        if not text:
            result = self._empty_result(task)
        else:
            result = self._score(task, text, duration)
        result["index"] = index
        result["label"] = task["label"]
        result["answer"] = text
        result["duration"] = round(duration, 1)
        result["words"] = len(tokenize_words(_strip_speaker_tags(text)))
        self.results[index] = result

        nxt = index + 1
        finished = nxt >= len(self.tasks)
        return {
            "result": result,
            "next": None if finished else self.payload(nxt),
            "finished": finished,
        }

    def _empty_result(self, task: dict) -> dict:
        return {
            "scores": {d[0]: 1 for d in DIMENSIONS},
            "level": "D",
            "score_pct": 0.0,
            "comment": "这一段没有检测到有效回答。如果是麦克风或识别问题，可以重录一次；"
                       "真实考试中沉默会被判为未作答。",
            "strengths": [],
            "improvements": ["先保证开口：哪怕只说两句，也比沉默得分高"],
            "better_version": "",
            "source": "rule",
        }

    def _score(self, task: dict, text: str, duration: float) -> dict:
        kind = task["kind"]
        wer_info = None
        if kind == "reading":
            wer_info = word_error_rate(self.paper["reading"].get("passage", ""), text)
        try:
            result = self._llm_score(task, text, duration, wer_info)
        except Exception:  # noqa: BLE001
            result = self._rule_score(task, text, duration, wer_info)
        if kind == "reading" and wer_info:
            # 朗读的准确度由客观 WER 决定，覆盖模型的主观判断
            result["scores"]["accuracy"] = _wer_to_score(wer_info["wer"])
            result["wer"] = wer_info
        result["score_pct"] = _pct(result["scores"])
        result["level"] = _grade(result["score_pct"])
        return result

    def _llm_score(self, task: dict, text: str, duration: float,
                   wer_info: dict | None) -> dict:
        dims = "\n".join(f"- {k} {zh}：{desc}" for k, zh, desc in DIMENSIONS)
        wer_block = ""
        if wer_info:
            wer_block = (
                f"\n客观朗读比对（本地计算，请勿推翻）：词错误率 WER={wer_info['wer']:.1%}，"
                f"共 {wer_info['ref_words']} 词，替换 {wer_info['substitutions']}、"
                f"漏读 {wer_info['deletions']}、多读 {wer_info['insertions']}。"
                f"读错的词：{', '.join(wer_info['missed'][:8]) or '无'}。"
                f"准确度一项已由 WER 决定，你只需评估其余五项。"
            )
        system = f"""你是 {self.spec['full_name']}（{self.spec['code']}）的考官，按官方评分标准打分。
官方六维标准（每项 1-5 分整数）：
{dims}

评分原则：
- 1 分 = 几乎无法完成任务；3 分 = 基本完成任务但明显不足；5 分 = 接近母语者的自然表达
- 参考真实考试水位：多数考生在 2.5-3.5 分区间，5 分只给真正出色的回答
- 任务未完成（比如问两个问题只答了一个、陈述漏掉提示点）要在 appropriateness 上体现
- 识别文本可能有语音识别误差；判断为识别问题而非考生错误时，不要扣分

只输出 JSON：
{{"scores": {{"accuracy": n, "range": n, "discourse": n, "coherence": n, "flexibility": n, "appropriateness": n}},
  "comment": "2-3 句中文总体点评，先说做得好的，再说最该改的一点",
  "strengths": ["具体亮点，中文，1-2 条"],
  "improvements": ["具体可执行的改进，中文，2-3 条"],
  "better_version": "把考生的回答改写成更地道的英文版本（保持原意，长度相近；考生没说的内容不要硬加）"}}

本场考试话题背景：{self._topic_context()}"""

        question = self._question_text(task)
        # 互动任务的提交内容带 Candidate / Partner 角色标签，评分要说明这是对话记录
        is_dialogue = "Partner:" in text
        answer_label = ("考生与搭档的对话记录（Candidate 为考生，Partner 为搭档；"
                        "请据此判断考生有没有接住搭档的话、有没有推进任务）"
                        if is_dialogue else "考生回答（语音识别文本）")
        user = (f"任务：{task['part_name']} · {task['label']}\n"
                f"题目：{question}\n"
                f"考生发言录音时长约 {duration:.0f} 秒，"
                f"识别文本 {len(tokenize_words(_strip_speaker_tags(text)))} 词。\n"
                f"{answer_label}：\n{text}{wer_block}")

        data = self._chat_json(system, user, purpose="exam")
        raw_scores = data.get("scores")
        # 模型偶尔会返回结构对但字段缺失的 JSON（比如只给一段点评）。
        # 少于 4 个维度视为评分失败，交给规则评分兜底，而不是给一串假 3 分。
        if not isinstance(raw_scores, dict):
            raise LLMError("评分结果缺少 scores 字段")
        valid_keys = {k for k, _zh, _d in DIMENSIONS}
        if len([k for k in raw_scores if k in valid_keys]) < 4:
            raise LLMError("评分维度不完整")

        scores = {}
        for key, _zh, _desc in DIMENSIONS:
            try:
                scores[key] = max(1, min(5, int(round(float(raw_scores.get(key, 3))))))
            except (TypeError, ValueError):
                scores[key] = 3
        return {
            "scores": scores,
            "comment": str(data.get("comment") or "").strip(),
            "strengths": _as_list(data.get("strengths")),
            "improvements": _as_list(data.get("improvements")),
            "better_version": str(data.get("better_version") or "").strip(),
            "source": "llm",
        }

    def _question_text(self, task: dict) -> str:
        kind = task["kind"]
        paper = self.paper
        if kind == "self_intro":
            return "Introduce yourself briefly."
        if kind == "reading":
            return f"Read aloud: {paper['reading'].get('title', '')}"
        if kind == "qa":
            return " / ".join(paper["reading"].get("questions", []))
        if kind == "presentation":
            pres = paper.get("presentation", {})
            return f"{pres.get('topic', '')}. Points: {'; '.join(pres.get('points', []))}"
        if kind == "interaction":
            inter = paper.get("interaction", {})
            return f"{inter.get('situation', '')} Task: {inter.get('task', '')}"
        if kind == "exam_qa":
            return " / ".join(paper.get("exam_qa", [])[:1])
        if kind == "discussion":
            return paper.get("discussion", {}).get("task", "")
        if kind == "followup":
            return " / ".join(paper.get("followup", [])[:1])
        return ""

    def _topic_context(self) -> str:
        paper = self.paper
        if self.level == "cet4":
            return (f"短文主题：{paper.get('reading', {}).get('title', '')}；"
                    f"个人陈述：{paper.get('presentation', {}).get('topic', '')}")
        return f"话题：{paper.get('presentation', {}).get('topic', '')}"

    def _rule_score(self, task: dict, text: str, duration: float,
                    wer_info: dict | None) -> dict:
        """离线兜底评分：只用语速、词量、词汇丰富度、连接词等可计算指标。

        明确标注为「离线简评」，不假装是考官判断。
        """
        words = tokenize_words(_strip_speaker_tags(text))
        n = len(words)
        vocab = len(set(words))
        answer_sec = max(task["answer"], 5)
        expected = max(8.0, answer_sec / 60 * 115)   # 115 词/分钟为参考语速
        fill = n / expected
        wpm = n / max(duration, 3) * 60
        unique_ratio = vocab / n if n else 0
        linkers = _count_linkers(words)

        scores = {d[0]: 3 for d in DIMENSIONS}
        if wer_info:
            scores["accuracy"] = _wer_to_score(wer_info["wer"])
        else:
            # 无参照文本时，用平均句长粗估：超短句堆砌说明组织能力弱
            sents = [s for s in _SENT_SPLIT.split(text) if s.strip()]
            avg_len = n / max(len(sents), 1)
            scores["accuracy"] = 4 if 6 <= avg_len <= 22 else 3
        scores["discourse"] = 5 if fill >= 0.95 else 4 if fill >= 0.7 else 3 if fill >= 0.45 else 2
        # 短回答里「不同词比例」天然偏高（25 词里 23 个不同 = 92%），
        # 所以给高分必须同时满足绝对词汇量，否则会虚高。
        if unique_ratio >= 0.62 and vocab >= 45:
            scores["range"] = 5
        elif unique_ratio >= 0.55 and vocab >= 30:
            scores["range"] = 4
        elif unique_ratio >= 0.45:
            scores["range"] = 3
        else:
            scores["range"] = 2
        scores["coherence"] = 5 if linkers >= 4 else 4 if linkers >= 2 else 3 if linkers >= 1 else 2
        scores["flexibility"] = 4 if linkers >= 3 and n >= expected * 0.6 else 3
        scores["appropriateness"] = 4 if fill >= 0.6 else 3 if fill >= 0.3 else 2

        tips = []
        if fill < 0.7:
            tips.append(f"内容偏短：{answer_sec} 秒的任务你只说了 {n} 词（约 {wpm:.0f} 词/分），"
                        f"目标至少 {int(expected)} 词。先把「观点 + 理由 + 例子」三段说完")
        if linkers < 2:
            tips.append("衔接词太少：试着用 because / however / for example / what's more 把句子串起来")
        if unique_ratio < 0.5 and n > 20:
            tips.append("重复用词偏多：同一意思换一种说法，能明显拉高「语言范围」分")
        if not tips:
            tips.append("结构完整，下一步重点打磨发音与语调（离线模式无法评估语音）")

        highlights = []
        if fill >= 0.9:
            highlights.append(f"内容量到位：{n} 词，约 {wpm:.0f} 词/分")
        if linkers >= 2:
            highlights.append(f"有衔接意识：使用了 {linkers} 处连接词")
        if wer_info and wer_info["wer"] <= 0.15:
            highlights.append(f"朗读准确：词错误率仅 {wer_info['wer']:.1%}")

        return {
            "scores": scores,
            "comment": f"离线简评（未连接语言模型）：说了 {n} 词，约 {wpm:.0f} 词/分，"
                       f"词汇丰富度 {unique_ratio:.0%}，衔接词 {linkers} 处。",
            "strengths": highlights,
            "improvements": tips,
            "better_version": "",
            "source": "rule",
        }

    # -- 整场报告 -----------------------------------------------------
    def report(self) -> dict:
        parts = [self.results[i] for i in sorted(self.results)]
        dims: dict[str, float] = {}
        for key, _zh, _desc in DIMENSIONS:
            vals = [p["scores"].get(key, 0) for p in parts if p.get("scores")]
            dims[key] = round(sum(vals) / len(vals), 2) if vals else 0.0
        overall = _pct(dims) if dims else 0.0

        issues: list[str] = []
        for p in parts:
            for item in p.get("improvements", []):
                if item and item not in issues:
                    issues.append(item)

        weakest = min(DIMENSIONS, key=lambda d: dims.get(d[0], 0)) if dims else DIMENSIONS[0]
        strongest = max(DIMENSIONS, key=lambda d: dims.get(d[0], 0)) if dims else DIMENSIONS[0]

        return {
            "level_key": self.level,
            "level_name": self.spec["full_name"],
            "code": self.spec["code"],
            "grade": _grade(overall),
            "score": round(overall, 1),
            "dimensions": [{"key": k, "name": zh, "desc": desc,
                            "score": dims.get(k, 0.0),
                            "pct": round((dims.get(k, 0) - 1) / 4 * 100, 1)}
                           for k, zh, desc in DIMENSIONS],
            "parts": [{
                "index": p["index"],
                "label": p["label"],
                "level": p.get("level", ""),
                "score": p.get("score_pct", 0),
                "comment": p.get("comment", ""),
                "strengths": p.get("strengths", []),
                "improvements": p.get("improvements", []),
                "better_version": p.get("better_version", ""),
                "answer": p.get("answer", ""),
                "words": p.get("words", 0),
                "duration": p.get("duration", 0),
                "wer": p.get("wer"),
            } for p in parts],
            "strongest": {"key": strongest[0], "name": strongest[1],
                          "score": dims.get(strongest[0], 0)},
            "weakest": {"key": weakest[0], "name": weakest[1],
                        "score": dims.get(weakest[0], 0)},
            "issues": issues[:6],
            "advice": _advice_for(weakest[0], self.level),
            # 有任何一段是规则评分就算「部分离线」，前端据此提示用户
            "offline": not any(p.get("source") == "llm" for p in parts) if parts else True,
            "paper_source": self.paper_source,
            "paper": self.paper_meta,
        }

    # -- 对话式任务（两人互动 / 讨论）：AI 扮演搭档 ---------------------
    def partner_reply(self, index: int, text: str) -> str:
        """AI 以搭档身份回应一句，推动互动任务。仅用于互动/讨论类任务。"""
        task = self.tasks[index]
        if task["kind"] not in ("interaction", "discussion"):
            return ""
        history = self.dialogue.setdefault(index, [])
        history.append({"role": "user", "content": text})
        if task["kind"] == "interaction":
            inter = self.paper.get("interaction", {})
            scene = f"情景：{inter.get('situation', '')}\n任务：{inter.get('task', '')}"
            role = inter.get("partner_role", "your partner")
        else:
            disc = self.paper.get("discussion", {})
            scene = f"讨论任务：{disc.get('task', '')}"
            role = disc.get("partner_role", "your partner")
        system = (
            f"你在 CET-SET 口试中扮演考生的对话搭档（{role}）。{scene}\n"
            "规则：\n"
            "1. 只说 1-2 句英文，口语化，像真人对话，不要旁白和解释\n"
            "2. 必须接着考生上一句说，或提出一个新问题推动任务\n"
            "3. 不要替考生做决定，要邀请他表达意见\n"
            "4. 不要评价考生的英语水平，你只是搭档不是考官"
        )
        messages = [{"role": "system", "content": system}] + history[-8:]
        try:
            reply = self.llm.chat(messages, purpose="exam")
        except Exception:  # noqa: BLE001
            reply = ""
        reply = (reply or "").strip().strip('"')
        if not reply:
            reply = "That sounds reasonable. What do you think we should decide first?"
        history.append({"role": "assistant", "content": reply})
        return reply


# ---------------------------------------------------------------------
# 等级与建议
# ---------------------------------------------------------------------
def _pct(scores: dict) -> float:
    """六维 1-5 分 → 百分制。1 分 = 0，5 分 = 100。"""
    vals = [v for v in scores.values() if isinstance(v, (int, float))]
    if not vals:
        return 0.0
    mean = sum(vals) / len(vals)
    return round((mean - 1) / 4 * 100, 1)


def _grade(pct: float) -> str:
    """百分制 → 等级。3 分（基本完成任务）对应 50%，落在 C 档，符合真实考试水位。"""
    if pct >= 85:
        return "A"
    if pct >= 68:
        return "B"
    if pct >= 45:
        return "C"
    return "D"


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _advice_for(dim_key: str, level: str) -> list[str]:
    """按最弱维度给训练建议（规则文本，稳定可控）。"""
    table = {
        "accuracy": [
            "每天 10 分钟跟读：选一段 VOA 慢速或 BBC 6 Minute English，逐句模仿重音和停顿",
            "把常错音标出来单独练（中国学生高频：th / v-w / 长短元音 / 词尾 -s -ed）",
            "朗读题先用真题短文练「不回头重读」——考试里读错一个词就继续往下",
        ],
        "range": [
            "建立「同义替换表」：把 important / good / very 换成 3 个更精确的说法",
            "背搭配而不是单词：不是 learn，而是 learn from experience / learn by doing",
            "陈述题强迫自己用一次分词结构或定语从句，避免全是简单句",
        ],
        "discourse": [
            "用「观点 + 理由 + 例子」三句模板练每个话题，先保证长度再谈质量",
            "卡住时用 well / let me put it this way / what I mean is 争取思考时间，别沉默",
            "计时练习：60 秒必须说满 8-10 句，用手机录音回放数句数",
        ],
        "coherence": [
            "背 8 个万能衔接：first of all / what's more / however / as a result / to be honest / in that case / what's interesting is / all in all",
            "陈述开头先说结论，再分两点，最后一句收口——结构分是白送的",
            "互动中先回应对方（I see your point, but...）再讲自己的，别各说各话",
        ],
        "flexibility": [
            "练「换个说法」：听到不会的词，用解释代替（a person who... / a kind of...）",
            "准备 3 个可迁移的个人例子（一次失败、一个爱好、一个人），几乎所有话题都能套",
            "被问住时不要停：先重复问题争取时间，再给一个部分回答",
        ],
        "appropriateness": [
            "读题要读全：提示卡上的 3 个点必须都覆盖，漏一个直接掉档",
            "互动任务要「一起做决定」，不要单方面陈述自己的方案",
            "六级注意深度：不要只给常识性观点，要给判断和理由",
        ],
    }
    advice = list(table.get(dim_key, []))
    if level == "cet6":
        advice.append("六级互动权重更高：每次搭档发言后都要有实质回应，别只点头说 yes")
    else:
        advice.append("四级先求「说完整」：把每个任务的时间用满，比追求高级词汇更能提分")
    return advice
