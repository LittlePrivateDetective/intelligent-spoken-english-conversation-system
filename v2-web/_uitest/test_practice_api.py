"""HTTP 端到端自检 2：场景练习 + 语音识别。用完可删。"""
import sys, os, json, time, wave, subprocess
from pathlib import Path
import numpy as np
import requests

HERE = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8000"
fails = []
def check(ok, msg, extra=""):
    print(("  PASS  " if ok else "  FAIL  ") + msg + (("  -> " + str(extra)[:200]) if (not ok and extra) else ""))
    if not ok:
        fails.append(msg)

print("=" * 62)
print("[I] 场景接口与练习链路")
print("=" * 62)
d = requests.get(BASE + "/api/scenarios", timeout=10).json()
scs = d.get("scenarios") or []
diffs = d.get("difficulties") or []
check(len(scs) >= 12, f"场景 {len(scs)} 个")
check(all(s.get("key") and s.get("name") for s in scs), "场景字段完整")
check(len(diffs) >= 3, f"难度 {len(diffs)} 档：{[x.get('key') if isinstance(x, dict) else x for x in diffs]}")

t = time.time()
rr = requests.post(BASE + "/api/session",
                   json={"scenario": "daily_smalltalk", "difficulty": "intermediate"}, timeout=180)
check(rr.status_code == 200, f"创建会话 {rr.status_code} ({time.time()-t:.1f}s)", rr.text[:200])
sd = rr.json()
sid = sd.get("session_id")
opening = sd.get("opening") or ""
check(bool(sid), f"session_id {sid}")
check(bool(opening.strip()), f"开场白：{opening[:80]}")
check(sum(1 for c in opening if c.isascii() and c.isalpha()) > len(opening) * 0.5, "开场白为英文")

# 故意带语法错误的句子，验证纠错通道
turns = [
    "Hello! I am fine, thank you. And you?",
    "I goes to school yesterday and I buyed a new book, it very interesting.",
    "I think learn English is important because it help me find a better job.",
]
corrections_all = []
for i, txt in enumerate(turns):
    t = time.time()
    rr = requests.post(BASE + "/api/chat", json={"session_id": sid, "text": txt}, timeout=240)
    check(rr.status_code == 200, f"第 {i+1} 轮对话 {rr.status_code} ({time.time()-t:.1f}s)", rr.text[:200])
    if rr.status_code != 200:
        break
    c = rr.json()
    check(bool((c.get("ai_line") or "").strip()), f"第 {i+1} 轮有 AI 回复：{(c.get('ai_line') or '')[:70]}")
    for k in ("corrections", "alternatives", "new_words", "stuck", "hint", "difficulty", "should_end"):
        check(k in c, f"第 {i+1} 轮含字段 {k}")
    corrections_all.extend(c.get("corrections") or [])

check(len(corrections_all) >= 1, f"纠错通道抓到 {len(corrections_all)} 条")
if corrections_all:
    c0 = corrections_all[0]
    check(bool(c0.get("original")) and bool(c0.get("corrected")),
          f"示例纠错：{c0.get('original')} -> {c0.get('corrected')}")
    # 防编造：original 必须是用户原话子串
    joined = " ".join(turns)
    bad = [c for c in corrections_all
           if (c.get("original") or "") not in joined and (c.get("original") or "").lower() not in joined.lower()]
    check(not bad, f"纠错原文均为用户原话子串（越界 {len(bad)} 条）", bad[:2])

t = time.time()
rr = requests.post(BASE + "/api/summary", json={"session_id": sid}, timeout=240)
check(rr.status_code == 200, f"练习总结 {rr.status_code} ({time.time()-t:.1f}s)", rr.text[:200])
if rr.status_code == 200:
    sm = rr.json()
    print("  总结字段:", list(sm.keys()))
    check("total_errors" in sm or "by_category" in sm, "总结含错误统计")
    check(isinstance(sm.get("by_category", {}), (dict, list)), "by_category 结构正常")

