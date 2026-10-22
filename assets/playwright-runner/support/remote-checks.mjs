import fs from 'node:fs';
import path from 'node:path';
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
export function trackSave(page, ctx, rule) {
  const listener = response => {
    if (new URL(response.url()).pathname === rule.path && response.request().method() === rule.method && response.ok()) ctx.savedAt = new Date().toISOString();
  };
  page.on('response', listener);
  return { dispose: async () => page.off('response', listener) };
}
