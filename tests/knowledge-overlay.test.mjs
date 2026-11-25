import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../assets/playwright-runner/node_modules/@playwright/test/index.mjs';

// Exercise the same packaged navigation module against a real browser, without a product account.
test('packaged run-local entry and control replay from the frozen batch after current hints change', async () => {
  const runner = path.resolve('assets/playwright-runner');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'uia-package-'));
  const old = { ...process.env };
  let browser;
  try {
    for (const name of ['support', 'flows']) fs.cpSync(path.join(runner, name), path.join(dir, name), { recursive: true });
    fs.symlinkSync(path.join(runner, 'node_modules'), path.join(dir, 'node_modules'));
    fs.copyFileSync(path.join(runner, 'environments.json'), path.join(dir, 'environments.json'));
    fs.mkdirSync(path.join(dir, 'knowledge'), { recursive: true });
    fs.mkdirSync(path.join(dir, 'state'), { recursive: true });
    const batch = path.join(dir, 'batch-knowledge', 'b1');
    fs.mkdirSync(path.join(batch, 'shared'), { recursive: true });
    const shared = 'schema_version: page-map.v1\npages: {}\ntargets: {}\n';
    const empty = 'schema_version: entry-hints.v1\nentries: {}\n';
    const route = 'schema_version: entry-hints.v1\nentries:\n  pilot.route:\n    label: Pilot\n    confirmed: true\n    steps: ["click:pilot.open"]\n';
    const targets = 'schema_version: page-map.v1\npages: {}\ntargets:\n  pilot.open:\n    selector: "#open"\n';
    for (const root of [path.join(dir, 'knowledge'), path.join(batch, 'shared')]) {
      fs.writeFileSync(path.join(root, 'page-map.yaml'), shared);
      fs.writeFileSync(path.join(root, 'entries.yaml'), empty);
    }
    for (const root of [path.join(dir, 'state'), batch]) {
      fs.writeFileSync(path.join(root, 'page-map-overlay.yaml'), targets);
      fs.writeFileSync(path.join(root, 'entries-overlay.yaml'), route);
    }
    for (const key of ['UIA_KNOWLEDGE_DIR', 'UIA_PAGE_MAP_OVERLAY', 'UIA_ENTRIES_OVERLAY', 'UIA_BATCH_KNOWLEDGE_ID']) delete process.env[key];
    const nav = await import(pathToFileURL(path.join(dir, 'support/navigation.mjs')).href);
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    const run = async () => {
      await page.setContent('<button id="open" onclick="document.querySelector(\'#result\').hidden=false">Open</button><p id="result" hidden>Ready</p>');
      await nav.openTarget(page, 'pilot.route', { cfg: {} });
      assert.equal(await page.locator('#result').isVisible(), true);
    };
    await run();
    // The archive's latest hint may change; selecting the batch must keep using its snapshot.
    fs.writeFileSync(path.join(dir, 'state', 'page-map-overlay.yaml'), targets.replace('#open', '#missing'));
    process.env.UIA_BATCH_KNOWLEDGE_ID = 'b1';
    await run();
  } finally {
    if (browser) await browser.close();
    for (const key of ['UIA_KNOWLEDGE_DIR', 'UIA_PAGE_MAP_OVERLAY', 'UIA_ENTRIES_OVERLAY', 'UIA_BATCH_KNOWLEDGE_ID']) {
      if (old[key] === undefined) delete process.env[key]; else process.env[key] = old[key];
    }
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
