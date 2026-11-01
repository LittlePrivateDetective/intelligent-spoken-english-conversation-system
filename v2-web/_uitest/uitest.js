/* UI 集成测试：用 jsdom 真跑 index.html + app.js + exam.js，捕获运行时错误。
 * 用法：node uitest.js   （在 _uitest 目录下执行）
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const WEB = path.join(__dirname, "..", "web");
const html = fs.readFileSync(path.join(WEB, "index.html"), "utf8");
const appJs = fs.readFileSync(path.join(WEB, "app.js"), "utf8");
const examJs = fs.readFileSync(path.join(WEB, "exam.js"), "utf8");

const errors = [];
const logs = [];

// ---------------- 模拟后端 ----------------
const SPEC = {
  key: "cet4",
  name: "四级口语",
  full_name: "大学英语四级口语考试",
  code: "CET-SET4",
  minutes: 15,
  blurb: "5 个任务：自我介绍 → 短文朗读 → 简短回答 → 个人陈述 → 两人互动",
  parts: [
    { no: 1, name: "自我介绍", name_en: "Self-introduction", span: "20 秒" },
    { no: 2, name: "短文朗读", name_en: "Reading Aloud", span: "45 秒准备 + 1 分钟" },
  ],
  task_count: 2,
  steps: [
    { index: 0, part: 1, part_name: "自我介绍", label: "自我介绍", prep: 0, answer: 20 },
    { index: 1, part: 2, part_name: "短文朗读", label: "朗读短文", prep: 45, answer: 60 },
  ],
};

const TASK0 = {
  index: 0, total: 2, part: 1, part_name: "自我介绍", label: "自我介绍",
  kind: "self_intro", prep: 0, answer: 20, tip: "姓名、学校专业、一个爱好",
  prompt: "Please introduce yourself briefly.", detail: { hints: ["name", "major"] },
  source: "llm",
};
const TASK1 = {
  index: 1, total: 2, part: 2, part_name: "短文朗读", label: "朗读短文",
  kind: "reading", prep: 45, answer: 60, tip: "先通读一遍再开口",
  prompt: "Read the passage below aloud.",
  detail: { title: "Reading Before Bed", passage: "Many students say they have no time to read. Yet reading for fifteen minutes helps." },
  source: "llm",
};

const TASK_INTER = {
  index: 0, total: 1, part: 5, part_name: "两人互动", label: "与 AI 搭档互动",
  kind: "interaction", prep: 60, answer: 180, tip: "主动提问、回应对方、一起做决定",
  prompt: "Talk with your partner and complete the task together.",
  detail: { situation: "Your class is planning a trip.", task: "Decide where to go.", partner_role: "a classmate" },
  source: "llm",
};
const SPEC6 = {
  ...SPEC, key: "cet6", code: "CET-SET6", full_name: "大学英语六级口语考试",
  minutes: 30, task_count: 1,
  parts: [{ no: 5, name: "两人互动", name_en: "Pair Interaction", span: "3 分钟" }],
  steps: [{ index: 0, part: 5, part_name: "两人互动", label: "与 AI 搭档互动", prep: 60, answer: 180 }],
};

const SCORES = { accuracy: 3, range: 4, discourse: 3, coherence: 4, flexibility: 3, appropriateness: 4 };

function result(index) {
  return {
    index,
    label: index === 0 ? "自我介绍" : "朗读短文",
    level: "B",
    score_pct: 70.8,
    comment: "结构清晰，但细节不够。",
    strengths: ["开口自然"],
    improvements: ["补充一个具体例子"],
    better_version: "My name is Li Ming, and I study automation.",
    scores: SCORES,
    source: "llm",
    answer: "some answer",
    duration: 18,
    words: 32,
    wer: index === 1 ? { wer: 0.09, ref_words: 20, matched: 18, substitutions: 0, deletions: 2, insertions: 0, missed: ["yet", "helps"] } : null,
  };
}

const REPORT = {
  level_key: "cet4",
  level_name: "大学英语四级口语考试",
  code: "CET-SET4",
  grade: "B",
  score: 72.5,
  dimensions: [
    { key: "accuracy", name: "准确性", desc: "", score: 3.2, pct: 55 },
    { key: "range", name: "语言范围", desc: "", score: 4.0, pct: 75 },
    { key: "discourse", name: "话语长短", desc: "", score: 3.0, pct: 50 },
    { key: "coherence", name: "连贯性", desc: "", score: 3.6, pct: 65 },
    { key: "flexibility", name: "灵活性", desc: "", score: 2.8, pct: 45 },
    { key: "appropriateness", name: "适切性", desc: "", score: 3.4, pct: 60 },
  ],
  parts: [result(0), result(1)].map((r) => ({
    index: r.index, label: r.label, level: r.level, score: r.score_pct,
    comment: r.comment, strengths: r.strengths, improvements: r.improvements,
    better_version: r.better_version, answer: r.answer, words: r.words,
    duration: r.duration, wer: r.wer,
  })),
  strongest: { key: "range", name: "语言范围", score: 4.0 },
  weakest: { key: "flexibility", name: "灵活性", score: 2.8 },
  issues: ["补充一个具体例子"],
  advice: ["每天跟读十分钟", "用连接词串句子"],
  offline: false,
  paper_source: "llm",
};

let submitCount = 0;
let lastStartBody = null;

const PAPERS = {
  cet4: {
    count: 2,
    papers: [
      { id: "cet4-01", title: "Reading Before Bed", tags: ["学习", "健康"], summary: "Many students say they have no time to read." },
      { id: "cet4-02", title: "Shared Bikes in the City", tags: ["城市", "科技"], summary: "Ten years ago, few people used a bicycle." },
    ],
  },
  cet6: {
    count: 1,
    papers: [
      { id: "cet6-01", title: "Will AI create more jobs than it destroys?", tags: ["科技", "就业"], summary: "Some people worry that AI will take away jobs." },
    ],
  },
};

const routes = {
  "/api/status": () => ({ spoken_ok: true, spoken_err: "", llm: "qwen-plus @ dashscope" }),
  "/api/scenarios": () => ({
    scenarios: [
      { key: "airport_checkin", name: "机场值机", name_en: "Airport Check-in" },
      { key: "job_interview", name: "求职面试", name_en: "Job Interview" },
    ],
    difficulties: [
      { key: "beginner", name: "初级" },
      { key: "intermediate", name: "中级" },
      { key: "advanced", name: "高级" },
    ],
  }),
  "/api/exam/specs": () => ({
    exams: [
      { ...SPEC, paper_count: 2 },
      { ...SPEC, key: "cet6", code: "CET-SET6", full_name: "大学英语六级口语考试", minutes: 30, paper_count: 1 },
    ],
  }),
  "/api/exam/papers": () => ({ levels: PAPERS }),
  "/api/exam/start": (body) => {
    lastStartBody = body;
    if (body && body.level === "cet6") {
      return {
        session_id: "cet6sid1", task: TASK_INTER, spec: SPEC6, llm: "qwen-plus",
        paper_source: "llm", paper: { id: "", title: "AI and Entry-Level Jobs", tags: [] },
      };
    }
    const pinned = body && body.paper_id ? "Shared Bikes in the City" : "Reading Before Bed";
    return {
      session_id: "abc12345", task: TASK0, spec: SPEC, llm: "qwen-plus",
      paper_source: "bank", paper: { id: body?.paper_id || "cet4-01", title: pinned, tags: ["学习"] },
      bank_size: 2,
    };
  },
  "/api/exam/submit": () => ({ result: result(submitCount++), next: submitCount >= 2 ? null : TASK1, finished: submitCount >= 2 }),
  "/api/exam/report": () => REPORT,
  "/api/exam/partner": () => ({ reply: "That sounds good. What about the cost?" }),
};

// ---------------- 启动 jsdom ----------------
const dom = new JSDOM(html, {
  url: "http://127.0.0.1:8000/",
  runScripts: "outside-only",
  pretendToBeVisual: true,
});

const { window } = dom;

// 补齐 jsdom 缺失的浏览器 API
window.fetch = async (url, options) => {
  const path = String(url);
  const handler = routes[path];
  if (!handler) throw new Error("未模拟的接口: " + path);
  let body = null;
  if (options && options.body) {
    try { body = JSON.parse(options.body); } catch (e) { body = null; }
  }
  const data = handler(body);
  return { ok: true, status: 200, json: async () => data };
};
window.Element.prototype.scrollIntoView = function () {};
window.HTMLMediaElement.prototype.play = function () {};
window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {} }));
window.speechSynthesis = { cancel() {}, speak() {} };
window.SpeechSynthesisUtterance = function () {};
window.AudioContext = function () { this.close = () => {}; };
window.OfflineAudioContext = function () {};
window.navigator.mediaDevices = { getUserMedia: async () => ({ getTracks: () => [] }) };
window.confirm = () => true;

window.addEventListener("error", (e) => errors.push("window.error: " + (e.error?.stack || e.message)));
const origError = console.error;
console.error = (...args) => { errors.push("console.error: " + args.join(" ")); origError(...args); };

// ---------------- 断言工具 ----------------
let pass = 0;
function check(name, cond, extra) {
  if (cond) { pass += 1; logs.push("PASS " + name); }
  else { logs.push("FAIL " + name + (extra ? " -> " + extra : "")); }
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(fn, timeout = 4000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try { if (fn()) return true; } catch (e) { /* 继续等 */ }
    await wait(40);
  }
  return false;
}

