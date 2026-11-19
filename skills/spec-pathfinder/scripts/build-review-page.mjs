#!/usr/bin/env node
// v1 审阅页生成器：把人审版 v1（SPEC-human-v1.md）与存疑清单 v1（DOUBTS-v1.md）
// 编成一个自包含的交互 HTML 审阅页，只改呈现、不改内容。
// 只依赖 SKILL.md 定义的 v1 固定格式（受控自然语言、固定字段）；Node 18+、零第三方依赖。
// 生成的页面复刻 skills/spec-pathfinder/review/v1-review.html 的结构与交互。
import fs from 'node:fs';
import path from 'node:path';

const USAGE = `用法：node scripts/build-review-page.mjs --spec <人审版v1.md> --doubts <存疑清单v1.md> --out <输出.html>
参数：
  --spec    人审版 v1 的 Markdown 文件路径（必填）
  --doubts  存疑清单 v1 的 Markdown 文件路径（必填）
  --out     输出 HTML 文件路径（必填，不存在父目录时自动创建）
  -h, --help  显示本用法`;

function fail(message) {
  console.error('生成审阅页失败：' + message);
  console.error(USAGE);
  process.exitCode = 1;
  throw new Error(message);
}

function parseArgs(argv) {
  const args = { spec: null, doubts: null, out: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    let key = null, value = null;
    const eq = a.indexOf('=');
    if (a === '-h' || a === '--help') { console.log(USAGE); process.exit(0); }
    if (a.startsWith('--') && eq > 2) { key = a.slice(2, eq); value = a.slice(eq + 1); }
    else if (a.startsWith('--')) { key = a.slice(2); value = argv[++i]; }
    else fail(`无法识别的参数：${a}`);
    if (!['spec', 'doubts', 'out'].includes(key)) fail(`无法识别的参数：--${key}`);
    if (value === undefined || value === '') fail(`参数 --${key} 缺少取值`);
    args[key] = value;
  }
  for (const k of ['spec', 'doubts', 'out']) if (!args[k]) fail(`缺少必填参数 --${k}`);
  return args;
}

function readFileOrFail(file, label) {
  try { return fs.readFileSync(file, 'utf8'); }
  catch (e) { fail(`读不到${label}文件：${file}（${e.code ?? e.message}）`); }
}

// ---------- 文本小工具 ----------
function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
// 只处理行内 **加粗**；其余原样呈现（v1 人审版是纯自然语言，不解析其他 Markdown）。
function inlineMd(s) {
  return escapeHtml(s).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
}
function stripTrailingPeriod(s) {
  return s.endsWith('。') ? s.slice(0, -1) : s;
}
// "中（用例原文……）。" -> { level: "中", rest: "（用例原文……）" }；无括号时 rest 为空。
function splitConfidence(value) {
  const v = value.trim();
  const i = v.indexOf('（');
  if (i < 0) return { level: stripTrailingPeriod(v), rest: '' };
  return { level: v.slice(0, i).trim(), rest: stripTrailingPeriod(v.slice(i)) };
}

// ---------- 解析人审版 v1 ----------
function splitSections(lines) {
  const sections = [];
  let current = null;
  for (const line of lines) {
    const m = /^##\s+(.*\S)\s*$/.exec(line);
    if (m) { current = { heading: m[1].trim(), lines: [] }; sections.push(current); }
    else if (current) current.lines.push(line);
  }
  return sections;
}

