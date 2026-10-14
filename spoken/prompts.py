"""Prompt 构建：系统提示、开场指令、总结指令、JSON 修复指令。"""

from __future__ import annotations

from .scenarios import get_difficulty, get_scenario

OPENING_INSTRUCTION = (
    "请开始对话：用你的第一句台词自然地打开这个场景。只输出规定的 JSON 对象。"
)

SUMMARY_INSTRUCTION = (
    "对话到此结束。请根据上面的完整对话记录，生成本次口语练习总结。"
    "只输出一个 JSON 对象（不要 markdown 代码块，不要其他文字），字段如下："
    '{"overall": "一两句中文总体评价", '
    '"suggestions": ["两条具体的中文练习建议"], '
    '"improvements": [{"issue": "最需要改进的点（中文）", "suggestion": "怎么改（中文）"}], '
    '"encouragement": "一句简短的英文鼓励"}'
)

JSON_REPAIR_INSTRUCTION = (
    "你上一条回复不是合法的 JSON。请严格按照系统提示中规定的字段，"
    "只输出一个 JSON 对象，不要使用 markdown 代码块，不要输出任何其他文字。"
)

# ------------------------------------------------------------------
# 跟读专项练习：按场景与难度生成练习句子
# ------------------------------------------------------------------
SHADOW_SENTENCES_SYSTEM = """你是英语口语教练，正在为「spoken」程序的跟读练习生成英文句子。

【要求】
- 句子必须紧扣给定场景，自然、口语化，适合大声跟读；
- 长度与难度匹配：初级 6-10 个词、简单句；中级 10-16 个词、含一个从句或连接；
  高级 14-22 个词、含习语或稍复杂结构；
- 每句都是完整、独立、地道的表达，避免生僻专有名词；
- 只输出 JSON，不要任何其他文字。

【输出格式】
{"sentences": ["句子1", "句子2", ...]}"""

SHADOW_SENTENCES_INSTRUCTION = (
    "请生成 {count} 句适合跟读练习的英文句子。只输出规定的 JSON 对象。"
)

# ------------------------------------------------------------------
# 生词本：查词 / 生词生成（新增调用场景，复用通义接入方式）
# ------------------------------------------------------------------
VOCAB_SYSTEM_PROMPT = """你是一个专业的英语词典与词汇教学助手，正在为「spoken」英语口语练习程序的智能生词本生成词条。

【目标】对给定的英文单词或短语，生成结构化、可直接用于学习的词条，包含四块：词头、词形变换（派生词）、近义/同词性对比、相关短语与搭配。

【输出 JSON 字段】
{
  "word": "单词或短语（保持原样，小写优先）",
  "phonetic": "音标（用 /.../ 包裹，如 /ˈwɜːd/，英式或美式均可）",
  "pos": "核心词性缩写，如 n. / v. / adj. / adv. / phr.",
  "definition_zh": "中文释义（简洁准确）",
  "derivations": [
    {"word": "派生词", "pos": "词性缩写", "definition_zh": "中文释义"}
  ],
  "contrast": [
    {
      "pos": "被对比的词性，如 adj. / v.",
      "items": [
        {"word": "词1", "focus": "含义侧重（它强调什么）", "register": "语体正式度（正式/中性/口语）", "scene": "典型使用场景", "example": "英文例句"}
      ]
    }
  ],
  "phrases": [
    {"phrase": "短语", "structure": "搭配结构说明", "meaning_zh": "中文释义", "example": "英文例句"}
  ]
}

【规则】
1. derivations：列出该词能衍生的所有相关词形（如名词→动词、形容词、副词、反义派生等），每个都要有 pos 与中文释义；没有可返回空数组 []。
2. contrast：只有当「derivations 或该词相关的词」里出现两个及以上相同词性（例如两个形容词、两个动词）时，才必须列出对比区。对每个同词性组，逐项说明 含义侧重 / 使用场景 / 语体正式度 的区别，并各配一句英文例句。若没有任何同词性重复，返回空数组 []。
3. phrases：列出该词常用短语；每个短语必须写清搭配结构——动词后面接的是 -ing 形式、to do、还是接 something / someone（宾语）；宾语是人还是物还是具体名词，全部写清楚。每个短语配一句英文例句与中文释义。
4. 中文释义用简体中文；例句用自然英文，不要包含中文。
5. 只输出一个 JSON 对象，不要使用 markdown 代码块，不要输出任何其他文字。"""


