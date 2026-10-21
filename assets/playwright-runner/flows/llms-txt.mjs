import fs from 'node:fs';
import path from 'node:path';
import { loadConfig, runtimeRoot } from '../support/environment.mjs';
import { bestCandidate } from '../support/heal.mjs';

const memoryPath = () => path.join(runtimeRoot, 'knowledge/llms-txt.json');
export function memory() {
  return JSON.parse(fs.readFileSync(memoryPath(), 'utf8'));
}

const visible = locator => locator.isVisible().catch(() => false);

function chain(entry) {
  const values = [];
  if (entry.last_success) values.push(entry.last_success);
  if (entry.primary?.value) values.push(entry.primary.value);
  for (const item of entry.fallbacks || []) values.push(item.value || item);
  return [...new Set(values.filter(Boolean))];
}

async function describe(locator) {
  return locator.evaluate(el => {
    const rect = el.getBoundingClientRect();
    const ancestors = [];
    let node = el.parentElement;
    for (let i = 0; i < 4 && node && node !== document.body; i += 1, node = node.parentElement) {
      ancestors.push(node.id ? `#${node.id}` : `${node.tagName.toLowerCase()}${node.classList[0] ? '.' + node.classList[0] : ''}`);
    }
    return {
      tag: el.tagName.toLowerCase(),
      text: (el.innerText || el.getAttribute('placeholder') || '').trim().slice(0, 80),
      classes: [...el.classList].slice(0, 8),
      role: el.getAttribute('role') || '',
      ancestors,
      bbox: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
    };
  }).catch(() => ({}));
}

function note(key, selector, via, score, facts) {
  const dir = process.env.UIA_RESULTS_DIR;
  if (!dir) return;
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'locator-hits.json');
  let hits = [];
  try { hits = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { hits = []; }
  let environment = null;
  try { environment = loadConfig().environment?.id || null; } catch { environment = null; }
  hits.push({
    key, selector, via, score: score ?? null, environment,
    case_id: process.env.UIA_CASE_ID || null,
    tag: facts.tag || null, text: facts.text || null, classes: facts.classes || [],
    ancestors: facts.ancestors || [], bbox: facts.bbox || null, at: new Date().toISOString(),
  });
  fs.writeFileSync(file, JSON.stringify(hits, null, 2));
}

async function candidates(page, scope) {
  return page.evaluate(rootSelector => {
    const root = document.querySelector(rootSelector) || document.body;
    return [...root.querySelectorAll('a,button,input,textarea,label')].slice(0, 250).flatMap(el => {
      const rect = el.getBoundingClientRect();
      if (rect.width < 1 || rect.height < 1) return [];
      const ancestors = [];
      let node = el.parentElement;
      for (let i = 0; i < 4 && node && node !== document.body; i += 1, node = node.parentElement) {
        ancestors.push(node.id ? `#${node.id}` : `${node.tagName.toLowerCase()}${node.classList[0] ? '.' + node.classList[0] : ''}`);
      }
      let selector = '';
      if (el.id) selector = `#${CSS.escape(el.id)}`;
      else if (el.parentElement?.id) selector = `#${CSS.escape(el.parentElement.id)} ${el.tagName.toLowerCase()}`;
      else return [];
      return [{
        selector, tag: el.tagName.toLowerCase(), visible: true,
        text: (el.innerText || el.getAttribute('placeholder') || '').trim().slice(0, 80),
        classes: [...el.classList].slice(0, 8),
        role: el.getAttribute('role') || '',
        ancestors,
        attributes: { id: el.id || '', type: el.getAttribute('type') || '' },
      }];
    });
  }, scope);
}

export async function locate(page, key) {
  const entry = memory().entries[key];
  if (!entry) throw new Error('UIA_LOCATOR_MISS ' + key);
  for (const selector of chain(entry)) {
    const locator = page.locator(selector).first();
    if (await visible(locator)) {
      note(key, selector, 'selector', null, await describe(locator));
      return { locator, via: 'selector', selector };
    }
  }
  if (entry.role && entry.name) {
    const locator = page.getByRole(entry.role, { name: entry.name, exact: true }).first();
    if (await visible(locator)) {
      const selector = `role=${entry.role}[name=${entry.name}]`;
      note(key, selector, 'role', null, await describe(locator));
      return { locator, via: 'role', selector };
    }
  }
  const choice = bestCandidate(await candidates(page, entry.scope || 'body'), entry);
  if (!choice) throw new Error('UIA_LOCATOR_MISS ' + key);
  const locator = page.locator(choice.selector).first();
  await locator.waitFor({ state: 'visible', timeout: 5000 });
  note(key, choice.selector, 'fingerprint', choice.score, await describe(locator));
  return { locator, via: 'fingerprint', selector: choice.selector, score: choice.score };
}

export async function dismissNotices(page) {
  for (let i = 0; i < 3; i += 1) {
    const ack = page.getByText('我知道了', { exact: true }).first();
    if (!(await visible(ack))) return;
    await ack.click();
  }
}

