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

function visibleLocator(page, selector) {
  return page.locator(selector).locator('visible=true').first();
}

export async function locate(page, key) {
  const entry = memory().entries[key];
  if (!entry) throw new Error('UIA_LOCATOR_MISS ' + key);
  const deadline = Date.now() + 8000;
  while (Date.now() <= deadline) {
    for (const selector of chain(entry)) {
      const locator = visibleLocator(page, selector);
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
    if (Date.now() >= deadline) break;
    await page.waitForTimeout(250);
  }
  const choice = bestCandidate(await candidates(page, entry.scope || 'body'), entry);
  if (!choice) throw new Error('UIA_LOCATOR_MISS ' + key);
  const locator = visibleLocator(page, choice.selector);
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
    const gear = (await locate(page, 'settings.inner')).locator;
    await gear.click({ timeout: 10000 });
    const shown = await open.waitFor({ state: 'visible', timeout: 8000 }).then(() => true).catch(() => false);
    if (!shown) {
      await gear.click({ timeout: 10000 });
      await open.waitFor({ state: 'visible', timeout: 15000 });
    }
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
  const dialog = page.locator('#backstage-dialog-customizeFile');
  await waitIdle(page);
  await locate(page, 'dialog');
  const llmsTab = dialog.locator('a.customize-file-tab', { hasText: 'llms.txt' }).first();
  const alreadyOn = await llmsTab.evaluate(el => el.classList.contains('on')).catch(() => false);
  if (!alreadyOn && await visible(llmsTab)) await llmsTab.click({ timeout: 5000 });
  const overview = dialog.locator('input.llms-overview').locator('visible=true');
  if (!(await visible(overview))) {
    const system = dialog.locator('label.llms-source-system').locator('visible=true').first();
    if (await visible(system)) await system.click({ timeout: 5000 });
    await overview.waitFor({ state: 'visible', timeout: 15000 });
  }
  return dialog;
}

export async function waitIdle(page) {
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

/** Public files are cached for about an hour. Record a cache-bust attempt; do not poll. */
export async function noteDeferredPublic(request, targets, note) {
  const record = { at: new Date().toISOString(), cache: 'deferred', note: String(note || '') };
  try {
    const bust = new URL(publicLlmsUrl(targets));
    bust.searchParams.set('uia_bust', String(Date.now()));
    const response = await request.get(bust.href, { timeout: 8000 });
    record.bust_status = response.status();
    record.bust_bypassed = response.ok();
  } catch {
    record.bust_status = 0;
    record.bust_bypassed = false;
  }
  const dir = process.env.UIA_RESULTS_DIR;
  if (dir) {
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, 'deferred-public.json');
    let rows = [];
    try { rows = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { rows = []; }
    if (!Array.isArray(rows)) rows = [];
    rows.push(record);
    fs.writeFileSync(file, JSON.stringify(rows, null, 2));
  }
  return record;
}

export async function readOverview(page) {
  await openLlms(page);
  return (await locate(page, 'overview')).locator.inputValue();
}

export async function writeOverview(page, value) {
  await openLlms(page);
  const input = (await locate(page, 'overview')).locator;
  if ((await input.inputValue()) === value) {
    await cancelDialog(page);
    return false;
  }
  await input.fill(value);
  await (await locate(page, 'save')).locator.click();
  await page.getByText('llms.txt 配置已保存').waitFor({ timeout: 20000 }).catch(() => {});
  await page.locator('#backstage-dialog-customizeFile').waitFor({ state: 'hidden', timeout: 15000 }).catch(async () => {
    await cancelDialog(page);
  });
  return true;
}

export async function clearOverview(page) {
  await writeOverview(page, '');
}

export async function markedDisabled(locator) {
  return locator.evaluate(el => {
    const cls = String(el.className || '');
    const style = getComputedStyle(el);
    return /disabled/i.test(cls) || el.getAttribute('aria-disabled') === 'true' || style.pointerEvents === 'none';
  });
}
