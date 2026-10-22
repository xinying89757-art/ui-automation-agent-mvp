// Copy this file with request.json. Node 18+, built-ins only. No authenticated state.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
const directory = path.dirname(fileURLToPath(import.meta.url));
export function evaluate(body, condition) {
  if (condition.op === 'contains') return body.includes(condition.value);
  if (condition.op === 'equals') return body === condition.value;
  if (condition.op === 'ordered_pairs') {
    const heading = String(condition.section).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const section = body.split(new RegExp('^##\\s+' + heading + '\\s*$', 'mi'))[1]?.split(/^##\s/m)[0];
    if (section === undefined) return false;
    const lines = section.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    return JSON.stringify(lines) === JSON.stringify(condition.value.flatMap(pair => pair));
  }
  throw new Error('Unsupported condition');
}
export async function checkOne(check, fetcher = fetch, clock = () => Date.now()) {
  const checked_at = new Date(clock()).toISOString();
  const row = { id: check.id, checked_at, status: 'unreachable', http_status: null, conditions: [], reason: 'network' };
  try {
    const url = new URL(check.url);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search) throw new Error('Unsafe URL');
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
