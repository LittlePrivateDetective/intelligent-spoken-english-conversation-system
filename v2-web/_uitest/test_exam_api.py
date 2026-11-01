"""HTTP 端到端自检（真实模型）。用完可删。

真实字段（2026-11-01 核对）：
  start  -> session_id / task / spec / llm / paper_source / paper / bank_size
  submit -> result / next / finished
  result -> scores(6维) / comment / strengths / improvements / better_version /
            wer / score_pct / level / index / label / answer / duration / words
  report -> grade / score / dimensions[list] / parts / strongest / weakest /
            issues / advice / offline / paper_source / paper
  cet4 kinds: self_intro reading qa presentation interaction
  cet6 kinds: self_intro exam_qa presentation discussion followup
"""
import sys, time
import requests

BASE = "http://127.0.0.1:8000"
fails = []
def check(ok, msg, extra=""):
    print(("  PASS  " if ok else "  FAIL  ") + msg + (("  -> " + str(extra)[:200]) if (not ok and extra) else ""))
    if not ok:
        fails.append(msg)

def post(path, payload, timeout=240):
    t = time.time()
    r = requests.post(BASE + path, json=payload, timeout=timeout)
    return r, time.time() - t

def start(level, **kw):
    body = {"level": level, "source": "bank"}
    body.update(kw)
    r, dt = post("/api/exam/start", body, 300)
    assert r.status_code == 200, r.text[:200]
    return r.json(), dt

ANSWERS = {
    "self_intro": "Good morning. My name is Li Ming, and I am a senior student majoring in automation at a university in southern China. In my free time I enjoy playing basketball with my roommates and watching documentaries about engineering.",
    "qa": "The speaker compares reading with a phone screen because a printed page does not keep sending you alerts, so your mind slows down and your thoughts settle. To start the habit, the speaker suggests picking one book, putting it beside your pillow, and opening it tonight.",
    "exam_qa": "In my opinion, artificial intelligence will change many jobs but it will not simply take them away. The people who lose out are those doing repetitive tasks, while those who can use these tools will do more valuable work. Students should learn to work with AI instead of fearing it.",
    "presentation": "The skill I would like to learn is public speaking, because I often feel nervous when I speak in front of a group. To learn it, I would join the English corner on campus and practise short speeches every week, and I would record myself and listen back. In the future this skill would help me in job interviews and when I present my work to a team.",
    "interaction": "Hey, about the trip, I was thinking we could go to the seaside park, because it is cheap and close to the campus. We could take the bus together, and I can bring some snacks and water. What do you think? Maybe you could handle the tickets and I will plan the route.",
    "discussion": "That is a good point. I agree that universities should teach students how to use AI tools, but I also think the basics still matter, because you cannot judge the output if you do not understand the subject. Maybe we can agree that every course should include one assignment with AI, and one without it, so students learn both.",
    "followup": "I would say the biggest change is that we need to keep learning new tools all the time, because the ones we use today may be replaced in two years. So the ability to learn quickly matters more than any single skill.",
}

print("=" * 62)
print("[A] 静态资源与页面结构")
print("=" * 62)
r = requests.get(BASE + "/", timeout=10)
check(r.status_code == 200, f"GET / -> {r.status_code}")
html = r.text
for f in ("app.js", "exam.js", "style.css"):
    check(f in html, f"index.html 引用 {f}")
for vid in ("view-home", "view-exam", "view-practice"):
    check(vid in html, f"含视图 {vid}")
for p in ("/app.js", "/exam.js", "/style.css"):
    rr = requests.get(BASE + p, timeout=10)
    check(rr.status_code == 200 and len(rr.content) > 5000, f"GET {p} ({len(rr.content)} B)")
rr = requests.get(BASE + "/no-such-page.html", timeout=10)
check(rr.status_code == 404, f"不存在的静态文件 -> {rr.status_code}")
check("<html" in html.lower() and "charset" in html.lower(), "HTML 结构与编码声明正常")

print()
print("=" * 62)
print("[B] 题库与规格接口")
print("=" * 62)
for lv, expect in (("cet4", 12), ("cet6", 10)):
    rr = requests.get(BASE + "/api/exam/papers", params={"level": lv}, timeout=10)
    lvl = (rr.json().get("levels") or {}).get(lv) or {}
    ps = lvl.get("papers") or []
    check(lvl.get("count") == expect, f"{lv} count={lvl.get('count')} (期望 {expect})")
    check(len(ps) == expect and all(p.get("id") and p.get("title") for p in ps),
          f"{lv} 列表 {len(ps)} 项，字段完整")
    check(all("reading" not in p and "passage" not in p for p in ps), f"{lv} 列表不含正文")
    check(all(p.get("tags") for p in ps), f"{lv} 每套有话题标签")

