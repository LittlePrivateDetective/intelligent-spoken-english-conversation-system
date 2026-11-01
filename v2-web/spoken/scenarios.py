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

# 每个场景的热词 / 专有名词：传给 faster-whisper 的 hotwords，提升识别准确率。
# 重点是容易识别错的专有名词、缩写、生词；尽量用小写、空格分隔。
SCENARIO_HOTWORDS: dict[str, str] = {
    "daily_smalltalk": (
        "small talk break the ice catch up weekend hobby weather "
        "coffee movie friend party relax"
    ),
    "airport_checkin": (
        "boarding pass check in gate luggage baggage overweight flight "
        "passport seat window aisle layover takeoff land terminal "
        "Boarding Pass"
    ),
    "job_interview": (
        "interview resume graduate project experience teamwork leadership "
        "responsibility challenge solution company position salary "
        "hands-on debug"
    ),
    "restaurant_order": (
        "menu order steak medium rare well done appetizer dessert "
        "recommend bill tip waiter beverage vegetarian spicy medium "
        "rare"
    ),
    "business_meeting": (
        "meeting agenda project proposal budget deadline milestone "
        "stakeholder deliverable KPI ROI negotiate contract "
        "follow up"
    ),
    "travel": (
        "itinerary attraction sightseeing booking reservation "
        "transport subway luggage tour guide budget scenic "
        "check out"
    ),
    "hotel": (
        "check in check out reception upgrade suite twin queen "
        "breakfast WiFi elevator deposit key card amenities "
        "housekeeping"
    ),
    "shopping": (
        "size color fitting room discount sale bargain receipt "
        "refund exchange cashier coupon fabric material "
        "try on"
    ),
    "hospital": (
        "symptom fever cough pain prescribe medication dosage "
        "allergy appointment temperature blood pressure "
        "prescription diagnose"
    ),
    "phone_call": (
        "operator hotline hold on callback extension voicemail "
        "confirm order number account refund representative "
        "transfer"
    ),
    "opinion": (
        "opinion agree disagree perspective argument evidence "
        "point of view compromise convince contrary however "
        "whereas"
    ),
    "campus": (
        "campus dormitory cafeteria lecture assignment exam "
        "club semester coursemate professor tutor library "
        "credit"
    ),
}


