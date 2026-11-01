/* =====================================================================
 * app.js —— spoken 2.0.0 公共层 + 场景练习
 *
 * 负责四件事：
 *   1. 通用工具：调 API、转义、朗读、轻提示、视图切换、深浅色
 *   2. 录音模块：浏览器录音 → 重采样 16kHz → 编码 WAV → 上传识别
 *      （考试与场景练习共用，考试通过 window.App.createRecorder 取）
 *   3. 场景练习的对话流程（原来的功能，界面沿用）
 *   4. 启动时加载服务状态与场景列表
 *
 * 语法对照 Python：
 *   const / let    ≈ 变量（const 不可改，let 可改）
 *   function f(){} ≈ def f():
 *   async / await  ≈ 与 Python 完全一致
 *   ${x}           ≈ f"{x}"（模板字符串）
 * ===================================================================== */

const App = (() => {
  // -------------------------------------------------------------------
  // 一、基础工具
  // -------------------------------------------------------------------
  const $ = (id) => document.getElementById(id);

  /** 防 XSS：任何插入 innerHTML 的外部文本都要先过这一层 */
  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  /** 调后端并解析 JSON */
  async function api(path, body) {
    const options = { headers: {} };
    if (body !== undefined) {
      options.method = "POST";
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const res = await fetch(path, options);
    let data = {};
    try {
      data = await res.json();
    } catch (e) {
      throw new Error(`服务返回了非 JSON 内容（HTTP ${res.status}）`);
    }
    if (!res.ok) {
      throw new Error(data.detail || data.error || `请求失败（HTTP ${res.status}）`);
    }
    return data;
  }

  /** 朗读英文（浏览器自带语音，无需依赖） */
  function speak(text, rate = 0.95) {
    if (!window.speechSynthesis || !text) return;
    speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = "en-US";
    utter.rate = rate;
    speechSynthesis.speak(utter);
  }

  let toastTimer = null;
  function toast(message) {
    const el = $("toast");
    el.textContent = message;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
  }

  /** 秒 → "1:05" */
  function fmtSec(total) {
    const s = Math.max(0, Math.round(total));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  // -------------------------------------------------------------------
  // 二、深浅色
  // -------------------------------------------------------------------
  const THEME_KEY = "spoken-theme";

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_KEY, theme);
    const btn = $("themeBtn");
    if (btn) btn.title = theme === "dark" ? "切换为浅色" : "切换为深色";
  }

  function initTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    const prefersDark = window.matchMedia
      && window.matchMedia("(prefers-color-scheme: dark)").matches;
    applyTheme(saved || (prefersDark ? "dark" : "light"));
  }

  function toggleTheme() {
    const now = document.documentElement.dataset.theme;
    applyTheme(now === "dark" ? "light" : "dark");
  }

  // -------------------------------------------------------------------
  // 三、视图切换（单页多视图，用 hash 记录位置）
  // -------------------------------------------------------------------
  const VIEWS = ["home", "exam", "practice"];

  function applyView(name) {
    const target = VIEWS.includes(name) ? name : "home";
    VIEWS.forEach((v) => {
      const el = $("view-" + v);
      if (el) el.hidden = v !== target;
    });
    document.querySelectorAll(".tab").forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.view === target);
    });
    $("main").scrollTop = 0;
    document.dispatchEvent(new CustomEvent("viewchange", { detail: target }));
  }

  function navigate(name) {
    if ((location.hash || "").slice(1) !== name) {
      location.hash = name === "home" ? "" : name;
    } else {
      applyView(name);
    }
  }

  // -------------------------------------------------------------------
  // 四、录音模块：录音 → 重采样 16kHz → WAV → 上传识别
  // -------------------------------------------------------------------
  /** float32 采样 → 16-bit PCM WAV（后端用标准库 wave 直接读） */
  function encodeWav(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const writeStr = (offset, str) => {
      for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
    };
    writeStr(0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    writeStr(8, "WAVE");
    writeStr(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);            // PCM
    view.setUint16(22, 1, true);            // 单声道
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeStr(36, "data");
    view.setUint32(40, samples.length * 2, true);
    let offset = 44;
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }
    return new Blob([view], { type: "audio/wav" });
  }

  /** 任意音频 Blob → 16kHz 单声道 WAV Blob */
  async function toWav16k(blob) {
    const arrayBuffer = await blob.arrayBuffer();
    const ctx = new AudioContext();
    const decoded = await ctx.decodeAudioData(arrayBuffer);
    const offline = new OfflineAudioContext(
      1, Math.ceil(decoded.duration * 16000) || 1, 16000);
    const src = offline.createBufferSource();
    src.buffer = decoded;
    src.connect(offline.destination);
    src.start();
    const rendered = await offline.startRendering();
    ctx.close();
    return encodeWav(rendered.getChannelData(0), 16000);
  }

  /** 上传音频，返回识别文本 */
  async function transcribe(blob) {
    const wav = await toWav16k(blob);
    const form = new FormData();
    form.append("file", wav, "speech.wav");
    const res = await fetch("/api/transcribe", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || data.error || "识别失败");
    return (data.text || "").trim();
  }

  /**
   * 创建一个录音器。
   * @param {object} opts
   *   button     录音按钮（会切换 .recording 类）
   *   onState    文字状态回调 (text)
   *   onPhase    阶段回调 (phase) —— "recording" | "transcribing" | "idle"
   *   onText     识别成功回调 (text, meta)
   *   onError    失败回调 (message)
   *   maxSeconds 最长录音秒数（到时自动停止）
   */
  function createRecorder(opts) {
    const {
      button, onState = () => {}, onText = () => {}, onError = () => {},
      onPhase = () => {}, maxSeconds = 0,
    } = opts;
    let mediaRecorder = null;
    let chunks = [];
    let stream = null;
    let startedAt = 0;
    let autoStop = null;

    const isRecording = () => mediaRecorder && mediaRecorder.state === "recording";

    async function start() {
      if (isRecording()) return;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        chunks = [];
        mediaRecorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };

        mediaRecorder.onstop = async () => {
          if (autoStop) { clearTimeout(autoStop); autoStop = null; }
          if (button) button.classList.remove("recording");
          if (stream) stream.getTracks().forEach((t) => t.stop());
          const duration = (Date.now() - startedAt) / 1000;
          onPhase("transcribing");
          onState("识别中…");
          try {
            const blob = new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" });
            if (blob.size < 1200) {
              onState("");
              onError("录音太短，再说一次");
              return;
            }
            const text = await transcribe(blob);
            onState("");
            onText(text, { duration });
          } catch (e) {
            onState("");
            onError(e.message);
          } finally {
            onPhase("idle");
          }
        };

        mediaRecorder.start();
        startedAt = Date.now();
        if (button) button.classList.add("recording");
        onPhase("recording");
        onState("录音中…再点一次结束");
        if (maxSeconds > 0) {
          autoStop = setTimeout(() => stop(), maxSeconds * 1000);
        }
      } catch (e) {
        onState("");
        onError(`无法使用麦克风：${e.message}`);
      }
    }

    function stop() {
      if (isRecording()) mediaRecorder.stop();
    }

    function toggle() {
      if (isRecording()) stop(); else start();
    }

    return { toggle, start, stop, isRecording };
  }

  // -------------------------------------------------------------------
  // 五、场景练习（对话 + 纠错 + 总结）
  // -------------------------------------------------------------------
  let sessionId = null;
  let selectedScenario = null;
  let selectedDifficulty = "intermediate";

  function addBubble(text, who) {
    const el = $("messages");
    const div = document.createElement("div");
    div.className = `bubble ${who}`;
    div.textContent = text;
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
    return div;
  }

  function addCorrections(corrections) {
    if (!corrections || corrections.length === 0) return;
    const el = $("messages");
    const div = document.createElement("div");
    div.className = "corrections";
    div.innerHTML = corrections.map((c) => `
      <div class="item">
        <span class="orig">${escapeHtml(c.original)}</span>
        →
        <span class="fixed">${escapeHtml(c.corrected)}</span>
        ${c.reason ? `<div class="why">${escapeHtml(c.reason)}</div>` : ""}
      </div>`).join("");
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
  }

  function addNewWords(words) {
    if (!words || words.length === 0) return;
    const el = $("messages");
    const div = document.createElement("div");
    div.className = "words";
    div.innerHTML = words.map((w) =>
      `<div><span class="word">${escapeHtml(w.word)}</span>` +
      `<span class="zh">${escapeHtml(w.meaning_zh || "")}</span></div>`).join("");
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
  }

  async function loadScenarios() {
    try {
      const data = await api("/api/scenarios");
      const list = $("scenarioList");
      list.innerHTML = "";
      data.scenarios.forEach((s, i) => {
        const btn = document.createElement("button");
        btn.className = "scenario-btn" + (i === 0 ? " active" : "");
        btn.innerHTML = `${escapeHtml(s.name)}<span class="en">${escapeHtml(s.name_en || "")}</span>`;
        btn.onclick = () => {
          document.querySelectorAll(".scenario-btn").forEach((b) => b.classList.remove("active"));
          btn.classList.add("active");
          selectedScenario = s.key;
        };
        list.appendChild(btn);
        if (i === 0) selectedScenario = s.key;
      });

      const row = $("difficultyRow");
      row.innerHTML = "";
      data.difficulties.forEach((d) => {
        const btn = document.createElement("button");
        btn.className = "diff-btn" + (d.key === selectedDifficulty ? " active" : "");
        btn.textContent = d.name;
        btn.onclick = () => {
          document.querySelectorAll(".diff-btn").forEach((b) => b.classList.remove("active"));
          btn.classList.add("active");
          selectedDifficulty = d.key;
        };
        row.appendChild(btn);
      });
    } catch (e) {
      $("scenarioList").innerHTML = `<p class="muted">场景加载失败：${escapeHtml(e.message)}</p>`;
    }
  }

  async function startSession() {
    if (!selectedScenario) {
      toast("先选一个场景");
      return;
    }
    const btn = $("startBtn");
    btn.disabled = true;
    try {
      const data = await api("/api/session", {
        scenario: selectedScenario,
        difficulty: selectedDifficulty,
      });
      sessionId = data.session_id;
      $("messages").innerHTML = "";
      addBubble(data.opening, "ai");
      speak(data.opening);
      $("endBtn").disabled = false;
      $("inputHint").textContent = `当前模型：${data.llm}`;
      $("textInput").focus();
    } catch (e) {
      toast(`开始对话失败：${e.message}`);
      btn.disabled = false;
    }
  }

  async function sendMessage() {
    const input = $("textInput");
    const text = input.value.trim();
    if (!text || !sessionId) return;
    input.value = "";
    addBubble(text, "user");
    try {
      const data = await api("/api/chat", { session_id: sessionId, text });
      if (data.hint) addBubble(data.hint, "hint");
      if (data.ai_line) {
        addBubble(data.ai_line, "ai");
        speak(data.ai_line);
      }
      addCorrections(data.corrections);
      addNewWords(data.new_words);
    } catch (e) {
      toast(`发送失败：${e.message}`);
    }
  }

  async function endSession() {
    if (!sessionId) return;
    try {
      const data = await api("/api/summary", { session_id: sessionId });
      showSummary(data);
    } catch (e) {
      toast(`获取总结失败：${e.message}`);
    }
    sessionId = null;
    $("startBtn").disabled = false;
    $("endBtn").disabled = true;
  }

  function showSummary(data) {
    const errors = data.total_errors ?? 0;
    let html = `<div class="stat"><span>本轮错误总数</span><span>${errors}</span></div>`;

    const cats = data.by_category || {};
    if (Object.keys(cats).length > 0) {
      html += "<h3>错误分类</h3>";
      for (const [k, v] of Object.entries(cats)) {
        html += `<div class="stat"><span>${escapeHtml(k)}</span><span>${v}</span></div>`;
      }
    }

    const unused = data.unused_vocabulary || [];
    if (unused.length > 0) {
      html += "<h3>没用到的词汇（下次试试）</h3><ul>";
      unused.forEach((w) => {
        html += `<li>${escapeHtml(w.word)} — ${escapeHtml(w.meaning_zh || "")}</li>`;
      });
      html += "</ul>";
    }

    if (data.overall) html += `<h3>总体评价</h3><p>${escapeHtml(data.overall)}</p>`;
    const tips = data.suggestions || data.improvements || [];
    if (tips.length > 0) {
      html += "<h3>改进建议</h3><ul>";
      tips.forEach((t) => { html += `<li>${escapeHtml(t)}</li>`; });
      html += "</ul>";
    }

    $("summaryBody").innerHTML = html;
    $("summaryModal").hidden = false;
  }

  // -------------------------------------------------------------------
  // 六、启动
  // -------------------------------------------------------------------
  let booted = false;

  async function init() {
    if (booted) return;
    booted = true;

    initTheme();

    // 顶栏导航
    document.querySelectorAll("[data-view]").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.preventDefault();
        navigate(el.dataset.view);
      });
    });
    $("themeBtn").onclick = toggleTheme;
    window.addEventListener("hashchange", () => {
      applyView((location.hash || "").slice(1) || "home");
    });
    applyView((location.hash || "").slice(1) || "home");

    // 服务状态
    try {
      const status = await api("/api/status");
      $("statusDot").className = `dot ${status.spoken_ok ? "ok" : "err"}`;
      let label = status.spoken_ok
        ? (status.llm || "就绪").replace(/^MockLLM.*$/, "离线演示模式")
        : "后端组件缺失";
      const asr = status.asr || {};
      if (status.spoken_ok && asr.error) {
        label += " · 语音不可用";
      } else if (status.spoken_ok && asr.loading && !asr.ready) {
        // 首次启动要加载识别模型（打包版可能要几分钟）
        label += " · 语音模型加载中，可先打字";
        $("statusDot").className = "dot warn";
        // 每隔几秒复查一次，加载完自动恢复
        const timer = setInterval(async () => {
          try {
            const s = await api("/api/status");
            if (s.asr && (s.asr.ready || s.asr.error)) {
              clearInterval(timer);
              $("statusDot").className = `dot ${s.spoken_ok ? "ok" : "err"}`;
              $("statusText").textContent = s.asr.error
                ? `${(s.llm || "就绪")} · 语音不可用`
                : (s.llm || "就绪").replace(/^MockLLM.*$/, "离线演示模式");
            }
          } catch (e) { /* 下次再试 */ }
        }, 4000);
      }
      $("statusText").textContent = label;
    } catch (e) {
      $("statusDot").className = "dot err";
      $("statusText").textContent = "无法连接后端";
    }

    await loadScenarios();

    // 场景练习交互
    $("startBtn").onclick = startSession;
    $("endBtn").onclick = endSession;
    $("sendBtn").onclick = sendMessage;
    $("closeSummary").onclick = () => { $("summaryModal").hidden = true; };
    $("textInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") sendMessage();
    });

    // 练习区的录音器（考试区用自己的实例）
    const practiceRecorder = createRecorder({
      button: $("micBtn2"),
      onState: (t) => { $("inputHint").textContent = t; },
      onText: (text) => {
        $("textInput").value = text;
        $("inputHint").textContent = "识别完成，可编辑后发送";
        $("textInput").focus();
      },
      onError: (m) => { $("inputHint").textContent = `识别失败：${m}`; },
    });
    $("micBtn2").onclick = () => practiceRecorder.toggle();
  }

  return {
    $, api, escapeHtml, speak, toast, fmtSec,
    navigate, applyView,
    createRecorder, transcribe,
    init,
  };
})();

window.App = App;
App.init();
