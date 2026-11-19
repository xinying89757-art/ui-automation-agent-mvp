/**
 * Shared content-editor page object.
 * Login material comes from the private config or UIA_ACCOUNT/UIA_PASSWORD.
 * Stable Playwright locators run first. Midscene runs only after they fail, and only when configured.
 */
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { credentials, loginOnce, openSiteArea, selectTargetSite, authenticatedSession } from './auth.mjs';
import { loadConfig } from './environment.mjs';
import { openTarget, pageMap, targetLocator } from './navigation.mjs';
import { performWithPatterns } from './interaction-patterns.mjs';
import { SkeletonError, publicReason } from './skeleton-errors.mjs';
import { locateControl, midsceneEnabled, setMidsceneAdapter, visualAssert as midsceneVisualAssert } from './midscene-bridge.mjs';

export { SkeletonError, midsceneEnabled, setMidsceneAdapter };
export { CODES } from './skeleton-errors.mjs';

const EDITABLE = '.tiptap.ProseMirror, [contenteditable="true"]';
const CLOSE_LABEL = /^(关闭|我知道了|知道了|×)$/u;

function sessionOf(options = {}) {
  if (options.session) return options.session;
  const session = { rescues: [], keyboardFallbacks: 0, lastReadBack: null };
  options.session = session;
  return session;
}

function noteRescue(page, session, control) {
  const row = { control: String(control).slice(0, 120), at: new Date().toISOString(), case_id: session.caseId || null };
  session.rescues.push(row);
  const dir = process.env.UIA_RESULTS_DIR;
  if (dir) {
    fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(path.join(dir, 'rescued-by-midscene.jsonl'), JSON.stringify(row) + '\n');
  }
  return import('@playwright/test').then(({ test }) => {
    try { test.info().annotations.push({ type: 'rescued_by_midscene', description: row.control }); }
    catch { /* Outside a Playwright test the JSONL record is enough. */ }
  }).catch(() => {});
}

/** Credentials from a private file or env. Never from source literals. */
export function resolveCredentials(cfg, env = process.env) {
  if (cfg?.auth?.credentials_file) return credentials(cfg);
  const account = env.UIA_ACCOUNT;
  const password = env.UIA_PASSWORD;
  if (typeof account === 'string' && account.trim() && typeof password === 'string' && password)
    return { account: account.trim(), password };
  throw new SkeletonError('LOGIN_FAILED', '缺少环境变量或 .auth 凭据引用');
}

async function submitLoginForm(page, cfg, env) {
  const value = resolveCredentials(cfg, env);
  const field = page.locator('#loginName');
  if (!await field.isVisible().catch(() => false))
    await page.goto(cfg.environment.login_url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.locator('#loginName').fill(value.account);
  await page.locator('#password').fill(value.password);
  await page.locator('#loginSubmit').click();
  await page.waitForFunction(() => {
    const input = document.querySelector('#loginName');
    const loggedOut = input && input.getClientRects().length > 0;
    const dashboard = document.querySelector('.contentShow, .wrap-webSite');
    return !loggedOut && Boolean(dashboard && dashboard.getClientRects().length);
  }, null, { timeout: 15000 });
}

/** @param {import('@playwright/test').Page} page */
export async function login(page, options = {}) {
  const cfg = options.cfg ?? loadConfig(options.configPath);
  try {
    if (options.fixture) {
      await page.goto(options.fixture, { waitUntil: 'domcontentloaded' });
      await submitLoginForm(page, cfg, options.env);
      return { ok: true, reused: false };
    }
    await loginOnce(page, cfg);
    return { ok: true, reused: false };
  } catch (error) {
    if (error instanceof SkeletonError) throw error;
    throw new SkeletonError('LOGIN_FAILED', '登录失败', { reason: publicReason(error, 'LOGIN_FAILED') });
  }
}

/** Opens an authenticated browser context. The summary does not include the account or site host. */
export async function openSession(browser, options = {}) {
  const cfg = options.cfg ?? loadConfig(options.configPath);
  try {
    const session = await authenticatedSession(browser, cfg, { allowLogin: true, force: Boolean(options.force), manual: Boolean(options.manual) });
    return session;
  } catch (error) {
    const reason = publicReason(error, 'LOGIN_FAILED');
    const code = reason === 'ENVIRONMENT_UNREACHABLE' || reason === 'ENVIRONMENT_MISMATCH' ? 'NAV_FAILED' : 'LOGIN_FAILED';
    throw new SkeletonError(code, '登录或环境失败', { reason });
  }
}

export async function enterSite(page, options = {}) {
  const cfg = options.cfg ?? loadConfig(options.configPath);
  try {
    const selected = await selectTargetSite(page, cfg);
    return { ok: true, kind: selected?.kind ?? 'site' };
  } catch (error) {
    throw new SkeletonError('NAV_FAILED', '未能进入目标站点', { reason: publicReason(error, 'NAV_FAILED') });
  }
}

async function clickExact(root, text, timeout = 2500) {
  const loc = root.getByText(text, { exact: true }).first();
  if (!await loc.isVisible().catch(() => false)) return false;
  await loc.click({ timeout });
  return true;
}

async function clickAnywhere(page, text, timeout = 6000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    for (const frame of page.frames()) {
      if (await clickExact(frame, text, 1500)) return true;
    }
    await page.waitForTimeout(150);
  }
  return false;
}

