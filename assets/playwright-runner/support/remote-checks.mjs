import fs from 'node:fs';
import path from 'node:path';
import { scrubText } from './redact.mjs';
function resolveFixture(state, value) {
  if (typeof value !== 'string' || !value.startsWith('$fixture.')) return value;
  const resolved = value.slice(9).split('.').reduce((node, key) => node?.[key], state);
  if (resolved === undefined) throw new Error('Unresolved fixture value');
  return resolved;
}
export function deferPublic(ctx, assertion, resource, conditions) {
  const url = new URL(resource.path, ctx.targets.public);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search) throw new Error('Unsafe public resource');
  const row = { assertion_id: assertion.id, expected: assertion.excel, url: url.href, method: 'GET',
    saved_at: ctx.savedAt ?? new Date().toISOString(), conditions: conditions.map(c => ({...c,
      value: resolveFixture(ctx.fixtureState, c.value) })),
    ...(ctx.readBack ? {read_back: ctx.readBack} : {}),
    ...(resource.max_latency_seconds ? {max_latency_seconds: resource.max_latency_seconds} : {}) };
  const file = path.join(process.env.UIA_RESULTS_DIR, 'remote-' + ctx.caseId + '.json');
  const all = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file,'utf8')) : [];
  all.push(row); fs.writeFileSync(file, JSON.stringify(all, null, 2));
}
export function markRestored(ctx) {
  const file = path.join(process.env.UIA_RESULTS_DIR ?? '', 'remote-' + ctx.caseId + '.json');
  if (!fs.existsSync(file)) return;
  const rows = JSON.parse(fs.readFileSync(file, 'utf8'));
  for (const row of rows) row.restored_at = new Date().toISOString();
  fs.writeFileSync(file, JSON.stringify(rows, null, 2));
}
const DEFAULT_OK_CODES = [0, 200, '0', '200', 'success', 'ok', true];
const codeKey = value => String(value).trim().toLowerCase();
export function businessSaveResult(httpOk, body, okCodes = DEFAULT_OK_CODES) {
  okCodes = okCodes ?? DEFAULT_OK_CODES;
  let businessCode = null, businessOk = Boolean(httpOk);
  if (body && typeof body === 'object' && !Array.isArray(body)) {
    const keys = ['code', 'status', 'errcode'].filter(k => Object.hasOwn(body, k));
    if (keys.length) businessCode = scrubText(keys.map(k => `${k}:${String(body[k])}`).join(',')).slice(0, 48);
    if (Object.hasOwn(body, 'success')) {
      const value = body.success;
      if (value === false || value === 0 || value === null || value === '' ||
          typeof value === 'string' && ['0', 'false', 'no'].includes(value.trim().toLowerCase())) businessOk = false;
    }
    if (keys.some(key => !okCodes.some(code => codeKey(code) === codeKey(body[key])))) businessOk = false;
  }
  return { businessCode, businessOk };
}
export function persistedResult(save, intended, actual) {
  return Boolean(save?.business_ok) && String(actual) === String(intended);
}
export async function readFieldValue(locator) {
  return locator.evaluate(element => 'value' in element ? element.value : element.textContent ?? '');
}
export function trackSave(page, ctx, rule) {
  ctx.saves ??= [];
  ctx.saveTasks ??= [];
  ctx.trackedSavePaths ??= new Set();
  ctx.trackedSavePaths.add(rule.path);
  const listener = response => {
    if (new URL(response.url()).pathname !== rule.path || response.request().method() !== rule.method) return;
    const task = (async () => {
      const at = new Date().toISOString();
      let body = null;
      try {
        body = await response.json();
      } catch { /* Non-JSON saves use the HTTP result only. */ }
      const { businessCode, businessOk } = businessSaveResult(response.ok(), body, rule.ok_codes);
      const row = { path: rule.path, http_status: response.status(), business_code: businessCode,
        business_ok: businessOk, at };
      ctx.saves.push(row);
      if (process.env.UIA_RESULTS_DIR) {
        fs.writeFileSync(path.join(process.env.UIA_RESULTS_DIR, 'save-observations-' + ctx.caseId + '.json'), JSON.stringify(ctx.saves, null, 2));
      }
      if (businessOk) ctx.savedAt = at;
      return row;
    })();
    ctx.saveTasks.push(task);
  };
  page.on('response', listener);
  return { dispose: async () => page.off('response', listener) };
}

export async function assertSaveBusinessOk(ctx) {
  await Promise.all(ctx.saveTasks ?? []);
  const rows = ctx.saves ?? [];
  for (const path of ctx.trackedSavePaths ?? []) {
    const matching = rows.filter(row => row.path === path);
    if (!matching.length || matching.some(row => !row.business_ok)) {
      throw new Error('UIA_SAVE_NOT_PERSISTED: tracked save response was not business-successful');
    }
  }
}

export async function verifyPersisted(page, ctx, declaration, rule, readValue) {
  await Promise.all(ctx.saveTasks ?? []);
  const save = [...(ctx.saves ?? [])].reverse().find(row => row.path === rule.path);
  const actual = await readValue();
  const intended = resolveFixture(ctx.fixtureState, declaration.value);
  const ok = persistedResult(save, intended, actual);
  const reason = ok ? null : !save ? 'save_not_observed' : !save.business_ok ? 'save_business_failed' : 'read_back_mismatch';
  const evidence = { assertion_id: declaration.id, target: declaration.target,
    intended: scrubText(intended).slice(0, 200), actual: scrubText(actual).slice(0, 200), ok, method: 'ui',
    ...(save ? {business_code: save.business_code, business_ok: save.business_ok} : {}), ...(reason ? {reason} : {}) };
  ctx.readBack = evidence;
  const file = path.join(process.env.UIA_RESULTS_DIR, 'read-back-' + ctx.caseId + '.json');
  fs.writeFileSync(file, JSON.stringify(evidence, null, 2));
  if (!ok) throw new Error('UIA_SAVE_NOT_PERSISTED: ' + reason);
}
