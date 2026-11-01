"""界面多语言：中文 / English 双语。

设计（"中文即键名"）：源码里所有用户可见文案直接用中文书写，
``t("开始对话")`` 在当前语言为 en 时返回英文翻译，否则原样返回。
好处：无需维护一套键名，新增文案忘记翻译时自动回退中文，不会 KeyError。

带占位符的动态文案用模板：``t("出现错误：{exc}").format(exc=exc)``。

切换语言：``set_language("en")`` 后 GUI 整体重建；监听者通过
``on_change(cb)`` 注册回调（用于二级窗口 reopen）。
"""

from __future__ import annotations

LANGUAGES: tuple[str, ...] = ("zh", "en")
DEFAULT_LANGUAGE = "zh"

_current = DEFAULT_LANGUAGE
_listeners: list = []

# 英文翻译表：键 = 中文原文，值 = English。缺失的键回退中文原文。
_EN: dict[str, str] = {
    # -- 欢迎页 --
    "口语练习助手": "Speaking Coach",
    "AI 陪你每天练英语口语 · 实时纠错 · 语音陪练":
        "Daily spoken English with AI · Real-time correction · Voice coaching",
    "本地模型驱动，离线也能练": "Runs on local models — practice even offline",
    "开始练习": "Start Practicing",
    # -- 设置页 --
    "练习设置": "Practice Settings",
    "选一个场景和难度，随时可以重新开始":
        "Pick a scenario and difficulty — restart anytime",
    "📚 生词本": "📚 Vocabulary",
    "📊 练习历史": "📊 History",
    "⚙ 语音设置": "⚙ Voice",
    "🔑 API 配置": "🔑 API",
    "← 返回": "← Back",
    "开始对话": "Start Conversation",
    "选择难度": "Difficulty",
    "选择场景": "Scenario",
    "自定义场景": "Custom Scenario",
    "点击新建你的专属场景": "Click to create your own scenario",
    "编辑场景": "Edit Scenario",
    "删除场景": "Delete Scenario",
    "保存": "Save",
    "取消": "Cancel",
    "场景中文名 *": "Scenario name (zh) *",
    "英文名 *": "Name (en) *",
    "一句话简介 *": "One-line summary *",
    "AI 扮演角色 *": "AI role *",
    "你的角色 *": "Your role *",
    "场景设定 *": "Setting *",
    "练习目标 *": "Goals *",
    "识别热词（可选）": "Hotwords (optional)",
    "如：商务谈判": "e.g. Business Negotiation",
    "卡片上显示的副标题": "Subtitle shown on the card",
    "如：合作方业务经理": "e.g. Partner Business Manager",
    "如：我方项目负责人": "e.g. Our Project Lead",
    "开头情境描述": "Opening situation",
    "希望达成的对话目标": "Conversation goals to achieve",
    "专有名词，空格分隔，提升识别率":
        "Proper nouns, space-separated — boosts recognition",
    "场景中文名与英文名不能为空": "Both zh and en scenario names are required",
    "编辑自定义场景": "Edit Custom Scenario",
    "新建自定义场景": "New Custom Scenario",
    # -- 对话页 --
    "结束对话": "End Conversation",
    "🎤 点击说话": "🎤 Tap to Speak",
    "⏹ 停止并发送": "⏹ Stop & Send",
    "⏹ 停止并评分": "⏹ Stop & Score",
    "发送": "Send",
    "🎯 跟读打分": "🎯 Shadowing",
    "🔊 重播": "🔊 Replay",
    "💡 纠错": "💡 Correction",
    "🗣 更地道": "🗣 More Natural",
    "你": "You",
    "你（跟读）": "You (shadowing)",
    "💡 卡壳提示": "💡 Stuck? Hint",
    "别急，试着用一个简单的句子回答。":
        "Take it easy — try answering with a simple sentence.",
    "正在聆听 …": "Listening …",
    "就绪 — 点击麦克风说话，或输入文字": "Ready — tap the mic or type below",
    "AI 思考中 …": "AI is thinking …",
    "AI 正在开口 …": "AI is starting …",
    "录音中……说完再点一次按钮": "Recording… tap again when you're done",
    "跟读录音中……读完参考句再点一次按钮":
        "Shadowing… tap again after reading the reference",
    "识别中……": "Recognizing…",
    "正在准备语音识别模型（首次需下载，约 150MB）…":
        "Preparing speech model (first run downloads ~150MB)…",
    "语音识别模型就绪": "Speech model ready",
    "正在加载语音识别模型（首次需下载，约 150MB）…":
        "Loading speech model (first run downloads ~150MB)…",
    "没有识别到内容，请再试一次": "Nothing recognized — please try again",
    "没有识别到内容": "Nothing recognized",
    "正在生成本次练习总结 …": "Generating session summary …",
    "语音自检：现在应该播放一句英文。如果没听到，请检查系统音量/输出设备（聊天区会提示错误）。":
        "Voice self-check: you should hear an English sentence now. "
        "If not, check your system volume / output device "
        "(errors show up in the chat area).",
    "语音合成出错：{message}": "Speech synthesis error: {message}",
    "出现错误：{exc}": "Something went wrong: {exc}",
    "无法开始录音：{exc}": "Cannot start recording: {exc}",
    "请检查麦克风是否连接、是否被其他程序占用。":
        "Check that your microphone is connected and not in use by another app.",
    "识别失败：{exc}": "Recognition failed: {exc}",
    "模型调用失败：{exc}（请重试或结束对话）":
        "Model call failed: {exc} (retry or end the conversation)",
    "AI 开口失败：{exc}": "AI failed to start: {exc}",
    "请检查 config.yaml 里的 API Key 与网络，然后重试。":
        "Check the API Key and network in config.yaml, then try again.",
    "总结生成失败：{exc}": "Summary generation failed: {exc}",
    "难度调整：{old} → {new}": "Difficulty adjusted: {old} → {new}",
    "场景目标已达成": "Scenario goal achieved",
    "📖 参考句：": "📖 Reference: ",
    "🔑 关键词：": "🔑 Keywords: ",
    "发音评分失败：{exc}": "Pronunciation scoring failed: {exc}",
    "（未配置发音评分：在 config.yaml 的 assessment 填入 "
    "nls AppKey/Token 后可用真实声学打分）":
        "(Pronunciation scoring not configured: fill in the nls AppKey/Token "
        "under assessment in config.yaml to enable acoustic scoring)",
    "跟读识别失败：{exc}": "Shadowing recognition failed: {exc}",
    "跟读评分：总分 {overall}｜准确度 {accuracy}｜完整度 {integrity}｜流利度 {fluency}":
        "Shadowing score: overall {overall}｜accuracy {accuracy}｜"
        "integrity {integrity}｜fluency {fluency}",
    "会话开始：{name}｜难度：{difficulty}":
        "Session started: {name}｜difficulty {difficulty}",
    "模型：{model}": "Model: {model}",
    "语音识别：": "Speech recognition: ",
    "就绪（首次说话时加载）": "ready (loads on first use)",
    "不可用（可打字）": "unavailable (typing still works)",
    "语音合成：": "Speech synthesis: ",
    "就绪": "ready",
    "不可用": "unavailable",
    # -- 总结弹窗 --
    "本次练习总结": "Session Summary",
    "好的": "OK",
    "📄 报告已保存：{path}": "📄 Report saved: {path}",
    # -- 评分弹窗 --
    "跟读评分": "Shadowing Score",
    "发音评分结果": "Pronunciation Score",
    "总分": "Overall",
    "准确度": "Accuracy",
    "完整度": "Integrity",
    "流利度": "Fluency",
    "建议：": "Tip: ",
    # -- 语音设置 --
    "语音设置": "Voice Settings",
    "发音人（本地 SAPI）": "Voice (local SAPI)",
    "（系统默认 / 自动选英文）": "(System default / auto-pick English)",
    "语速": "Speed",
    "慢": "Slow",
    "中": "Normal",
    "快": "Fast",
    "音量": "Volume",
    "试听": "Preview",
    "正在试听当前设置…": "Previewing current settings…",
    "当前环境无可用语音引擎（未安装 pyttsx3，且云端 TTS 未配置）":
        "No voice engine available (pyttsx3 not installed and cloud TTS not configured)",
    "试听失败：{exc}": "Preview failed: {exc}",
    "关闭窗口将自动应用当前设置": "Closing this window applies your changes",
    "云端 TTS（CosyVoice，可选）": "Cloud TTS (CosyVoice, optional)",
    "启用云端 TTS（音色更清晰）": "Enable cloud TTS (clearer voice)",
    "口音 / 发音人（CosyVoice 官方音色）": "Accent / Voice (official CosyVoice)",
    "· 非英语口音": "· non-English accent",
    "· 暂不支持": "· not supported",
    "· 泰/印/越/马/哈/乌：CosyVoice 官方暂无音色；"
    "日/韩音色只朗读对应语言。缺少的口音可在下方自定义音色 ID 接入。":
        "· Thai / Hindi / Vietnamese / Malay / Kazakh / Uzbek: no official "
        "CosyVoice voice yet; Japanese / Korean voices only speak their own "
        "language. Missing accents can be added via a custom voice ID below.",
    "自定义音色 ID（可选，填了则忽略上面的选择）":
        "Custom voice ID (optional — overrides the selection above)",
    # -- API 配置 --
    "API 配置": "API Configuration",
    "🔑 连接 AI 服务": "🔑 Connect an AI Service",
    "支持任意 OpenAI 兼容接口；保存后立即可用。":
        "Any OpenAI-compatible endpoint works; applies immediately after saving.",
    "已选择预设，填入你的 API Key 后点「保存」":
        "Preset selected — enter your API Key, then click Save",
    "接口地址（Base URL）": "Base URL",
    "模型名称": "Model",
    "接口地址与模型名称不能为空。": "Base URL and model name are required.",
    "请填入 API Key（本地 Ollama 可留空）。":
        "Please enter an API Key (leave empty for local Ollama).",
    "✅ API 配置已保存，现在可以开始对话了。":
        "✅ API settings saved — you can start a conversation now.",
    "稍后再说": "Later",
    "保存语音设置失败：{exc}": "Failed to save voice settings: {exc}",
    # -- 练习历史 --
    "练习历史（共 {count} 次）": "Practice History ({count} sessions)",
    "平均分 —— 总分 {overall}｜准确度 {accuracy}｜完整度 {integrity}｜流利度 {fluency}":
        "Average — overall {overall}｜accuracy {accuracy}｜"
        "integrity {integrity}｜fluency {fluency}",
    "暂无数据": "No data yet",
    # -- 生词本 --
    "🔍 查询并收藏": "🔍 Look up & Save",
    "搜索": "Search",
    "按时间": "By time",
    "按字母": "Alphabetical",
    "共 {count} 个生词": "{count} words",
    "还没有生词。在上方输入单词/短语，点击「查询并收藏」即可添加；离线也能查看已收藏的词条。":
        "No words yet. Type a word or phrase above and click "
        "“Look up & Save” to add one; saved entries stay viewable offline.",
    "读取生词本失败：{exc}": "Failed to load vocabulary: {exc}",
    "🗑 删除": "🗑 Delete",
    "词形变换": "Word Forms",
    "近义对比（{pos}）": "Synonyms ({pos})",
    "短语搭配": "Phrases",
    "侧重：": "Focus: ",
    "语体：": "Register: ",
    "场景：": "Scene: ",
    "例：": "e.g. ",
    "请输入要查询的单词或短语": "Enter a word or phrase to look up",
    "正在查询「{word}」…（需联网 / 通义 Key）":
        "Looking up “{word}”… (needs internet / a Qwen API key)",
    "查询失败：{exc}": "Lookup failed: {exc}",
    "保存失败：{exc}": "Save failed: {exc}",
    "已收藏「{word}」": "Saved “{word}”",
    "删除失败：{exc}": "Delete failed: {exc}",
    # -- 更新提示 --
    "发现新版本": "New Version Available",
    "🎉 发现新版本可用": "🎉 A new version is available",
    "当前 {current} → 最新 {latest}": "Current {current} → latest {latest}",
    "前往下载": "Download",
    "稍后": "Later",
    # -- 难度名（scenarios.DIFFICULTIES） --
    "初级": "Beginner",
    "中级": "Intermediate",
    "高级": "Advanced",
    # -- 模板类动态文案 --
    "：": ": ",
    "“{original}” → “{corrected}”（{reason}）":
        "“{original}” → “{corrected}” ({reason})",
    "正在下载语音识别模型 {filename}：{pct}%（{done}/{total} MB）":
        "Downloading speech model {filename}: {pct}% ({done}/{total} MB)",
    "{ts}  {scenario}/{difficulty}  {overall_label} {overall}":
        "{ts}  {scenario}/{difficulty}  {overall_label} {overall}",
    "侧重：{focus}": "Focus: {focus}",
    "语体：{register}　场景：{scene}": "Register: {register}  Scene: {scene}",
    "例：{example}": "e.g. {example}",
    "搭配：{structure}": "Collocation: {structure}",
    # -- 其他 --
    "通义千问": "Qwen",
    "Ollama 本地": "Ollama (local)",
    "spoken — 智能英语口语教练": "spoken — AI Speaking Coach",
    "语音识别组件不可用（未安装 faster-whisper）":
        "Speech recognition unavailable (faster-whisper not installed)",
    # -- 界面偏好设置（v1.1.1 新增） --
    "界面设置": "Appearance",
    "语言": "Language",
    "主题": "Theme",
    "浅色": "Light",
    "深色": "Dark",
    "切换后立即生效": "Applies immediately",
    "窗口": "Window",
    "记住窗口位置和大小": "Remember window position and size",
    # -- 跟读专项练习（v1.1.1 新增） --
    "🎯 跟读练习": "🎯 Shadowing",
    "跟读练习": "Shadowing Practice",
    "AI 生成贴近场景的英文句子，你逐句跟读，系统对发音打分；低分句子会自动安排重练。":
        "AI generates scene-based English sentences; shadow each one and get "
        "a pronunciation score. Low-scoring sentences are automatically "
        "scheduled for another round.",
    "低分句子会自动插入队尾重练（每句最多 2 次）；成绩计入练习历史。":
        "Low scores are re-queued automatically (max 2 retries per sentence); "
        "results are saved to your practice history.",
    "句子数量": "Sentences",
    "{n} 句": "{n}",
    "开始跟读": "Start",
    "选择句子数量后开始；使用设置页已选的场景与难度":
        "Pick a sentence count to start; uses the scenario and difficulty "
        "selected on the settings page",
    "正在生成练习句子…": "Generating practice sentences…",
    "句子生成失败：{exc}": "Failed to generate sentences: {exc}",
    "第 {done} 句 / 共 {total} 句": "Sentence {done} of {total}",
    "🔊 播放": "🔊 Play",
    "🎤 录音": "🎤 Record",
    "⏹ 停止并评分": "⏹ Stop & Score",
    "跳过": "Skip",
    "就绪 — 点击播放熟悉句子，然后录音跟读（空格键也可以）":
        "Ready — play the sentence, then record your shadowing (Space works too)",
    "跟读录音中……读完句子再点一次按钮":
        "Shadowing… tap again after finishing the sentence",
    "正在识别与评分…": "Recognizing and scoring…",
    "正在播放……": "Playing…",
    "（未配置发音评分，仅显示识别结果；在 config.yaml 的 assessment 填入 "
    "nls AppKey/Token 后可用真实声学打分）":
        "(Pronunciation scoring not configured — only recognition is shown. "
        "Fill in the nls AppKey/Token under assessment in config.yaml to "
        "enable acoustic scoring)",
    "识别结果：": "Recognized: ",
    "下一句": "Next",
    "再练一次": "Retry",
    "结束练习": "Finish",
    "得分偏低，已自动加入重练队列":
        "Low score — automatically re-queued for another round",
    "跟读练习总结": "Shadowing Summary",
    "练习 {attempts} 次（共 {count} 句，重练 {retry} 次）":
        "{attempts} attempts ({count} sentences, {retry} retries)",
    "本次没有获得评分（未配置发音评分）":
        "No scores this round (pronunciation scoring not configured)",
    "再练一组": "Another round",
    "完成": "Done",
    "成绩已写入练习历史": "Results saved to practice history",
    # -- 生词本复习提醒（v1.1.1 新增） --
    "今天没有到期的复习词": "No words due for review today",
    "今日待复习 {count} 个": "{count} words due today",
    "认识": "Know",
    "模糊": "Vague",
    "忘记": "Forgot",
    "复习更新失败：{exc}": "Failed to update review: {exc}",
    "🔍 查询并收藏「{text}」": "🔍 Look up & save “{text}”",
    # -- 一键更新（v1.1.1 新增） --
    "下载并更新": "Download & Update",
    "正在下载更新…": "Downloading update…",
    "正在下载更新… {pct}%": "Downloading update… {pct}%",
    "更新已就绪，应用后程序将自动重启":
        "Update ready — the app will restart automatically",
    "更新失败：{exc}（可双击本窗口前往下载页手动更新）":
        "Update failed: {exc} (double-click this window to download manually)",
    "更新失败：{exc}": "Update failed: {exc}",
    "请前往下载页手动获取新版本": "Please visit the download page for the new version",
}


def get_language() -> str:
    return _current


def set_language(lang: str) -> bool:
    """切换界面语言；返回是否发生了变化。"""
    global _current
    if lang not in LANGUAGES:
        return False
    if lang == _current:
        return False
    _current = lang
    for cb in list(_listeners):
        try:
            cb(lang)
        except Exception:
            pass
    return True


def on_change(cb) -> None:
    """注册语言切换回调（GUI 用它重建界面 / 重开二级窗口）。"""
    if cb not in _listeners:
        _listeners.append(cb)


def off_change(cb) -> None:
    if cb in _listeners:
        _listeners.remove(cb)


def t(text: str, **kwargs) -> str:
    """翻译。kwargs 存在时按模板格式化（t("出现错误：{exc}").format 的简写）。"""
    if _current != "en" or not text:
        return text.format(**kwargs) if kwargs else text
    translated = _EN.get(text, text)
    return translated.format(**kwargs) if kwargs else translated


def coverage() -> tuple[int, int]:
    """(已翻译条目数,  EN 表条目数) —— 供测试断言用。"""
    return len(_EN), len(_EN)