async function clickEdit(page, kind) {
  const frameSel = kind === 'article' ? 'iframe[name="article"]' : 'iframe[name="prod"]';
  const locator = page.frameLocator(frameSel);
  const edit = locator.locator('a[href*="invokeAction=prod_new_update"], a[href*="article_edit"], a.edit-detail').first();
  if (await edit.isVisible().catch(() => false)) {
    await edit.click({ timeout: 5000 });
    return true;
  }
  return clickAnywhere(page, '编辑', 4000);
}

async function openDetail(page, kind) {
  const label = kind === 'article' ? '文章' : '产品';
  const tab = kind === 'article' ? '正文' : '产品描述';
  const frameSel = kind === 'article' ? 'iframe[name="article"]' : 'iframe[name="prod"]';
  await page.locator(frameSel).first().waitFor({ state: 'attached', timeout: 8000 }).catch(() => {});
  await clickAnywhere(page, label, 5000);
  if (!await clickEdit(page, kind)) throw new SkeletonError('NAV_FAILED', '未找到详情编辑入口');
  await clickAnywhere(page, tab, 4000);
}

/** @param {import('@playwright/test').Page} page */
export async function openContentEditor(page, options = {}) {
  const cfg = options.cfg ?? loadConfig(options.configPath);
  let surface = page;
  if (!options.skipEntry) {
    try { surface = await openSiteArea(page, cfg, '内容管理'); }
    catch (error) {
      throw new SkeletonError('NAV_FAILED', '未能进入内容管理', { reason: publicReason(error, 'NAV_FAILED') });
    }
  }
  const order = options.kind === 'article' || options.kind === 'product' ? [options.kind] : ['product', 'article'];
  let last = new SkeletonError('NAV_FAILED', '未能打开内容编辑器');
  for (const kind of order) {
    try {
      await openDetail(surface, kind);
      await waitForEditorReady(surface, { ...options, kind });
      return surface;
    } catch (error) {
      last = error instanceof SkeletonError ? error : new SkeletonError('NAV_FAILED', '未能打开内容编辑器');
      if (last.code === 'OVERLAY_BLOCKING') throw last;
    }
  }
  throw last;
}

async function frameChain(frame) {
  const chain = [];
  let current = frame;
  while (current?.parentFrame?.()) {
    try {
      const element = await current.frameElement();
      const selector = await element.evaluate(node => node.id ? `#${CSS.escape(node.id)}` : node.getAttribute('name') ? `iframe[name="${node.getAttribute('name')}"]` : 'iframe');
      chain.unshift(selector);
    } catch { break; }
    current = current.parentFrame();
  }
  return chain;
}

