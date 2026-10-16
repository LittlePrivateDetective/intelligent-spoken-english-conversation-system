# spoken — 智能英语口语教练（Windows 桌面版）

选择场景和难度，AI 扮演对应角色陪你练英语：**对着麦克风说话**，软件自动识别成文字发给大模型，AI 用语音回复并同步显示文字；每轮附带委婉的纠错反馈（错在哪、为什么、更地道的说法）；对话结束后弹出总结报告。

适用于：想提升英语口语表达能力、需要真实场景演练（寒暄 / 值机 / 面试 / 点餐）的学习者。

## 功能特性

- **12 大场景 × 3 档难度**：日常寒暄 / 机场值机 / 英文面试 / 餐厅点餐 / 商务会议 / 旅行规划 / 酒店入住 / 购物沟通 / 就医问诊 / 电话沟通 / 观点讨论 / 校园生活；初级（A2）/ 中级（B1）/ 高级（C1）
- **语音对话**：点击麦克风说话，本地语音识别（faster-whisper）转文字；AI 回复自动语音朗读（Windows 自带语音）
- **实时纠错**：规则引擎 + AI 双通道，指出错误、说明原因、给出更地道表达；**没有错误时不硬凑反馈**
- **动态难度**：根据每轮表现评估你的水平，自动调整用词和句法难度
- **卡壳给提示**：检测到卡壳时给提示和参考句子，不会直接结束对话
- **不编造**：所有纠错的“原话”必须是你真实说过的句子片段，引擎硬校验
- **总结报告**：错误总数、分类统计、没用到的词汇、改进点清单，并保存 Markdown 报告
- **文字兜底**：语音组件未安装或麦克风不可用时，可直接打字，功能不受影响
- **发音评分**：接入阿里云语音评测，跟读后返回准确度 / 完整度 / 流利度三维评分与简短反馈（可选）
- **实时字幕与提示**：跟读时显示当前参考句与关键词提示，识别结果实时字幕辅助对照（可选）
- **智能生词本**：对话或查词时一键收藏生词，自动生成词形变换、同词性对比、短语搭配，本地 SQLite 存储，支持搜索 / 排序 / 删除
- **练习历史**：记录每次练习的日期 / 场景 / 难度 / 得分，提供历史列表与平均分趋势统计
- **云端语音（可选）**：启用 DashScope CosyVoice 可获得更清晰音色与多语种口音；离线默认使用系统语音
- **自定义场景**：内置 12 个场景之外，可自行创建专属场景（角色、设定、目标、识别热词），配置保存在本地、持久化复用
- **自动更新检查**：启动后静默查询 GitHub Release，发现新版本时弹出非阻塞下载提示（限流与离线自动跳过）
- **中英双语界面**：设置页一键切换 中文 / English，场景卡片等数据内容同步切换主显示语言
- **深色模式**：浅色 / 深色双主题，长时间练习不刺眼；窗口位置与大小自动记忆
- **快捷键**：对话页空格键开始/停止录音，Esc 取消当前录音
- **跟读专项练习**：AI 按场景和难度生成英文句子，逐句播放/跟读/三维评分，低分句子自动安排重练（每句最多 2 次），成绩计入练习历史
- **发音评分趋势图**：练习历史按日期绘制总分/准确度/完整度/流利度四条折线，进步一目了然
- **生词本复习提醒**：按遗忘曲线排期（认识进下一档 / 模糊保持 / 忘记当天再现），对话中选中文字右键即可查询收藏，待复习数量实时显示在按钮角标
- **语音设置试听**：调整发音人 / 语速 / 音量 / 口音后，点「试听」先听效果再保存，不合适随时改

## 安装

### 1. 准备 Python

需要 **Python 3.10 及以上**，且必须包含 `tkinter`（图形界面库）。
python.org 官方安装包默认包含 tkinter；安装时勾选 “Add Python to PATH”。

### 2. 获取项目

```bash
git clone https://github.com/LittlePrivateDetective/intelligent-spoken-english-conversation-system.git
cd intelligent-spoken-english-conversation-system
```

