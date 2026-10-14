"""LLM 客户端：OpenAI 兼容接口 + 离线 Mock。"""

from __future__ import annotations

import json

import requests

from .scenarios import DIFFICULTIES, SCENARIOS, resolve_scenario


class LLMError(Exception):
    """模型调用失败，或返回内容无法解析。"""


def parse_json_robust(raw: str) -> dict:
    """从模型输出中稳健地解析 JSON 对象。

    依次尝试：整体解析 -> 剥离 markdown 代码块 -> 截取首尾大括号之间的内容。
    """
    text = (raw or "").strip()
    if not text:
        raise LLMError("模型返回了空内容")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 情况一：被 markdown 代码块包裹
    if "```" in text:
        for chunk in text.split("```"):
            chunk = chunk.strip()
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            if chunk.startswith("{"):
                try:
                    return json.loads(chunk)
                except json.JSONDecodeError:
                    continue
    # 情况二：JSON 前后夹杂其他文字
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise LLMError("无法解析模型返回的 JSON 内容")


class OpenAICompatibleLLM:
    """任何 OpenAI 兼容的 /chat/completions 接口（OpenAI、DeepSeek、Moonshot、Ollama 等）。"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float = 0.7, timeout: int = 60,
                 think: bool | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        # None = 不下发 think 参数（绝大多数服务商）；True/False = Ollama 思考开关
        self.think = think

    def chat(self, messages: list[dict], purpose: str = "turn") -> str:
        """调用对话接口，返回模型输出的文本内容。"""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        try:
            response = requests.post(
                url, headers=headers,
                json=self._payload(messages, json_mode=True),
                timeout=self.timeout,
            )
            if response.status_code == 400:
                # 个别服务商不支持 response_format 参数，去掉后重试一次
                response = requests.post(
                    url, headers=headers,
                    json=self._payload(messages, json_mode=False),
                    timeout=self.timeout,
                )
        except requests.RequestException as exc:
            raise LLMError(f"网络请求失败：{exc}") from exc

        if response.status_code != 200:
            raise LLMError(
                f"服务端返回 HTTP {response.status_code}：{response.text[:200]}"
            )
        try:
            return response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"服务端响应格式异常：{response.text[:200]}") from exc

    def _payload(self, messages: list[dict], json_mode: bool) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.think is not None:
            payload["think"] = self.think
        return payload


class MockLLM:
    """离线模拟 LLM：无需 API Key 即可体验完整流程，也是验证脚本的测试替身。

    根据系统提示识别场景与难度，按用户输入中的关键词给出确定性的预设回复，
    行为稳定、可重复，便于自动化测试。
    """

    def __init__(self) -> None:
        self.calls = 0
        self._followup_index: dict[str, int] = {}

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def chat(self, messages: list[dict], purpose: str = "turn") -> str:
        self.calls += 1
        system = messages[0]["content"]
        scenario = self._detect_scenario(system)
        difficulty = self._detect_difficulty(system)

        if purpose == "open":
            data = self._opening(scenario, difficulty)
        elif purpose == "summary":
            data = self._summary(scenario, messages)
        elif purpose == "shadow":
            data = {"sentences": self._shadow_sentences(scenario, difficulty)}
        else:
            data = self._turn(scenario, difficulty, messages[-1]["content"])
        return json.dumps(data, ensure_ascii=False)

    # ------------------------------------------------------------------
    # 识别
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_scenario(system: str) -> str:
        for key, sc in SCENARIOS.items():
            if sc["name"] in system:
                return key
        return "daily_smalltalk"

    @staticmethod
    def _detect_difficulty(system: str) -> str:
        for key, df in DIFFICULTIES.items():
            if df["name"] in system:
                return key
        return "intermediate"

    def _tpl(self, scenario: str) -> str:
        """Mock 模板仅预设 4 个内置场景；其余（新增 / 自定义）场景回退到
        “日常寒暄”模板，保证离线测试与体验不崩。"""
        return scenario if scenario in self._OPENINGS else "daily_smalltalk"

    # ------------------------------------------------------------------
    # 回复生成
    # ------------------------------------------------------------------
    def _opening(self, scenario: str, difficulty: str) -> dict:
        return self._pack(next_line=self._OPENINGS[self._tpl(scenario)],
                          difficulty=difficulty)

    # 跟读练习句子（按场景确定性生成，供离线测试/体验）
    _SHADOW_SENTENCES = {
        "daily_smalltalk": [
            "How has your week been so far?",
            "I usually start my day with a cup of coffee.",
            "What do you like to do on weekends?",
            "It was really nice running into you today.",
            "Let's grab lunch together sometime next week.",
        ],
        "airport_checkin": [
            "I would like to check in for my flight, please.",
            "Could I get an aisle seat if one is available?",
            "How many bags can I bring on board?",
            "What time does boarding start for this flight?",
            "Is there a layover on the way to my destination?",
        ],
        "job_interview": [
            "Could you tell me a bit about the team?",
            "In my last role, I led a small development team.",
            "I am eager to take on more responsibility.",
            "What does success look like in this position?",
            "I believe my experience fits this role well.",
        ],
        "restaurant_order": [
            "Could I see the menu, please?",
            "I would like the grilled salmon, without rice.",
            "Does this dish come with any side vegetables?",
            "Could we get the bill when you have a moment?",
            "Everything tasted wonderful, thank you.",
        ],
    }

    def _shadow_sentences(self, scenario: str, difficulty: str) -> list[str]:
        return list(self._SHADOW_SENTENCES.get(
            scenario, self._SHADOW_SENTENCES["daily_smalltalk"]))

    def _turn(self, scenario: str, difficulty: str, user_text: str) -> dict:
        text = " ".join((user_text or "").lower().split())
        bare = text.rstrip(".!?，。！？")
        s = self._tpl(scenario)

        # 0. 测试专用：诱导编造，用于验证引擎的防编造校验
        if "fabricate" in text:
            return self._pack(
                next_line=self._FOLLOW_UPS[s][0],
                difficulty=difficulty,
                corrections=[{
                    "original": "the moon is made of cheese",
                    "corrected": "the moon is made of cheese",
                    "reason": "（测试用）这句话用户根本没说过，引擎必须丢弃它",
                    "type": "grammar",
                }],
            )

        # 1. 卡壳：给提示，不结束对话
        if (bare in self._STUCK_PHRASES or "hint" in text
                or "stuck" in text or "i don't know" in text
                or "not sure" in text or "how do i say" in text
                or "怎么说" in text):
            return self._pack(
                next_line="Take your time, it's okay.",
                difficulty=difficulty,
                stuck=True,
                hint=self._HINTS[s],
            )

        # 2. 告别：自然收尾
        if "bye" in text or "see you" in text:
            return self._pack(
                next_line=self._CLOSINGS[s],
                difficulty=difficulty,
                should_end=True,
                end_reason="场景目标已达成，用户自然告别",
            )

        # 3. 纠错触发：只对用户原话中真实存在的片段纠错
        corrections: list[dict] = []
        alternatives: list[str] = []
        new_words: list[dict] = []
        for predicate, pack in self._TRIGGERS[s]:
            if predicate(text):
                corrections.extend(pack["corrections"])
                alternatives.extend(pack["alternatives"])
                new_words.extend(pack.get("new_words", []))

        # 4. 用户表达流畅信号 -> 提升难度
        if "comfortable" in text or "fluent" in text:
            difficulty = "advanced"

        # 5. 常规推进：循环使用场景台词，并补充生词
        index = self._followup_index.get(scenario, 0)
        self._followup_index[scenario] = index + 1
        followups = self._FOLLOW_UPS[s]
        pool = self._WORD_POOL[s]
        new_words.append(pool[index % len(pool)])

        return self._pack(
            next_line=followups[index % len(followups)],
            difficulty=difficulty,
            corrections=corrections,
            alternatives=alternatives,
            new_words=new_words,
        )

    def _summary(self, scenario: str, messages: list[dict]) -> dict:
        sc = resolve_scenario(scenario)
        user_lines = [
            m["content"] for m in messages
            if m["role"] == "user"
            and not m["content"].startswith(
                ("对话到此结束", "请开始对话", "你上一条回复"))
        ]
        first_user = user_lines[0] if user_lines else "I very like meeting new people."
        return {
            "overall": (
                f"你在「{sc['name']}」场景中完成了整段英语对话，表达意愿积极，"
                "基本达成了交流目标；主要问题集中在动词形式和场景常用语上，"
                "多说多练会越来越自然。"
            ),
            "scores": {"fluency": 7, "grammar": 6, "vocabulary": 6, "appropriateness": 7},
            "vocabulary": self._WORD_POOL[self._tpl(scenario)][:2],
            "improvements": [{
                "issue": "动词形式与场景常用语",
                "example_from_conversation": first_user,
                "suggestion": "注意 want to 后接动词原形；服务场景用 I'd like to ... 更礼貌自然",
            }],
            "suggestions": [
                "每天朗读并跟读一段同类场景的标准对话",
                "把生词本中的表达用到下一次练习中",
            ],
            "encouragement": "Keep going — every conversation makes you more natural!",
        }

    @staticmethod
    def _pack(next_line: str, difficulty: str, corrections=None,
              alternatives=None, new_words=None, stuck: bool = False,
              hint: str | None = None, should_end: bool = False,
              end_reason: str | None = None) -> dict:
        return {
            "corrections": corrections or [],
            "alternatives": alternatives or [],
            "new_words": new_words or [],
            "next_line": next_line,
            "stuck": stuck,
            "hint": hint,
            "should_end": should_end,
            "end_reason": end_reason,
            "difficulty": difficulty,
        }

    # ------------------------------------------------------------------
    # 预设数据
    # ------------------------------------------------------------------
    _STUCK_PHRASES = {
        "", "i don't know", "i dont know", "idk", "help", "hint", "no idea",
        "不知道", "怎么说", "呃", "啊", "...", "um", "er", "sorry",
    }

    _OPENINGS = {
        "daily_smalltalk": "Hi there! I don't think we've met before. I'm Alex — how's your day going?",
        "airport_checkin": "Good morning! Are you checking in today? May I see your passport, please?",
        "job_interview": "Good morning, please take a seat. To start off, could you tell me a little about yourself?",
        "restaurant_order": "Good evening! Here is your table and the menu. Would you like a few minutes, or shall I recommend something?",
    }

    _CLOSINGS = {
        "daily_smalltalk": "It was really nice talking to you. Take care, and see you around!",
        "airport_checkin": "You're all set. Here is your boarding pass. Have a great flight!",
        "job_interview": "Thank you for coming in today. We'll be in touch next week. Goodbye!",
        "restaurant_order": "Of course, I'll bring the bill right away. Thank you for coming, goodbye!",
    }

    _HINTS = {
        "daily_smalltalk": "可以试着说：I usually go running after work.（我下班后通常去跑步。）",
        "airport_checkin": "可以试着问：Which gate does my flight leave from?（我的航班在几号登机口？）",
        "job_interview": "可以试着回答：I'm a quick learner and I enjoy solving practical problems.（我学得快，喜欢解决实际问题。）",
        "restaurant_order": "可以试着问：What do you recommend tonight?（今晚有什么推荐？）",
    }

    _FOLLOW_UPS = {
        "daily_smalltalk": [
            "So, what do you usually like to do in your free time?",
            "That sounds fun! Do you often do that on weekends?",
            "By the way, have you watched any good movies lately?",
            "Anyway, it was really nice talking to you!",
        ],
        "airport_checkin": [
            "Thank you. Are you checking in any bags today?",
            "How many bags would you like to check?",
            "Your seat is 32A, by the window. Is that alright?",
            "Boarding starts at 7:40 at Gate 23. Anything else I can help you with?",
        ],
        "job_interview": [
            "That sounds interesting. Could you tell me about a project you're most proud of?",
            "What was the hardest part of that project, and how did you solve it?",
            "Why do you want to join our company?",
            "Do you have any questions for me?",
        ],
        "restaurant_order": [
            "Certainly. Would you like anything to drink?",
            "How would you like your steak done — rare, medium, or well done?",
            "Would you like soup or a salad to start?",
            "Anything else, or shall I bring the dessert menu?",
        ],
    }

    _WORD_POOL = {
        "daily_smalltalk": [
            {"word": "small talk", "meaning_zh": "闲聊；寒暄", "example": "We made small talk about the weather."},
            {"word": "break the ice", "meaning_zh": "打破僵场", "example": "A joke is a good way to break the ice."},
            {"word": "catch up", "meaning_zh": "叙旧；了解近况", "example": "Let's grab a coffee and catch up."},
        ],
        "airport_checkin": [
            {"word": "boarding pass", "meaning_zh": "登机牌", "example": "Here is your boarding pass."},
            {"word": "check in", "meaning_zh": "值机；办理登机手续", "example": "I'd like to check in for flight CA1234."},
            {"word": "gate", "meaning_zh": "登机口", "example": "My flight leaves from Gate 23."},
        ],
        "job_interview": [
            {"word": "take a seat", "meaning_zh": "请坐", "example": "Please take a seat."},
            {"word": "hands-on", "meaning_zh": "动手实践的", "example": "I have hands-on experience with STM32."},
            {"word": "be in touch", "meaning_zh": "保持联系", "example": "We'll be in touch next week."},
        ],
        "restaurant_order": [
            {"word": "medium rare", "meaning_zh": "五分熟", "example": "I'd like my steak medium rare."},
            {"word": "recommend", "meaning_zh": "推荐", "example": "What would you recommend?"},
            {"word": "the bill", "meaning_zh": "账单", "example": "Could I have the bill, please?"},
        ],
    }

    # 纠错触发器：(判定函数, 纠错内容)。判定函数保证 correction 的 original
    # 一定出现在用户输入中，模拟“只纠真正说错的部分”。
    _TRIGGERS = {
        "daily_smalltalk": [
            (lambda t: "i am agree" in t, {
                "corrections": [{
                    "original": "I am agree",
                    "corrected": "I agree",
                    "reason": "agree 本身就是动词，前面不需要再加 am；I agree 就是完整说法",
                    "type": "grammar",
                }],
                "alternatives": ["I totally agree with you."],
                "new_words": [],
            }),
            (lambda t: "very like" in t, {
                "corrections": [{
                    "original": "very like",
                    "corrected": "really like",
                    "reason": "汉语的“很”不能直译成 very 修饰动词，英语用 really 更自然",
                    "type": "expression",
                }],
                "alternatives": ["I really like hiking on weekends."],
                "new_words": [],
            }),
        ],
        "airport_checkin": [
            (lambda t: "a fly" in t, {
                "corrections": [{
                    "original": "a fly",
                    "corrected": "a flight",
                    "reason": "“航班”是 flight，fly 是动词“飞”",
                    "type": "word",
                }],
                "alternatives": ["I have a flight to Beijing at 8 o'clock."],
                "new_words": [{"word": "flight", "meaning_zh": "航班",
                               "example": "My flight to Beijing leaves at 8."}],
            }),
            (lambda t: "8 clock" in t, {
                "corrections": [{
                    "original": "8 clock",
                    "corrected": "8 o'clock",
                    "reason": "整点时间要用 o'clock，这是固定说法",
                    "type": "word",
                }],
                "alternatives": [],
                "new_words": [],
            }),
        ],
        "job_interview": [
            (lambda t: "i am graduated" in t, {
                "corrections": [{
                    "original": "I am graduated",
                    "corrected": "I will graduate",
                    "reason": "2027 年毕业是将来的事，要用一般将来时；只有已经毕业才说 I graduated",
                    "type": "grammar",
                }],
                "alternatives": ["I will graduate from Guangdong Ocean University in June 2027."],
                "new_words": [{"word": "graduate", "meaning_zh": "毕业",
                               "example": "I will graduate in June 2027."}],
            }),
        ],
        "restaurant_order": [
            (lambda t: "want to eat" in t, {
                "corrections": [{
                    "original": "want to eat a steak",
                    "corrected": "I'd like the steak",
                    "reason": "点餐时英语习惯用 I'd like / I'll have，want to eat 偏中式直译",
                    "type": "word",
                }],
                "alternatives": ["I'd like the steak, medium rare, please."],
                "new_words": [{"word": "I'd like ...", "meaning_zh": "我想要……（礼貌点餐用语）",
                               "example": "I'd like the steak, medium rare."}],
            }),
        ],
    }
