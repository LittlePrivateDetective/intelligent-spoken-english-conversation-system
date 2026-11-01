"""server.py —— spoken 2.0.0 Web 版后端（FastAPI）。

把 v1-desktop 里的 spoken 包（对话引擎 / 纠错 / 语音识别）暴露成 HTTP 接口，
前端（web/ 目录）只负责界面和调用。

启动：
    pip install -r requirements.txt
    python server.py          # 然后浏览器打开 http://127.0.0.1:8000

接口：
    GET  /api/status        服务状态（spoken 是否可用、当前 LLM）
    GET  /api/scenarios     场景列表
    POST /api/session       创建会话 {scenario, difficulty} -> {session_id, opening}
    POST /api/chat          一轮对话 {session_id, text} -> AI 回复 + 纠错 + 新词
    POST /api/summary       结束并总结 {session_id}
    POST /api/transcribe    语音识别（上传 16kHz 单声道 WAV）-> {text}

四六级口语考试（CET-SET）：
    GET  /api/exam/specs    四级/六级考试结构（部分、时长、任务、题库套数）
    GET  /api/exam/papers   题库目录（套号 / 标题 / 话题标签）
    POST /api/exam/start    开始一场考试 {level, paper_id?, source?} -> {session_id, task, spec}
    POST /api/exam/submit   提交一段作答并评分 {session_id, index, text, duration}
    POST /api/exam/partner  互动任务的 AI 搭档回一句 {session_id, index, text}
    POST /api/exam/report   整场报告 {session_id} -> 等级 / 六维 / 逐部分点评
"""

import io
import os
import sys
import threading
import uuid
import wave
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------
# 定位资源目录并导入 spoken 核心包
# ---------------------------------------------------------------------
from apppaths import bundle_dir, config_file, ensure_config, web_dir

# 源码态 = v2-web 目录；冻结态 = PyInstaller 解包目录。
# 两种情况里 spoken/ 与 exam.py 都在同一层，因此统一插 ROOT 即可。
ROOT = bundle_dir()
sys.path.insert(0, str(ROOT))
V1_DIR = ROOT.parent / "v1-desktop"  # 仅源码态兜底用

# spoken 包导入失败时（比如没装 faster-whisper），静态页面照样能打开，
# 只是相关 API 返回 503 并说明原因，不会整个服务起不来。
try:
    from spoken.asr import Transcriber
    from spoken.config import load_config
    from spoken.dialogue import DialogueEngine
    from spoken.llm import MockLLM, OpenAICompatibleLLM
    from spoken.scenarios import get_difficulty, get_scenario, list_scenario_keys

    # exam.py 依赖 spoken.llm 的 JSON 解析；放在同一 try 里，缺依赖时统一降级
    from exam import EXAM_SPECS, ExamEngine, bank_size, list_papers

    SPOKEN_OK = True
    SPOKEN_ERR = ""
except Exception as exc:  # noqa: BLE001
    SPOKEN_OK = False
    SPOKEN_ERR = str(exc)

# ---------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------
@asynccontextmanager
async def _lifespan(_app):
    # 后台预热语音识别模型：实测打包后首次加载要 4-5 分钟（small 模型），
    # 不能等用户按下录音按钮才开始转 —— 那会让人以为程序卡死了。
    _start_asr_warmup()
    yield


app = FastAPI(title="spoken 2.0.0", lifespan=_lifespan)

# 会话表：session_id -> DialogueEngine（内存保存，重启服务即清空）
# 上限 64 场，超出淘汰最旧的 —— 用户中途关页面不总结也不会一直堆积。
MAX_SESSIONS = 64


class SessionTable(OrderedDict):
    """有上限的会话表（FIFO 淘汰最旧），避免只增不减造成内存泄漏。"""

    def __init__(self, limit: int = MAX_SESSIONS):
        super().__init__()
        self.limit = limit

    def put(self, session_id: str, engine) -> None:
        self[session_id] = engine
        self.move_to_end(session_id)
        while len(self) > self.limit:
            self.popitem(last=False)


SESSIONS: "SessionTable" = SessionTable()

# 考试会话表：session_id -> ExamEngine
EXAM_SESSIONS: "SessionTable" = SessionTable()

# 识别器单例：faster-whisper 模型只加载一次（加载慢，约几秒到几十秒）
_TRANSCRIBER: "Transcriber | None" = None