### 3. 安装依赖

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e ".[voice]"
```

- `requirements.txt`：核心依赖（requests、PyYAML）
- `[voice]`：语音能力（faster-whisper、sounddevice、pyttsx3）；**不装也能以纯文字模式运行**

### 方式二：下载独立 exe（免 Python 环境）

如果你不想安装 Python 与依赖，可以直接下载打包好的单文件 exe：

1. 打开 [Releases 页面](https://github.com/LittlePrivateDetective/intelligent-spoken-english-conversation-system/releases)
2. 在最新版本下找到 `spoken_vX.X.X_win64.zip`（完整版，约 108MB，含本地语音），
   下载解压到本地任意目录（如桌面）
3. **双击 `spoken.exe` 即可运行**，无需安装任何环境
4. 首次运行会在 `%APPDATA%\spoken` 下创建配置文件 `config.yaml` 与数据库；
   语音识别模型会在首次对话时自动下载到该目录（约 150MB，需联网）
5. 发现新版本时程序会弹出提示，点「下载并更新」即可自动下载并重启安装

> 网速慢？Release 页面同时提供**纯文字精简版** `spoken_vX.X.X_win64_lite.zip`
> （约 24MB，无语音识别/合成，自动降级为文字对话模式），也可在 Actions 页面的
> Artifact 里下载。
>
> 想自己打包？在项目根目录双击 `build_exe.bat` 即可（`build_exe.bat lite` 打精简版，
> 产物为 `dist\spoken.exe`）。

### 4. 配置 API Key

```bash
copy config.example.yaml config.yaml
```

用记事本打开 `config.yaml`，填入你的 Key。支持任何 OpenAI 兼容接口：

| 服务商 | base_url | model 示例 |
| --- | --- | --- |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| Ollama（本地模型） | `http://localhost:11434/v1` | `qwen2.5` 等，key 可随意填 |

> `config.yaml` 含你的密钥，已被 `.gitignore` 排除，不会上传，请勿分享该文件。

**配置文件与数据位置：**

- 源码运行（`python -m spoken`）：配置与数据库写在项目根目录（`config.yaml` / `*.db` / `reports/`）。
- 独立 exe 运行：写到用户数据目录 `%APPDATA%\spoken`（`config.yaml` / `*.db` /
  `models/` / `reports/`），避免写入安装目录（如 `Program Files`）导致无权限。
- 优先级：`--config` 参数 > `SPOKEN_CONFIG` 环境变量 > 当前目录 > `%APPDATA%\spoken`。
- 自定义场景保存在 `custom_scenarios.json`（位置同上），不进入仓库、随机器持久化。

## 运行

**双击项目根目录的 `run.bat`**，或在项目目录执行：

```bash
.venv\Scripts\python.exe -m spoken
```

首次说话时，语音识别模型会自动下载（约 150MB），之后完全离线可用。

> 模型从 HuggingFace 国内镜像 `hf-mirror.com` 下载（`run.bat` 已默认启用），并自动禁用 Xet 协议（该协议经镜像下载会返回 401）。下载器支持**断点续传**：网络中断后再次点击麦克风即可从已下载的位置继续，不会从头再来。
>
> 若多次重试仍下载失败，可手动下载：访问 https://hf-mirror.com/Systran/faster-whisper-base ，下载全部文件（config.json / model.bin / tokenizer.json / vocabulary.txt）放到 `models/faster-whisper-base/`，然后在 `config.yaml` 中设置 `asr_model_local_path: "models/faster-whisper-base"`；或直接打字输入，不使用麦克风。

## 使用方法

1. 在顶部下拉框选择**场景**和**难度**，点击「开始对话」
2. AI 用语音说出开场白，同时显示在聊天区
3. 点击「🎤 点击说话」按钮开始录音，说完再点一次（按钮变为「⏹ 停止并发送」）——识别出的文字会自动发送；也可以直接在输入框打字，回车发送
4. 每轮你会看到：
   - **AI 台词**（自动朗读）
   - **💡 纠错**：“原话” → “更合适的说法”（附原因）
   - **🗣 更地道**：基于你的表达改写的整句