async function dismissOverlays(frame) {
  const overlay = frame.locator('.blocking-overlay, [data-uia-overlay="blocking"]').first();
  if (!await overlay.isVisible().catch(() => false)) return;
  const close = overlay.locator('button, [role="button"], a').filter({ hasText: CLOSE_LABEL }).first();
  if (await close.isVisible().catch(() => false)) await close.click({ timeout: 2000 }).catch(() => {});
  if (await overlay.isVisible().catch(() => false))
    throw new SkeletonError('OVERLAY_BLOCKING', '遮罩挡住了编辑器');
}

/** Re-resolves the editable root after iframe redraws. */
export async function resolveEditor(page, options = {}) {
  const preferred = options.kind === 'article' ? 'article' : options.kind === 'product' ? 'prod' : '';
  const ordered = [...page.frames()].sort((a, b) => {
    const score = frame => (preferred && frame.name() === preferred ? 0 : frame.url().includes('canvas') ? 1 : 2);
    return score(a) - score(b);
  });
  for (const frame of ordered) {
    const editable = frame.locator(EDITABLE).first();
    if (!await editable.count().catch(() => 0)) continue;
    if (!await editable.isVisible().catch(() => false)) continue;
    await dismissOverlays(frame);
    const chain = await frameChain(frame);
    return { frame, editable: frame.locator(EDITABLE).first(), chain };
  }
  return null;
}

export async function waitForEditorReady(page, options = {}) {
  const timeout = options.timeout ?? 20000;
  const deadline = Date.now() + timeout;
  let last = '编辑器未出现';
  while (Date.now() < deadline) {
    try {
      const resolved = await resolveEditor(page, options);
      if (resolved) return { ready: true, chain: resolved.chain };
    } catch (error) {
      if (error instanceof SkeletonError && error.code === 'OVERLAY_BLOCKING') throw error;
      last = error instanceof Error ? error.message : last;
    }
    await page.waitForTimeout(200);
  }
  throw new SkeletonError('EDITOR_NOT_READY', '编辑器未就绪', { reason: last.slice(0, 120) });
}

async function focusEditable(page, options = {}) {
  let resolved = await resolveEditor(page, options);
  if (!resolved) resolved = await waitForEditorReady(page, options).then(() => resolveEditor(page, options));
  if (!resolved) throw new SkeletonError('EDITOR_NOT_READY', '没有可编辑区域');
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const before = await resolved.editable.elementHandle();
    await resolved.editable.click({ timeout: 3000 });
    await page.waitForTimeout(40);
    const again = await resolveEditor(page, options);
    if (!again) continue;
    const after = await again.editable.elementHandle();
    const same = before && after ? await before.evaluate((node, other) => node === other, after).catch(() => false) : false;
    resolved = again;
    if (same) return resolved;
  }
  return resolved;
}

async function readEditorText(page, options = {}) {
  for (const frame of page.frames()) {
    const persisted = frame.locator('#persisted');
    if (await persisted.count().catch(() => 0) && String(await persisted.innerText().catch(() => '')).trim())
      return persisted.innerText();
  }
  const resolved = await resolveEditor(page, options);
  if (!resolved) return '';
  return resolved.editable.innerText().catch(() => '');
}

async function findCard(page, name, selector = '.slash-card, [data-component]') {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&');
  for (const frame of page.frames()) {
    const cards = frame.locator(selector).filter({ hasText: new RegExp(`^${escaped}$`, 'u') });
    const count = await cards.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const card = cards.nth(index);
      if (await card.isVisible().catch(() => false)) return card;
    }
  }
  return page.locator(selector).filter({ hasText: name }).first();
}

async function componentPresent(page, name) {
  for (const frame of page.frames()) {
    const node = frame.locator(`[data-component="${name}"].inserted-component, .inserted-component`).filter({ hasText: name }).first();
    if (await node.isVisible().catch(() => false)) return true;
  }
  return false;
}

