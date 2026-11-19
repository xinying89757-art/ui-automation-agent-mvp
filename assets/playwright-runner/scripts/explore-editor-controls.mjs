/** One-time editor control inventory. Prints JSON only; never prints credentials or field values. */
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '@playwright/test';
import { loadConfig, launchOptions } from '../support/environment.mjs';
import { collectEditorControls, openContentEditor, openSession, waitForEditorReady } from '../support/editor-skeleton.mjs';

function option(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

async function revealSlashMenu(page) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    for (const frame of page.frames()) {
      const editable = frame.locator('.tiptap.ProseMirror, [contenteditable="true"]').first();
      if (!await editable.isVisible().catch(() => false)) continue;
      await editable.click({ timeout: 2000 }).catch(() => {});
      await page.keyboard.type('/');
      return;
    }
    await page.waitForTimeout(100);
  }
}

async function openFixture(page, file) {
  const base = pathToFileURL(path.resolve(file)).href;
  const url = base + (base.includes('?') ? '&' : '?') + 'autodrive=1';
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  const prod = page.frameLocator('iframe[name="prod"]');
  await prod.getByText('产品', { exact: true }).click();
  await prod.locator('a[href*="invokeAction=prod_new_update"]').click();
  await prod.getByText('产品描述', { exact: true }).click();
  await waitForEditorReady(page, { kind: 'product', timeout: 15000 });
  await revealSlashMenu(page);
}

const fixture = option('--fixture');
const configPath = option('--config');
let browser;
try {
  const cfg = configPath ? loadConfig(configPath) : null;
  browser = await chromium.launch(cfg ? launchOptions(cfg) : { headless: true });
  let page;
  if (fixture) {
    page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await openFixture(page, fixture);
  } else if (cfg) {
    const session = await openSession(browser, { cfg });
    page = await openContentEditor(session.page, { cfg, kind: 'product' });
    await revealSlashMenu(page);
  } else {
    throw Object.assign(new Error('missing target'), { code: 'NAV_FAILED' });
  }
  const report = await collectEditorControls(page);
  console.log(JSON.stringify({ ok: true, midscene: report.midscene, controls: report.controls }));
} catch (error) {
  console.log(JSON.stringify({ ok: false, code: error?.code || 'NAV_FAILED', error: 'editor explore failed' }));
  process.exitCode = 2;
} finally {
  await browser?.close();
}
