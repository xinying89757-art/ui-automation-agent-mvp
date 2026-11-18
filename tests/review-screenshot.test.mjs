import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { chromium } from '../assets/playwright-runner/node_modules/@playwright/test/index.mjs';
import { redactedDialogScreenshot } from '../assets/playwright-runner/support/review-screenshot.mjs';

test('review screenshots are dialog-only and mask arbitrary text, inputs and media', async () => {
  const browser = await chromium.launch({ headless: true });
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'uia-review-'));
  try {
    const page = await browser.newPage();
    await page.setContent('<div>private shell</div><div role="dialog" style="width:300px;height:150px;background:white"><p>private text</p><input value="private value"><button aria-disabled="true">保存</button></div>');
    const result = await redactedDialogScreenshot(page, path.join(dir, 'redacted.png'));
    assert.equal(result.redacted, true);
    assert.equal(result.masked_nodes, 1);
    assert.ok((await fs.stat(result.path)).size > 100);
    assert.equal(await page.locator('[data-uia-review-mask]').count(), 0);
  } finally {
    await browser.close();
    await fs.rm(dir, { recursive: true, force: true });
  }
});