d = requests.get(BASE + "/api/exam/specs", timeout=10).json()
ex = {e["key"]: e for e in d.get("exams", [])}
check(set(ex) == {"cet4", "cet6"}, f"两级规格 {list(ex)}")
check(ex["cet4"]["task_count"] == 5 and ex["cet6"]["task_count"] == 5, "两级各 5 段")
check(ex["cet4"]["paper_count"] == 12 and ex["cet6"]["paper_count"] == 10,
      f"paper_count {ex['cet4']['paper_count']}/{ex['cet6']['paper_count']}")
check([s["part"] for s in ex["cet4"]["steps"]] == [1, 2, 3, 4, 5], "四级步骤 1-5")
# 六级官方只有 3 个大 Part：1=自我介绍与问答(2 子任务) 2=陈述和讨论(2 子任务) 3=问答
check([s["part"] for s in ex["cet6"]["steps"]] == [1, 1, 2, 2, 3],
      f"六级 part 分组 {[s['part'] for s in ex['cet6']['steps']]}（官方 3 大 Part）")
check(len({s["label"] for s in ex["cet6"]["steps"]}) == 5, "六级 5 个子任务标签互不重复")

print()
print("=" * 62)
print("[C] 非法入参")
print("=" * 62)
rr = requests.post(BASE + "/api/exam/start", json={"level": "cet8"}, timeout=30)
check(rr.status_code == 400, f"非法级别 -> {rr.status_code}")
rr = requests.post(BASE + "/api/exam/start", json={"level": "cet4", "paper_id": "bogus-99"}, timeout=60)
check(rr.status_code == 200 and rr.json().get("paper_source") == "bank",
      f"不存在 paper_id 自动降级（{rr.status_code}）")
rr = requests.post(BASE + "/api/exam/submit", json={"session_id": "no-such", "index": 0, "text": "hi"}, timeout=20)
check(rr.status_code == 404, f"未知 session 提交 -> {rr.status_code}")
rr = requests.post(BASE + "/api/exam/report", json={"session_id": "no-such"}, timeout=20)
check(rr.status_code == 404, f"未知 session 报告 -> {rr.status_code}")

# 越界索引
d0, _ = start("cet4", paper_id="cet4-01")
rr = requests.post(BASE + "/api/exam/submit",
                   json={"session_id": d0["session_id"], "index": 99, "text": "x"}, timeout=20)
check(rr.status_code == 400, f"越界题号 -> {rr.status_code}")

print()
print("=" * 62)
print("[D] 真实模型 · 四级完整流程（cet4-01，答案全部切题）")
print("=" * 62)
sd, dt = start("cet4", paper_id="cet4-01")
sid = sd["session_id"]
task = sd["task"]
check(bool(sd["paper"].get("title")), f"套卷 {sd['paper'].get('title')}")
check(sd["paper_source"] == "bank", f"来源 {sd['paper_source']}")
check("qwen" in (sd.get("llm") or ""), f"模型 {sd.get('llm')}")
check(task["kind"] == "self_intro" and task["index"] == 0, f"首段 {task['kind']}")
check(len(sd["spec"]["steps"]) == 5, f"spec 带 {len(sd['spec']['steps'])} 步路线图")
print(f"  (start {dt:.1f}s)")