async function keyboardFallback(page, name, session) {
  session.keyboardFallbacks += 1;
  const resolved = await focusEditable(page).catch(() => null);
  if (!resolved) return false;
  await page.keyboard.type(name);
  await page.keyboard.press('Enter');
  if (await componentPresent(page, name)) return true;
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  return componentPresent(page, name);
}

async function rescueClick(page, description, session, options = {}) {
  if (!midsceneEnabled(options.env) && !options.adapter) return false;
  const located = await locateControl(page, description, options);
  if (!located) return false;
  try {
    await located.click({ timeout: 3000 });
    await noteRescue(page, session, description);
    return true;
  } catch {
    return false;
  }
}

/** Slash menu: click the card. Keyboard is only the fallback, and it must actually insert. */
export async function insertComponent(page, name, options = {}) {
  if (!name || typeof name !== 'string') throw new SkeletonError('CONTROL_MISSING', '组件名缺失');
  const session = sessionOf(options);
  await focusEditable(page, options);
  await page.keyboard.type('/');
  const selector = options.cardSelector || '.slash-card, [data-component]';
  try {
    const card = await findCard(page, name, selector);
    await card.waitFor({ state: 'visible', timeout: options.timeout ?? 4000 });
    await card.scrollIntoViewIfNeeded().catch(() => {});
    await card.click({ timeout: 3000 });
  } catch {
    const rescued = await rescueClick(page, `slash card ${name}`, session, options);
    if (!rescued) {
      const typed = options.allowKeyboardFallback === false ? false : await keyboardFallback(page, name, session);
      if (!typed) throw new SkeletonError('CONTROL_MISSING', '未找到可点击的组件卡片');
    }
  }
  if (!await componentPresent(page, name)) throw new SkeletonError('CONTROL_MISSING', '组件卡片点击后没有插入');
  return { ok: true, keyboardFallbacks: session.keyboardFallbacks, rescued: session.rescues.length };
}

export async function typeText(page, text, options = {}) {
  if (typeof text !== 'string') throw new SkeletonError('CONTROL_MISSING', '文本必须是字符串');
  await focusEditable(page, options);
  await page.keyboard.type(text);
  let value = await readEditorText(page, options);
  if (!value.includes(text)) {
    const again = await focusEditable(page, options);
    await again.editable.click();
    await page.keyboard.type(text);
    value = await readEditorText(page, options);
  }
  if (!value.includes(text)) throw new SkeletonError('EDITOR_NOT_READY', '重绘后文本没有留在编辑器里');
  return { ok: true };
}

export async function selectMenuItem(page, name, options = {}) {
  const session = sessionOf(options);
  const item = () => {
    const exact = new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&')}$`, 'u');
    return page.locator('[role="menuitem"], [role="option"], [data-menu-item]').filter({ hasText: exact }).first();
  };
  let found = null;
  for (const frame of page.frames()) {
    const candidate = frame.locator('[role="menuitem"], [role="option"], [data-menu-item]').filter({ hasText: name }).first();
    if (await candidate.isVisible().catch(() => false)) { found = candidate; break; }
  }
  try {
    const target = found || item();
    await target.waitFor({ state: 'visible', timeout: 3000 });
    await target.scrollIntoViewIfNeeded().catch(() => {});
    await target.click({ timeout: 3000 });
  } catch {
    session.keyboardFallbacks += 1;
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    const selected = page.frames();
    let ok = false;
    for (const frame of selected) {
      ok = await frame.locator(`[data-menu-item="${name}"][data-selected="1"], [role="menuitem"][aria-selected="true"]`).count().then(count => count > 0).catch(() => false);
      if (ok) break;
    }
    if (!ok) {
      const rescued = await rescueClick(page, `menu item ${name}`, session, options);
      if (!rescued) throw new SkeletonError('CONTROL_MISSING', '菜单项不可点');
    }
  }
  return { ok: true, keyboardFallbacks: session.keyboardFallbacks };
}