5. 卡壳时 AI 会给中文提示，不会结束对话
6. 点击「结束对话」弹出总结：错误总数、分类统计、没用到的词汇、改进点清单（同时保存 Markdown 报告到 `reports\`）

### 输入输出示例

```
刚认识的朋友: Hi there! I don't think we've met before. How's your day going?
你:  Pretty good. I very like this party.
💡 纠错：“very like” → “really like”（汉语的“很”不能直译成 very 修饰动词，用 really 更自然）
🗣 更地道：I really like this party.
刚认识的朋友: Same here! So, what do you usually like to do in your free time?
...
（结束对话后弹出总结）
错误总数：2
分类统计：表达 1 处；语法 1 处
改进点清单：
  1. 表达问题 1 处 — 多积累完整句型，避免把中文逐字直译成英语。
  2. 语法问题 1 处 — 重点复习动词形式（时态、主谓一致、非谓语）和句子结构。
没用到的词汇：
  · break the ice —— 打破僵场
```

## 语音技术说明

| 能力 | 技术 | 说明 |
| --- | --- | --- |
| 语音识别 | faster-whisper | 本地离线运行，保护隐私；模型大小可在 `config.yaml` 的 `voice.asr_model` 调整（tiny/base/small/medium，默认 base） |
| 语音合成 | pyttsx3 | 调用 Windows 自带语音，离线可用；语速在 `voice.tts_rate` 调整 |
| 云端语音合成 | DashScope CosyVoice | 可选；更清晰音色、多语种口音，需在 `config.yaml` 配置云端 TTS Key |
| 发音评分 | 阿里云语音评测 | 可选；真实声学打分，需单独开通智能语音交互并配置 AppKey |
| 图形界面 | tkinter | Python 官方 GUI 库，无额外依赖 |

纠错说明：**规则引擎**负责常见中式英语错误（主谓一致、时态、介词、固定搭配等 30+ 条规则，确定性强、干净句子零误报）；**AI 通道**补充规则之外的错误，且同样经过“原话必须真实出现过”的校验。

## 验证

```bash
.venv\Scripts\python.exe quick_validate.py
```

离线自动验证（无需 API Key 和麦克风）：12 种场景 × 难度组合完整跑通、纠错命中典型错误、干净句子零误报、同一错误不重复输出、总结结构完整、GUI 正常构建。

## 项目结构

```
spoken/
  gui.py             桌面界面（tkinter）
  dialogue.py        对话引擎（双通道纠错、动态难度、卡壳提示、总结）
  corrector.py       规则纠错模块
  asr.py             语音识别（录音 + faster-whisper）
  model_download.py  模型下载器（国内镜像 + 断点续传 + 重试）
  tts.py             语音合成（pyttsx3 播放队列）
  llm.py             OpenAI 兼容 LLM 客户端 + 离线 Mock
  prompts.py         系统提示构建
  scenarios.py       场景与难度定义
  report.py          总结报告渲染与保存
  accents.py         口音注册表（云端 TTS 多语种口音）
  cloud_tts.py       云端语音合成（CosyVoice HTTP 接口）
  assessor.py        发音评分（阿里云语音评测）
  history.py         练习历史（SQLite）
  vocab_model.py     生词数据模型
  vocab_gen.py       生词生成（通义 Plus）
  vocab_store.py     生词本存储（SQLite）
  cli.py             旧版命令行界面（python -m spoken.cli）
run.bat                双击启动
quick_validate.py      自动验证脚本
config.example.yaml    配置模板
```

## 已知限制

- 暂不支持：账号登录、云端同步、多人对话、手机版
- 语音合成默认使用 Windows 系统语音（音色偏机械）；启用云端 CosyVoice 可获得更自然音色与多语种口音（需配置 Key）
- 发音评分与云端 TTS 为可选增强，需分别开通阿里云「智能语音交互」与百炼 CosyVoice 并配置密钥
- exe 未做代码签名，个别杀毒软件可能误报（打包已关闭 UPX 压缩降低误报概率），遇拦截请添加信任后运行
- 一键更新依赖 GitHub Release：网络不通或被限流时自动跳过，可手动下载新版 zip 覆盖
- 多语种口音目前以 CosyVoice 官方音色清单为准：英语仅美式 / 英式，泰/印/越/马/哈/乌暂无官方音色（可用自定义音色 ID 接入）

## 反馈与贡献

遇到问题或有功能建议，欢迎在 [Issues](https://github.com/LittlePrivateDetective/intelligent-spoken-english-conversation-system/issues) 提交反馈；提交 PR 前请先跑一遍 `quick_validate.py` 与 `verify.py` 确保离线验证全部通过。

## 许可证

MIT License，见 [LICENSE](LICENSE)。