(async () => {
  // 执行前端脚本（模拟 <script src> 顺序加载）
  window.eval(appJs + "\n" + examJs);

  const $ = (id) => window.document.getElementById(id);
  const q = (sel) => window.document.querySelector(sel);
  const qa = (sel) => Array.from(window.document.querySelectorAll(sel));

  await waitFor(() => qa("#examCards .exam-card").length === 2);
  check("首页渲染 2 张考试卡", qa("#examCards .exam-card").length === 2,
        "实际 " + qa("#examCards .exam-card").length);
  check("首页卡片显示官方编码", (qa("#examCards .exam-code")[0] || {}).textContent === "CET-SET4");
  check("首页卡片列出各 Part", qa("#examCards .exam-card")[0].textContent.includes("自我介绍"));
  check("场景列表已渲染", qa("#scenarioList .scenario-btn").length === 2);
  check("难度按钮已渲染", qa("#difficultyRow .diff-btn").length === 3);
  check("状态栏显示模型", $("statusText").textContent.includes("qwen-plus"), $("statusText").textContent);
  check("默认视图为首页", !$("view-home").hidden && $("view-exam").hidden);

  // ---- 题库：列表渲染 + 点某套直接开考 ----
  await waitFor(() => qa("#setupCards .paper-item").length === 3);
  check("题库列表已渲染（四级 2 套 + 六级 1 套）", qa("#setupCards .paper-item").length === 3,
        "实际 " + qa("#setupCards .paper-item").length);
  check("题库折叠显示套数",
        (q("#setupCards .paper-bank summary") || {}).textContent.includes("题库 2 套"),
        (q("#setupCards .paper-bank summary") || {}).textContent);
  check("级别卡片显示题库角标",
        qa("#examCards .exam-minutes")[0].textContent.includes("题库 2 套"),
        qa("#examCards .exam-minutes")[0].textContent);

  q('[data-paper="cet4-02"]').click();
  check("点题库某一套：请求带 paper_id",
        await waitFor(() => lastStartBody && lastStartBody.paper_id === "cet4-02"),
        JSON.stringify(lastStartBody));
  check("指定套号出卷后进入考试", await waitFor(() => !$("examRun").hidden));
  check("侧栏显示当前套卷名", $("paperName").textContent.includes("Shared Bikes"),
        $("paperName").textContent);

  // ---- 点击四级，进入考试 ----
  q('[data-start="cet4"]').click();
  const started = await waitFor(() => !$("examRun").hidden && $("taskLabel").textContent === "自我介绍");
  check("点击卡片进入考试视图", started, "taskLabel=" + $("taskLabel").textContent);
  check("Part 徽章正确", $("partBadge").textContent === "Part 1", $("partBadge").textContent);
  check("进度显示 1 / 2", $("stageCount").textContent === "1 / 2", $("stageCount").textContent);
  check("题目卡渲染提示点", $("promptCard").textContent.includes("可以讲"));
  check("侧栏步骤渲染 2 段", qa("#stepList .step").length === 2);
  check("当前步骤高亮", qa("#stepList .step.current").length === 1);
  check("自我介绍无准备阶段直接作答", $("submitBtn").textContent === "提交这一段", $("submitBtn").textContent);
  check("倒计时开始跑（≤20）", Number($("timerNum").textContent) <= 20 && Number($("timerNum").textContent) > 0,
        $("timerNum").textContent);
  check("互动搭档按钮在非互动任务中隐藏", $("partnerBtn").hidden === true);

  // ---- 提交第一段 ----
  $("answerText").value = "My name is Li Ming. I study automation.";
  $("submitBtn").click();
  const fbShown = await waitFor(() => !$("feedback").hidden);
  check("提交后显示单段反馈", fbShown);
  check("反馈含等级徽章", Boolean(q("#feedback .grade-badge")), $("feedback").innerHTML.slice(0, 80));
  check("反馈含六维条", qa("#feedback .dim-row").length === 6, String(qa("#feedback .dim-row").length));
  check("反馈含参考表达", $("feedback").textContent.includes("更地道的说法"));
  check("反馈含下一步按钮", Boolean($("nextBtn")));

  // ---- 下一段：朗读（有准备阶段）----
  $("nextBtn").click();
  const onReading = await waitFor(() => $("taskLabel").textContent === "朗读短文");
  check("进入第二段朗读", onReading);
  check("朗读题展示原文", $("promptCard").textContent.includes("Many students say"));
  check("朗读题进入准备阶段", $("timerLabel").textContent === "准备", $("timerLabel").textContent);
  check("准备阶段提交按钮为开始作答", $("submitBtn").textContent === "准备好了，开始作答");
  check("准备阶段录音按钮禁用", $("micBtn").disabled === true);

  // 跳过准备，进入作答
  $("submitBtn").click();
  check("点击后进入作答阶段", $("timerLabel").textContent === "作答", $("timerLabel").textContent);
  check("作答阶段录音可用", $("micBtn").disabled === false);

  $("answerText").value = "Many students say they have no time to read.";
  $("submitBtn").click();
  await waitFor(() => !$("feedback").hidden && $("feedback").textContent.includes("朗读客观比对"));
  check("朗读反馈显示 WER 比对", $("feedback").textContent.includes("词错误率"),
        $("feedback").textContent.slice(0, 120));
  check("最后一段按钮变为查看报告", ($("nextBtn") || {}).textContent === "查看整场报告",
        ($("nextBtn") || {}).textContent);

  // ---- 报告 ----
  $("nextBtn").click();
  const reportShown = await waitFor(() => !$("examReport").hidden && Boolean(q("svg.radar")));
  check("报告视图渲染雷达图", reportShown);
  check("雷达图有 6 个维度标签", qa("svg.radar .dim-label").length === 6,
        String(qa("svg.radar .dim-label").length));
  check("报告显示等级", q("#examReport .report-badge b").textContent === "B");
  check("报告显示 6 个分段卡", qa("#examReport .part-report").length === 2);
  check("报告含训练建议", $("examReport").textContent.includes("下一步怎么练"));
  check("报告含再考一次", Boolean($("againBtn")));

  // ---- 切回首页 / 深色主题 ----
  $("backHomeBtn").click();
  await wait(80);
  check("报告页可回到首页", !$("view-home").hidden && $("view-exam").hidden);
  $("themeBtn").click();
  check("主题可切换", ["dark", "light"].includes(window.document.documentElement.dataset.theme),
        window.document.documentElement.dataset.theme);

  // ---- 场景练习视图仍可用 ----
  window.location.hash = "practice";
  await wait(120);
  check("场景练习视图可切换", !$("view-practice").hidden);

  // ---- 互动任务：AI 搭档接话 ----
  window.location.hash = "home";
  await wait(120);
  const cet6Card = qa('#examCards [data-start="cet6"]')[0];
  check("首页有六级入口", Boolean(cet6Card));
  cet6Card.click();
  const inInter = await waitFor(() => !$("examRun").hidden && $("taskLabel").textContent === "与 AI 搭档互动");
  check("六级互动任务进入考试视图", inInter, $("taskLabel").textContent);
  check("互动任务显示搭档对话区", $("dialogue").hidden === false);
  check("互动任务显示「对搭档说」按钮", $("partnerBtn").hidden === false);
  check("搭档开场白已渲染", $("dialogue").textContent.includes("搭档"));
  check("互动任务有准备阶段", $("timerLabel").textContent === "准备", $("timerLabel").textContent);

  $("submitBtn").click();
  await wait(80);
  $("answerText").value = "I think we should go to the old town because it is cheap.";
  $("partnerBtn").click();
  const replied = await waitFor(() => $("dialogue").textContent.includes("What about the cost"));
  check("发给搭档后收到英语回复", replied, $("dialogue").textContent.slice(-120));
  check("对话区记录了我的发言", $("dialogue").textContent.includes("old town"));
  check("发言发给搭档后输入框清空", $("answerText").value === "");

  // ---- 题库：让 AI 现出一套新题 ----
  const aiBtn = q('[data-ai="cet6"]');
  check("题库里有「AI 现出一套」按钮", Boolean(aiBtn));
  if (aiBtn) {
    aiBtn.click();
    check("AI 现出：请求带 source=ai",
          await waitFor(() => lastStartBody && lastStartBody.source === "ai"),
          JSON.stringify(lastStartBody));
    check("AI 现出：题目渲染正常", await waitFor(() => !$("examRun").hidden));
  }

  check("无未捕获的 JS 运行时错误", errors.length === 0, errors.slice(0, 3).join(" | "));

  console.log(logs.join("\n"));
  console.log("\n==== " + pass + " 项通过 ====");
  if (errors.length) console.log("运行时错误:\n" + errors.join("\n"));
  window.close();
  process.exit(pass >= 30 && errors.length === 0 ? 0 : 1);
})();