# ---------------------------------------------------------------------
# 请求体模型（FastAPI 用它们自动校验前端发来的 JSON）
# ---------------------------------------------------------------------
class SessionIn(BaseModel):
    scenario: str
    difficulty: str = "intermediate"


class ChatIn(BaseModel):
    session_id: str
    text: str


class SummaryIn(BaseModel):
    session_id: str


class ExamStartIn(BaseModel):
    level: str = "cet4"
    # 指定套号（题库里的 id）；不传则随机抽一套
    paper_id: str | None = None
    # bank：题库随机（默认，秒开）；ai：模型现出一套新题；auto：模型优先
    source: str = "bank"


class ExamSubmitIn(BaseModel):
    session_id: str
    index: int
    text: str = ""
    duration: float = 0.0


class ExamPartnerIn(BaseModel):
    session_id: str
    index: int
    text: str


class ExamReportIn(BaseModel):
    session_id: str


# ---------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------
def _build_llm():
    """构造 LLM 客户端。

    优先读真实配置（首次运行会自动从内置模板生成 config.yaml）；
    没有配置文件或没填 api_key 时降级为 MockLLM（离线演示）。
    返回 (llm 实例, 人类可读的描述)。
    """
    cfg_path, _created = ensure_config()
    if not cfg_path.is_file():
        return MockLLM(), "MockLLM（未找到 config.yaml，离线演示模式）"
    try:
        cfg = load_config(str(cfg_path))
    except Exception as exc:  # noqa: BLE001
        return MockLLM(), f"MockLLM（config.yaml 读取失败：{exc}）"
    if not cfg.api_key or cfg.api_key.startswith("sk-在这里"):
        return MockLLM(), f"MockLLM（还没填 API Key：{cfg_path}）"
    llm = OpenAICompatibleLLM(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        model=cfg.model,
        temperature=cfg.temperature,
        timeout=cfg.timeout,
        think=cfg.think,
    )
    return llm, f"{cfg.model} @ {cfg.base_url}"


def _wav_to_float32(raw: bytes) -> np.ndarray:
    """把 16kHz 单声道 16-bit PCM WAV 字节流转成 float32 波形（-1.0 ~ 1.0）。"""
    with wave.open(io.BytesIO(raw), "rb") as wf:
        n_frames = wf.getnframes()
        channels = wf.getnchannels()
        pcm = wf.readframes(n_frames)
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:  # 多声道取平均，转单声道
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio


def _get_transcriber() -> "Transcriber":
    """识别器懒加载：第一次用时才下载/加载模型（faster-whisper）。"""
    global _TRANSCRIBER
    if _TRANSCRIBER is None:
        model_size, local_path = "base", None
        cfg_path = config_file()
        if cfg_path.is_file():
            try:
                cfg = load_config(str(cfg_path))
                model_size = cfg.asr_model or "base"
                local_path = cfg.asr_model_local_path or None
            except Exception:  # noqa: BLE001
                pass  # 配置读不出来就用默认 base
        _TRANSCRIBER = Transcriber(model_size=model_size,
                                   language="en",
                                   local_path=local_path)
        _TRANSCRIBER.load()
    return _TRANSCRIBER


# 语音模型加载状态，供前端显示「模型加载中，可以先打字」
_ASR_STATE = {"ready": False, "loading": False, "error": ""}


def _warmup_asr() -> None:
    if _ASR_STATE["ready"] or _ASR_STATE["loading"]:
        return
    _ASR_STATE["loading"] = True
    try:
        _get_transcriber()
        _ASR_STATE["ready"] = True
        _ASR_STATE["error"] = ""
    except Exception as exc:  # noqa: BLE001
        _ASR_STATE["error"] = str(exc)[:300]
    finally:
        _ASR_STATE["loading"] = False


def _start_asr_warmup() -> None:
    """启动时后台线程预热识别模型（可用 SPOKEN_SKIP_ASR_WARMUP=1 关闭）。"""
    if not SPOKEN_OK:
        return
    if os.environ.get("SPOKEN_SKIP_ASR_WARMUP") == "1":
        return
    threading.Thread(target=_warmup_asr, name="asr-warmup", daemon=True).start()


