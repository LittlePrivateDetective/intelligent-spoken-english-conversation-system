"""场景与难度等级定义。

新增场景只需在 SCENARIOS 中加一项，键名同时用作 --scenario 参数值。
"""

from __future__ import annotations

DIFFICULTIES: dict[str, dict] = {
    "beginner": {
        "name": "初级",
        "cefr": "A2",
        "guidance": (
            "用简单短句和高频词汇，避免从句、习语和专业词；"
            "每轮只说一两句话，语速放慢，像在带初学者入门。"
        ),
    },
    "intermediate": {
        "name": "中级",
        "cefr": "B1",
        "guidance": (
            "用日常词汇和适量从句，可以自然使用常见短语；"
            "句长适中、语速正常，像真实的日常交流。"
        ),
    },
    "advanced": {
        "name": "高级",
        "cefr": "C1",
        "guidance": (
            "可以使用复杂句式、习语、惯用表达和一定的专业词汇，"
            "像母语者一样自然交流，可以适当使用缩略和省略。"
        ),
    },
}

SCENARIOS: dict[str, dict] = {
    "hotel_checkin": {
        "name": "办理入住",
        "name_en": "Hotel Check-in",
        "summary": "在酒店前台办理入住登记",
        "ai_role": "酒店前台接待员",
        "user_role": "刚到店的客人",
        "setting": "晚上八点，客人走进酒店大堂，前台主动问候。",
        "goals": "确认预订信息、登记证件、说明房型/早餐/退房时间、交付房卡，必要时处理加床或投诉。",
    },
    "airport_checkin": {
        "name": "机场值机",
        "name_en": "Airport Check-in",
        "summary": "在机场柜台办理值机和托运",
        "ai_role": "航空公司值机柜员",
        "user_role": "准备乘机的旅客",
        "setting": "起飞前三小时，旅客拖着行李来到值机柜台。",
        "goals": "出示证件和行程、选座、托运行李、确认登机口和时间，处理超重或改签等问题。",
    },
    "job_interview": {
        "name": "英文面试",
        "name_en": "Job Interview",
        "summary": "应聘技术岗位的英文面试",
        "ai_role": "技术岗位面试官",
        "user_role": "求职者（应届本科毕业生）",
        "setting": "一场面试刚开始，面试官请求职者自我介绍。",
        "goals": "完成自我介绍、讲述项目经历、回答技术/行为面试问题、向面试官提问，最后礼貌收尾。",
    },
    "restaurant_order": {
        "name": "餐厅点餐",
        "name_en": "Restaurant Ordering",
        "summary": "在西餐厅看菜单点餐",
        "ai_role": "餐厅服务员",
        "user_role": "来用餐的顾客",
        "setting": "晚餐时间，顾客入座，服务员递上菜单。",
        "goals": "询问推荐、点主菜和饮品、说明忌口/熟度、加单或甜点，最后结账。",
    },
}

SCENARIO_ORDER: list[str] = list(SCENARIOS)
DIFFICULTY_ORDER: list[str] = list(DIFFICULTIES)


def get_scenario(key: str) -> dict:
    """按键名取场景定义，不存在时抛出带可选值的错误。"""
    try:
        return SCENARIOS[key]
    except KeyError:
        raise ValueError(f"未知场景：{key}（可选：{', '.join(SCENARIOS)}）") from None


def get_difficulty(key: str) -> dict:
    """按键名取难度定义，不存在时抛出带可选值的错误。"""
    try:
        return DIFFICULTIES[key]
    except KeyError:
        raise ValueError(f"未知难度：{key}（可选：{', '.join(DIFFICULTIES)}）") from None
