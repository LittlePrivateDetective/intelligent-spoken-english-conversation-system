/* =====================================================================
 * exam.js —— 四六级口语考试前端流程
 *
 * 一场考试的推进顺序：
 *   出题 → 准备倒计时 → 答题（录音 / 打字，互动任务可让 AI 搭档接话）
 *   → 提交评分 → 单段反馈 → 下一段 … → 整场报告
 *
 * 依赖 app.js 提供的 window.App（fetch 封装、录音器、主题、视图切换）。
 * ===================================================================== */

const Exam = (() => {
  const { $, api, escapeHtml, toast, fmtSec, navigate } = App;

  // -------------------------------------------------------------------
  // 状态
  // -------------------------------------------------------------------
  let specs = [];              // 从后端拿到的四级/六级结构
  let papersByLevel = {};      // 题库目录：{cet4: [{id,title,tags}], cet6: [...]}
  let lastLevel = "cet4";      // 上一次选的级别（报告页「再考一次」复用）
  let sessionId = null;
  let spec = null;             // 当前级别结构
  let task = null;             // 当前题目
  let nextTask = null;         // 后端返回的下一题
  let finished = false;        // 是否已是最后一段
  let phase = "idle";          // idle | prep | answer | scoring | feedback
  let answers = {};            // index -> 是否已完成（渲染进度用）
  let timer = null;            // 倒计时句柄
  let remaining = 0;
  let total = 0;
  let recDuration = 0;         // 本次录音时长
  let recorder = null;
  let transcribing = false;
  let transcribeWaiters = [];
  let dialogueLog = [];        // 互动任务的对话记录
  let finishing = false;

  // -------------------------------------------------------------------
  // 一、加载考试结构
  // -------------------------------------------------------------------
  async function loadSpecs() {
    try {
      const data = await api("/api/exam/specs");
      specs = data.exams || [];
      renderCards($("examCards"), specs, false);
      renderCards($("setupCards"), specs, true);
      loadPapers();
    } catch (e) {
      const msg = `<p class="muted">考试结构加载失败：${escapeHtml(e.message)}</p>`;
      $("examCards").innerHTML = msg;
      $("setupCards").innerHTML = msg;
    }
  }

  // 题库：{cet4: [...], cet6: [...]}，用于级别卡片里的选卷列表
  async function loadPapers() {
    try {
      const data = await api("/api/exam/papers");
      const levels = data.levels || {};
      Object.keys(levels).forEach((lv) => {
        papersByLevel[lv] = levels[lv].papers || [];
      });
      renderCards($("setupCards"), specs, true);
    } catch (e) {
      // 题库拉不到不影响随机出卷，静默降级
      papersByLevel = {};
    }
  }

  function renderCards(container, list, detailed) {
    if (!container) return;
    if (!list.length) {
      container.innerHTML = '<p class="muted">暂无可用的考试级别</p>';
      return;
    }
    container.innerHTML = list.map((s) => {
      const bank = papersByLevel[s.key] || [];
      const card = `
      <button class="exam-card" data-start="${escapeHtml(s.key)}">
        <div class="exam-card-top">
          <span class="exam-code">${escapeHtml(s.code)}</span>
          <span class="exam-minutes">约 ${s.minutes} 分钟 · ${s.task_count} 段${s.paper_count ? ` · 题库 ${s.paper_count} 套` : ""}</span>
        </div>
        <h3>${escapeHtml(s.full_name)}</h3>
        <p class="blurb">${escapeHtml(s.blurb)}</p>
        <div class="chips">
          ${s.parts.map((p) => `<span class="chip">${escapeHtml(p.name)}</span>`).join("")}
        </div>
        ${detailed ? `<div class="chips">
          ${s.parts.map((p) => `<span class="chip">${escapeHtml(p.span)}</span>`).join("")}
        </div>` : ""}
        <div class="exam-card-foot">
          <span>${detailed ? "随机抽一套开始" : "进入模拟"}</span>
          <span>→</span>
        </div>
      </button>`;

      if (!detailed) return card;
      const items = bank.length ? `
        <details class="paper-bank">
          <summary>题库 ${bank.length} 套 · 挑一套练</summary>
          <div class="paper-items">
            ${bank.map((p) => `
              <button class="paper-item" data-paper="${escapeHtml(p.id)}" data-level="${escapeHtml(s.key)}">
                <span class="paper-id">${escapeHtml((p.id || "").split("-").pop())}</span>
                <span class="paper-main">
                  <b>${escapeHtml(p.title)}</b>
                  <small>${escapeHtml((p.tags || []).join(" · "))}</small>
                </span>
              </button>`).join("")}
          </div>
          <button class="paper-ai" data-ai="${escapeHtml(s.key)}">
            都练过了？让 AI 现出一套新题
          </button>
        </details>` : "";
      return `<div class="exam-card-wrap">${card}${items}</div>`;
    }).join("");
    // 点击由 init() 里的全局委托统一处理（首页 hero 按钮和卡片共用 data-start）
  }

  // -------------------------------------------------------------------
  // 二、开始考试
  // -------------------------------------------------------------------
  async function start(level, opts = {}) {
    if (!specs.length) {
      toast("考试结构还没加载好");
      return;
    }
    const source = opts.source || "bank";
    const paperId = opts.paperId || null;
    lastLevel = level;

    navigate("exam");
    showSetup();
    const waiting = source === "ai"
      ? "AI 正在出题（约 5-15 秒）…"
      : "正在抽卷…";
    $("setupCards").innerHTML = `
      <div class="card loading" style="grid-column:1/-1">
        <span class="spinner"></span>
        ${waiting}
      </div>`;

    try {
      const data = await api("/api/exam/start", {
        level, paper_id: paperId, source,
      });
      sessionId = data.session_id;
      spec = data.spec;
      answers = {};
      dialogueLog = [];
      recDuration = 0;
      renderCards($("setupCards"), specs, true);

      if (data.paper_source === "bank") {
        const name = data.paper && data.paper.title ? `《${data.paper.title}》` : "题库套卷";
        toast(`本次用题库套卷 ${name}`);
      } else if (data.paper_source === "llm") {
        toast("本次试卷由 AI 现出");
      }
      showRun();
      $("examCode").textContent = spec.code;
      $("paperName").textContent = (data.paper && data.paper.title) || "";
      enterTask(data.task);
    } catch (e) {
      renderCards($("setupCards"), specs, true);
      toast(`出题失败：${e.message}`);
      showSetup();
    }
  }

  function showSetup() {
    $("examSetup").hidden = false;
    $("examRun").hidden = true;
    $("examReport").hidden = true;
  }

  function showRun() {
    $("examSetup").hidden = true;
    $("examRun").hidden = false;
    $("examReport").hidden = true;
  }

  // -------------------------------------------------------------------
  // 三、进入某一段
  // -------------------------------------------------------------------
  function enterTask(t) {
    task = t;
    nextTask = null;
    finished = false;
    recDuration = 0;
    dialogueLog = [];

    $("partBadge").textContent = `Part ${t.part}`;
    $("taskLabel").textContent = t.label;
    $("stageCount").textContent = `${t.index + 1} / ${t.total}`;
    $("tipLine").textContent = `提示：${t.tip || ""}`;
    $("feedback").hidden = true;
    $("feedback").innerHTML = "";
    $("answerText").value = "";
    $("answerText").disabled = false;
    $("stageCount").textContent = `${t.index + 1} / ${t.total}`;

    renderSteps();
    renderPrompt(t);
    prepareDialogueUI(t);
    bindRecorder(t);

    if (t.prep > 0) {
      startPrep(t);
    } else {
      startAnswer(t);
    }
  }

  function renderSteps() {
    $("stepList").innerHTML = spec.steps.map((s) => {
      const done = answers[s.index] !== undefined && s.index !== task.index;
      const cls = s.index === task.index ? "current" : (done ? "done" : "");
      return `
        <li class="step ${cls}">
          <span class="step-dot">${done ? "✓" : s.part}</span>
          <span class="step-body">
            ${escapeHtml(s.label)}
            <small>${s.prep ? s.prep + "s 准备 + " : ""}${s.answer}s</small>
          </span>
        </li>`;
    }).join("");
  }

  function renderPrompt(t) {
    const d = t.detail || {};
    let html = "";

    if (t.kind === "reading") {
      html += `<p class="prompt-title">Read aloud · ${escapeHtml(d.title || "")}</p>`;
      html += `<p class="passage">${escapeHtml(d.passage || "")}</p>`;
    } else if (t.kind === "qa" || t.kind === "exam_qa" || t.kind === "followup") {
      html += `<p class="prompt-en">${escapeHtml(t.prompt)}</p>`;
      (d.questions || []).forEach((q, i) => {
        html += `<div class="q-item"><span class="q-no">${i + 1}</span><span>${escapeHtml(q)}</span></div>`;
      });
    } else if (t.kind === "presentation") {
      html += `<p class="prompt-en">${escapeHtml(t.prompt)}</p>`;
      html += `<p style="margin-top:12px;font-weight:650;font-size:16px">${escapeHtml(d.topic || "")}</p>`;
      html += `<ul>${(d.points || []).map((p) => `<li>${escapeHtml(p)}</li>`).join("")}</ul>`;
    } else if (t.kind === "interaction" || t.kind === "discussion") {
      html += `<p class="prompt-en">${escapeHtml(d.situation || d.task || "")}</p>`;
      if (d.situation && d.task) {
        html += `<p style="margin-top:8px">${escapeHtml(d.task)}</p>`;
      }
      html += `<p style="margin-top:10px;color:var(--text-3);font-size:12.5px">
        你的搭档：${escapeHtml(d.partner_role || "your partner")}（由 AI 扮演，会说英语）
      </p>`;
    } else {
      html += `<p class="prompt-en">${escapeHtml(t.prompt)}</p>`;
      if (d.hints) {
        html += `<p style="margin-top:8px;color:var(--text-3);font-size:12.5px">
          可以讲：${d.hints.map(escapeHtml).join(" · ")}</p>`;
      }
    }
    $("promptCard").innerHTML = html;
  }

  function prepareDialogueUI(t) {
    const isInteractive = t.kind === "interaction" || t.kind === "discussion";
    $("dialogue").hidden = !isInteractive;
    $("dialogue").innerHTML = "";
    $("partnerBtn").hidden = !isInteractive;
    if (isInteractive) {
      appendDialogue("partner", `Hi! Let's work on this together. What do you think we should start with?`);
    }
  }

  function appendDialogue(who, text) {
    const box = $("dialogue");
    const div = document.createElement("div");
    div.className = `d-line ${who}`;
    div.innerHTML = `<span class="d-who">${who === "me" ? "你" : "搭档"}</span>` +
                    `<span class="d-text">${escapeHtml(text)}</span>`;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  // -------------------------------------------------------------------
  // 四、录音
  // -------------------------------------------------------------------
  function bindRecorder(t) {
    recorder = App.createRecorder({
      button: $("micBtn"),
      maxSeconds: t.answer + 8,
      onPhase: (p) => {
        if (p === "transcribing") {
          transcribing = true;
          $("stateLine").textContent = "识别中…";
          $("stateLine").classList.remove("strong");
        } else {
          transcribing = false;
          transcribeWaiters.forEach((fn) => fn());
          transcribeWaiters = [];
        }
        $("micText").textContent = p === "recording" ? "停止" : "录音";
      },
      onState: (text) => {
        if (text) {
          $("stateLine").textContent = text;
        } else if (phase === "answer") {
          $("stateLine").textContent = "作答中 · 说完了点「提交这一段」";
        }
      },
      onText: (text, meta) => {
        if (!text) {
          toast("没识别到内容，再说一次或直接打字");
          return;
        }
        const box = $("answerText");
        box.value = box.value ? `${box.value} ${text}` : text;
        recDuration = (recDuration || 0) + (meta.duration || 0);
      },
      onError: (msg) => { toast(msg); },
    });
    $("micBtn").onclick = () => {
      if (phase !== "answer") return;
      recorder.toggle();
    };
  }

  function waitTranscribe(timeoutMs = 15000) {
    if (!transcribing) return Promise.resolve();
    return new Promise((resolve) => {
      const t = setTimeout(resolve, timeoutMs);
      transcribeWaiters.push(() => { clearTimeout(t); resolve(); });
    });
  }

  // -------------------------------------------------------------------
  // 五、倒计时与阶段切换
  // -------------------------------------------------------------------
  const RING_CIRCUMFERENCE = 339.292;

  function setPhase(p) {
    phase = p;
    const micBtn = $("micBtn");
    const submitBtn = $("submitBtn");
    const skipBtn = $("skipBtn");
    const partnerBtn = $("partnerBtn");

    if (p === "prep") {
      micBtn.disabled = true;
      submitBtn.disabled = false;
      submitBtn.textContent = "准备好了，开始作答";
      skipBtn.hidden = false;
      skipBtn.textContent = "直接开始";
      partnerBtn.disabled = true;
      $("answerText").disabled = true;
    } else if (p === "answer") {
      micBtn.disabled = false;
      submitBtn.disabled = false;
      const interactive = task.kind === "interaction" || task.kind === "discussion";
      submitBtn.textContent = interactive ? "结束互动并评分" : "提交这一段";
      skipBtn.hidden = false;
      skipBtn.textContent = "跳过这段";
      partnerBtn.disabled = false;
      $("answerText").disabled = false;
    } else if (p === "scoring") {
      micBtn.disabled = true;
      submitBtn.disabled = true;
      skipBtn.hidden = true;
      partnerBtn.disabled = true;
      $("answerText").disabled = true;
    } else if (p === "feedback") {
      micBtn.disabled = true;
      submitBtn.disabled = true;
      skipBtn.hidden = true;
      partnerBtn.disabled = true;
      $("answerText").disabled = true;
    }
  }

  function startPrep(t) {
    setPhase("prep");
    $("stateLine").textContent = "准备时间 · 可以先想好结构，倒计时结束自动开始作答";
    $("stateLine").classList.remove("strong");
    startCountdown(t.prep, "准备", () => startAnswer(t));
  }

  function startAnswer(t) {
    setPhase("answer");
    $("stateLine").textContent = "作答中 · 点「录音」开始说，说错了可以继续说，识别结果会累积";
    $("stateLine").classList.add("strong");
    startCountdown(t.answer, "作答", () => {
      // 时间到：仿真考试，自动收卷
      $("stateLine").textContent = "时间到，正在提交…";
      finishAnswer(false, true);
    });
  }

  function startCountdown(seconds, label, onDone) {
    clearInterval(timer);
    total = Math.max(1, seconds);
    remaining = total;
    $("timerLabel").textContent = label;
    updateRing();
    const t0 = Date.now();
    timer = setInterval(() => {
      remaining = Math.max(0, total - (Date.now() - t0) / 1000);
      updateRing();
      if (remaining <= 0) {
        clearInterval(timer);
        timer = null;
        onDone();
      }
    }, 120);
  }

  function updateRing() {
    const ratio = total > 0 ? remaining / total : 0;
    const ring = $("ringFg");
    ring.style.strokeDashoffset = String(RING_CIRCUMFERENCE * (1 - ratio));
    ring.className = "ring-fg" + (ratio < 0.14 ? " danger" : ratio < 0.34 ? " warn" : "");
    $("timerNum").textContent = String(Math.ceil(remaining));
  }

  function stopTimer() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  // -------------------------------------------------------------------
  // 六、提交与评分
  // -------------------------------------------------------------------
  /**
   * 组装这一段的作答文本。
   * 互动 / 讨论任务要把搭档台词一起交给评分，模型才能判断「有没有接住对方」。
   */
  function composeAnswer() {
    const interactive = task.kind === "interaction" || task.kind === "discussion";
    const pending = $("answerText").value.trim();
    if (!interactive) return pending;

    const lines = dialogueLog.map(
      (d) => `${d.who === "me" ? "Candidate" : "Partner"}: ${d.text}`);
    if (pending) lines.push(`Candidate: ${pending}`);
    return lines.join("\n");
  }

  async function finishAnswer(skip, timeUp) {
    if (finishing) return;
    finishing = true;

    const elapsed = total - remaining;
    stopTimer();
    setPhase("scoring");
    $("stateLine").textContent = skip ? "已跳过，正在生成反馈…" : "正在评分（约 3-15 秒）…";
    $("stateLine").classList.remove("strong");

    if (recorder && recorder.isRecording()) recorder.stop();
    await waitTranscribe();

    const text = skip ? "" : composeAnswer();
    const duration = skip
      ? task.answer
      : Math.min(task.answer + 8, Math.round(recDuration || elapsed || task.answer));

    try {
      const data = await api("/api/exam/submit", {
        session_id: sessionId,
        index: task.index,
        text,
        duration,
      });
      answers[task.index] = true;
      nextTask = data.next;
      finished = data.finished;
      renderSteps();
      renderFeedback(data.result, timeUp);
      setPhase("feedback");
    } catch (e) {
      toast(`提交失败：${e.message}`);
      // 恢复可作答状态，避免卡死在评分中
      startAnswer(task);
    } finally {
      finishing = false;
    }
  }

  // -------------------------------------------------------------------
  // 七、单段反馈
  // -------------------------------------------------------------------
  const DIM_LABELS = {
    accuracy: "准确性", range: "语言范围", discourse: "话语长短",
    coherence: "连贯性", flexibility: "灵活性", appropriateness: "适切性",
  };

  function dimBars(scores) {
    return Object.entries(DIM_LABELS).map(([key, name]) => {
      const v = Number(scores[key] || 0);
      const pct = Math.max(0, Math.min(100, ((v - 1) / 4) * 100));
      const cls = v >= 4 ? "high" : v <= 2 ? "low" : "";
      return `
        <div class="dim-row">
          <div class="dim-top"><span>${name}</span><span>${v.toFixed(0)} / 5</span></div>
          <div class="dim-track"><div class="dim-fill ${cls}" style="width:${pct}%"></div></div>
        </div>`;
    }).join("");
  }

  function renderFeedback(result, timeUp) {
    const wer = result.wer;
    let html = `
      <div class="fb-head">
        <div class="grade-badge grade-${escapeHtml(result.level)}">${escapeHtml(result.level)}</div>
        <div class="fb-title">
          <strong>${escapeHtml(result.label || "")}</strong>
          <span>${Number(result.score_pct || 0).toFixed(0)} 分 · ${result.words} 词 · ${result.duration} 秒${timeUp ? " · 时间到自动提交" : ""}</span>
        </div>
      </div>`;

    if (result.comment) {
      html += `<p class="fb-comment">${escapeHtml(result.comment)}</p>`;
    }

    if (wer) {
      const pct = (wer.wer * 100).toFixed(1);
      const missed = (wer.missed || []).join(", ");
      html += `
        <div class="wer-box">
          <div class="wer-top">
            <span>朗读客观比对</span>
            <strong>词错误率 ${pct}%</strong>
          </div>
          <p>原文 ${wer.ref_words} 词，读对 ${wer.matched} 词 ·
             替换 ${wer.substitutions} · 漏读 ${wer.deletions} · 多读 ${wer.insertions}</p>
          ${missed ? `<p class="wer-missed">需重点练：${escapeHtml(missed)}</p>` : ""}
        </div>`;
    }

    html += `<div class="dim-grid">${dimBars(result.scores || {})}</div>`;

    if (result.strengths && result.strengths.length) {
      html += `<div class="fb-block good"><h4>做得好的</h4><ul>
        ${result.strengths.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ul></div>`;
    }
    if (result.improvements && result.improvements.length) {
      html += `<div class="fb-block"><h4>下一步改这里</h4><ul>
        ${result.improvements.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ul></div>`;
    }
    if (result.better_version) {
      html += `<div class="reference">
        <span class="label">更地道的说法</span>${escapeHtml(result.better_version)}</div>`;
    }
    if (result.source === "rule") {
      html += `<p class="muted" style="margin-top:10px;font-size:12px">
        本段使用离线规则评分（未连接语言模型），只评估可计算的指标。</p>`;
    }

    html += `<div class="fb-next">
      <button class="btn btn-primary" id="nextBtn">${finished ? "查看整场报告" : "下一段"}</button>
    </div>`;

    const box = $("feedback");
    box.innerHTML = html;
    box.hidden = false;
    $("nextBtn").onclick = goNext;
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function goNext() {
    if (finished) {
      loadReport();
      return;
    }
    if (nextTask) enterTask(nextTask);
  }

  // -------------------------------------------------------------------
  // 八、整场报告
  // -------------------------------------------------------------------
  function radarSvg(dims) {
    const cx = 150;
    const cy = 140;
    const R = 92;
    const n = dims.length;
    const angle = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
    const point = (i, r) => [cx + r * Math.cos(angle(i)), cy + r * Math.sin(angle(i))];

    let svg = `<svg class="radar" viewBox="0 0 300 296" width="300" height="296" role="img" aria-label="六维得分雷达图">`;
    for (let k = 1; k <= 4; k++) {
      const pts = dims.map((_, i) => point(i, (R * k) / 4).join(",")).join(" ");
      svg += `<polygon class="grid-line" points="${pts}"></polygon>`;
    }
    dims.forEach((_, i) => {
      const [x, y] = point(i, R);
      svg += `<line class="axis" x1="${cx}" y1="${cy}" x2="${x}" y2="${y}"></line>`;
    });

    const shapePts = dims.map((d, i) => {
      const ratio = Math.max(0.06, (Number(d.score) - 1) / 4);
      return point(i, R * ratio).join(",");
    }).join(" ");
    svg += `<polygon class="shape" points="${shapePts}"></polygon>`;

    dims.forEach((d, i) => {
      const ratio = Math.max(0.06, (Number(d.score) - 1) / 4);
      const [x, y] = point(i, R * ratio);
      svg += `<circle class="pt" cx="${x}" cy="${y}" r="3.2"></circle>`;
    });

    dims.forEach((d, i) => {
      const [x, y] = point(i, R + 26);
      const anchor = Math.abs(x - cx) < 14 ? "middle" : (x > cx ? "start" : "end");
      svg += `<text class="dim-label" x="${x}" y="${y}" text-anchor="${anchor}">${escapeHtml(d.name)}</text>`;
      svg += `<text class="dim-score" x="${x}" y="${y + 13}" text-anchor="${anchor}">${Number(d.score).toFixed(1)}</text>`;
    });

    svg += `</svg>`;
    return svg;
  }

  function partCard(p) {
    const wer = p.wer
      ? `<p class="muted" style="font-size:12.5px;margin-top:6px">
           词错误率 ${(p.wer.wer * 100).toFixed(1)}%（读对 ${p.wer.matched}/${p.wer.ref_words} 词）</p>`
      : "";
    return `
      <details class="part-report">
        <summary>
          <span class="p-grade grade-${escapeHtml(p.level)}">${escapeHtml(p.level)}</span>
          <span>${escapeHtml(p.label)}</span>
          <span class="p-score">${Number(p.score).toFixed(0)} 分 · ${p.words} 词</span>
          <span class="p-arrow">›</span>
        </summary>
        <div class="p-body">
          ${p.comment ? `<p class="fb-comment">${escapeHtml(p.comment)}</p>` : ""}
          ${wer}
          ${p.strengths && p.strengths.length ? `<div class="fb-block good"><h4>做得好的</h4><ul>
            ${p.strengths.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ul></div>` : ""}
          ${p.improvements && p.improvements.length ? `<div class="fb-block"><h4>改进点</h4><ul>
            ${p.improvements.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ul></div>` : ""}
          ${p.better_version ? `<div class="reference"><span class="label">更地道的说法</span>${escapeHtml(p.better_version)}</div>` : ""}
          ${p.answer ? `<div class="fb-block"><h4>你的回答</h4>
            <p class="muted" style="font-size:13px;line-height:1.7">${escapeHtml(p.answer)}</p></div>` : ""}
        </div>
      </details>`;
  }

  async function loadReport() {
    $("examRun").hidden = true;
    $("examReport").hidden = false;
    $("examReport").innerHTML = `<div class="card loading"><span class="spinner"></span>正在汇总报告…</div>`;
    try {
      const data = await api("/api/exam/report", { session_id: sessionId });
      renderReport(data);
    } catch (e) {
      $("examReport").innerHTML = `
        <div class="card"><p class="muted">报告生成失败：${escapeHtml(e.message)}</p></div>`;
    }
  }

  function renderReport(data) {
    const grade = escapeHtml(data.grade);
    const paperName = data.paper && data.paper.title
      ? `${data.paper_source === "llm" ? "AI 现出卷" : "题库套卷"}《${escapeHtml(data.paper.title)}》`
      : "";
    let html = `
      <div class="report-head">
        <div class="report-badge grade-${grade}">
          <b>${grade}</b><small>模拟等级</small>
        </div>
        <div class="report-title">
          <h1>${escapeHtml(data.level_name)}</h1>
          <p>${escapeHtml(data.code)} · 按官方六维标准模拟评分，练习参考用${paperName ? ` · ${paperName}` : ""}</p>
        </div>
        <div class="report-score">
          <b>${Number(data.score).toFixed(0)}</b><span> / 100</span>
        </div>
      </div>`;

    if (data.offline) {
      html += `<div class="notice" style="margin-top:14px">
        本次未连接语言模型：评分由规则计算（语速、词量、词汇丰富度、衔接词），
        不含发音与内容质量判断。配置 API Key 后可获得完整考官点评。
      </div>`;
    }

    html += `<div class="report-grid">
      <div class="card">
        <h3>六维能力</h3>
        ${radarSvg(data.dimensions || [])}
        <div style="margin-top:10px">
          <div class="kv"><span>最强项</span><span>${escapeHtml(data.strongest.name)} ${Number(data.strongest.score).toFixed(1)}</span></div>
          <div class="kv"><span>最弱项</span><span>${escapeHtml(data.weakest.name)} ${Number(data.weakest.score).toFixed(1)}</span></div>
        </div>
      </div>
      <div>
        ${(data.parts || []).map(partCard).join("")}
      </div>
    </div>`;

    if (data.advice && data.advice.length) {
      html += `<div class="card" style="margin-top:18px">
        <h3>下一步怎么练</h3>
        <ol class="advice-list">${data.advice.map((a) => `<li>${escapeHtml(a)}</li>`).join("")}</ol>
      </div>`;
    }

    if (data.issues && data.issues.length) {
      html += `<div class="card" style="margin-top:18px">
        <h3>各段提到的问题</h3>
        <ul class="advice-list">${data.issues.map((a) => `<li>${escapeHtml(a)}</li>`).join("")}</ul>
      </div>`;
    }

    html += `<div class="report-actions">
      <button class="btn btn-primary" id="againBtn">再考一次（${escapeHtml(data.code)}）</button>
      <button class="btn btn-ghost" id="backHomeBtn">回到首页</button>
    </div>`;

    $("examReport").innerHTML = html;
    $("againBtn").onclick = () => start(data.level_key);
    $("backHomeBtn").onclick = () => { navigate("home"); showSetup(); };
    $("main").scrollTop = 0;
  }

  // -------------------------------------------------------------------
  // 九、互动任务：让 AI 搭档接话
  // -------------------------------------------------------------------
  async function talkToPartner() {
    if (phase !== "answer") return;
    const box = $("answerText");
    const text = box.value.trim();
    if (!text) {
      toast("先说一句（点录音或打字），再发给搭档");
      return;
    }
    box.value = "";
    dialogueLog.push({ who: "me", text });
    appendDialogue("me", text);

    const btn = $("partnerBtn");
    btn.disabled = true;
    appendDialogue("partner", "…");
    try {
      const data = await api("/api/exam/partner", {
        session_id: sessionId,
        index: task.index,
        text,
      });
      const box2 = $("dialogue");
      const last = box2.lastElementChild;
      if (last) last.remove();
      if (data.reply) {
        dialogueLog.push({ who: "partner", text: data.reply });
        appendDialogue("partner", data.reply);
        App.speak(data.reply, 0.92);
      }
    } catch (e) {
      const box2 = $("dialogue");
      if (box2.lastElementChild) box2.lastElementChild.remove();
      toast(`搭档没接上：${e.message}`);
    } finally {
      btn.disabled = false;
    }
  }

  // -------------------------------------------------------------------
  // 十、中途结束
  // -------------------------------------------------------------------
  async function quit() {
    const done = Object.keys(answers).length;
    if (!done) {
      if (!confirm("还没完成任何一段，确定退出？")) return;
      stopTimer();
      if (recorder && recorder.isRecording()) recorder.stop();
      sessionId = null;
      showSetup();
      return;
    }
    if (!confirm(`已完成 ${done} 段，确定结束并生成报告？`)) return;
    stopTimer();
    if (recorder && recorder.isRecording()) recorder.stop();
    await loadReport();
  }

  // -------------------------------------------------------------------
  // 十一、启动
  // -------------------------------------------------------------------
  function init() {
    // 首页 hero 按钮与考试卡片共用 data-start（事件委托，避免重复绑定）
    document.addEventListener("click", (e) => {
      // 题库里的某一套：指定套号直接开考
      const paper = e.target.closest("[data-paper]");
      if (paper) {
        e.preventDefault();
        start(paper.dataset.level, { paperId: paper.dataset.paper });
        return;
      }
      // 让 AI 现出一套新题
      const aiBtn = e.target.closest("[data-ai]");
      if (aiBtn) {
        e.preventDefault();
        start(aiBtn.dataset.ai, { source: "ai" });
        return;
      }
      const target = e.target.closest("[data-start]");
      if (target) {
        e.preventDefault();
        start(target.dataset.start);
      }
    });

    $("submitBtn").onclick = () => {
      if (phase === "prep") { stopTimer(); startAnswer(task); return; }
      if (phase === "answer") finishAnswer(false, false);
    };
    $("skipBtn").onclick = () => {
      if (phase === "prep") { stopTimer(); startAnswer(task); return; }
      if (phase === "answer") finishAnswer(true, false);
    };
    $("partnerBtn").onclick = talkToPartner;
    $("quitBtn").onclick = quit;

    // 输入框回车 = 在互动任务里发给搭档，其它情况不拦截
    $("answerText").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        if (task && (task.kind === "interaction" || task.kind === "discussion")) {
          talkToPartner();
        }
      }
    });

    // 从首页 / 导航进入考试时，重置到级别选择
    document.addEventListener("viewchange", (e) => {
      if (e.detail === "exam" && !sessionId) showSetup();
    });

    loadSpecs();
  }

  return { init, start, loadSpecs };
})();

window.Exam = Exam;
Exam.init();
