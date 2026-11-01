"""自检脚本：题库完整性 + 引擎端到端。用完可删。"""
import sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "v2-web"))
sys.path.insert(0, str(ROOT / "v1-desktop"))

import exam as E

fails = []
def check(ok, msg):
    print(("  PASS  " if ok else "  FAIL  ") + msg)
    if not ok:
        fails.append(msg)

def _norm(s):
    return (s or "").strip()

print("=" * 62)
print("[1] 题库结构与内容")
print("=" * 62)

for level, expect in (("cet4", 12), ("cet6", 10)):
    bank = E.load_bank(level)
    check(len(bank) == expect, f"{level} 套数 = {len(bank)} (期望 {expect})")
    check(E.bank_size(level) == expect, f"{level} bank_size() 一致")
    ids = [p.get("id") for p in bank]
    check(len(set(ids)) == len(ids), f"{level} id 无重复")
    titles = [_norm(p.get("title")) for p in bank]
    check(all(titles), f"{level} 每套有标题")
    check(len(set(titles)) == len(titles), f"{level} 标题无重复")

    bad = []
    for p in bank:
        pid = p.get("id")
        if not pid or not p.get("title"):
            bad.append((pid, "缺 id/title"))
            continue
        if not p.get("tags"):
            bad.append((pid, "缺 tags"))
        if level == "cet4":
            r = p.get("reading") or {}
            words = len(_norm(r.get("passage")).split())
            if words < 60:
                bad.append((pid, f"短文仅 {words} 词"))
            if len(r.get("questions") or []) < 2:
                bad.append((pid, f"简答仅 {len(r.get('questions') or [])} 题"))
            pr = p.get("presentation") or {}
            if not _norm(pr.get("topic")):
                bad.append((pid, "陈述缺 topic"))
            if len(pr.get("points") or []) < 2:
                bad.append((pid, "陈述要点不足 2 条"))
            it = p.get("interaction") or {}
            for k in ("situation", "task", "partner_role"):
                if not _norm(it.get(k)):
                    bad.append((pid, f"互动缺 {k}"))
        else:
            qa = p.get("exam_qa") or []
            if len(qa) < 2:
                bad.append((pid, f"问答仅 {len(qa)} 题"))
            pr = p.get("presentation") or {}
            if not _norm(pr.get("topic")):
                bad.append((pid, "陈述缺 topic"))
            if len(pr.get("points") or []) < 2:
                bad.append((pid, "陈述要点不足 2 条"))
            ds = p.get("discussion") or {}
            for k in ("task", "partner_role"):
                if not _norm(ds.get(k)):
                    bad.append((pid, f"讨论缺 {k}"))
            fu = p.get("followup") or []
            if isinstance(fu, dict):
                fu = [fu.get("question")] if fu.get("question") else []
            if not [x for x in fu if _norm(x)]:
                bad.append((pid, "追问为空"))
    check(not bad, f"{level} 字段完整" + ("" if not bad else f" -> {bad[:6]}"))

    # 内容去重：短文/主题不应跨卷重复
    if level == "cet4":
        sigs = [_norm((p.get("reading") or {}).get("passage"))[:80] for p in bank]
    else:
        sigs = [_norm((p.get("presentation") or {}).get("topic")) for p in bank]
    check(len(set(sigs)) == len(sigs), f"{level} 主题/短文无跨卷重复")

print()
print("=" * 62)
print("[2] 引擎逐套加载（离线）")
print("=" * 62)
for level in ("cet4", "cet6"):
    broken = []
    for p in E.load_bank(level):
        try:
            eng = E.ExamEngine(None, level=level, paper_id=p["id"], source="bank")
            eng.prepare()
            if eng.paper_id != p["id"]:
                broken.append((p["id"], "paper_id 不匹配"))
            n = len(eng.tasks)
            if n < 5:
                broken.append((p["id"], f"仅 {n} 段"))
            for i in range(n):
                pl = eng.payload(i)
                if not isinstance(pl, dict) or "index" not in pl or "kind" not in pl or "prompt" not in pl:
                    broken.append((p["id"], f"第 {i} 段 payload 异常"))
                    break
                json.dumps(pl)
        except Exception as e:
            broken.append((p["id"], str(e)[:70]))
    check(not broken, f"{level} 全部 {len(E.load_bank(level))} 套可加载" +
          ("" if not broken else f" -> {broken}"))

check(E.find_paper("cet4", "cet4-01") is not None, "find_paper 正常 id 命中")
check(E.find_paper("cet4", "no-such-id") is None, "find_paper 非法 id 返回 None")
check(E.find_paper("cet6", "cet4-01") is None, "跨级别 id 不串（六级查四级 id 返回 None）")

print()
print("=" * 62)
print("[3] 离线评分兜底")
print("=" * 62)
eng = E.ExamEngine(None, level="cet4", paper_id="cet4-01", source="bank")
eng.prepare()
for i in range(len(eng.tasks)):
    eng.submit(i, "I think reading before bed is a good habit because it helps me relax and sleep better. "
                  "However, sometimes I am too tired to read. In my opinion, we should try it first.", 55)
rep = eng.report()
check(isinstance(rep, dict), "无模型也能出报告")
check(bool(rep.get("grade")), f"报告有等级: {rep.get('grade')} / {rep.get('score')}")
dims = rep.get("dimensions") or []
check(len(dims) == 6, f"六维齐全: {[d.get('name') for d in dims]}")
check(all(d.get("key") and d.get("name") and isinstance(d.get("score"), (int, float)) for d in dims),
      "六维字段完整")
check(len(rep.get("parts") or []) == len(eng.tasks), f"分段卡 {len(rep.get('parts') or [])} 张")
check(bool(rep.get("strongest")) and bool(rep.get("weakest")),
      f"最强项 {rep.get('strongest', {}).get('name') if isinstance(rep.get('strongest'), dict) else rep.get('strongest')} / "
      f"最弱项 {rep.get('weakest', {}).get('name') if isinstance(rep.get('weakest'), dict) else rep.get('weakest')}")
check(bool(rep.get("offline")), "标记为离线路由")
check(rep.get("paper_source") == "bank", f"来源标记 = {rep.get('paper_source')}")

print()
print("=" * 62)
print(f"[4] 结果：{'全部通过' if not fails else str(len(fails)) + ' 项失败'}")
print("=" * 62)
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