# ---------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------
@app.get("/api/status")
def status():
    """前端加载时调用：显示 spoken 包是否可用、当前用的什么 LLM。"""
    llm_desc = None
    if SPOKEN_OK:
        _, llm_desc = _build_llm()
    return {
        "spoken_ok": SPOKEN_OK,
        "spoken_err": SPOKEN_ERR,
        "llm": llm_desc,
        # 语音模型状态：前端据此提示「加载中，可以先打字」
        "asr": dict(_ASR_STATE),
        "version": "2.0.0",
    }


@app.get("/api/scenarios")
def scenarios():
    """场景列表（复用 v1 的 12 个内置场景 + 用户自定义场景）。"""
    if not SPOKEN_OK:
        return JSONResponse(
            status_code=503,
            content={"error": f"spoken 包不可用：{SPOKEN_ERR}"})
    items = []
    for key in list_scenario_keys():
        s = get_scenario(key)
        items.append({
            "key": key,
            "name": s.get("name", key),
            "name_en": s.get("name_en", ""),
        })
    difficulties = []
    for key in ("beginner", "intermediate", "advanced"):
        d = get_difficulty(key)
        difficulties.append({"key": key, "name": d.get("name", key)})
    return {"scenarios": items, "difficulties": difficulties}


@app.post("/api/session")
def create_session(body: SessionIn):
    """创建一次练习会话，返回开场白。"""
    if not SPOKEN_OK:
        return JSONResponse(
            status_code=503,
            content={"error": f"spoken 包不可用：{SPOKEN_ERR}"})
    llm, llm_desc = _build_llm()
    try:
        engine = DialogueEngine(llm, body.scenario, body.difficulty,
                                feedback_language="zh")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400,
                            detail=f"场景或难度无效：{exc}") from exc
    session_id = uuid.uuid4().hex[:8]
    SESSIONS.put(session_id, engine)
    opening = engine.start()  # AI 的第一句话
    return {"session_id": session_id, "opening": opening, "llm": llm_desc}


@app.post("/api/chat")
def chat(body: ChatIn):
    """发送用户本轮输入，返回 AI 回复 + 纠错 + 新词。"""
    engine = SESSIONS.get(body.session_id)
    if engine is None:
        raise HTTPException(status_code=404, detail="会话不存在或已结束")
    result = engine.reply(body.text)
    return {
        "ai_line": result.ai_line,
        "corrections": result.corrections,
        "alternatives": result.alternatives,
        "new_words": result.new_words,
        "stuck": result.stuck,
        "hint": result.hint,
        "difficulty": result.difficulty,
        "should_end": result.should_end,
    }


@app.post("/api/summary")
def summary(body: SummaryIn):
    """结束会话，返回练习总结（错误统计 / 未掌握词汇 / 改进建议）。"""
    engine = SESSIONS.pop(body.session_id, None)
    if engine is None:
        raise HTTPException(status_code=404, detail="会话不存在或已结束")
    return engine.summarize()


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """语音识别：接收前端上传的 16kHz 单声道 WAV，返回英文文本。

    前端 app.js 里已封装好「浏览器录音 → 重采样 → 编码 WAV」全流程。
    """
    if not SPOKEN_OK:
        return JSONResponse(
            status_code=503,
            content={"error": f"spoken 包不可用：{SPOKEN_ERR}"})
    raw = await file.read()
    try:
        audio = _wav_to_float32(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400,
                            detail=f"音频解析失败（需要 16kHz WAV）：{exc}") from exc
    try:
        transcriber = _get_transcriber()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503,
                            detail=f"识别模型加载失败：{exc}") from exc
    text = transcriber.transcribe(audio)
    return {"text": text}


# ---------------------------------------------------------------------
# 四六级口语考试（CET-SET）
# ---------------------------------------------------------------------
def _exam_spec_brief(spec: dict) -> dict:
    return {
        "key": spec["key"],
        "name": spec["name"],
        "full_name": spec["full_name"],
        "code": spec["code"],
        "minutes": spec["minutes"],
        "blurb": spec["blurb"],
        "parts": spec["parts"],
        "task_count": len(spec["tasks"]),
        "paper_count": bank_size(spec["key"]),
        "steps": [{
            "index": t["index"],
            "part": t["part"],
            "part_name": t["part_name"],
            "label": t["label"],
            "prep": t["prep"],
            "answer": t["answer"],
        } for t in spec["tasks"]],
    }