export async function inspectPreview(page) {
  const facts = await page.evaluate(() => {
    const frame = document.querySelector('#backstage-innerpage');
    let sameOrigin = false;
    let access = 'missing';
    let frameCanvas = 0;
    if (frame) {
      try {
        const href = frame.contentWindow?.location?.href;
        sameOrigin = Boolean(href);
        access = sameOrigin ? 'same-origin' : 'unreadable';
        frameCanvas = frame.contentWindow?.document?.querySelectorAll('canvas').length || 0;
      } catch {
        sameOrigin = false;
        access = 'cross-origin';
      }
    }
    return {
      access, sameOrigin, frameCanvas,
      parentCanvas: document.querySelectorAll('canvas').length,
      iframeCount: document.querySelectorAll('iframe').length,
    };
  });
  const dir = process.env.UIA_RESULTS_DIR;
  if (dir) {
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'preview.json'), JSON.stringify({ iframe: '#backstage-innerpage', ...facts }, null, 2));
  }
  note('preview.frame', '#backstage-innerpage', 'preview', null, {});
  const file = dir ? path.join(dir, 'locator-hits.json') : '';
  if (file && fs.existsSync(file)) {
    const hits = JSON.parse(fs.readFileSync(file, 'utf8'));
    const last = hits[hits.length - 1];
    if (last?.key === 'preview.frame') Object.assign(last, facts);
    fs.writeFileSync(file, JSON.stringify(hits, null, 2));
  }
  return facts;
}

export async function openSettings(page) {
  await dismissNotices(page);
  await page.waitForFunction(() => {
    const frame = document.getElementById('backstage-innerpage');
    try { return Boolean(frame && frame.contentWindow && frame.contentWindow.jQuery); }
    catch { return false; }
  }, null, { timeout: 30000 });
  const open = page.locator('li.backstage-siteTool-setting.backstage-siteTool-on');
  if (!(await visible(open))) {
    await (await locate(page, 'settings.inner')).locator.click();
    await open.waitFor({ state: 'visible', timeout: 20000 });
  }
  await locate(page, 'settings.open');
}

export async function openLlms(page) {
  await openSettings(page);
  const feature = page.getByText('llms.txt 功能').first();
  if (!(await visible(feature))) {
    await (await locate(page, 'manageTxt')).locator.click();
    await feature.waitFor({ state: 'visible', timeout: 20000 });
  }
  await dismissNotices(page);
  await locate(page, 'dialog');
  return page.locator('#backstage-dialog-customizeFile');
}

async function waitIdle(page) {
  await page.waitForFunction(() => {
    const nodes = [...document.querySelectorAll('#backstage-dialog-customizeFile, #backstage-dialog-viewCustomizeFile')];
    return nodes.every(dialog => dialog.getAttribute('data-llms-busy') !== 'saving');
  }, null, { timeout: 20000 }).catch(() => {});
}

export async function cancelDialog(page) {
  await waitIdle(page);
  const addCancel = page.locator('#backstage-dialog-viewCustomizeFile a.backstage-dialog-cancel').first();
  if (await visible(addCancel)) await addCancel.click({ timeout: 10000 }).catch(() => {});
  const cancel = page.locator('#backstage-dialog-customizeFile a.backstage-dialog-cancel').first();
  if (await visible(cancel)) await cancel.click({ timeout: 15000 });
}

export function publicLlmsUrl(targets) {
  const url = new URL('/llms.txt', targets.public);
  url.protocol = 'http:';
  url.search = '';
  url.hash = '';
  return url.href;
}

export async function waitForPublic(request, targets, predicate) {
  const budgetMs = 45_000;
  const started = Date.now();
  let status = 0;
  while (Date.now() - started < budgetMs) {
    let response;
    try {
      response = await request.get(publicLlmsUrl(targets), {
        headers: { 'cache-control': 'no-cache', pragma: 'no-cache' }, timeout: 8_000,
      });
    } catch {
      if (Date.now() - started >= budgetMs) break;
      await new Promise(resolve => setTimeout(resolve, 2000));
      continue;
    }
    status = response.status();
    if (response.ok()) {
      const body = await response.text();
      if (predicate(body)) return;
    } else if (Date.now() - started >= budgetMs - 2000) {
      throw new Error('UIA_ENVIRONMENT_BLOCKED: public file HTTP ' + status);
    }
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  if (status >= 400) throw new Error('UIA_ENVIRONMENT_BLOCKED: public file HTTP ' + status);
  throw new Error('UIA_BUSINESS_FAILURE [public-file]: public file did not match the expected structure');
}

export async function clearOverview(page) {
  await openLlms(page);
  const input = (await locate(page, 'overview')).locator;
  if ((await input.inputValue()).trim()) {
    await input.fill('');
    const pending = page.getByText('llms.txt 配置已保存').waitFor({ timeout: 20000 }).catch(() => {});
    await (await locate(page, 'save')).locator.click();
    await pending;
  }
  await cancelDialog(page);
}

export async function markedDisabled(locator) {
  return locator.evaluate(el => {
    const cls = String(el.className || '');
    const style = getComputedStyle(el);
    return /disabled/i.test(cls) || el.getAttribute('aria-disabled') === 'true' || style.pointerEvents === 'none';
  });
}