async function findSave(page) {
  const selectors = ['.topBts_menu_save', 'button.save', '#save'];
  for (const frame of page.frames()) {
    for (const selector of selectors) {
      const button = frame.locator(selector).first();
      if (await button.isVisible().catch(() => false)) return button;
    }
    const labeled = frame.getByRole('button', { name: '保存', exact: true }).first();
    if (await labeled.isVisible().catch(() => false)) return labeled;
  }
  return null;
}

export async function saveEditor(page, options = {}) {
  const button = await findSave(page);
  if (!button) {
    const session = sessionOf(options);
    const rescued = await rescueClick(page, 'editor save button', session, options);
    if (!rescued) throw new SkeletonError('CONTROL_MISSING', '未找到保存按钮');
  } else {
    try { await button.click({ timeout: 5000 }); }
    catch {
      const session = sessionOf(options);
      const rescued = await rescueClick(page, 'editor save button', session, options);
      if (!rescued) throw new SkeletonError('SAVE_FAILED', '保存按钮点击失败');
    }
  }
  const timeout = options.timeout ?? 8000;
  const waits = [];
  for (const frame of page.frames()) {
    waits.push(frame.locator('[data-uia-saved="1"], .save-ok').first()
      .waitFor({ state: 'visible', timeout }).then(() => 'editor-marker'));
    waits.push(frame.getByText(/保存成功|保存完成|已保存/u).first()
      .waitFor({ state: 'visible', timeout }).then(() => 'success-notice'));
    waits.push(frame.waitForFunction(() => document.body?.getAttribute('data-uia-saved') === '1', null, { timeout })
      .then(() => 'editor-marker'));
  }
  try { return { ok: true, signal: await Promise.any(waits) }; }
  catch { throw new SkeletonError('SAVE_FAILED', '保存没有完成信号'); }
}

export async function readBack(page, record = {}, options = {}) {
  let current = page;
  if (record?.reopen?.length) {
    await current.reload({ waitUntil: 'domcontentloaded' }).catch(() => {});
    for (const target of record.reopen) current = await openTarget(current, target, options);
  }
  const ctx = options.caseContext;
  const map = options.map ?? safePageMap();
  if (ctx && record?.save_target && map?.targets?.[record.save_target]?.network) {
    const { verifyPersisted, readFieldValue } = await import('./remote-checks.mjs');
    await verifyPersisted(current, ctx, record, map.targets[record.save_target].network,
      async () => readFieldValue(targetLocator(current, record.target, { map })));
    return current;
  }
  const text = await readEditorText(current, options);
  if (record?.value != null && record.value !== '' && !String(text).includes(String(record.value)))
    throw new SkeletonError('READBACK_MISMATCH', '保存后读回与预期不一致');
  sessionOf(options).lastReadBack = { ok: true };
  return current;
}

function safePageMap() {
  try { return pageMap(); }
  catch { return { targets: {}, pages: {} }; }
}

function patternsFor(entry, verb, target) {
  const patterns = [...(entry?.patterns ?? [])];
  const blob = `${target} ${entry?.selector ?? ''} ${entry?.role ?? ''}`;
  const menu = /menu|listbox|suggest|command|slash|dropdown|option|menuitem/iu.test(blob);
  if (verb === 'click' && menu && !patterns.includes('MENU_KEYBOARD')) patterns.push('MENU_KEYBOARD');
  return patterns;
}