SCENARIOS: dict[str, dict] = {
    "daily_smalltalk": {
        "name": "日常寒暄",
        "name_en": "Small Talk",
        "summary": "与刚认识的人闲聊日常话题",
        "ai_role": "刚认识的朋友",
        "user_role": "初次见面的访客",
        "setting": "在一场社区活动或公司茶水间，你和一位刚认识的人聊了起来。",
        "goals": "自然地打开并维持话题（天气、爱好、工作学习、周末计划），对话有来有回，最后礼貌道别。",
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
    "business_meeting": {
        "name": "商务会议",
        "name_en": "Business Meeting",
        "summary": "在跨国会议中汇报与讨论",
        "ai_role": "合作方业务经理",
        "user_role": "我方项目负责人",
        "setting": "一场视频商务会议刚开始，双方就一个合作项目交换意见。",
        "goals": "开场寒暄、介绍项目进展、提出方案与顾虑、回应质疑、敲定下一步，最后礼貌收尾。",
    },
    "travel": {
        "name": "旅行规划",
        "name_en": "Travel Planning",
        "summary": "向当地导游咨询并规划行程",
        "ai_role": "当地旅行顾问",
        "user_role": "来旅行的游客",
        "setting": "你走进一家旅行社门店，想规划接下来几天的行程。",
        "goals": "说明偏好与预算、询问景点与交通、比较方案、预订或约定，处理突发改期。",
    },
    "hotel": {
        "name": "酒店入住",
        "name_en": "Hotel Check-in",
        "summary": "在前台办理入住与咨询",
        "ai_role": "酒店前台接待",
        "user_role": "办理入住的住客",
        "setting": "长途飞行后你抵达酒店，拖着行李来到前台。",
        "goals": "出示预订与证件、选房与升级、询问早餐/WiFi/设施、报修或延退，处理账单问题。",
    },
    "shopping": {
        "name": "购物沟通",
        "name_en": "Shopping",
        "summary": "在商场或集市挑选与议价",
        "ai_role": "店员 / 摊主",
        "user_role": "逛街购物的顾客",
        "setting": "你在一家服饰店或集市摊位前驻足，想看看商品。",
        "goals": "询问款式尺码与材质、试穿、讨价还价、处理退换、顺便闲聊拉近距离。",
    },
    "hospital": {
        "name": "就医问诊",
        "name_en": "Doctor Visit",
        "summary": "向医生描述病情并配合问诊",
        "ai_role": "全科医生",
        "user_role": "前来就诊的患者",
        "setting": "你在诊室坐下，医生开始询问你的身体状况。",
        "goals": "描述症状与病史、回答生活习惯问题、听懂医嘱、询问用药与复诊，表达顾虑。",
    },
    "phone_call": {
        "name": "电话沟通",
        "name_en": "Phone Call",
        "summary": "在电话中预约与处理事务",
        "ai_role": "客服 / 接线员",
        "user_role": "拨打热线的人",
        "setting": "你拨通一个服务热线，等待对方接听。",
        "goals": "说明来意、提供订单/账号信息、听懂并确认要点、转接或投诉、礼貌结束通话。",
    },
    "opinion": {
        "name": "观点讨论",
        "name_en": "Opinion & Debate",
        "summary": "就一个话题表达并捍卫立场",
        "ai_role": "持不同看法的讨论伙伴",
        "user_role": "参与讨论的人",
        "setting": "你们就一个社会或生活话题展开轻松但认真的讨论。",
        "goals": "清晰陈述观点、给出理由与例子、倾听并反驳对方、适时让步、保持礼貌不跑题。",
    },
    "campus": {
        "name": "校园生活",
        "name_en": "Campus Life",
        "summary": "在校园里与同学老师交流",
        "ai_role": "同校同学 / 助教",
        "user_role": "在校学生",
        "setting": "课间或社团活动里，你和同学聊起学校生活。",
        "goals": "约饭约自习、讨论课业与社团、吐槽与分享、请教选课、自然地维持对话。",
    },
}

SCENARIO_ORDER: list[str] = list(SCENARIOS)
DIFFICULTY_ORDER: list[str] = list(DIFFICULTIES)


def get_scenario(key: str) -> dict:
    """按键名取场景定义，不存在时抛出带可选值的错误。

    兼容旧调用：内置与自定义场景都能解析（委托给 resolve_scenario）。
    """
    return resolve_scenario(key)


def get_difficulty(key: str) -> dict:
    """按键名取难度定义，不存在时抛出带可选值的错误。"""
    try:
        return DIFFICULTIES[key]
    except KeyError:
        raise ValueError(f"未知难度：{key}（可选：{', '.join(DIFFICULTIES)}）") from None


# ------------------------------------------------------------------
# 内置 + 自定义 统一解析层
# ------------------------------------------------------------------
def _custom_data() -> dict:
    """懒加载自定义场景（避免模块导入期触达用户数据目录）。"""
    from .custom_scenarios import load
    return load()


def is_custom(key: str) -> bool:
    """是否为用户自定义场景 key（以 custom_ 前缀）。"""
    return isinstance(key, str) and key.startswith("custom_")


def resolve_scenario(key: str) -> dict:
    """按 key 取场景定义，先查内置再查自定义，都不存在抛错。

    返回 dict 含字段：name / name_en / summary / ai_role / user_role /
    setting / goals，自定义场景还可能含 hotwords。
    """
    if key in SCENARIOS:
        return SCENARIOS[key]
    custom = _custom_data()
    if key in custom:
        return custom[key]
    choices = ", ".join(list(SCENARIOS) + list(custom))
    raise ValueError(f"未知场景：{key}（可选：{choices}）")


def resolve_hotwords(key: str) -> str:
    """返回某场景的 ASR 热词；内置取 SCENARIO_HOTWORDS，自定义取 hotwords 字段。"""
    if key in SCENARIO_HOTWORDS:
        return SCENARIO_HOTWORDS[key]
    if is_custom(key):
        return _custom_data().get(key, {}).get("hotwords", "")
    return ""


def list_scenario_keys() -> list:
    """全部可选场景 key：先内置（按 SCENARIO_ORDER），后自定义（按创建时间）。"""
    from .custom_scenarios import ordered_keys
    return list(SCENARIO_ORDER) + ordered_keys()
