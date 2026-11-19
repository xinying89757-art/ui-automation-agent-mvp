/** Live smoke for the shared editor skeleton, with bounded redacted entry evidence. */
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { chromium } from '@playwright/test';
import { launchOptions, loadConfig } from '../support/environment.mjs';
import { openContentEditor, openSession, saveEditor, readBack, insertComponent, typeText, waitForEditorReady } from '../support/editor-skeleton.mjs';
import { scrubText } from '../support/redact.mjs';

const evidenceMaskStyle = `*[class*="user"], *[class*="member"], *[class*="account"], .contentShow * { color: transparent !important; text-shadow: none !important; }`;
const accountPattern = /\b(?:demo|test|user)[-_][A-Za-z0-9_-]{4,}\b/giu;

function scrubEvidence(value) {
  if (Array.isArray(value)) return value.map(scrubEvidence);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, scrubEvidence(item)]));
  return typeof value === 'string' ? scrubText(value).replace(accountPattern, '[account]') : value;
}

function option(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

const configPath = option('--config');
const outDir = option('--out') || path.resolve(process.cwd(), '../../.auth/live-smoke');
fs.mkdirSync(outDir, { recursive: true, mode: 0o700 });
const steps = [];
let session;
let tracing = false;
const pages = [];
async function stage(name, fn) {
  const started = Date.now();
  try {
    const value = await fn();
    steps.push({ name, ok: true, ms: Date.now() - started });
    return value;
  } catch (error) {
    steps.push({ name, ok: false, ms: Date.now() - started, code: error?.code || 'NAV_FAILED', reason: error?.details?.reason || null,
      ...(error?.details?.searched ? { searched: error.details.searched } : {}),
      ...(error?.details?.observed ? { observed: error.details.observed } : {}) });
    throw error;
  }
}

async function saveEntryEvidence(outDir) {
  const observed = [];
  for (const [index, page] of pages.entries()) {
    let url = { origin: null, path: null };
    try { const parsed = new URL(page.url()); url = { origin: parsed.origin, path: parsed.pathname }; } catch {}
    const frames = page.frames().map(frame => {
      try { const parsed = new URL(frame.url()); return { main: frame === page.mainFrame(), name: frame.name() || null, origin: parsed.origin, path: parsed.pathname }; }
      catch { return { main: frame === page.mainFrame(), name: frame.name() || null, origin: null, path: null }; }
    });
    let dom = { unavailable: true };
    try {
      dom = await page.locator('body').evaluate(body => {
        const visible = node => node.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && !node.closest('[hidden],[aria-hidden="true"]');
        const name = node => (node.innerText || node.getAttribute('aria-label') || node.title || '').trim().slice(0, 120);
        const nodes = [...body.querySelectorAll('a,button,[role],iframe,[aria-modal="true"],dialog,.announcement-overlay,.member-warning-box,.contentShow')]
          .filter(visible).slice(0, 300).map(node => ({
            tag: node.tagName.toLowerCase(), role: node.getAttribute('role') || undefined,
            name: /userStatus-name|account-name/iu.test(String(node.className)) ? '[account]' : name(node),
            id: node.id || undefined, classes: typeof node.className === 'string' ? node.className.split(/\s+/u).filter(Boolean).slice(0, 8) : [],
            href: node.tagName === 'A' ? (() => { try { return new URL(node.href).pathname; } catch { return null; } })() : undefined,
            frameName: node.tagName === 'IFRAME' ? node.name || null : undefined,
            framePath: node.tagName === 'IFRAME' ? (() => { try { return new URL(node.src, location.href).pathname; } catch { return null; } })() : undefined,
            overlay: (() => { const style = getComputedStyle(node); return style.position === 'fixed' || Number(style.zIndex) > 10; })(),
          }));
        const dialogs = [...body.querySelectorAll('[role="dialog"],[aria-modal="true"],dialog,.announcement-overlay')].filter(visible).map(name);
        return { nodes, dialogs };
      });
    } catch {}
    const safeDom = scrubEvidence(dom);
    observed.push({ index, closed: page.isClosed(), url, frames, dom: safeDom });
    if (!page.isClosed()) await page.screenshot({ path: path.join(outDir, `entry-page-${index}.png`), fullPage: true,
      mask: [page.locator('.userStatus-name, [class*="account-name"]')], maskColor: '#000000', style: evidenceMaskStyle }).catch(() => {});
  }
  fs.writeFileSync(path.join(outDir, 'dom-snapshot.json'), JSON.stringify({ pages: observed }, null, 2));
  if (tracing && session?.context) {
    const raw = path.join(outDir, '.trace-raw.zip');
    await session.context.tracing.stop({ path: raw }).catch(() => {});
    tracing = false;
    // Keep the action timeline, drop network and resource payloads, then scrub identifiers.
    const sanitizer = path.join(path.dirname(new URL(import.meta.url).pathname), 'sanitize-trace.py');
    execFileSync('python3', [sanitizer, raw, path.join(outDir, 'trace.zip')]);
    fs.unlinkSync(raw);
  }
}

let browser;
try {
  const cfg = loadConfig(configPath);
  browser = await chromium.launch(launchOptions(cfg, true));
  session = await stage('login', () => openSession(browser, { cfg }));
  pages.push(session.page);
  session.context.on('page', page => pages.push(page));
  await session.context.tracing.start({ screenshots: false, snapshots: false, sources: false });
  tracing = true;
  const beforeEntry = await session.page.locator('body').evaluate(body => {
    const visible = node => node.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && !node.closest('[hidden],[aria-hidden="true"]');
    const acknowledgements = [...body.querySelectorAll('button.hasMessage_url')].filter(visible);
    const notices = [...body.querySelectorAll('.member-warning-box')].filter(visible);
    const entries = [...body.querySelectorAll('.contentShow a')].filter(visible).filter(node => node.innerText.trim() === '内容管理');
    return { announcement_acknowledgement_count: acknowledgements.length,
      announcement_acknowledgement_labels: acknowledgements.map(node => (node.innerText || '').trim().slice(0, 40)),
      dismissible_notice_count: notices.length,
      site_entry_count: entries.length,
      fixed_overlays: [...body.querySelectorAll('body *')].filter(visible).filter(node => {
        const style = getComputedStyle(node); return style.position === 'fixed' && Number(style.zIndex) > 10;
      }).slice(0, 20).map(node => ({ tag: node.tagName.toLowerCase(), classes: String(node.className || '').split(/\s+/u).filter(Boolean).slice(0, 6) })) };
  });
  fs.writeFileSync(path.join(outDir, 'entry-before.json'), JSON.stringify(scrubEvidence(beforeEntry), null, 2));
  await session.page.screenshot({ path: path.join(outDir, 'entry-before.png'), fullPage: true,
    mask: [session.page.locator('.userStatus-name, [class*="account-name"]')], maskColor: '#000000', style: evidenceMaskStyle }).catch(() => {});
  await stage('enter-site', async () => ({ ok: true, kind: session.site?.kind || 'session' }));
  const page = await stage('open-editor', () => openContentEditor(session.page, { cfg, kind: 'product' }));
  await stage('editor-ready', () => waitForEditorReady(page, { kind: 'product', timeout: 30000 }));
  const shot = path.join(outDir, '01-editor-ready.png');
  const editorFrame = page.frames().find(frame => frame !== page.mainFrame() && /tiptap|canvas|editor/iu.test(frame.url() + frame.name()));
  if (editorFrame) await editorFrame.locator('body').screenshot({ path: shot }).catch(() => page.screenshot({ path: shot }));
  else await page.screenshot({ path: shot });
  const marker = 'uia-smoke';
  const shared = { rescues: [], keyboardFallbacks: 0, lastReadBack: null };
  let inserted = false;
  try {
    await stage('insert-component-card-click', () => insertComponent(page, 'Markdown', {
      session: shared, allowKeyboardFallback: false,
    }));
    inserted = true;
  } catch (error) {
    if (error?.code !== 'CONTROL_MISSING') throw error;
    steps.push({ name: 'insert-component-absent', ok: true, ms: 0, code: 'CONTROL_MISSING' });
  }
  await stage('type-text', () => typeText(page, marker, { session: shared }));
  await stage('save', () => saveEditor(page));
  await stage('read-back', () => readBack(page, { value: marker }));
  const after = path.join(outDir, '02-after-save.png');
  if (editorFrame) await editorFrame.locator('body').screenshot({ path: after }).catch(() => {});
  console.log(JSON.stringify({
    ok: true,
    inserted,
    rescued_by_midscene: shared.rescues.length,
    screenshots: [shot, after].filter(file => fs.existsSync(file)),
    steps,
  }));
} catch (error) {
  await saveEntryEvidence(outDir).catch(() => {});
  console.log(JSON.stringify({ ok: false, code: error?.code || 'NAV_FAILED', reason: error?.details?.reason || null, error: 'editor smoke failed', steps }));
  process.exitCode = 2;
} finally {
  if (tracing) await saveEntryEvidence(outDir).catch(() => {});
  await browser?.close();
}
