// Copy this file with request.json. Node 18+, built-ins only. No authenticated state.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
const directory = path.dirname(fileURLToPath(import.meta.url));
function sectionFor(body, wanted) {
  const lines = body.split(/\r?\n/); let start = -1, level = 0;
  for (let i = 0; i < lines.length; i++) {
    const match = /^(#{2,6})\s+(.+?)\s*#*\s*$/.exec(lines[i]);
    if (match && match[2].trim().toLowerCase() === String(wanted).trim().toLowerCase()) { start = i; level = match[1].length; break; }
  }
  if (start < 0) return null;
  let end = lines.length;
  for (let i = start + 1; i < lines.length; i++) {
    const match = /^(#{1,6})\s+/.exec(lines[i]);
    if (match && match[1].length <= level) { end = i; break; }
  }
  return { text: lines.slice(start, end).join('\n'), content: lines.slice(start + 1, end) };
}
function stripDecoration(line) {
  return line.trim().replace(/^(?:[-*+]\s+|\d+\.\s+)/, '').trim()
    .replace(/\*\*|__/g, '').replace(/(^|\s)\*([^*]+)\*/g, '$1$2').trim();
}
function parsePairs(lines) {
  const pairs = []; let question = null;
  const qmark = /^(?:Q\s*[:：]\s*|问\s*[:：]\s*)/i, amark = /^(?:A\s*[:：]\s*|答\s*[:：]\s*)/i;
  for (const raw of lines) {
    let line = stripDecoration(raw); if (!line) continue;
    const q = qmark.exec(line), a = amark.exec(line);
    const combined = /^(?:Q\s*[:：]\s*|问\s*[:：]\s*)([\s\S]*?)(?:\s+)(?:A\s*[:：]\s*|答\s*[:：]\s*)([\s\S]*)$/i.exec(line);
    if (combined) { pairs.push([combined[1].trim(), combined[2].trim()]); question = null; continue; }
    if (q) { question = line.slice(q[0].length).trim(); continue; }
    if (a && question !== null) { pairs.push([question, line.slice(a[0].length).trim()]); question = null; continue; }
    if (question !== null) { pairs.push([question, line]); question = null; continue; }
    // Backward-compatible unmarked two-line pairs.
    question = line;
  }
  return question === null ? pairs : [...pairs, [question, null]];
}
export function evaluate(body, condition) {
  if (condition.op === 'contains') return body.includes(condition.value);
  if (condition.op === 'equals') return body === condition.value;
  if (condition.op === 'ordered_pairs') {
    const section = sectionFor(body, condition.section);
    if (!section) return false;
    return JSON.stringify(parsePairs(section.content)) === JSON.stringify(condition.value);
  }
  throw new Error('Unsupported condition');
}
const redactEvidence = text => String(text).replace(/eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g, '[REDACTED]')
  .replace(/\bbearer\s+[^&\s"']+/gi, 'Bearer [REDACTED]')
  .replace(/(authorization|token|access_token|password)=([^&\s"']+)/gi, '$1=[REDACTED]')
  .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '[email]')
  .replace(/(PIN码[:：]\s*)\S+/g, '$1[REDACTED]').replace(/tel:\+?[\d-]{6,}/gi, 'tel:[REDACTED]')
  .replace(/(?<!\d)1[3-9]\d{9}(?!\d)/g, '[phone]').replace(/(uin=)\d+/gi, '$1[REDACTED]')
  .replace(/(\[QQ\]\([^)]*\)):\s*\d+/g, '$1').replace(/\x1b\[[0-9;]*m/g, '')
  .replace(/\d{7,}/g, '[REDACTED]');
function evidenceFor(body, condition) {
  let excerpt;
  if (condition.op === 'ordered_pairs') excerpt = sectionFor(body, condition.section)?.text ?? body.slice(0, 400);
  else if (condition.op === 'equals') excerpt = body.slice(0, 400);
  else { const i = body.indexOf(condition.value); excerpt = i < 0 ? body.slice(0, 400) : body.slice(Math.max(0, i - 200), Math.min(body.length, i + String(condition.value).length + 200)); }
  excerpt = redactEvidence(excerpt).slice(0, 2000);
  return { section_sha256: createHash('sha256').update(excerpt).digest('hex'), excerpt };
}
export async function checkOne(check, fetcher = fetch, clock = () => Date.now()) {
  const checked_at = new Date(clock()).toISOString();
  const row = { id: check.id, checked_at, status: 'unreachable', http_status: null, conditions: [], reason: 'network', variant: check.cache_bust ? 'cache_busted' : 'default' };
  try {
    const url = new URL(check.url);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search) throw new Error('Unsafe URL');
    if (check.cache_bust) url.searchParams.set('uia_cb', String(clock()) + '-' + encodeURIComponent(check.id));
    const response = await fetcher(url, { method: check.method, credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(check.timeout_ms) });
    row.http_status = response.status;
    // Bounded stream; never save/print response text or headers.
    let body = '', size = 0;
    const decoder = new TextDecoder();
    for await (const chunk of response.body) {
      size += chunk.length;
      if (size > 1024 * 1024) throw new Error('Oversized public file');
      body += decoder.decode(chunk, { stream: true });
    }
    body += decoder.decode();
    row.conditions = check.conditions.map(c => evaluate(body, c));
    row.evidence = check.conditions.map(c => evidenceFor(body, c));
    if (clock() > Date.parse(check.deadline)) row.reason = 'deadline';
    else if (check.restored_at && Date.parse(checked_at) >= Date.parse(check.restored_at)) row.reason = 'data_restored';
    else if (check.max_latency_seconds && Date.parse(checked_at) - Date.parse(check.saved_at) > check.max_latency_seconds * 1000) row.reason = 'immediate_timing_unverified';
    else if (response.ok && row.conditions.every(Boolean)) { row.status = 'pass'; row.reason = 'conditions_met'; }
    else if (Date.parse(checked_at) < Date.parse(check.earliest_check_at) && (response.ok || response.status === 404)) { row.status = 'still-cached'; row.reason = 'cache_window'; }
    else if (response.status >= 500 || response.status === 401 || response.status === 403) row.reason = 'http_unavailable';
    else { row.status = 'fail'; row.reason = 'conditions_mismatch'; }
  } catch { /* No transport errors, URLs, headers or bodies in the output. */ }
  return row;
}
export async function main(dir = directory) {
  const bytes = fs.readFileSync(path.join(dir, 'request.json'));
  const request = JSON.parse(bytes);
  if (request.schema_version !== 'uia-remote-request.v1') throw new Error('Unsupported request');
  const results = [];
  for (const check of request.checks) results.push(await checkOne(check));
  const output = { schema_version: 'uia-remote-results.v1', run_id: request.run_id,
    request_sha256: createHash('sha256').update(bytes).digest('hex'), results };
  fs.writeFileSync(path.join(dir, 'results.json.tmp'), JSON.stringify(output, null, 2) + '\n');
  fs.renameSync(path.join(dir, 'results.json.tmp'), path.join(dir, 'results.json'));
  console.log(JSON.stringify({ statuses: results.map(r => ({ id: r.id, status: r.status, reason: r.reason })) }));
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