function parseSpec(text) {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const titleLine = lines.find(l => /^#\s+\S/.test(l));
  if (!titleLine) fail('人审版缺少一级标题（# ……）');
  const title = titleLine.replace(/^#\s+/, '').trim();

  // 标题前的引用块：第一块是指引，第二块起是版本说明（原样放进页头介绍）。
  const headLines = [];
  for (const l of lines) { if (/^##\s/.test(l)) break; headLines.push(l); }
  const quoteBlocks = [];
  let block = [];
  for (const l of headLines) {
    const q = /^>\s?(.*)$/.exec(l);
    if (q) block.push(q[1]);
    else if (block.length) { quoteBlocks.push(block); block = []; }
  }
  if (block.length) quoteBlocks.push(block);
  const introBlocks = quoteBlocks.slice(1).map(b => b.join('')).filter(Boolean);

  // 公共前置条件
  const sections = splitSections(lines);
  const precondSection = sections.find(s => s.heading === '公共前置条件');
  const commonPrecond = [];
  if (precondSection) {
    for (const l of precondSection.lines) {
      const b = /^-\s+(.*\S)\s*$/.exec(l);
      if (b) commonPrecond.push(b[1].trim());
    }
  }

  // 用例：## TC-0008：标题
  const cases = [];
  const caseRe = /^([A-Za-z]+-[0-9A-Za-z-]+)：(.+)$/;
  for (const sec of sections) {
    const m = caseRe.exec(sec.heading);
    if (!m) continue;
    const c = { id: m[1], title: m[2].trim(), status: '', precond: '', steps: [], cleanup: '' };
    let step = null;
    let lastField = null; // { obj, key }，接住跨行续写的值
    for (const raw of sec.lines) {
      const line = raw.trim();
      if (!line) { lastField = null; continue; }
      const head = /^\*\*(.+?)\*\*：(.*)$/.exec(line);
      if (head) {
        const key = head[1].trim(), value = head[2].trim();
        lastField = null;
        if (key === '状态') c.status = value;
        else if (key === '前置条件') c.precond = value;
        else if (key === '清理') c.cleanup = value;
        else if (/^步骤\s*\d+$/.test(key)) {
          step = { no: Number(key.replace(/^步骤\s*/, '')), fields: [] };
          c.steps.push(step);
        } else if (step) { step.fields.push({ key, value }); lastField = { obj: step, key }; }
        continue;
      }
      const bullet = /^-\s+([^：:]+)[：:]\s*(.*)$/.exec(line);
      if (bullet && step) {
        step.fields.push({ key: bullet[1].trim(), value: bullet[2].trim() });
        lastField = { obj: step, key: bullet[1].trim() };
        continue;
      }
      // 其余非空行是上一字段的续写（同一句话被换行写开），拼回原字段。
      if (lastField) {
        const f = lastField.obj.fields.find(x => x.key === lastField.key);
        if (f) f.value += line;
      }
    }
    for (const s of c.steps) {
      const get = k => s.fields.find(f => f.key === k)?.value;
      if (!get('操作')) fail(`${c.id} 步骤 ${s.no} 缺少「操作」`);
      if (!get('预期')) fail(`${c.id} 步骤 ${s.no} 缺少「预期」`);
      if (!get('置信度')) fail(`${c.id} 步骤 ${s.no} 缺少「置信度」`);
    }
    cases.push(c);
  }
  if (!cases.length) fail('人审版里没有解析到用例（需要形如 "## TC-0008：标题" 的小节）');

  // 页脚尾句：文件末尾最后一段非表格行；去掉 "详见……" 这种指向句。
  let tail = '';
  for (let i = lines.length - 1; i >= 0; i--) {
    const l = lines[i].trim();
    if (!l || l.startsWith('|') || l.startsWith('#')) continue;
    tail = l; break;
  }
  const tailSentences = tail.split(/(?<=。)/).map(s => s.trim())
    .filter(s => s && !s.startsWith('详见'));
  tail = tailSentences.join('');
  return { title, introBlocks, commonPrecond, cases, tail };
}

// ---------- 解析存疑清单 v1 ----------
function parseDoubts(text) {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const sections = splitSections(lines);
  const doubts = [];
  const doubtRe = /^([A-Za-z]+-[0-9A-Za-z-]+)：(.+)$/;
  for (const sec of sections) {
    const m = doubtRe.exec(sec.heading);
    if (!m) continue;
    const rest = m[2].trim();
    const dash = rest.indexOf('——');
    const status = dash >= 0 ? rest.slice(0, dash).trim() : '';
    const title = dash >= 0 ? rest.slice(dash + 2).trim() : rest;
    const rows = [];
    for (const raw of sec.lines) {
      const b = /^-\s+\*\*(.+?)\*\*[：:]\s*(.*)$/.exec(raw.trim());
      if (b) rows.push({ key: b[1].trim(), value: b[2].trim() });
    }
    if (!rows.length) fail(`${m[1]} 没有解析到任何条目（需要形如 "- **答案**：……" 的行）`);
    doubts.push({ id: m[1], status: status || '未标注', title, rows });
  }
  if (!doubts.length) fail('存疑清单里没有解析到条目（需要形如 "## Q-v1-1：已解答——标题" 的小节）');
  return doubts;
}

// ---------- 页面样式：与 review/v1-review.html 完全一致 ----------
const CSS = `
  :root{
    --bg:#f4f5f7; --surface:#ffffff; --surface-2:#eef1f4; --ink:#182230; --ink-2:#46536a; --ink-3:#7a8699;
    --line:#dde2ea; --line-strong:#c6cedb;
    --pass:#0e7a5f; --pass-bg:#e6f4ef;
    --issue:#b42318; --issue-bg:#fdf0ee;
    --pending:#9a6a00; --pending-bg:#fdf6e0;
    --accent:#175cd3; --accent-bg:#eaf1fe;
    --radius:14px;
    --shadow:0 1px 2px rgba(16,24,40,.05),0 1px 3px rgba(16,24,40,.06);
  }
  @media (prefers-color-scheme: dark){
    :root{
      --bg:#11151c; --surface:#1a2029; --surface-2:#232b37; --ink:#eef1f6; --ink-2:#b9c2d0; --ink-3:#8a96a8;
      --line:#2e3847; --line-strong:#3d4a5e;
      --pass:#3ecfae; --pass-bg:#12332c;
      --issue:#ff8a7a; --issue-bg:#3d1f1b;
      --pending:#f2c14e; --pending-bg:#38300f;
      --accent:#7db1ff; --accent-bg:#1d2f4d;
      --shadow:0 1px 2px rgba(0,0,0,.3);
    }
  }
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  @media (prefers-reduced-motion: reduce){ html{scroll-behavior:auto} *{transition:none!important} }
  body{margin:0;background:var(--bg);color:var(--ink);
    font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,-apple-system,"Segoe UI",sans-serif;
    font-size:15px;line-height:1.65;-webkit-font-smoothing:antialiased}
  button{font:inherit;cursor:pointer}
  .mono{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace}

  /* ---------- sticky top ---------- */
  .topbar{position:sticky;top:0;z-index:50;background:var(--surface);border-bottom:1px solid var(--line);box-shadow:var(--shadow)}
  .topbar-in{max-width:980px;margin:0 auto;padding:12px 16px 10px}
  .top-row{display:flex;align-items:flex-start;gap:12px;flex-wrap:wrap}
  .top-title{flex:1 1 260px;min-width:220px}
  .top-title h1{font-size:17px;line-height:1.35;margin:0 0 2px;font-weight:700;letter-spacing:.01em}
  .top-title p{margin:0;font-size:12.5px;color:var(--ink-2)}
  .counts{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
  .chip{display:inline-flex;align-items:center;gap:5px;font-size:12.5px;font-weight:600;
    padding:3px 10px;border-radius:999px;border:1px solid var(--line);background:var(--surface-2);color:var(--ink-2);min-height:26px}
  .chip b{font-size:13px;color:var(--ink)}
  .chip.pass{background:var(--pass-bg);border-color:transparent}.chip.pass b{color:var(--pass)}
  .chip.issue{background:var(--issue-bg);border-color:transparent}.chip.issue b{color:var(--issue)}
  .chip.pending{background:var(--pending-bg);border-color:transparent}.chip.pending b{color:var(--pending)}
  .progress{height:8px;border-radius:99px;background:var(--surface-2);overflow:hidden;display:flex;margin-top:10px}
  .progress i{display:block;height:100%;width:0;transition:width .25s ease}
  .progress .seg-pass{background:var(--pass)} .progress .seg-issue{background:var(--issue)} .progress .seg-pending{background:var(--pending)}
  .progress-label{font-size:12px;color:var(--ink-3);margin-top:5px}
  .top-actions{display:flex;gap:8px;flex-wrap:wrap}
  .btn{min-height:40px;padding:8px 16px;border-radius:10px;border:1px solid var(--line-strong);
    background:var(--surface);color:var(--ink);font-weight:600;font-size:14px}
  .btn:hover{border-color:var(--ink-3)}
  .btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
  @media (prefers-color-scheme: dark){ .btn.primary{color:#0b1526} }
  .btn.small{min-height:36px;padding:6px 12px;font-size:13px}
  .filters{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
  .fbtn{min-height:36px;padding:6px 14px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--ink-2);font-size:13px;font-weight:600}
  .fbtn[aria-pressed="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
  .save-note{font-size:12px;color:var(--ink-3);margin-top:8px}

  main{max-width:980px;margin:0 auto;padding:20px 16px 40px}
  .intro{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;box-shadow:var(--shadow)}
  .intro h2{font-size:15px;margin:0 0 6px}
  .intro p{margin:0 0 8px;color:var(--ink-2);font-size:14px}
  .intro p:last-child{margin-bottom:0}
  .intro .src{font-size:12.5px;color:var(--ink-3)}
  details.precond{margin-top:12px;border-top:1px dashed var(--line);padding-top:10px}
  details.precond summary{min-height:36px;display:flex;align-items:center;font-weight:600;font-size:14px;cursor:pointer;color:var(--accent)}
  details.precond ul{margin:6px 0 4px;padding-left:20px;color:var(--ink-2);font-size:14px}
  details.precond li{margin-bottom:5px}

  .section-head{display:flex;align-items:baseline;gap:10px;margin:28px 2px 12px;flex-wrap:wrap}
  .section-head h2{font-size:19px;margin:0;font-weight:750}
  .section-head span{font-size:13px;color:var(--ink-3)}

  /* ---------- case cards ---------- */
  .case{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);margin-bottom:16px;overflow:hidden}
  .case-head{padding:14px 18px 10px;border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap}
  .case-id{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-weight:700;font-size:13px;
    background:var(--accent-bg);color:var(--accent);border-radius:7px;padding:3px 9px;white-space:nowrap;margin-top:2px}
  .case-head h3{font-size:16px;margin:0;line-height:1.45;flex:1 1 300px}
  .case-status{font-size:12.5px;font-weight:700;padding:3px 10px;border-radius:999px;background:var(--pass-bg);color:var(--pass);white-space:nowrap}
  .case-meta{padding:10px 18px 2px;font-size:13.5px;color:var(--ink-2)}
  .case-meta .lbl{font-weight:700;color:var(--ink);margin-right:6px}
  .cleanup{margin:10px 18px 14px;font-size:13.5px;color:var(--ink-2);background:var(--surface-2);border-radius:9px;padding:8px 12px}
  .cleanup .lbl{font-weight:700;color:var(--ink);margin-right:6px}

  .step{padding:14px 18px;border-top:1px solid var(--line)}
  .step:first-of-type{border-top:none}
  .step-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}
  .step-no{font-weight:750;font-size:14px}
  .badge{font-size:12px;font-weight:700;padding:2px 9px;border-radius:999px;border:1px solid var(--line-strong);color:var(--ink-3)}
  .badge.st-pass{background:var(--pass-bg);color:var(--pass);border-color:transparent}
  .badge.st-issue{background:var(--issue-bg);color:var(--issue);border-color:transparent}
  .badge.st-pending{background:var(--pending-bg);color:var(--pending);border-color:transparent}
  .conf{margin-left:auto;font-size:12.5px;color:var(--ink-3)}
  .conf b{color:var(--ink-2)}
  .kv{margin:0 0 6px;font-size:14.5px}
  .kv .k{font-weight:700;color:var(--ink-2);font-size:13px;margin-right:8px;letter-spacing:.02em}
  .kv.expect{background:var(--surface-2);border-radius:9px;padding:8px 12px}
  .note-line{font-size:13.5px;color:var(--ink-2);margin:0 0 6px}
  .note-line .k{font-weight:700;font-size:13px;margin-right:8px;color:var(--pending)}
  .note-line.loc .k{color:var(--accent)}

  .markrow{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;align-items:stretch}
  .markbtn{flex:1 1 96px;min-height:44px;border-radius:10px;border:1.5px solid var(--line-strong);background:var(--surface);
    font-weight:700;font-size:14px;color:var(--ink-2);display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:8px 6px}
  .markbtn .dot{width:9px;height:9px;border-radius:50%;background:currentColor;opacity:.45}
  .markbtn[data-val="pass"][aria-pressed="true"]{background:var(--pass-bg);border-color:var(--pass);color:var(--pass)}
  .markbtn[data-val="issue"][aria-pressed="true"]{background:var(--issue-bg);border-color:var(--issue);color:var(--issue)}
  .markbtn[data-val="pending"][aria-pressed="true"]{background:var(--pending-bg);border-color:var(--pending);color:var(--pending)}
  .step[data-status="pass"]{box-shadow:inset 0 0 0 999px color-mix(in srgb, var(--pass-bg) 45%, transparent)}
  .step[data-status="issue"]{box-shadow:inset 0 0 0 999px color-mix(in srgb, var(--issue-bg) 55%, transparent)}
  .step[data-status="pending"]{box-shadow:inset 0 0 0 999px color-mix(in srgb, var(--pending-bg) 55%, transparent)}
  .notebox{display:none;margin-top:10px}
  .step[data-status="issue"] .notebox,.step[data-status="pending"] .notebox{display:block}
  .notebox label{font-size:13px;font-weight:600;color:var(--ink-2);display:block;margin-bottom:5px}
  .notebox textarea{width:100%;min-height:64px;border:1px solid var(--line-strong);border-radius:9px;padding:9px 11px;
    font:inherit;font-size:14px;background:var(--surface);color:var(--ink);resize:vertical}
  .notebox textarea:focus{outline:2px solid var(--accent);outline-offset:1px;border-color:transparent}

  /* ---------- doubts ---------- */
  .doubt{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);margin-bottom:12px;overflow:hidden}
  .doubt .step{border-top:none}
  .q-id{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-weight:700;font-size:13px;
    background:var(--pending-bg);color:var(--pending);border-radius:7px;padding:3px 9px;white-space:nowrap}
  .doubt h3{display:inline;font-size:15px;margin:0 0 0 4px}
  .q-state{font-size:12px;font-weight:700;padding:2px 9px;border-radius:999px;background:var(--pass-bg);color:var(--pass);white-space:nowrap}

  .empty{display:none;text-align:center;color:var(--ink-3);padding:34px 16px;font-size:14px;
    border:1.5px dashed var(--line-strong);border-radius:var(--radius);margin-bottom:16px}

  /* ---------- export ---------- */
  .export-panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);padding:16px 18px;margin-top:28px}
  .export-panel h2{font-size:16px;margin:0 0 6px}
  .export-panel p{margin:0 0 12px;font-size:13.5px;color:var(--ink-2)}
  #exportText{width:100%;min-height:180px;border:1px solid var(--line-strong);border-radius:10px;padding:11px 12px;
    font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:12.5px;line-height:1.6;background:var(--surface-2);color:var(--ink);resize:vertical}
  .export-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
  .toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%) translateY(16px);opacity:0;pointer-events:none;
    background:var(--ink);color:var(--bg);font-size:14px;font-weight:600;padding:10px 18px;border-radius:999px;transition:all .22s ease;z-index:99;max-width:90vw;text-align:center}
  .toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
  footer{max-width:980px;margin:0 auto;padding:0 16px 34px;font-size:12.5px;color:var(--ink-3)}
  .hidden{display:none!important}
`;

// ---------- 页面交互脚本：与 review/v1-review.html 完全一致，只参数化两处 ----------
// __FIRST_CASE__：首条用例编号（进度条初始文案用）；__DOWNLOAD_NAME__：导出下载文件名。
const PAGE_JS = `
(function(){
  "use strict";
  var STATUS = {
    pass:   { label: "通过",   cls: "st-pass" },
    issue:  { label: "有问题", cls: "st-issue" },
    pending:{ label: "待定",   cls: "st-pending" }
  };
  var items = Array.prototype.slice.call(document.querySelectorAll("[data-item]"));
  var state = {}; // id -> {status:"", note:""}
  items.forEach(function(el){ state[el.id] = { status:"", note:"" }; });

  // Build mark buttons for every item
  items.forEach(function(el){
    var row = el.querySelector("[data-markrow]");
    if(!row) return;
    ["pass","issue","pending"].forEach(function(val){
      var b = document.createElement("button");
      b.type = "button";
      b.className = "markbtn";
      b.setAttribute("data-val", val);
      b.setAttribute("aria-pressed", "false");
      b.setAttribute("aria-label", "标记 " + el.getAttribute("data-label") + " 为" + STATUS[val].label);
      b.innerHTML = '<span class="dot" aria-hidden="true"></span>' + STATUS[val].label;
      b.addEventListener("click", function(){
        var cur = state[el.id].status;
        state[el.id].status = (cur === val) ? "" : val; // click again to undo
        syncItem(el);
        refresh();
        if(state[el.id].status === "issue" || state[el.id].status === "pending"){
          var ta = el.querySelector("[data-note]");
          if(ta){ setTimeout(function(){ ta.focus({preventScroll:true}); }, 60); }
        }
      });
      row.appendChild(b);
    });
    var ta = el.querySelector("[data-note]");
    if(ta){
      ta.addEventListener("input", function(){
        state[el.id].note = ta.value;
        refreshExport();
      });
    }
  });

  function syncItem(el){
    var s = state[el.id].status;
    el.setAttribute("data-status", s);
    var badge = el.querySelector("[data-badge]");
    if(badge){
      badge.textContent = s ? STATUS[s].label : "未审";
      badge.className = "badge" + (s ? " " + STATUS[s].cls : "");
    }
    el.querySelectorAll(".markbtn").forEach(function(b){
      b.setAttribute("aria-pressed", b.getAttribute("data-val") === s ? "true" : "false");
    });
  }

  function counts(){
    var c = { total: items.length, pass:0, issue:0, pending:0, done:0 };
    items.forEach(function(el){
      var s = state[el.id].status;
      if(s){ c.done++; c[s]++; }
    });
    c.todo = c.total - c.done;
    return c;
  }

  var filter = "all";
  function applyFilter(){
    var visibleCases = 0, visibleDoubts = 0;
    items.forEach(function(el){
      var s = state[el.id].status;
      var show = filter === "all" ? true :
                 filter === "todo" ? !s :
                 s === filter;
      if(el.closest(".doubt")){ el.closest(".doubt").style.display = show ? "" : "none"; if(show) visibleDoubts++; }
      else { el.style.display = show ? "" : "none"; if(show) visibleCases++; }
    });
    // hide case cards with no visible steps; hide/show their meta & cleanup with the card
    document.querySelectorAll(".case").forEach(function(card){
      var any = Array.prototype.some.call(card.querySelectorAll("[data-item]"), function(s){ return s.style.display !== "none"; });
      card.style.display = any ? "" : "none";
    });
    document.getElementById("emptyCases").style.display = visibleCases === 0 ? "block" : "none";
    document.getElementById("emptyDoubts").style.display = visibleDoubts === 0 ? "block" : "none";
  }

  function refresh(){
    var c = counts();
    document.getElementById("cTotal").textContent = c.total;
    document.getElementById("cDone").textContent = c.done;
    document.getElementById("cPass").textContent = c.pass;
    document.getElementById("cIssue").textContent = c.issue;
    document.getElementById("cPending").textContent = c.pending;
    document.getElementById("cTodo").textContent = c.todo;
    var pct = function(n){ return (c.total ? (n / c.total * 100) : 0) + "%"; };
    document.getElementById("segPass").style.width = pct(c.pass);
    document.getElementById("segIssue").style.width = pct(c.issue);
    document.getElementById("segPending").style.width = pct(c.pending);
    var bar = document.getElementById("progressBar");
    bar.setAttribute("aria-valuenow", c.done); bar.setAttribute("aria-valuemax", c.total);
    var lbl = document.getElementById("progressLabel");
    if(c.done === 0) lbl.textContent = "还没开始审，从 __FIRST_CASE__ 第一步往下看就行。";
    else if(c.todo === 0) lbl.textContent = "全部审完了，去底部导出结果发回即可。";
    else lbl.textContent = "已审 " + c.done + " / " + c.total + "，还剩 " + c.todo + " 条未审。";
    applyFilter();
    refreshExport();
  }

  function buildExport(){
    var c = counts();
    var lines = [];
    lines.push("# v1 审阅结果");
    lines.push("");
    lines.push("进度：" + c.done + "/" + c.total + " 已审（通过 " + c.pass + " · 有问题 " + c.issue + " · 待定 " + c.pending + " · 未审 " + c.todo + "）");
    function section(title, val){
      var list = items.filter(function(el){ return state[el.id].status === val; });
      lines.push("");
      lines.push("## " + title + "（" + list.length + "）");
      if(!list.length){ lines.push("- （无）"); return; }
      list.forEach(function(el){
        var note = (state[el.id].note || "").trim();
        lines.push("- " + el.getAttribute("data-label") + (note ? "：备注：" + note.replace(/\\n/g, " ") : "：（无备注）"));
      });
    }
    section("有问题", "issue");
    section("待定", "pending");
    section("通过", "pass");
    var todo = items.filter(function(el){ return !state[el.id].status; });
    lines.push("");
    lines.push("## 未审（" + todo.length + "）");
    if(!todo.length) lines.push("- （无）");
    todo.forEach(function(el){ lines.push("- " + el.getAttribute("data-label")); });
    return lines.join("\\n");
  }
  function refreshExport(){
    document.getElementById("exportText").value = buildExport();
  }

  // Filters
  document.querySelectorAll(".fbtn").forEach(function(b){
    b.addEventListener("click", function(){
      filter = b.getAttribute("data-filter");
      document.querySelectorAll(".fbtn").forEach(function(x){ x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
      applyFilter();
    });
  });

  // Toast
  var toastTimer = null;
  function toast(msg){
    var t = document.getElementById("toast");
    t.textContent = msg; t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function(){ t.classList.remove("show"); }, 2400);
  }

  // Copy
  function copyExport(){
    var text = buildExport();
    var ta = document.getElementById("exportText");
    function fallback(){
      ta.removeAttribute("readonly"); ta.select();
      try { document.execCommand("copy"); toast("已复制，粘贴发回聊天里就行"); }
      catch(e){ toast("复制没成功，请长按文本框手动复制"); }
      ta.setAttribute("readonly","");
    }
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(function(){ toast("已复制，粘贴发回聊天里就行"); }, fallback);
    } else fallback();
  }
  document.getElementById("btnCopy").addEventListener("click", copyExport);
  document.getElementById("btnExportTop").addEventListener("click", function(){
    document.getElementById("exportPanel").scrollIntoView({behavior:"smooth", block:"start"});
    setTimeout(copyExport, 450);
  });

  // Download
  document.getElementById("btnDownload").addEventListener("click", function(){
    var blob = new Blob([buildExport()], {type:"text/markdown;charset=utf-8"});
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url; a.download = "__DOWNLOAD_NAME__";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function(){ URL.revokeObjectURL(url); }, 800);
    toast("已下载 __DOWNLOAD_NAME__");
  });

  // Reset
  document.getElementById("btnReset").addEventListener("click", function(){
    items.forEach(function(el){
      state[el.id] = { status:"", note:"" };
      var ta = el.querySelector("[data-note]"); if(ta) ta.value = "";
      syncItem(el);
    });
    refresh();
    toast("标记已清空");
  });

  items.forEach(syncItem);
  refresh();
})();
`;

// ---------- 生成 HTML ----------
function stepHtml(c, s) {
  const id = `${c.id}-S${s.no}`;
  const label = `${c.id} 步骤 ${s.no}`;
  const get = k => s.fields.find(f => f.key === k)?.value;
  const conf = splitConfidence(get('置信度'));
  const rows = [];
  for (const f of s.fields) {
    if (f.key === '置信度') continue;
    if (f.key === '操作') rows.push(`<p class="kv"><span class="k">操作</span>${inlineMd(f.value)}</p>`);
    else if (f.key === '预期') rows.push(`<p class="kv expect"><span class="k">预期</span>${inlineMd(f.value)}</p>`);
    else if (f.key === '定位依据') rows.push(`<p class="note-line loc"><span class="k">定位依据</span>${inlineMd(f.value)}</p>`);
    else if (f.key === '注意') rows.push(`<p class="note-line"><span class="k">注意</span>${inlineMd(f.value)}</p>`);
    else rows.push(`<p class="kv"><span class="k">${escapeHtml(f.key)}</span>${inlineMd(f.value)}</p>`);
  }
  return `    <div class="step" data-item id="${id}" data-label="${escapeHtml(label)}">
      <div class="step-top"><span class="step-no">步骤 ${s.no}</span><span class="badge" data-badge>未审</span><span class="conf">置信度：<b>${escapeHtml(conf.level)}</b>${escapeHtml(conf.rest)}</span></div>
${rows.join('\n')}
      <div class="markrow" data-markrow></div>
      <div class="notebox"><label for="note-${id}">备注（这条哪里不对 / 缺什么）</label><textarea id="note-${id}" data-note placeholder="例如：这句看不懂 / 这里缺一步 / 预期少了一项…"></textarea></div>
    </div>`;
}

function caseHtml(c) {
  const steps = c.steps.map(s => stepHtml(c, s)).join('\n');
  const meta = c.precond ? `\n    <p class="case-meta"><span class="lbl">前置条件</span>${inlineMd(c.precond)}</p>` : '';
  const cleanup = c.cleanup ? `\n    <p class="cleanup"><span class="lbl">清理</span>${inlineMd(c.cleanup)}</p>` : '';
  const status = c.status ? `\n      <span class="case-status">${escapeHtml(c.status)}</span>` : '';
  return `  <article class="case" data-case="${escapeHtml(c.id)}">
    <div class="case-head">
      <span class="case-id">${escapeHtml(c.id)}</span>
      <h3>${inlineMd(c.title)}</h3>${status}
    </div>${meta}
${steps}${cleanup}
  </article>`;
}

function doubtHtml(d) {
  const rows = d.rows.map(r =>
    `    <p class="kv"><span class="k">${escapeHtml(r.key)}</span>${inlineMd(r.value)}</p>`).join('\n');
  const label = `${d.id} ${d.title}`;
  return `  <article class="doubt"><div class="step" data-item id="${escapeHtml(d.id)}" data-label="${escapeHtml(label)}">
    <div class="step-top"><span class="q-id">${escapeHtml(d.id)}</span><h3>${inlineMd(d.title)}</h3><span class="q-state">${escapeHtml(d.status)}</span><span class="badge" data-badge>未审</span></div>
${rows}
    <div class="markrow" data-markrow></div>
    <div class="notebox"><label for="note-${escapeHtml(d.id)}">备注 / 你能补的答案</label><textarea id="note-${escapeHtml(d.id)}" data-note placeholder="补充说明…"></textarea></div>
  </div></article>`;
}

function buildHtml(spec, doubts, specBase, doubtsBase, outBase) {
  const totalSteps = spec.cases.reduce((n, c) => n + c.steps.length, 0);
  const total = totalSteps + doubts.length;
  const firstCase = spec.cases[0].id;
  const lastCase = spec.cases[spec.cases.length - 1].id;
  const firstQ = doubts[0].id;
  const lastQ = doubts[doubts.length - 1].id;
  const h1Base = spec.title.replace(/（[^）]*）\s*$/, '').trim();
  const h1 = `${h1Base} 审阅`;
  const downloadName = `${outBase.replace(/\.html?$/i, '')}-result.md`;
  const resolved = new Set(['已解答', '已由原型解答', '已约定', '已裁决']);
  const allResolved = doubts.every(d => resolved.has(d.status));
  const doubtsNote = allResolved ? '全部已解答或已约定，扫一眼即可，能补答案的写在备注里'
    : '有未解答项，先看状态再补答案';
  const introFirst = `审的是 ${spec.cases.length} 条用例的逻辑：步骤写得对不对、预期全不全、有没有漏的。存疑清单是附录，只列「用例没说清楚的地方」，不用逐条审——顺手扫一眼，能补答案的在标记里写一句就行。`;
  const introRest = spec.introBlocks.map(b => `    <p>${inlineMd(b)}</p>`).join('\n');
  const precond = spec.commonPrecond.length
    ? `    <details class="precond">
      <summary>公共前置条件（${spec.cases.length} 条用例共用，点开看）</summary>
      <ul>
${spec.commonPrecond.map(x => `        <li>${inlineMd(x)}</li>`).join('\n')}
      </ul>
    </details>`
    : '';
  const js = PAGE_JS.split('__FIRST_CASE__').join(firstCase).split('__DOWNLOAD_NAME__').join(downloadName);
  const footerTail = spec.tail ? inlineMd(spec.tail) : '';
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="color-scheme" content="light dark" />
<link rel="icon" href="data:," />
<title>v1 审阅页</title>
<style>${CSS}</style>
</head>
<body>

<header class="topbar">
  <div class="topbar-in">
    <div class="top-row">
      <div class="top-title">
        <h1>${inlineMd(h1)}</h1>
        <p>逐条看步骤和预期对不对、有没有漏。每条点一个标记；点「有问题 / 待定」可以写一句备注。</p>
        <div class="counts" aria-live="polite">
          <span class="chip">共 <b id="cTotal">${total}</b> 条</span>
          <span class="chip">已审 <b id="cDone">0</b></span>
          <span class="chip pass">通过 <b id="cPass">0</b></span>
          <span class="chip issue">有问题 <b id="cIssue">0</b></span>
          <span class="chip pending">待定 <b id="cPending">0</b></span>
          <span class="chip">未审 <b id="cTodo">${total}</b></span>
        </div>
        <div class="progress" role="progressbar" aria-label="审阅进度" aria-valuemin="0" aria-valuemax="${total}" aria-valuenow="0" id="progressBar">
          <i class="seg-pass" id="segPass"></i><i class="seg-issue" id="segIssue"></i><i class="seg-pending" id="segPending"></i>
        </div>
        <div class="progress-label" id="progressLabel">还没开始审，从 ${escapeHtml(firstCase)} 第一步往下看就行。</div>
      </div>
      <div class="top-actions">
        <button class="btn primary" id="btnExportTop" type="button">导出审阅结果</button>
        <button class="btn" id="btnReset" type="button">清空标记</button>
      </div>
    </div>
    <div class="filters" role="group" aria-label="筛选">
      <button class="fbtn" type="button" data-filter="all" aria-pressed="true">全部</button>
      <button class="fbtn" type="button" data-filter="todo" aria-pressed="false">只看未审</button>
      <button class="fbtn" type="button" data-filter="issue" aria-pressed="false">只看有问题</button>
      <button class="fbtn" type="button" data-filter="pending" aria-pressed="false">只看待定</button>
      <button class="fbtn" type="button" data-filter="pass" aria-pressed="false">只看通过</button>
    </div>
    <div class="save-note">标记只在本次打开期间保留，审完点「导出审阅结果」复制发回即可。</div>
  </div>
</header>

<main>
  <section class="intro" aria-label="审阅说明">
    <h2>审什么</h2>
    <p>${introFirst}</p>
${introRest}
    <p class="src">页面内容与人审版 v1（${escapeHtml(specBase)}）及存疑清单 v1（${escapeHtml(doubtsBase)}）原文一致，只改呈现方式。</p>
${precond}
  </section>

  <div class="section-head"><h2>用例审阅</h2><span>${escapeHtml(firstCase)} ～ ${escapeHtml(lastCase)} · 共 ${totalSteps} 个步骤，逐步标记</span></div>
  <div class="empty" id="emptyCases">当前筛选下没有步骤。换个筛选看看。</div>

${spec.cases.map(caseHtml).join('\n\n')}

  <div class="section-head"><h2>存疑清单</h2><span>${escapeHtml(firstQ)} ～ ${escapeHtml(lastQ)} · ${doubtsNote}</span></div>
  <div class="empty" id="emptyDoubts">当前筛选下没有存疑条目。换个筛选看看。</div>

${doubts.map(doubtHtml).join('\n\n')}

  <section class="export-panel" id="exportPanel" aria-label="导出审阅结果">
    <h2>导出审阅结果</h2>
    <p>下面这份清单会随你的标记实时更新。审完点「复制结果」，粘贴发回聊天里，就能按清单改 v1。</p>
    <textarea id="exportText" readonly aria-label="审阅结果清单"></textarea>
    <div class="export-actions">
      <button class="btn primary" id="btnCopy" type="button">复制结果</button>
      <button class="btn" id="btnDownload" type="button">下载为 .md 文件</button>
    </div>
  </section>
</main>

<footer>内容来源：人审版 v1（${escapeHtml(specBase)}）与存疑清单 v1（${escapeHtml(doubtsBase)}），原文呈现，未改动逻辑。${footerTail}</footer>
<div class="toast" id="toast" role="status"></div>

<script>${js}</script>
</body>
</html>
`;
}

// ---------- main ----------
function main() {
  const args = parseArgs(process.argv.slice(2));
  const specText = readFileOrFail(args.spec, '人审版 v1');
  const doubtsText = readFileOrFail(args.doubts, '存疑清单 v1');
  const spec = parseSpec(specText);
  const doubts = parseDoubts(doubtsText);
  const html = buildHtml(spec, doubts, path.basename(args.spec), path.basename(args.doubts),
    path.basename(args.out));
  fs.mkdirSync(path.dirname(path.resolve(args.out)), { recursive: true });
  fs.writeFileSync(args.out, html, 'utf8');
  const totalSteps = spec.cases.reduce((n, c) => n + c.steps.length, 0);
  console.log(JSON.stringify({
    out: args.out, cases: spec.cases.length, steps: totalSteps,
    doubts: doubts.length, total: totalSteps + doubts.length,
  }));
}

try { main(); }
catch (e) {
  if (process.exitCode !== 1) { console.error('生成审阅页失败：' + e.message); console.error(USAGE); }
  process.exitCode = 1;
}
