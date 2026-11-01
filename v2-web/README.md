# spoken 2.0.0 · 智能英语口语教练（Web + 桌面应用）

英语口语教练的 2.0 版本。后端是 FastAPI + 内置的 `spoken` 包（对话引擎、纠错、语音识别），前端是纯 HTML/CSS/JS。

两种用法：

- **桌面应用**：双击 `spoken-web.exe`，自动起服务并用浏览器打开页面（分发给别人用这个）
- **源码运行**：`python launcher.py` 或 `python server.py`

两条主线：
1. **四六级口语考试（CET-SET4 / CET-SET6）**——按官方机考流程复刻，逐段打分并出整场报告
2. **场景练习**——自由对话，实时纠错

## 目录结构

```
v2-web/
├── README.md            本文件（开发指南）
├── requirements.txt     Python 依赖
├── launcher.py          桌面应用入口：找端口起服务 + 开浏览器 + 控制小窗
├── apppaths.py          路径解析（源码态 / exe 冻结态两套规则）
├── server.py            FastAPI 后端：把 spoken 包暴露成 HTTP 接口
├── exam.py              四六级口语考试引擎（考试结构 / 出题 / 六维评分 / 报告）
├── spoken/              spoken 核心包（对话 / 纠错 / ASR / 场景）
├── papers/              题库（纯 JSON，加题只改这里，不用动代码）
│   ├── cet4.json        四级卷 12 套
│   └── cet6.json        六级卷 10 套
├── web/                 前端（纯 HTML/CSS/JS，无需构建，改完刷新即生效）
│   ├── index.html       三个视图：首页 / 四六级考试 / 场景练习
│   ├── style.css        设计系统（浅色为主 + 深色切换，CSS 变量驱动）
│   ├── app.js           公共层：API 封装、录音、主题、视图切换、场景练习
│   └── exam.js          考试流程：选卷 → 准备倒计时 → 作答 → 评分反馈 → 报告
├── spoken_web.spec      PyInstaller 打包配置
├── config.example.yaml  配置模板（首次运行复制到用户目录）
├── .github/workflows/   CI：推 tag 自动构建 exe 并发 Release
└── _uitest/             回归测试（jsdom 58 项 + 3 个 Python e2e 脚本）
```

## 快速开始（源码）

```bash
# 1. 装依赖（用 v1-desktop/.venv 那个环境最省事）
pip install -r requirements.txt

# 2. 启动（在 v2-web/ 目录下）
python launcher.py        # 推荐：自动开浏览器 + 控制小窗
python server.py          # 纯后端，自己开 http://127.0.0.1:8000
```

说明：
- 后端会自动读取配置里的 API Key 调用真实大模型；没配置时考试板块降级为
  「内置题库 + 离线规则评分」，场景练习降级为 MockLLM。
- 源码运行时配置优先读 `v2-web/config.yaml`，没有就沿用 `../v1-desktop/config.yaml`。
- 语音识别模型启动时就在后台预热（打包版首次要几分钟，页面顶部会提示）。
- 首次使用浏览器会弹出麦克风授权，点允许。不授权也能用打字完成全部流程。

## 打包成 Windows 应用

```bash
# 在 v2-web/ 目录下（需要先 pip install pyinstaller）
python -m PyInstaller spoken_web.spec --noconfirm --clean
# 产物：dist/spoken-web/ ，整个文件夹压缩成 zip 即可分发
```

几个刻意为之的决定：

| 决定 | 原因 |
| --- | --- |
| onedir 而不是 onefile | 包里有 ctranslate2/tokenizers 的原生 DLL，单文件每次启动都要解压两三百 MB，冷启动十几秒 |
| 不开 UPX | 压缩过的 bootloader 常被杀毒软件误报，用户不敢运行 |
| 语音模型不打包 | 省几百 MB；首次用麦克风时自动下载，还方便换模型 |
| 配置不打包 | 只带 `config.example.yaml` 模板，首次运行生成到 `%APPDATA%\spoken-web\config.yaml`，不会泄露开发者的 API Key |
| 用浏览器而不是内嵌 WebView | 录音依赖 `getUserMedia`，WebView2 里常被静默拒绝；浏览器权限流程最可靠 |

推送 tag 时 CI 会自动构建并发布：

```bash
git tag v2.0.0 && git push origin v2.0.0
```

Workflow 里带体积与内容自检：产物小于 80MB（依赖缺失）、前端/题库没打进去、
或检测到 `config.yaml` 被打包（可能泄露 Key）都会直接失败。

## 四六级口语考试板块

### 考试结构（对照官方表格）

**CET-SET4（约 15 分钟，5 个任务）**

