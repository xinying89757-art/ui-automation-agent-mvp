/** Shared named navigation for generated tests and bounded exploration. */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { runtimeRoot, loadConfig } from './environment.mjs';
import { openLlms, openSettings } from '../flows/llms-txt.mjs';
// Reuse the YAML parser shipped with the locked Playwright runtime.
const require = createRequire(import.meta.url);
const { yaml } = require(path.join(path.dirname(require.resolve('playwright-core/package.json')), 'lib/utilsBundle.js'));
export const pageMap = () => yaml.parse(fs.readFileSync(path.join(runtimeRoot, 'knowledge/page-map.yaml'), 'utf8'));
export const urlPath = value => { try { return new URL(value, 'https://snapshot.invalid').pathname; } catch { return null; } };
export function allowedURL(value, cfg) {
  const env = cfg.environment ?? {};
  const base = env.entry_url ?? cfg.targets?.admin;
  const url = new URL(value, base);
  const origins = [base, env.login_url, env.cloud_url, ...(env.allowed_hosts ?? [])].filter(Boolean)
    .map(host => new URL(host.includes('://') ? host : `${new URL(base).protocol}//${host}`).origin);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || !origins.includes(url.origin))
    throw new Error('Navigation origin is not allowed by the configured environment');
  return url.href;
}
export function targetLocator(page, target, { frame, scope, map = pageMap() } = {}) {
  const entry = map.targets?.[target];
  let root = (entry?.frame ?? frame) ? page.frameLocator(entry?.frame ?? frame) : page;
  for (const nested of entry?.nested_frames ?? []) root = root.frameLocator(nested);
  if (entry?.scope ?? scope) root = root.locator(entry?.scope ?? scope);
  if (entry?.selector) return root.locator(entry.selector).filter({ visible: true }).first();
  if (entry?.role) return root.getByRole(entry.role, { name: entry.name, exact: true }).filter({ visible: true }).first();
  if (target.startsWith('text=')) return root.getByText(target.slice(5), { exact: true }).filter({ visible: true }).first();
  const role = /^role=([^\[]+)(?:\[name=(.*)\])?$/u.exec(target);
  if (role) return root.getByRole(role[1], { ...(role[2] !== undefined ? { name: role[2], exact: true } : {}) }).filter({ visible: true }).first();
  return root.locator(target).filter({ visible: true }).first();
}

async function frameDetails(frame) {
  const selector = await (await frame.frameElement()).evaluate(el => el.id ? '#' + CSS.escape(el.id) :
    el.name ? 'iframe[name=' + JSON.stringify(el.name) + ']' : 'iframe').catch(() => 'iframe');
  return { selector, name: frame.name(), path: urlPath(frame.url()) };
}

/** Semantic actions search the top document, then attached same-origin frames in DOM order. */
export async function resolveActionTarget(page, target, options = {}) {
  const role = /^role=([^\[]+)(?:\[name=(.*)\])?$/u.exec(target);
  if (options.frame || options.map?.targets?.[target] || !(target.startsWith('text=') || role))
    return { locator: targetLocator(page, target, options), frame: options.frame ? { selector: options.frame } : null };
  const text = role ? role[2] : target.slice(5);
  const roots = [{ root: page, frame: null }];
  async function visit(parent) {
    for (const frame of parent.childFrames()) {
      try {
        if (frame.isDetached() || !await frame.evaluate(() => { void window.top.document; return true; })) continue;
        if (!await (await frame.frameElement()).isVisible()) continue;
        roots.push({ root: frame, frame });
        await visit(frame);
      } catch { /* Cross-origin and detached frames are outside this search. */ }
    }
  }
  await visit(page.mainFrame());
  const escaped = (text ?? '').replace(/[.*+?^${}()|[\]\\]/gu, '\\$&');
  for (const mode of role ? ['exact', 'hover', 'substring'] : ['action-exact', 'action-hover', 'exact', 'hover', 'substring']) {
    if (mode === 'substring' && (!text || [...text].length > 8)) continue;
    const matches = [];
    for (const item of roots) {
      const root = options.scope ? item.root.locator(options.scope) : item.root;
      const name = mode === 'substring' ? new RegExp(escaped, 'iu') : text;
      const hover = mode.endsWith('hover');
      const groups = mode.startsWith('action-') ? [...['link', 'button'].map(kind => root.getByRole(kind, { name, exact: true, includeHidden: hover })),
        root.getByTitle(name, { exact: true }), root.getByText(name, { exact: true })] :
        [role ? root.getByRole(role[1], { ...(name !== undefined ? { name, exact: mode !== 'substring' } : {}), includeHidden: hover }) :
          root.getByText(name, { exact: mode !== 'substring' })];
      for (const candidates of groups) for (let index = 0; index < await candidates.count(); index++) {
        const locator = candidates.nth(index);
        if (mode.startsWith('action-') && !await locator.evaluate(el => Boolean(el.closest('a,button,[role="link"],[role="button"]')))) continue;
        if (hover && !await locator.isVisible()) {
          const row = locator.locator('xpath=ancestor::*[self::tr or self::li or @role="row"][1]');
          if (await row.isVisible()) await row.hover({ timeout: 1000 });
        }
        if (!await locator.isVisible()) continue;
        const matched = { locator, frame: item.frame ? await frameDetails(item.frame) : null };
        if (mode !== 'substring') return matched;
        const preferred = await locator.evaluate(el => Boolean(el.closest('a,button,[role="link"],[role="button"]')));
        matches.push({ ...matched, preferred });
      }
    }
    if (matches.length) return matches.find(x => x.preferred) ?? matches[0];
  }
  return null;
}
export async function openTarget(page, target, options = {}, seen = new Set()) {
  if (seen.has(target)) throw new Error('Cyclic named route');
  seen.add(target);
  if (target === 'settings') { await openSettings(page); return page; }
  if (target === 'llms') { await openLlms(page); return page; }
  const map = options.map ?? pageMap();
  const entry = map.targets?.[target] ?? map.pages?.[target];
  if (!entry) throw new Error('UIA_EXPLORATION_REQUIRED: unknown named target');
  const cfg = options.cfg ?? loadConfig();
  if (entry.entry) {
    const { openSiteArea } = await import('./auth.mjs');
    return openSiteArea(page, cfg, entry.entry);
  }
  if (entry.url ?? entry.path) {
    await page.goto(allowedURL(entry.url ?? entry.path, cfg), { timeout: 10000, waitUntil: 'domcontentloaded' });
    return page;
  }
  if (entry.route) {
    const reached = await navigateSnapshot(page, cfg, { ...options, steps: entry.route });
    if (reached.failed_step) throw new Error('Named route action failed');
    return reached.page;
  }
  if (entry.open && entry.open !== target) return openTarget(page, entry.open, options, seen);
  else await targetLocator(page, target, { ...options, map }).click({ timeout: 10000 });
  return page;
}
export function parseStep(action) {
  const match = /^(click|hover|fill|press|wait):(.*)$/su.exec(action);
  if (!match) throw new Error('Expected click/hover/fill/press/wait step');
  const [, verb, value] = match;
  if (verb === 'wait' && (!/^\d+$/u.test(value) || Number(value) > 10000)) throw new Error('wait must be 0..10000 ms');
  if (verb === 'fill') {
    let split = -1, depth = 0, quote = null;
    for (let i = /^(text|role)=/u.test(value) ? 5 : 0; i < value.length; i++) {
      const char = value[i];
      if (quote) { if (char === quote && value[i - 1] !== '\\') quote = null; }
      else if (char === '"' || char === "'") quote = char;
      else if (char === '[' || char === '(') depth++;
      else if (char === ']' || char === ')') depth--;
      else if (char === '=' && depth === 0) { split = i; break; }
    }
    if (split < 1) throw new Error('fill requires target=value');
    return { verb, target: value.slice(0, split), value: value.slice(split + 1) };
  }
  return { verb, target: value, value };
}
export async function navigateSnapshot(page, cfg, { goto, openTarget: named, steps = [], clicks = [], hover, entrySteps = 0, ...options } = {}) {
  const actions = [...(goto ? [['goto', goto]] : []), ...(named ? [['open', named]] : []),
    ...clicks.map(x => ['legacy', 'click:' + x]), ...(hover ? [['legacy', 'hover:' + hover]] : []), ...steps.map(x => ['step', x])];
  const popups = [];
  const results = [];
  let failed_step = null;
  for (const [index, [kind, action]] of actions.entries()) {
    const opened = [];
    const context = page.context();
    const onPage = next => opened.push(next);
    context.on('page', onPage);
    let timer;
    const budget = kind === 'open' ? 60000 : 10000;
    try {
      await Promise.race([(async () => {
        if (kind === 'goto') await page.goto(allowedURL(action, cfg), { timeout: 10000, waitUntil: 'domcontentloaded' });
        else if (kind === 'open') {
          const destination = await openTarget(page, action, { ...options, cfg });
          if (destination?.context) page = destination;
        } else {
          const step = parseStep(action);
          if (step.verb === 'wait') await page.waitForTimeout(Number(step.value));
          else if (step.verb === 'press') await page.keyboard.press(step.value);
          else {
            const actionOptions = index < entrySteps ? { ...options, frame: undefined, scope: undefined } : options;
            if (step.verb === 'click' && (actionOptions.map ?? pageMap()).pages?.[step.target]) {
              page = await openTarget(page, step.target, { ...actionOptions, cfg });
            } else {
              let matched = kind === 'legacy' ? { locator: page.locator(step.target), frame: null } : null;
              const deadline = Date.now() + 8000;
              while (!matched) {
                matched = await resolveActionTarget(page, step.target, actionOptions);
                if (!matched && Date.now() >= deadline) throw new Error('No visible target');
                if (!matched) await new Promise(resolve => setTimeout(resolve, 150));
              }
              await matched.locator[step.verb](...(step.verb === 'fill' ? [step.value] : []), { timeout: 10000 });
              results.push({ index: index + 1, frame: matched.frame });
            }
          }
        }
        // Popup creation can be delivered just after the initiating click resolves.
        if (kind === 'open' || ['step', 'legacy'].includes(kind) && /^(click|press):/u.test(action))
          await new Promise(resolve => setTimeout(resolve, 250));
        // A popup can begin at about:blank before receiving its destination.
        if (opened.length) {
          page = opened.at(-1);
          await page.waitForLoadState('domcontentloaded', { timeout: 10000 }).catch(() => {});
        }
      })(), new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Navigation budget exceeded')), budget); })]);
    } catch (error) {
      // Do not echo Playwright call logs, which may contain filled values or URLs.
      failed_step = { index: index + 1, action: kind === 'step' && action.startsWith('fill:') ? 'fill:[REDACTED]' : kind === 'goto' ? 'goto:' + urlPath(action) : action,
        reason: /origin|wait must|requires|Expected|Cyclic|unknown named/u.test(error.message) ? error.message :
          /intercepts pointer events/u.test(error.message) ? 'Target is covered by another element' :
          /not enabled/u.test(error.message) ? 'Target is disabled' : `Navigation/action failed or exceeded ${budget} ms` };
    } finally {
      clearTimeout(timer);
      context.off('page', onPage);
      for (const popup of opened) popups.push({ path: urlPath(popup.url()) });
      if (opened.length) page = opened.at(-1);
    }
    if (failed_step) break;
  }
  return { page, failed_step, popups, steps: results };
}