# 非法场景 / 已结束会话
rr = requests.post(BASE + "/api/session", json={"scenario": "no_such_scene"}, timeout=60)
check(rr.status_code == 400, f"非法场景 -> {rr.status_code}")
rr = requests.post(BASE + "/api/chat", json={"session_id": "nope", "text": "hi"}, timeout=30)
check(rr.status_code == 404, f"未知会话对话 -> {rr.status_code}")
rr = requests.post(BASE + "/api/summary", json={"session_id": sid}, timeout=30)
check(rr.status_code == 404, f"重复总结（会话已 pop） -> {rr.status_code}")

print()
print("=" * 62)
print("[J] 语音识别链路（真实 SAPI 合成 + faster-whisper）")
print("=" * 62)
SPOKEN = "The weather is nice today. I would like to go to the park with my friends."
raw = HERE / "_tts_raw.wav"
wav16 = HERE / "_tts_16k.wav"
for p in (raw, wav16):
    if p.exists():
        p.unlink()

# 用 Windows SAPI 合成（比 pyttsx3 的 save_to_file 稳）
ps = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    f"$s.SetOutputToWaveFile('{raw}'); "
    f'$s.Speak("{SPOKEN}"); '
    "$s.Dispose()"
)
subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, timeout=120)
check(raw.exists() and raw.stat().st_size > 20000, f"合成 WAV {raw.stat().st_size if raw.exists() else 0} B")

if raw.exists():
    with wave.open(str(raw), "rb") as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        frames = w.readframes(n)
    check(sw == 2, f"源音频 {sr}Hz {ch}ch {sw*8}bit")
    pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if ch == 2:
        pcm = pcm.reshape(-1, 2).mean(axis=1)
    # 线性插值重采样到 16000
    tgt = 16000
    if sr != tgt:
        idx = np.linspace(0, len(pcm) - 1, int(len(pcm) * tgt / sr))
        pcm = np.interp(idx, np.arange(len(pcm)), pcm).astype(np.float32)
    out = (np.clip(pcm, -1, 1) * 32767).astype("<i2")
    with wave.open(str(wav16), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(tgt)
        w.writeframes(out.tobytes())
    check(wav16.exists(), f"重采样 16k 单声道 {wav16.stat().st_size} B")

    t = time.time()
    with open(wav16, "rb") as f:
        rr = requests.post(BASE + "/api/transcribe",
                           files={"file": ("speech.wav", f, "audio/wav")}, timeout=600)
    el = time.time() - t
    check(rr.status_code == 200, f"转写 {rr.status_code} ({el:.1f}s)", rr.text[:300])
    if rr.status_code == 200:
        got = (rr.json().get("text") or "").strip()
        print(f"  识别结果：{got!r}")
        check(bool(got), "识别出文本")
        low = got.lower()
        hits = [w for w in ("weather", "nice", "today", "park", "friends", "like", "would") if w in low]
        check(len(hits) >= 3, f"关键词命中 {len(hits)}/7：{hits}")
        # 词级准确率
        ref = SPOKEN.lower().replace(".", "").split()
        hyp = low.replace(".", "").replace(",", "").split()
        import difflib
        sm_ = difflib.SequenceMatcher(None, ref, hyp)
        acc = sum(b.size for b in sm_.get_matching_blocks()) / max(1, len(ref))
        check(acc >= 0.7, f"词级准确率 {acc:.0%}")

# 异常输入
rr = requests.post(BASE + "/api/transcribe",
                   files={"file": ("x.txt", b"this is not audio", "text/plain")}, timeout=60)
check(rr.status_code == 400, f"非音频文件 -> {rr.status_code}（未 500）")
rr = requests.post(BASE + "/api/transcribe",
                   files={"file": ("e.wav", b"", "audio/wav")}, timeout=60)
check(rr.status_code in (400, 422), f"空文件 -> {rr.status_code}（未 500）")

for p in (raw, wav16):
    if p.exists():
        p.unlink()

print()
print("=" * 62)
print(f"[K] 结果：{'全部通过' if not fails else str(len(fails)) + ' 项失败'}")
print("=" * 62)
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