| 部分 | 任务 | 准备 | 答题 |
| --- | --- | --- | --- |
| Part 1 | 自我介绍 | — | 20 秒 |
| Part 2 | 短文朗读（约 120 词） | 45 秒 | 1 分钟 |
| Part 3 | 简短回答（2 个问题） | — | 40 秒 |
| Part 4 | 个人陈述 | 45 秒 | 1 分钟 |
| Part 5 | 两人互动 | 1 分钟 | 3 分钟 |

**CET-SET6（约 30 分钟，5 个作答段）**

| 部分 | 任务 | 准备 | 答题 |
| --- | --- | --- | --- |
| Part 1 | 自我介绍 | — | 20 秒 |
| Part 1 | 回答考官提问 | — | 30 秒 |
| Part 2 | 个人陈述 | 1 分钟 | 1 分 30 秒 |
| Part 2 | 两人讨论 | —（含在准备内） | 3 分钟 |
| Part 3 | 回答追问 | — | 45 秒 |

### 题库：22 套仿真卷，可自己加

题库放在 `papers/cet4.json` 与 `papers/cet6.json`，**不写在代码里**——加题只改 JSON，刷新页面即生效。

| 级别 | 套数 | 覆盖话题 |
| --- | --- | --- |
| 四级 | 12 | 学习习惯、城市出行、兼职、图书馆、独立生活、健康、环保、睡眠、志愿、公共交通、兴趣爱好 |
| 六级 | 10 | AI 与就业、创业、短视频与注意力、老龄化、远程办公、传统文化、快时尚、心理健康、城市选择、考研与学历 |

出题有两种方式：

- **题库（默认）**：点级别卡片随机抽一套，秒开、可复现、离线可用。展开卡片里的「题库 N 套」可以按话题挑特定一套。
- **AI 现出**：题库折叠里点「让 AI 现出一套新题」，由模型现场生成一整套（约 5–15 秒），适合题库刷完之后。

加一套卷子：往对应 JSON 的 `papers` 数组追加一个对象即可。

```jsonc
// papers/cet4.json —— 四级一套（其余字段见现有条目）
{
  "id": "cet4-13",                       // 唯一套号，前端显示为序号
  "title": "卷名（列表里显示）",
  "tags": ["话题1", "话题2"],             // 中文标签，便于按话题挑卷
  "reading": {
    "title": "短文标题",
    "passage": "约 120 词的英文短文……",   // 少于 60 词会被判为无效卷而跳过
    "questions": ["问题一？", "问题二？"]  // 至少 2 个，且必须能从短文里答出来
  },
  "presentation": {
    "topic": "陈述主题",
    "points": ["提示点一", "提示点二", "提示点三"],
    "prompt": "Describe … You have one minute."
  },
  "interaction": {
    "situation": "互动场景设定",
    "task": "两人要一起完成的任务",
    "partner_role": "AI 搭档扮演的角色"
  }
}
```

六级的字段是 `exam_qa`（考官提问，2 个）、`presentation`、`discussion`、`followup`（追问）。

> 说明：题库为**按官方题型与时长编写的仿真卷**，话题取自历年高频题类，不是官方真题原文。
> 想换成真题原文，直接替换 `passage` 字段即可（注意版权与来源标注）。

### 评分：官方六维

准确性、语言范围、话语长短、连贯性、灵活性、适切性，每项 1-5 分，折算百分制与 A/B/C/D 等级。
每段答完立即出反馈（等级、六维条、点评、改进点、更地道的参考表达），全部答完出整场报告（六维雷达图 + 逐段明细 + 训练建议）。

**朗读题不让模型"凭感觉"打准确度**：本地做词级 Levenshtein 对齐算 WER（词错误率），
准确度一项由 WER 决定，并列出读错/漏读/多读的具体单词；模型只评估流利度与表达。

### 两人互动由 AI 扮演搭档

互动与讨论环节，你可以说一句、发给搭档，AI 会接话、提问、甚至表达不同意见。
提交评分时，对话记录（`Candidate:` / `Partner:`）会一起交给模型，
这样"有没有接住对方、有没有推进任务"才能被评出来。

### 离线兜底

没有 API Key 或模型调用失败时：
- 题目来自 `papers/*.json` 的题库（四级 12 套、六级 10 套），整套流程照样跑
- 评分退化为规则计算（语速、词量、词汇丰富度、衔接词密度），并在界面明确标注"离线简评"
- 朗读题的 WER 客观比对不受影响（本来就是本地算的）