kinds, times = [], []
ok_flow = True
for _ in range(10):
    k = task["kind"]
    kinds.append(k)
    if k == "reading":
        text = ((task.get("detail") or {}).get("passage") or "").strip()
    else:
        text = ANSWERS.get(k, "I think it is an interesting question. In my opinion there are several reasons.")
    rr, st = post("/api/exam/submit",
                  {"session_id": sid, "index": task["index"], "text": text,
                   "duration": task.get("answer") or 60})
    times.append(st)
    if rr.status_code != 200:
        check(False, f"段{task['index']+1} {k} 提交失败", rr.text)
        ok_flow = False
        break
    b = rr.json()
    res = b["result"]
    check(bool(res.get("comment")), f"段{task['index']+1} {k} 有评语 ({st:.1f}s)")
    sc = res.get("scores") or {}
    check(len(sc) == 6 and all(isinstance(v, int) and 1 <= v <= 5 for v in sc.values()),
          f"段{task['index']+1} 六维合法 {list(sc.values())}")
    check(isinstance(res.get("level"), str) and res["level"] in "ABCD", f"段{task['index']+1} 等级 {res.get('level')}")
    if k == "reading":
        wer = res.get("wer") or {}
        check(isinstance(wer, dict) and "wer" in wer, f"朗读段 WER 字段存在 {wer.get('wer')}")
        _w = wer.get("wer")
        check(_w is not None and _w < 0.15, f"读原文 WER 应≈0（实测 {_w}）")
        check((sc or {}).get("accuracy", 0) >= 4, f"读原文准确度应高分（{sc.get('accuracy')}）")
        check(len((task.get("detail") or {}).get("passage") or "") > 100, "朗读段下发了原文")
    if b.get("finished"):
        check(b.get("next") is None, "最后一段后 next 为空")
        break
    task = b["next"]

check(kinds == ["self_intro", "reading", "qa", "presentation", "interaction"], f"五段顺序 {kinds}")
print(f"  (各段 {[round(x,1) for x in times]} s)")

rr, rt = post("/api/exam/report", {"session_id": sid})
check(rr.status_code == 200, f"报告生成 ({rt:.1f}s)")
rep = rr.json()
check(bool(rep.get("grade")), f"等级 {rep.get('grade')} / {rep.get('score')}")
check(len(rep.get("dimensions") or []) == 6, f"六维 {len(rep.get('dimensions') or [])} 项")
check(all(d.get("key") and d.get("name") and "score" in d for d in rep["dimensions"]), "六维字段完整")
check(not rep.get("offline"), f"走真实模型（offline={rep.get('offline')}）")
check(len(rep.get("parts") or []) == 5, f"分段卡 {len(rep.get('parts') or [])} 张")
check(bool(rep.get("advice")), f"建议 {len(rep.get('advice') or [])} 条")
check(rep.get("paper_source") == "bank", f"来源 {rep.get('paper_source')}")
check(rep.get("paper", {}).get("id") == "cet4-01", f"报告套卷 {rep.get('paper', {}).get('id')}")
check((rep.get("score") or 0) >= 60, f"切题作答应达 B 档（{rep.get('score')} 分，等级 {rep.get('grade')}）")
print(f"  >>> {rep.get('grade')} / {rep.get('score')}；"
      f"强项 {(rep.get('strongest') or {}).get('name')}，弱项 {(rep.get('weakest') or {}).get('name')}")

