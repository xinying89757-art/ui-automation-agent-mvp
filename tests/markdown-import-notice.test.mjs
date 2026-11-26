import test from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from '../assets/playwright-runner/node_modules/@playwright/test/index.mjs';
import { matchingImportNotice, watchImportNotices } from '../assets/playwright-runner/tests/markdown/import-result.mjs';

test('import outcome ignores existing success and a new unrelated toast', async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.setContent('<div role="alert">已导入 sample.md 并转化为文档样式</div><main></main>');
    const watcher = await watchImportNotices(page);
    const captured = () => watcher.evaluate(state => [...state.seen]);
    await page.locator('main').evaluate(node => { node.innerHTML = '<div class="el-message">保存成功</div>'; });
    assert.deepEqual(await captured(), ['保存成功']);
    assert.equal(matchingImportNotice(await captured(), 'sample.md'), '');
    await page.locator('main .el-message').evaluate(node => { node.textContent = '已导入 other.md 并转化为文档样式'; });
    assert.equal(matchingImportNotice(await captured(), 'sample.md'), '');
    await page.locator('main .el-message').evaluate(node => { node.textContent = '已导入 sample.md 并转化为文档样式'; });
    assert.equal(matchingImportNotice(await captured(), 'sample.md'), '已导入 sample.md 并转化为文档样式');
    await watcher.evaluate(state => state.observer.disconnect());
    await watcher.dispose();
  } finally {
    await browser.close();
  }
});
