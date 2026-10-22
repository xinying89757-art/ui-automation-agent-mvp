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
function cacheBust(url, identity, clock) {
  url.searchParams.set('uia_cb', String(clock()) + '-' + encodeURIComponent(identity));
}
export async function checkOne(check, fetcher = fetch, clock = () => Date.now()) {
  const checked_at = new Date(clock()).toISOString();
  const row = { id: check.id, checked_at, status: 'unreachable', http_status: null, conditions: [], reason: 'network', variant: check.cache_bust ? 'cache_busted' : 'default' };
  try {
    const url = new URL(check.url);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search) throw new Error('Unsafe URL');
    if (check.cache_bust) cacheBust(url, check.id, clock);
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
async function boundedBody(response) {
  let body = '', size = 0;
  const decoder = new TextDecoder();
  for await (const chunk of response.body) {
    size += chunk.length;
    if (size > 1024 * 1024) throw new Error('Oversized public file');
    body += decoder.decode(chunk, { stream: true });
  }
  return body + decoder.decode();
}
export async function runWatch(request, fetcher = fetch, clock = () => Date.now(), sleeper = ms => new Promise(resolve => setTimeout(resolve, ms))) {
  const start = clock(), polls = [], offsets = [], timeline = [];
  let first_poll_at = null, last_poll_at = null, last_absent_at = null, first_present_at = null;
  let confirmed_present = false, consecutive = 0, error_count = 0, evidence = null, previous = null, max_gap_ms = 0, priorT = null;
  const stopAt = Date.parse(request.watch_until);
  while (clock() <= stopAt) {
    const before = clock();
    if (first_poll_at === null) first_poll_at = new Date(before).toISOString();
    last_poll_at = new Date(before).toISOString();
    let ok = false, present = false;
    try {
      const url = new URL(request.url);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search) throw new Error('Unsafe URL');
      cacheBust(url, request.watch_id + '-' + polls.length, () => before);
      const response = await fetcher(url, { method: 'GET', credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(request.timeout_ms) });
      const responseAt = clock();
      const body = await boundedBody(response);
      ok = response.ok;
      const outcomes = request.conditions.map(c => evaluate(body, c));
      present = ok && outcomes.length > 0 && outcomes.every(Boolean);
      const date = response.headers?.get?.('Date');
      // Date has 1 s resolution (truncated); +500 ms centres the estimate.
      if (date) { const parsed = Date.parse(date); if (Number.isFinite(parsed)) offsets.push(parsed + 500 - (before + responseAt) / 2); }
      if (present && !evidence) evidence = evidenceFor(body, request.conditions[0]);
      if (!ok) error_count++;
    } catch { error_count++; }
    const at = clock(), t_ms = Math.max(0, Math.round(at - start));
    if (priorT !== null) max_gap_ms = Math.max(max_gap_ms, t_ms - priorT);
    priorT = t_ms;
    polls.push({ t_ms, ok, present });
    const state = !ok ? 'error' : present ? 'present' : 'absent';
    if (state !== previous) { timeline.push({ t_ms, state }); previous = state; }
    const iso = new Date(at).toISOString(); last_poll_at = iso;
    // Conservative: absent is only proven up to request start; present by response end.
    if (ok && !present) last_absent_at = new Date(before).toISOString();
    if (present) { if (!first_present_at) first_present_at = iso; consecutive++; }
    else consecutive = 0;
    if (consecutive >= 3) { confirmed_present = true; break; }
    const remaining = stopAt - clock();
    if (remaining <= 0) break;
    await sleeper(Math.min(request.interval_ms, remaining));
  }
  offsets.sort((a,b)=>a-b);
  const middle = Math.floor(offsets.length / 2);
  const clock_offset_ms = offsets.length ? Math.round(offsets.length % 2 ? offsets[middle] : (offsets[middle - 1] + offsets[middle]) / 2) : null;
  return { schema_version: 'uia-remote-watch-results.v1', run_id: request.run_id, watch_id: request.watch_id,
    request_sha256: request.request_sha256, first_poll_at, last_poll_at, poll_count: polls.length, error_count,
    max_gap_ms, baseline_absent: polls.some(p => p.ok) && !polls.find(p => p.ok).present,
    last_absent_at, first_present_at, confirmed_present, clock_offset_ms, evidence, timeline, polls };
}
export async function main(dir = directory) {
  const bytes = fs.readFileSync(path.join(dir, 'request.json'));
  const request = JSON.parse(bytes);
  if (request.schema_version === 'uia-remote-watch.v1') {
    request.request_sha256 = createHash('sha256').update(bytes).digest('hex');
    const output = await runWatch(request);
    fs.writeFileSync(path.join(dir, 'watch-results.json.tmp'), JSON.stringify(output, null, 2) + '\n');
    fs.renameSync(path.join(dir, 'watch-results.json.tmp'), path.join(dir, 'watch-results.json'));
    console.log(JSON.stringify({ watch_id: output.watch_id, poll_count: output.poll_count, confirmed_present: output.confirmed_present }));
    return;
  }
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