print()
print("=" * 62)
print("[E] 质量校验：读错词 / 答非所问 / 空回答")
print("=" * 62)
# E1 朗读读错 → WER 上升、准确度下降
d1, _ = start("cet4", paper_id="cet4-05")
b1 = post("/api/exam/submit", {"session_id": d1["session_id"], "index": 0, "text": "My name is Li. I study English.", "duration": 20})[0].json()
reading_task = b1["next"]
passage = (reading_task.get("detail") or {}).get("passage") or ""
# 后半句改成乱词，模拟读错一半
words = passage.split()
half = " ".join(words[: len(words) // 2]) + " " + " ".join(["banana"] * max(3, len(words) // 4))
rr = post("/api/exam/submit", {"session_id": d1["session_id"], "index": 1, "text": half, "duration": 60})[0]
res = rr.json()["result"]
wer2 = (res.get("wer") or {}).get("wer")
check(wer2 is not None and wer2 > 0.2, f"读错后 WER 上升（{wer2}）")
check((res.get("scores") or {}).get("accuracy", 5) <= 3, f"读错后准确度下降（{(res.get('scores') or {}).get('accuracy')}）")

# E2 答非所问 → 低分
OFF_TOPIC = "I have a cat. My cat is orange. Yesterday I bought some milk and bread from the supermarket near my home. The weather is nice today."
d2, _ = start("cet4", paper_id="cet4-07")
sid2 = d2["session_id"]
b = post("/api/exam/submit", {"session_id": sid2, "index": 0, "text": ANSWERS["self_intro"], "duration": 20})[0].json()
p2 = (b["next"].get("detail") or {}).get("passage") or ""
post("/api/exam/submit", {"session_id": sid2, "index": 1, "text": p2, "duration": 60})
rr = post("/api/exam/submit", {"session_id": sid2, "index": 2, "text": OFF_TOPIC, "duration": 40})[0]
check(rr.status_code == 200, f"答非所问提交 {rr.status_code}")
res = rr.json()["result"]
check(res.get("level") in ("C", "D"), f"答非所问判低等级（{res.get('level')} / {res.get('score_pct')}）")
_pct = res.get("score_pct")
check(_pct is not None and _pct < 60, f"答非所问分数偏低（{_pct}）")

# E3 空回答 → 未作答提示 + 1 分
d3, _ = start("cet4", paper_id="cet4-09")
rr = post("/api/exam/submit", {"session_id": d3["session_id"], "index": 0, "text": "", "duration": 20})[0]
res = rr.json()["result"]
check((res.get("score_pct") or -1) == 0 or res.get("level") == "D", f"空回答判 D/0（{res.get('level')} / {res.get('score_pct')}）")
check("没有检测到有效回答" in (res.get("comment") or "") or "未作答" in (res.get("comment") or ""),
      "空回答给出未作答提示")

print()
print("=" * 62)
print("[F] 六级完整流程 + AI 搭档")
print("=" * 62)
d6, _ = start("cet6", paper_id="cet6-02")
sid6 = d6["session_id"]
t6 = d6["task"]
check(d6["paper"].get("title") == "AI and the Job Market" or bool(d6["paper"].get("title")),
      f"六级套卷 {d6['paper'].get('title')}")
k6, ok6 = [], True
for _ in range(10):
    k = t6["kind"]
    k6.append(k)
    rr, st = post("/api/exam/submit",
                  {"session_id": sid6, "index": t6["index"],
                   "text": ANSWERS.get(k, ANSWERS["discussion"]),
                   "duration": t6.get("answer") or 30})
    if rr.status_code != 200:
        check(False, f"六级段{k} 失败", rr.text)
        ok6 = False
        break
    b = rr.json()
    check(bool(b["result"].get("comment")), f"六级段{t6['index']+1} {k} 有评语 ({st:.1f}s)")
    if b.get("finished"):
        break
    t6 = b["next"]
check(k6 == ["self_intro", "exam_qa", "presentation", "discussion", "followup"], f"六级五段顺序 {k6}")

rr, pt = post("/api/exam/partner",
              {"session_id": sid6, "index": 3,
               "text": "I think universities should teach AI tools, but they should also keep the basics."})
check(rr.status_code == 200, f"partner 响应 ({pt:.1f}s)")
pj = rr.json()
reply = (pj.get("reply") or "").strip()
check(bool(reply), f"搭档回复：{reply[:90]}")
if reply:
    ascii_letters = sum(1 for c in reply if c.isascii() and c.isalpha())
    check(ascii_letters > len(reply) * 0.5, "回复以英文为主")

rr, gt = post("/api/exam/report", {"session_id": sid6})
check(rr.status_code == 200, f"六级报告 ({gt:.1f}s)")
r6 = rr.json()
check(bool(r6.get("grade")) and len(r6.get("dimensions") or []) == 6,
      f"六级 {r6.get('grade')} / {r6.get('score')}，六维 {len(r6.get('dimensions') or [])}")
print(f"  >>> 六级 {r6.get('grade')} / {r6.get('score')}")

print()
print("=" * 62)
print("[G] AI 现出一套（source=ai）")
print("=" * 62)
rr, at = post("/api/exam/start", {"level": "cet4", "source": "ai"}, 300)
check(rr.status_code == 200, f"AI 出题 ({at:.1f}s)")
da = rr.json()
check(da.get("paper_source") == "llm", f"来源 {da.get('paper_source')}")
t = da.get("task") or {}
check(t.get("kind") == "self_intro", f"AI 卷首段 {t.get('kind')}")
# AI 卷的朗读段要下发正文，否则朗读题没法做
b = post("/api/exam/submit", {"session_id": da["session_id"], "index": 0,
                              "text": ANSWERS["self_intro"], "duration": 20})[0].json()
nxt = b.get("next") or {}
check(nxt.get("kind") == "reading", f"AI 卷第 2 段 {nxt.get('kind')}")
check(len((nxt.get("detail") or {}).get("passage") or "") > 100,
      f"AI 卷朗读段有正文（{len((nxt.get('detail') or {}).get('passage') or '')} 字符）")

print()
print("=" * 62)
print(f"[H] 结果：{'全部通过' if not fails else str(len(fails)) + ' 项失败'}")
print("=" * 62)
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
