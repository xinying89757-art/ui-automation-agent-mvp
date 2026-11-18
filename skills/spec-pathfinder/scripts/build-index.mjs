#!/usr/bin/env node
// 无依赖的候选证据索引器。正则/词法扫描不等于 Java AST 或模板运行结果。
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const VERSION = 1;
const SKIP = new Set(['.git', 'node_modules', 'target', 'dist', 'build', '.idea', '.cache']);
const slash = p => p.split(path.sep).join('/');
const lineAt = (s, p) => s.slice(0, p).split('\n').length;
const blank = s => s.replace(/[^\r\n]/g, ' ');
const quotes = s => [...s.matchAll(/"((?:\\.|[^"\\])*)"/g)].map(m => m[1]);

// 保留偏移与行号；maskStrings=true 时括号扫描不会受字符串中的括号干扰。
function mask(s, maskStrings = false) {
  return s.replace(/\/\*[\s\S]*?\*\/|\/\/[^\r\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/g,
    x => x.startsWith('/') || maskStrings ? blank(x) : x);
}
function matching(s, start, open, close) {
  let depth = 0;
  for (let i = start; i < s.length; i++) {
    if (s[i] === open) depth++;
    if (s[i] === close && --depth === 0) return i;
    // 仅在 close 处递减；上面的短路表达式保证这一点。
  }
  return -1;
}
function evidence(file, source, start, end = start) {
  return { file, line: lineAt(source, start), endLine: lineAt(source, end) };
}
function signals(source, code, from, to, file) {
  const out = [];
  const patterns = [
    ['status', /\.put\s*\(\s*"status"\s*,\s*"success"\s*\)/g],
    ['status-check', /\bresponse\.status\s*={2,3}\s*['"]success['"]/g],
    ['toast-candidate', /\b(?:showToast|toast)\s*\(/g],
    ['redirect', /\breturn\s+"redirect:[^"]*"/g],
    ['success-helper-call', /\bsuccessBody\s*\(/g],
    ['dialog-close-candidate', /\b(?:close\s*\(\s*\)|dialog\.close\s*\()/g]
  ];
  const part = code.slice(from, to);
  for (const [kind, re] of patterns) for (const m of part.matchAll(re)) {
    const pos = from + m.index;
    const lines = source.split('\n'), line = lineAt(source, pos);
    out.push({ kind, ...evidence(file, source, pos),
      excerpt: lines.slice(line - 1, kind === 'toast-candidate' ? Math.min(line + 3, lineAt(source, to)) : line).map(x => x.trim()).join('\n'),
      interpretation: '候选信号，必须读上下文确认分支及含义' });
  }
  return out.sort((a, b) => a.line - b.line || a.kind.localeCompare(b.kind));
}

function parseJava(source, file) {
  const code = mask(source), syntax = mask(source, true);
  const routes = [], actions = [], warnings = [];
  const cls = /\bclass\s+(\w+)/.exec(syntax);
  if (!cls) return { routes, actions, elements: [], warnings: ['未识别 Controller 类声明'] };
  const constants = new Map([...code.matchAll(/\b(?:static\s+final|final\s+static)\s+String\s+(\w+)\s*=\s*"([^"\n]*)"\s*;/g)]
    .map(m => [m[1], { value: m[2], ...evidence(file, source, m.index) }]));
  const annotations = [];
  const re = /@(RequestMapping|GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping)\b/g;
  for (const m of syntax.matchAll(re)) {
    let start = m.index + m[0].length;
    while (/\s/.test(syntax[start] ?? '') && start < syntax.length) start++;
    let end = start, args = '';
    if (syntax[start] === '(') {
      const close = matching(syntax, start, '(', ')');
      if (close < 0) { warnings.push(`第 ${lineAt(source, start)} 行注解括号不完整`); continue; }
      args = code.slice(start + 1, close); end = close + 1;
    }
    const pathArg = /\b(?:value|path)\s*=\s*(\{[^}]*\}|"(?:\\.|[^"\\])*")/.exec(args) ?? /^\s*(\{[^}]*\}|"(?:\\.|[^"\\])*")/.exec(args);
    const rawPath = pathArg?.[1];
    let paths = rawPath ? quotes(rawPath) : [''];
    const literalTail = pathArg ? args.slice(pathArg.index + pathArg[0].length).trimStart() : '';
    const mixedArray = rawPath?.startsWith('{') && rawPath.replace(/"(?:\\.|[^"\\])*"/g, '').replace(/[{},\s]/g, '') !== '';
    const unresolved = (rawPath && (mixedArray || (literalTail && !literalTail.startsWith(',')))) ||
      (!rawPath && args.trim() && (/\b(?:value|path)\s*=/.test(args) || !/^\s*(?:method|produces|consumes|params|headers)\s*=/.test(args)));
    if (unresolved) { paths = [null]; warnings.push(`第 ${lineAt(source, m.index)} 行路由表达式未解析：${args.trim()}`); }
    const methods = m[1] === 'RequestMapping'
      ? [...args.matchAll(/RequestMethod\.(\w+)/g)].map(x => x[1])
      : [m[1].replace('Mapping', '').toUpperCase()];
    annotations.push({ name: m[1], start: m.index, end, paths, methods });
  }
  const base = annotations.filter(a => a.start < cls.index).at(-1) ?? { paths: [''], methods: [] };
  const methods = annotations.filter(a => a.start > cls.index);
  for (const a of methods) {
    const boundary = syntax.indexOf('{', a.end);
    const nextAnnotation = methods.find(x => x.start > a.start)?.start ?? syntax.length;
    if (boundary < 0 || boundary > nextAnnotation) { warnings.push(`第 ${lineAt(source, a.start)} 行未识别方法体`); continue; }
    const header = syntax.slice(a.end, boundary);
    // 取紧邻方法体的声明，避免 @RequestParam 的参数被当成方法。
    const signature = /\b(?:public|protected|private)\s+(?:(?:static|final|synchronized)\s+)*([\w.$<>?,\s\[\]]+?)\s+(\w+)\s*\(/.exec(header);
    if (!signature) { warnings.push(`第 ${lineAt(source, a.start)} 行未识别方法签名`); continue; }
    const end = matching(syntax, boundary, '{', '}');
    if (end < 0) { warnings.push(`第 ${lineAt(source, boundary)} 行方法体不完整`); continue; }
    const returnType = signature[1].trim().replace(/\s+/g, ' ');
    const body = code.slice(boundary + 1, end);
    const responseKind = /@RestController\b/.test(code.slice(0, cls.index)) || /@ResponseBody\b/.test(code.slice(a.end, boundary)) ||
      /@ResponseBody\s*$/.test(code.slice(Math.max(0, a.start - 100), a.start).trim())
      ? 'response-body' : /renderJson\s*\(/.test(body) ? 'render-json' : returnType === 'String' ? 'view-candidate' : 'unknown';
    const views = [];
    if (responseKind === 'view-candidate') for (const m of body.matchAll(/\breturn\s+("[^"\n]*"|[A-Z][A-Z_0-9]*)\s*;/g)) {
      const token = m[1]; const constant = constants.get(token);
      if (token.startsWith('"') || constant) views.push({ name: token.startsWith('"') ? token.slice(1, -1) : constant.value,
        ...evidence(file, source, boundary + 1 + m.index), ...(constant ? { resolvedFrom: constant } : {}) });
      else warnings.push(`第 ${lineAt(source, boundary + 1 + m.index)} 行返回常量未解析：${token}`);
    }
    const ownMethods = a.methods.length ? a.methods : base.methods.length ? base.methods : ['ANY'];
    const httpMethods = base.methods.length && a.methods.length ? a.methods.filter(m => base.methods.includes(m)) : ownMethods;
    if (!httpMethods.length) warnings.push(`第 ${lineAt(source, a.start)} 行类/方法 HTTP 条件无交集`);
    for (const prefix of base.paths) for (const suffix of a.paths) {
      const url = prefix === null || suffix === null ? null : ('/' + [prefix, suffix].map(p => p.replace(/^\/+|\/+$/g, '')).filter(Boolean).join('/'));
      const route = { url, httpMethods, controller: cls[1], method: signature[2], returnType, responseKind, views,
        ...evidence(file, source, a.start, end), parser: 'regex-candidate' };
      routes.push(route);
      const writeCandidate = httpMethods.some(x => ['POST', 'PUT', 'PATCH', 'DELETE'].includes(x)) || /save|delete|remove|create|update|insert|enable|disable/i.test(signature[2] + (url ?? ''));
      if (writeCandidate) {
        const found = signals(source, code, boundary + 1, end, file);
        // 有限追踪本文件 successBody；调用证据与定义证据均保留，禁止推广到所有请求分支。
        if (found.some(x => x.kind === 'success-helper-call')) {
          const helper = /\bsuccessBody\s*\(\s*\)\s*\{/.exec(syntax);
          if (helper) {
            const hb = syntax.indexOf('{', helper.index), he = matching(syntax, hb, '{', '}');
            found.push(...signals(source, code, hb + 1, he, file).map(s => ({ ...s, via: 'successBody' })));
          }
        }
        actions.push({ ...route, kind: 'backend-write-candidate', successSignals: found,
          unresolved: found.length ? [] : ['未识别成功信号，需按需读方法实现'], frontendEvidence: [] });
      }
    }
  }
  return { routes, actions, elements: [], warnings };
}

function parseTemplate(source, file) {
  // 不执行 JSP/FTL；移除注释但保持偏移，标签解析允许引号内嵌 JSP 自定义标签。
  const code = source.replace(/<%--[\s\S]*?--%>|<!--[^]*?-->|<#--[^]*?-->/g, blank)
    .replace(/<script\b[^>]*>[\s\S]*?<\/script\s*>/gi, blank);
  const tags = /<([a-zA-Z][\w:-]*)\b((?:"[^"]*"|'[^']*'|[^'">])*)>/g;
  const elements = [];
  const attrRe = /([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/g;
  for (const m of code.matchAll(tags)) {
    const tag = m[1].toLowerCase();
    if (tag.includes(':')) continue;
    const attrs = {};
    for (const a of m[2].matchAll(attrRe)) attrs[a[1].toLowerCase()] = a[2] ?? a[3] ?? a[4];
    const classes = (attrs.class ?? '').split(/\s+/).filter(Boolean);
    if (!['a', 'button', 'input', 'select', 'textarea', 'form', 'label'].includes(tag) &&
      !attrs.id && !attrs['data-testid'] && !attrs.role && !attrs['data-enabled'] && !attrs.onclick && !attrs.tabindex && !classes.some(c => /llms-(?:fields|form|banner|system-fields|custom-fields|source|extra|status|lock|save-error)/.test(c))) continue;
    const closing = code.indexOf(`</${tag}`, m.index + m[0].length);
    const inner = closing < 0 || ['input'].includes(tag) ? '' : code.slice(m.index + m[0].length, closing);
    const i18n = [...inner.matchAll(/<smartTag:message\b[^>]*?\btext=(?:"([^"]*)"|'([^']*)')[^>]*\/?\s*>/g)].map(x => x[1] ?? x[2]);
    const text = inner.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 240);
    const dynamic = /\$\{|<#|<%|<c:|<smartTag:/.test(m[0] + inner);
    const locator = attrs['data-testid'] ? { strategy: 'data-testid', value: attrs['data-testid'] } : attrs.id ? { strategy: 'id', value: attrs.id } :
      text && !dynamic ? { strategy: 'text', value: text } : classes.length ? { strategy: 'structure', value: tag + classes.map(c => '.' + c).join('') } :
      attrs.name ? { strategy: 'structure', value: `${tag}[name="${attrs.name}"]` } : null;
    elements.push({ template: file, tag, id: attrs.id ?? null, text, i18nFallbacks: i18n, name: attrs.name ?? null,
      type: attrs.type ?? null, classes, attributes: attrs, locatorCandidate: locator,
      dynamic, runtimeUniqueness: '未验证；检查条件分支、循环、隐藏副本与所在容器', ...evidence(file, source, m.index) });
  }
  return { routes: [], actions: [], elements, warnings: [] };
}

function parseJS(source, file) {
  const code = mask(source), syntax = mask(source, true), actions = [], warnings = [];
  // 仅解析字面量 API 对象，不执行 JS，不猜测字符串拼接、动态 URL 或 payload。
  const constants = new Map();
  for (const obj of syntax.matchAll(/\b(?:var|let|const)\s+(\w+)\s*=\s*\{/g)) {
    const begin = syntax.indexOf('{', obj.index), end = matching(syntax, begin, '{', '}');
    if (end < 0) continue;
    const objectBody = code.slice(begin + 1, end);
    for (const m of objectBody.matchAll(/\b(\w+)\s*:\s*(['"])(\/[^'"\n]*)\2/g)) {
      const tail = objectBody.slice(m.index + m[0].length).trimStart();
      if (tail && !tail.startsWith(',')) { warnings.push(`第 ${lineAt(source, begin + 1 + m.index)} 行动态 API 值未解析`); continue; }
      constants.set(`${obj[1]}.${m[1]}`, { url: m[3], ...evidence(file, source, begin + 1 + m.index) });
    }
  }
  for (const m of syntax.matchAll(/\bajax\s*\(\s*\{/g)) {
    const begin = syntax.indexOf('{', m.index), end = matching(syntax, begin, '{', '}');
    if (end < 0) { warnings.push(`第 ${lineAt(source, m.index)} 行 ajax 块不完整`); continue; }
    const body = code.slice(begin + 1, end);
    const raw = /\burl\s*:\s*(['"])([^'"]+)\1/.exec(body);
    const ref = /\burl\s*:\s*(\w+\.\w+)/.exec(body);
    const resolved = constants.get(ref?.[1]);
    const literalTail = raw ? body.slice(raw.index + raw[0].length).trimStart() : '';
    const refTail = ref ? body.slice(ref.index + ref[0].length).trimStart() : '';
    const dynamic = (literalTail && !literalTail.startsWith(',')) || (!raw && refTail && !refTail.startsWith(','));
    const url = dynamic ? null : raw?.[2] ?? resolved?.url ?? null;
    const method = /\btype\s*:\s*['"](\w+)['"]/.exec(body)?.[1]?.toUpperCase() ?? 'UNKNOWN';
    if (!url) warnings.push(`第 ${lineAt(source, m.index)} 行 ajax URL 未解析`);
    actions.push({ kind: 'frontend-request-candidate', url, httpMethods: [method], reference: ref?.[1] ?? null,
      ...(resolved ? { urlDefinition: resolved } : {}), ...evidence(file, source, m.index, end),
      successSignals: signals(source, code, begin + 1, end, file),
      unresolved: ['payload/DOM/国际化最终文本及回调控制流须读源代码确认'], frontendEvidence: [] });
  }
  return { routes: [], actions, elements: [], warnings };
}

async function atomicJSON(file, data) {
  const tmp = `${file}.${process.pid}.tmp`;
  try { await fs.writeFile(tmp, JSON.stringify(data, null, 2) + '\n', 'utf8'); await fs.rename(tmp, file); }
  finally { await fs.rm(tmp, { force: true }); }
}
async function main() {
  const args = process.argv.slice(2); let rootArg, outArg, force = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--help' || args[i] === '-h') {
      console.log('用法：node scripts/build-index.mjs <代码根路径> [--out <索引目录>] [--force]\n默认写入当前工作目录 index/；要求 Node.js 18+，无第三方依赖。'); return;
    }
    if (args[i] === '--force') force = true;
    else if (args[i] === '--out') { outArg = args[++i]; if (!outArg || outArg.startsWith('--')) throw new Error('--out 缺少目录'); }
    else if (!args[i].startsWith('-') && !rootArg) rootArg = args[i];
    else throw new Error(`未知参数：${args[i]}`);
  }
  if (!rootArg) throw new Error('必须传入代码根路径；运行 --help 查看用法');
  const root = await fs.realpath(path.resolve(rootArg));
  if (!(await fs.stat(root)).isDirectory()) throw new Error('代码根路径必须是目录');
  const output = path.resolve(outArg ?? 'index');
  await fs.mkdir(output, { recursive: true });
  const outReal = await fs.realpath(output);
  if (outReal === root) throw new Error('索引目录不能等于代码根路径');
  const cacheFile = path.join(output, '.cache.json');
  let old = {};
  if (!force) try {
    const candidate = JSON.parse(await fs.readFile(cacheFile, 'utf8'));
    if (candidate.version === VERSION && candidate.root === root && candidate.scriptMtimeMs === (await fs.stat(fileURLToPath(import.meta.url))).mtimeMs) old = candidate.files ?? {};
  } catch (e) { if (e.code !== 'ENOENT') console.error('缓存不可用，完整重建：' + e.message); }
  const files = {}, warnings = []; let parsed = 0, reused = 0;
  async function walk(dir) {
    for (const entry of (await fs.readdir(dir, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
      const full = path.join(dir, entry.name), rel = slash(path.relative(root, full));
      if (entry.isSymbolicLink()) { warnings.push(`${rel}：跳过符号链接`); continue; }
      if (entry.isDirectory()) {
        if (!SKIP.has(entry.name) && full !== outReal && !/tiptapEditor\/assets\/chunks(?:\/|$)/.test(rel)) await walk(full);
        else if (/tiptapEditor/.test(rel)) warnings.push(`${rel}：构建产物跳过；需历史脚本/人工补充`);
        continue;
      }
      if (!entry.isFile() || !/(?:Controller\.java|\.(?:ftl|ftlh|jsp|html|js|mjs))$/i.test(entry.name)) continue;
      const stat = await fs.stat(full, { bigint: true });
      const fingerprint = `${stat.mtimeNs}:${stat.size}`;
      if (old[rel]?.fingerprint === fingerprint) { files[rel] = old[rel]; reused++; continue; }
      const source = await fs.readFile(full, 'utf8');
      const after = await fs.stat(full, { bigint: true });
      if (`${after.mtimeNs}:${after.size}` !== fingerprint) throw new Error(`${rel} 扫描时发生变化，请重跑`);
      const result = /Controller\.java$/i.test(entry.name) ? parseJava(source, rel) : /\.(?:js|mjs)$/i.test(entry.name) ? parseJS(source, rel) : parseTemplate(source, rel);
      files[rel] = { fingerprint, ...result }; parsed++;
    }
  }
  await walk(root);
  const all = Object.values(files);
  const routes = all.flatMap(x => x.routes), elements = all.flatMap(x => x.elements);
  const actions = all.flatMap(x => x.actions).map(a => ({ ...a, frontendEvidence: [] }));
  for (const a of actions.filter(a => a.kind === 'backend-write-candidate')) {
    a.frontendEvidence = actions.filter(b => b.kind === 'frontend-request-candidate' && a.url && b.url === a.url &&
      b.httpMethods.some(m => a.httpMethods.includes(m) || a.httpMethods.includes('ANY')))
      .map(b => ({ file: b.file, line: b.line, endLine: b.endLine, successSignals: b.successSignals,
        relation: 'URL/HTTP 方法一致；候选关联，尚未验证运行时分支' }));
  }
  for (const [file, info] of Object.entries(files)) warnings.push(...info.warnings.map(w => `${file}：${w}`));
  const metadata = { version: VERSION, root, generatedAt: new Date().toISOString(),
    cache: { scanned: all.length, parsed, reused, removed: Object.keys(old).filter(k => !files[k]).length, forced: force }, warnings,
    limits: ['正则候选索引；读源代码后才能写入高置信规格', '不解析继承/自定义组合注解/跨文件常量/动态拼接/模板渲染/CSS', 'POST 只代表写操作候选（如草稿生成不一定持久化）；不推断 404 或实际部署状态'] };
  for (const [name, entries] of [['routes', routes], ['template-elements', elements], ['actions', actions]]) await atomicJSON(path.join(output, `${name}.json`), { ...metadata, entries });
  await atomicJSON(cacheFile, { version: VERSION, root, scriptMtimeMs: (await fs.stat(fileURLToPath(import.meta.url))).mtimeMs, files });
  console.log(JSON.stringify({ output, routes: routes.length, elements: elements.length, actions: actions.length, ...metadata.cache, warnings: warnings.length }));
}
main().catch(error => { console.error('建索引失败：' + error.message); process.exitCode = 1; });