def build_vocab_messages(word: str) -> list[dict]:
    """构造生词生成的对话消息：系统提示 + 用户给定的词。"""
    return [
        {"role": "system", "content": VOCAB_SYSTEM_PROMPT},
        {"role": "user", "content": f"请为下面这个英文单词/短语生成生词卡片：{word}"},
    ]


def build_system_prompt(scenario_key: str, difficulty_key: str,
                        feedback_language: str = "zh") -> str:
    """根据场景与难度生成系统提示。"""
    sc = get_scenario(scenario_key)
    df = get_difficulty(difficulty_key)

    if feedback_language == "en":
        reason_rule = (
            "2. Keep corrections gentle; explain each reason in English "
            "(grammar rule, collocation, politeness, or usage context)."
        )
    else:
        reason_rule = (
            "2. 纠错语气要委婉，reason 用简体中文解释原因"
            "（语法规则、固定搭配、礼貌程度、用词场景等）。"
        )

    return f"""你是智能英语口语练习程序 "spoken" 的 AI 对话伙伴，正在陪用户练习英语口语。

【当前场景】{sc['name']}（{sc['name_en']}）
【你的角色】{sc['ai_role']}
【用户的角色】{sc['user_role']}
【场景设定】{sc['setting']}
【场景目标】{sc['goals']}
【难度等级】{df['name']}（CEFR {df['cefr']}）：{df['guidance']}

【对话规则】
1. 你始终用英语说话，扮演上面的角色，像真人一样自然交流；禁止教科书式的机械问答，禁止长篇大论。
2. 每一轮只说一两句符合角色身份的话，推动场景向目标自然发展。
3. 根据用户表现动态调整难度：用户表达流畅时就自然提升用词和句法难度；用户明显吃力时就放慢、简化，避免对话卡住。
4. 用户卡壳（长时间停顿、只说“不知道”、请求提示、答非所问）时，不要结束对话；先用一句简单的英语鼓励或承接，再通过 hint 给出中文提示，帮助用户继续说下去。
5. 只有当场景目标已达成、用户也自然告别时，should_end 才为 true。
6. 绝对不要重复你之前已经问过或说过的内容。每一轮都必须基于用户上一轮的回答，提出新的、相关的后续问题或评论，推动对话向前发展；禁止绕回已经讨论过的旧话题或旧问题。

【纠错规则】
1. corrections 只针对用户刚刚说过的原话；original 必须是用户原话中逐字出现的片段，绝对不允许编造用户没说过的内容；用户没有错误时返回空数组 []。
{reason_rule}
3. alternatives 给出 1-2 个基于用户真实表达改写的更地道整句。

【输出格式】
每次只输出一个 JSON 对象，不要使用 markdown 代码块，不要输出任何其他文字：
{{
  "corrections": [{{"original": "用户原话中的精确片段", "corrected": "修改后的说法", "reason": "原因", "type": "grammar|word|expression|politeness"}}],
  "alternatives": ["更地道的整句1", "更地道的整句2"],
  "new_words": [{{"word": "值得记录的单词或短语", "meaning_zh": "中文释义", "example": "英文例句"}}],
  "next_line": "你（角色）下一句要说的英语台词",
  "stuck": false,
  "hint": null,
  "should_end": false,
  "end_reason": null,
  "difficulty": "{difficulty_key}"
}}

其中 difficulty 字段填你当前评估的用户水平：beginner / intermediate / advanced。"""