export async function actVerified(page, verb, target, value, patterns, options = {}) {
  const map = options.map ?? safePageMap();
  const entry = map.targets?.[target] ?? map.pages?.[target];
  if (!entry) throw new SkeletonError('CONTROL_MISSING', '知识库没有这个控件');
  const session = sessionOf(options);
  const chosen = patterns?.length ? patterns : patternsFor(entry, verb, target);
  const locate = () => targetLocator(page, target, { map });
  const action = async node => {
    if (verb === 'double_click') {
      const { doubleClick } = await import('../flows/network-control.mjs');
      await doubleClick(page, node);
    } else if (verb === 'attempt_click') {
      const { attemptClick } = await import('../flows/network-control.mjs');
      await attemptClick(page, node);
    } else if (verb === 'click' || verb === 'close') await node.click();
    else if (verb === 'hover') await node.hover();
    else if (verb === 'check') await node.check();
    else if (verb === 'uncheck') await node.uncheck();
    else if (verb === 'fill') await node.fill(value ?? '');
    else if (verb === 'press') await node.press(value ?? '');
    else if (verb === 'select') await node.selectOption(value ?? '');
    else if (verb === 'upload') await node.setInputFiles(value ?? '');
    else throw new SkeletonError('CONTROL_MISSING', '不支持的动作');
  };
  try {
    await performWithPatterns(page, locate, chosen, action);
    return { ok: true, rescued: false };
  } catch (error) {
    const rescued = await rescueClick(page, target, session, options);
    if (!rescued) throw new SkeletonError('CONTROL_MISSING', '稳定定位失败', { reason: publicReason(error, 'CONTROL_MISSING') });
    return { ok: true, rescued: true };
  }
}