## API 一览

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/status` | 服务状态（spoken 包是否可用、当前 LLM） |
| GET | `/api/scenarios` | 场景列表（复用 v1 的 12 场景 + 自定义场景） |
| POST | `/api/session` | 创建会话 `{scenario, difficulty}` → 开场白 |
| POST | `/api/chat` | 发一轮 `{session_id, text}` → AI 回复 + 纠错 + 新词 |
| POST | `/api/summary` | 结束并生成练习总结 |
| POST | `/api/transcribe` | 上传 16kHz 单声道 WAV → 识别文本 |
| GET | `/api/exam/specs` | 四级/六级考试结构（部分、时长、任务、题库套数） |
| GET | `/api/exam/papers` | 题库目录 `?level=cet4` → 每套的套号 / 标题 / 话题标签 |
| POST | `/api/exam/start` | 开始考试 `{level, paper_id?, source?}` → `{session_id, task, spec, paper}`；`source` 为 `bank`（默认，题库随机）/ `ai`（模型现出）/ `auto`（模型优先） |
| POST | `/api/exam/submit` | 提交一段并评分 `{session_id, index, text, duration}` → `{result, next, finished}` |
| POST | `/api/exam/partner` | 互动任务中 AI 搭档回一句 `{session_id, index, text}` |
| POST | `/api/exam/report` | 整场报告 `{session_id}` → 等级 / 六维 / 逐段点评 / 建议 |

## 回归测试

三段测试，改完代码按需跑。Python 脚本用 v1-desktop 的虚拟环境（复用同一套依赖）：

```bash
# 1) 离线题库校验（秒级，不需要起服务）
../v1-desktop/.venv/Scripts/python.exe _uitest/test_bank.py
#    22 套卷的字段完整性、主题去重、逐套可加载、离线六维兜底

# 2) 考试链路 e2e（需要服务已启动，真实调模型，约 2 分钟）
../v1-desktop/.venv/Scripts/python.exe _uitest/test_exam_api.py
#    静态资源 / 题库接口 / 非法入参 / 四级五段完整流程 / WER 客观性
#    / 答非所问判低分 / 空回答 / 六级讨论 + AI 搭档 / source=ai 现出题

# 3) 练习链路 e2e（需要服务已启动，含真实语音识别，约 1 分钟）
../v1-desktop/.venv/Scripts/python.exe _uitest/test_practice_api.py
#    场景列表 / 建会话 / 三轮对话纠错 / 总结 / 非法场景
#    / SAPI 合成语音 → 重采样 16k → faster-whisper 转写准确率

# 4) 前端 UI 集成测试（jsdom）
cd _uitest && npm install && node uitest.js
```

前端用 jsdom 真跑 `index.html + app.js + exam.js`，模拟后端响应，驱动完整点击流程，
并断言无未捕获的 JS 运行时错误。改完前端跑一遍，能拦住大部分低级错误。

## 分阶段开发计划

**阶段 1（已完成）**：页面骨架、场景练习、语音输入（录音 → 重采样 16kHz → WAV）、AI 朗读。

**阶段 2（已完成）**：四六级口语考试板块 —— 官方流程复刻、六维评分、朗读 WER 客观比对、AI 搭档、整场报告；界面重做（三视图 + 深浅色）。

**阶段 3（进行中）**：题库扩充（已完成 22 套仿真卷 + 选卷入口）、练习历史与趋势（复用 v1 的 `history.py`）、错题收藏。

**阶段 4**：部署上线 —— 后端 Render/Railway，前端静态托管，或整体 Docker。
注意：部署到公网后 API Key 放服务端环境变量，**绝不要放前端代码里**；公网还需自己加登录与限流。

## 前端学习路径（给第一次写 Web 的你）

重点先看懂这五件事（`app.js` / `exam.js` 里都有中文注释）：

1. **`fetch`** —— 向后端发请求，等价于 Python 的 `requests.post`
2. **`async/await`** —— 和 Python 3.5+ 的写法一模一样
3. **DOM 操作** —— `document.getElementById("x").innerText = ...` 改页面内容
   （Python 里没有对应物，唯一真正的新概念）
4. **事件绑定 / 事件委托** —— `el.onclick = fn`，或在 `document` 上统一监听
5. **录音三件套** —— `getUserMedia`（申请麦克风）→ `MediaRecorder`（录音）→
   `OfflineAudioContext`（重采样到 16kHz）

改哪里：改文字和结构 → `index.html`；改配色与间距 → `style.css` 顶部的 CSS 变量；
改交互 → `app.js`（公共）或 `exam.js`（考试流程）。保存后刷新浏览器即可，无需重启后端。

## 与 v1-desktop 的关系

```
v1-desktop/    Windows 桌面版（tkinter GUI），继续独立维护，git 仓库在这里
v2-web/        Web 版（本目录），复用 v1 的 spoken 核心包
miniprogram/   微信小程序（独立项目，未纳入版本管理）
```

`server.py` 通过 `sys.path` 指向 `../v1-desktop` 导入 `spoken` 包。
**改对话逻辑/纠错规则请去 v1-desktop 改**（两边同时生效）；考试相关的逻辑全在 `exam.py`。