@app.get("/api/exam/specs")
def exam_specs():
    """四级 / 六级考试结构（时长与任务对照官方表格）。"""
    if not SPOKEN_OK:
        return JSONResponse(
            status_code=503,
            content={"error": f"spoken 包不可用：{SPOKEN_ERR}"})
    return {"exams": [_exam_spec_brief(s) for s in EXAM_SPECS.values()]}


@app.get("/api/exam/papers")
def exam_papers(level: str = ""):
    """题库目录：每套的套号 / 标题 / 话题标签。

    不带 level 时返回两个级别的全部；前端用它渲染选题列表与套数角标。
    """
    if not SPOKEN_OK:
        return JSONResponse(
            status_code=503,
            content={"error": f"spoken 包不可用：{SPOKEN_ERR}"})
    levels = [level] if level in EXAM_SPECS else list(EXAM_SPECS)
    return {
        "levels": {lv: {"count": bank_size(lv), "papers": list_papers(lv)}
                   for lv in levels},
    }


@app.post("/api/exam/start")
def exam_start(body: ExamStartIn):
    """开始一场考试：默认从题库抽卷（秒开、可复现），source=ai 时让模型现出。"""
    if not SPOKEN_OK:
        return JSONResponse(
            status_code=503,
            content={"error": f"spoken 包不可用：{SPOKEN_ERR}"})
    if body.level not in EXAM_SPECS:
        raise HTTPException(status_code=400, detail=f"不支持的考试级别：{body.level}")
    llm, llm_desc = _build_llm()
    engine = ExamEngine(llm, body.level, paper_id=body.paper_id,
                        source=body.source)
    engine.prepare()
    session_id = uuid.uuid4().hex[:8]
    EXAM_SESSIONS.put(session_id, engine)
    return {
        "session_id": session_id,
        "task": engine.payload(0),
        "spec": _exam_spec_brief(engine.spec),
        "llm": llm_desc,
        "paper_source": engine.paper_source,
        "paper": engine.paper_meta,
        "bank_size": bank_size(body.level),
    }


@app.post("/api/exam/submit")
def exam_submit(body: ExamSubmitIn):
    """提交一段作答并评分，同时返回下一题。

    这条请求会同步调用语言模型打分，通常 3-15 秒，前端需显示「评分中」。
    """
    engine = EXAM_SESSIONS.get(body.session_id)
    if engine is None:
        raise HTTPException(status_code=404, detail="考试会话不存在，请重新开始")
    if not 0 <= body.index < len(engine.tasks):
        raise HTTPException(status_code=400, detail="题号超出范围")
    return engine.submit(body.index, body.text, body.duration)


@app.post("/api/exam/partner")
def exam_partner(body: ExamPartnerIn):
    """两人互动 / 讨论任务：AI 以搭档身份回一句，推动对话继续。"""
    engine = EXAM_SESSIONS.get(body.session_id)
    if engine is None:
        raise HTTPException(status_code=404, detail="考试会话不存在，请重新开始")
    return {"reply": engine.partner_reply(body.index, body.text)}


@app.post("/api/exam/report")
def exam_report(body: ExamReportIn):
    """整场报告：等级、六维得分、逐部分点评与训练建议。"""
    engine = EXAM_SESSIONS.get(body.session_id)
    if engine is None:
        raise HTTPException(status_code=404, detail="考试会话不存在，请重新开始")
    return engine.report()


# ---------------------------------------------------------------------
# 静态前端（必须放在 API 路由之后注册）
# ---------------------------------------------------------------------
app.mount("/", StaticFiles(directory=str(web_dir()), html=True), name="web")


if __name__ == "__main__":
    print("=" * 50)
    print("spoken 2.0.0 Web 服务")
    if SPOKEN_OK:
        print(f"spoken 包：可用（{ROOT}）")
        cfg_used, cfg_created = ensure_config()
        print(f"配置文件：{cfg_used}" + ("（本次新建，请填 api_key）" if cfg_created else ""))
        try:
            print("题库：四级 %d 套 / 六级 %d 套（papers/*.json）"
                  % (bank_size("cet4"), bank_size("cet6")))
        except Exception:  # noqa: BLE001
            pass
    else:
        print(f"spoken 包：不可用 —— {SPOKEN_ERR}")
        print("（页面能打开，但对话/识别 API 会返回 503）")
    print("浏览器打开：http://127.0.0.1:8000")
    print("按 Ctrl+C 停止服务")
    print("=" * 50)
    uvicorn.run(app, host="127.0.0.1", port=8000)