export async function expectVerified(page, target, op, value, extra = {}) {
  const { expect } = await import('@playwright/test');
  const map = extra.map ?? safePageMap();
  if (op === 'occurrence_count') {
    await expect.poll(() => extra.observations?.[target]?.count?.() ?? 0).toBe(value);
    return;
  }
  if (op === 'request_count') {
    await expect.poll(() => extra.networks?.[target]?.count?.() ?? 0).toBe(value);
    return;
  }
  const loc = () => targetLocator(page, target, { map });
  if (!map.targets?.[target] && !map.pages?.[target]) throw new SkeletonError('CONTROL_MISSING', '知识库没有这个控件');
  if (op === 'visible_text') {
    await expect.poll(() => loc().innerText()).toBe(value);
    return;
  }
  if (op === 'blocked') {
    await expect.poll(() => loc().evaluate(el => el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true' || /disabled/i.test(el.className) || getComputedStyle(el).pointerEvents === 'none')).toBe(true);
    return;
  }
  if (op === 'left_of') {
    const other = targetLocator(page, value, { map });
    expect((await loc().boundingBox()).x).toBeLessThan((await other.boundingBox()).x);
    return;
  }
  const method = {
    visible: 'toBeVisible', hidden: 'toBeHidden', text: 'toHaveText', contains: 'toContainText', value: 'toHaveValue',
    attribute: 'toHaveAttribute', count: 'toHaveCount', enabled: 'toBeEnabled', disabled: 'toBeDisabled',
  }[op];
  if (!method) throw new SkeletonError('CONTROL_MISSING', '不支持的断言');
  const args = [];
  if (op === 'attribute') args.push(extra.attribute);
  if (value !== undefined && !['visible', 'hidden', 'enabled', 'disabled'].includes(op)) args.push(value);
  await expect(loc())[method](...args);
}

export async function observeTarget(page, target, options = {}) {
  const map = options.map ?? safePageMap();
  const text = map.targets?.[target]?.observe_text;
  if (typeof text !== 'string') throw new SkeletonError('CONTROL_MISSING', '没有可观察文本');
  const { observeOccurrences } = await import('../flows/network-control.mjs');
  return observeOccurrences(page, text);
}

export async function visualAssert(page, expectation, options = {}) {
  return midsceneVisualAssert(page, expectation, options);
}

/** One-time DOM inventory. Names are visible control labels, never field values. */
export async function collectEditorControls(page, options = {}) {
  const controls = [];
  for (const frame of page.frames()) {
    let found = [];
    try {
      found = await frame.locator('body').evaluate(root => {
        const visible = node => {
          const css = getComputedStyle(node);
          return css.display !== 'none' && css.visibility !== 'hidden' && node.getClientRects().length > 0;
        };
        const interesting = [...root.querySelectorAll('button, a, [role="button"], [role="menuitem"], [role="option"], .slash-card, [data-component], [data-menu-item]')];
        return interesting.filter(visible).map(node => {
          const name = (node.getAttribute('aria-label') || node.getAttribute('data-component') || node.textContent || '').trim().replace(/\s+/gu, ' ').slice(0, 80);
          let selector = '';
          let strategy = '';
          if (node.id && root.querySelectorAll(`#${CSS.escape(node.id)}`).length === 1) {
            selector = `#${CSS.escape(node.id)}`;
            strategy = 'id';
          } else if (node.getAttribute('data-component')) {
            const value = node.getAttribute('data-component');
            const css = `[data-component="${value.replace(/"/gu, '')}"]`;
            if (root.querySelectorAll(css).length === 1) { selector = css; strategy = 'data-component'; }
          } else if (node.getAttribute('data-menu-item')) {
            const value = node.getAttribute('data-menu-item');
            const css = `[data-menu-item="${value.replace(/"/gu, '')}"]`;
            if (root.querySelectorAll(css).length === 1) { selector = css; strategy = 'data-menu-item'; }
          }
          const role = node.getAttribute('role') || (node.tagName === 'BUTTON' ? 'button' : node.tagName === 'A' ? 'link' : '');
          return { name, selector, strategy, role, match_count: selector ? 1 : 0 };
        }).filter(item => item.match_count === 1 && item.name && !item.name.includes('@'));
      });
    } catch { found = []; }
    const chain = await frameChain(frame);
    for (const item of found) {
      controls.push({ ...item, frame: chain[0] || '', nested_frames: chain.slice(1), midscene: false });
    }
  }
  let midscene = 'skipped';
  const adapter = options.adapter;
  if (adapter?.locateSelector || midsceneEnabled(options.env)) {
    midscene = 'used';
    const selector = adapter?.locateSelector ? await adapter.locateSelector(page, 'editor control') : '';
    if (typeof selector === 'string' && selector && selector.length < 200) {
      let matches = 0;
      for (const frame of page.frames()) matches += await frame.locator(selector).count().catch(() => 0);
      if (matches === 1) {
        const chain = await frameChain(page.frames().find(frame => frame !== page.mainFrame()) || page.mainFrame());
        controls.push({ name: 'midscene-control', selector, strategy: 'midscene', role: '', match_count: 1, frame: chain[0] || '', nested_frames: chain.slice(1), midscene: true });
      }
    }
  }
  return { controls, midscene };
}

/**
 * @param {(() => import('@playwright/test').Page) | import('@playwright/test').Page} getPage
 */
export function createContentEditor(getPage, options = {}) {
  const read = typeof getPage === 'function' ? getPage : () => getPage;
  const session = sessionOf(options);
  session.caseId = options.caseContext?.caseId || options.caseId || null;
  const call = (fn, args) => fn(read(), ...args, { ...options, session });
  return {
    session,
    login: extra => login(read(), { ...options, ...extra }),
    enterSite: extra => enterSite(read(), { ...options, ...extra }),
    openContentEditor: extra => openContentEditor(read(), { ...options, ...extra, session }),
    waitForEditorReady: extra => waitForEditorReady(read(), { ...options, ...extra }),
    insertComponent: (name, extra) => insertComponent(read(), name, { ...options, ...extra, session }),
    typeText: (text, extra) => typeText(read(), text, { ...options, ...extra, session }),
    selectMenuItem: (name, extra) => selectMenuItem(read(), name, { ...options, ...extra, session }),
    save: extra => saveEditor(read(), { ...options, ...extra, session }),
    readBack: record => readBack(read(), record, { ...options, session }),
    openTarget: target => openTarget(read(), target, options),
    actVerified: (verb, target, value, patterns) => actVerified(read(), verb, target, value, patterns, { ...options, session }),
    expectVerified: (target, op, value, extra) => expectVerified(read(), target, op, value, { ...options, ...extra }),
    observe: target => observeTarget(read(), target, options),
    visualAssert: (expectation, extra) => visualAssert(read(), expectation, { ...options, ...extra }),
    rescues: () => session.rescues.map(item => ({ ...item })),
  };
}

export function fixtureUrl(name = 'index.html') {
  return pathToFileURL(path.join(path.dirname(new URL(import.meta.url).pathname), '../fixtures/editor-nested', name)).href;
}
