# spoken —— 智能英语口语对话练习程序

`spoken` 是一个开源的命令行英语口语练习程序：选择场景和难度后，AI 会扮演对应角色（酒店前台、值机柜员、面试官、餐厅服务员）与你进行自然的英语对话，实时纠正语法和用词错误、给出更地道的表达，并在对话结束后生成生词本和改进建议。

## 功能特性

- **场景角色扮演**：内置办理入住、机场值机、英文面试、餐厅点餐 4 个场景，可自行扩展
- **三级难度**：初级（A2）/ 中级（B1）/ 高级（C1），AI 根据你的表现动态调整用词难度
- **实时纠错**：每轮对话后委婉指出错误并说明原因；只针对你真实说过的原话，绝不编造
- **卡壳提示**：明显卡壳时给出中文提示和参考句子，而不是直接结束对话
- **总结报告**：对话结束后输出能力评分、生词本、改进点和练习建议，可保存为 Markdown
- **任意 OpenAI 兼容接口**：OpenAI / DeepSeek / Moonshot / 通义 / Ollama 等均可
- **离线演示**：内置 `--mock` 模式，无需 API Key 即可体验完整流程

明确不支持：语音识别、语音合成、图形界面、多用户账号、云端同步。

## 环境要求与安装

需要 Python 3.10+。

```bash
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. 以可编辑模式安装（安装后可直接使用 spoken 命令）
pip install -e .
```

也可以不安装，直接在项目根目录运行 `python -m spoken`。

## 配置

复制 `config.example.yaml` 为 `config.yaml`，填入你的 API Key：

```yaml
llm:
  base_url: "https://api.deepseek.com/v1"   # 任何 OpenAI 兼容接口
  api_key: "sk-你的Key"
  model: "deepseek-chat"
dialogue:
  max_turns: 25          # 单次对话最多轮数
  feedback_language: zh  # 纠错解释语言：zh / en
  save_report: true      # 结束后保存 Markdown 报告
  report_dir: reports    # 报告保存目录
```

也可以用环境变量临时覆盖：`SPOKEN_BASE_URL`、`SPOKEN_API_KEY`、`SPOKEN_MODEL`。

## 使用方法

```bash
python -m spoken                                          # 启动，按菜单选择场景和难度
spoken                                                    # 安装后可直接使用
python -m spoken --mock                                   # 离线演示模式（无需 API Key）
python -m spoken --scenario job_interview --level advanced # 跳过菜单直接开始
```

对话过程中的命令：

| 命令 | 作用 |
| --- | --- |
| `/quit` | 结束对话并生成总结报告 |
| `/hint` | 卡壳时请求 AI 给一句提示 |
| `/level` | 查看当前难度与练习统计 |
| `/help` | 查看帮助 |

## 输入输出示例

以下是一次真实的 `--mock` 离线演示会话（办理入住 / 中级）：

```text
请选择练习场景：
  1. 办理入住（Hotel Check-in）—— 在酒店前台办理入住登记
  2. 机场值机（Airport Check-in）—— 在机场柜台办理值机和托运
  3. 英文面试（Job Interview）—— 应聘技术岗位的英文面试
  4. 餐厅点餐（Restaurant Ordering）—— 在西餐厅看菜单点餐
请输入序号 > 1
请选择难度等级：
  1. 初级（CEFR A2）
  2. 中级（CEFR B1）
  3. 高级（CEFR C1）
请输入序号 > 2

场景：办理入住｜难度：中级｜你的角色：刚到店的客人｜AI 角色：酒店前台接待员

酒店前台接待员: Good evening, welcome to the Grand Hotel! How may I help you tonight?

你: Hello, I want to booking a room for two night.
  ────────────────────────────────────────────────────
  ✏️  纠错：want to booking  →  want to book
      原因：want to 后面要接动词原形，不能用动名词形式
  ✏️  纠错：two night  →  two nights
      原因：表示“两晚”时 night 是可数名词，要用复数
  💡 更地道的说法：
      · I'd like to book a room for two nights, please.
  ────────────────────────────────────────────────────
酒店前台接待员: Certainly. Could you spell your last name for me, please?

你: I don't know.
  💡 卡壳提示：可以试着问：Do you have any rooms available tonight?（今晚还有空房吗？）
酒店前台接待员: Take your time, it's okay.

你: My name is Paul. I have a reservation.
酒店前台接待员: Thank you. I've found your reservation — a standard room for two nights. Is that correct?

你: Thank you so much for your help. Goodbye!
酒店前台接待员: You're welcome. Enjoy your stay, and have a good night!

（场景目标已达成，用户自然告别）

════════════════════════════════════════════════════════
📋 本次对话总结
════════════════════════════════════════════════════════

你在「办理入住」场景中完成了整段英语对话，表达意愿积极，基本达成了交流目标；
主要问题集中在动词形式和场景常用语上，多说多练会越来越自然。

能力评分：流利度 7/10  语法 6/10  词汇 6/10  得体度 7/10

📚 生词本：
  · book a room —— 订房
  · check in —— 办理入住
  · reservation —— 预订；订好的房间

🔧 改进点：
  1. 动词形式与场景常用语：注意 want to 后接动词原形；服务场景用 I'd like to ... 更礼貌自然

🏋️ 练习建议：
  · 每天朗读并跟读一段同类场景的标准对话
  · 把生词本中的表达用到下一次练习中

💪 Keep going — every conversation makes you more natural!
════════════════════════════════════════════════════════

📄 报告已保存：reports\spoken_20261013_012727.md
```

## 项目结构

```text
spoken/
├── spoken/
│   ├── __init__.py
│   ├── __main__.py      # python -m spoken 入口
│   ├── cli.py           # 命令行交互（菜单、对话循环、渲染）
│   ├── config.py        # 配置加载（YAML + 环境变量覆盖）
│   ├── scenarios.py     # 场景与难度定义
│   ├── prompts.py       # 系统提示构建
│   ├── llm.py           # OpenAI 兼容客户端 + 离线 Mock
│   ├── dialogue.py      # 对话引擎（纠错/提示/动态难度/总结）
│   └── report.py        # 总结报告渲染与保存
├── config.example.yaml  # 配置模板
├── requirements.txt
├── verify.py            # 验证脚本（4 场景 × 3 难度离线测试）
└── README.md
```

## 运行验证脚本

```bash
python verify.py
```

使用内置 Mock 模型离线跑通 4 个场景 × 3 个难度的完整对话流程，共 243 项断言，覆盖：系统提示生成、开场白、纠错（含“纠错原文必须逐字来自用户输入”的防编造校验）、替代表达、卡壳提示、动态难度调整、自然收尾、总结报告、JSON 解析健壮性、配置加载与报告保存、CLI 冒烟测试。

## 如何扩展新场景

编辑 `spoken/scenarios.py`，在 `SCENARIOS` 中新增一项即可：

```python
"library_card": {
    "name": "办理借书证",
    "name_en": "Library Card",
    "summary": "在大学图书馆办理借书证",
    "ai_role": "图书馆馆员",
    "user_role": "新入学学生",
    "setting": "开学第一周，学生来到图书馆服务台。",
    "goals": "填写申请表、出示学生证、说明借阅规则、领取借书证。",
},
```

## 说明

本程序通过调用大语言模型 API 实现对话与纠错，纠错质量取决于所用模型，内容仅供参考。使用第三方 API 可能产生费用，请知悉。

## License

MIT
