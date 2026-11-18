/** Live smoke for the shared editor skeleton. Evidence is timings plus editor-frame screenshots. */
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from '@playwright/test';
import { launchOptions, loadConfig } from '../support/environment.mjs';
import { openContentEditor, openSession, saveEditor, readBack, insertComponent, typeText, waitForEditorReady } from '../support/editor-skeleton.mjs';

function option(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

const configPath = option('--config');
const outDir = option('--out') || path.resolve(process.cwd(), '../../.auth/live-smoke');
fs.mkdirSync(outDir, { recursive: true, mode: 0o700 });
const steps = [];
async function stage(name, fn) {
  const started = Date.now();
  try {
    const value = await fn();
    steps.push({ name, ok: true, ms: Date.now() - started });
    return value;
  } catch (error) {
    steps.push({ name, ok: false, ms: Date.now() - started, code: error?.code || 'NAV_FAILED', reason: error?.details?.reason || null });
    throw error;
  }
}

let browser;
try {
  const cfg = loadConfig(configPath);
  browser = await chromium.launch(launchOptions(cfg, true));
  const session = await stage('login', () => openSession(browser, { cfg }));
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
  console.log(JSON.stringify({ ok: false, code: error?.code || 'NAV_FAILED', reason: error?.details?.reason || null, error: 'editor smoke failed', steps }));
  process.exitCode = 2;
} finally {
  await browser?.close();
}
