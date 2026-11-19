import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createServer } from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { chromium } from '../assets/playwright-runner/node_modules/@playwright/test/index.mjs';
import { dismissShellNotices, openSiteArea } from '../assets/playwright-runner/support/auth.mjs';
import {
  CODES, SkeletonError, collectEditorControls, createContentEditor, fixtureUrl, insertComponent,
  saveEditor, visualAssert, waitForEditorReady,
} from '../assets/playwright-runner/support/editor-skeleton.mjs';

function credentialsConfig(url) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'uia-editor-'));
  const file = path.join(dir, 'credentials.json');
  fs.writeFileSync(file, JSON.stringify({ account: 'fixture-user', password: 'fixture-pass' }), { mode: 0o600 });
  return {
    cfg: {
      site: 'shop.example.test',
      environment: { id: 'production', login_url: url, entry_url: url, cloud_url: url },
      network: { mode: 'direct' },
      auth: { provider: 'leadong', credentials_file: file, storage_state: path.join(dir, 'state.json') },
      targets: { admin: url, public: 'https://shop.example.test' },
    },
  };
}

async function withBrowser(fn) {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    await fn(page);
  } finally { await browser.close(); }
}

test('editor primitives use env credentials, click the slash card, and round-trip text', async () => {
  const source = fs.readFileSync(new URL('../assets/playwright-runner/support/editor-skeleton.mjs', import.meta.url), 'utf8');
  assert.equal(source.includes('fixture-pass'), false);
  assert.equal(source.includes('password:'), false);
  await withBrowser(async page => {
    const url = fixtureUrl();
    const editor = createContentEditor(() => page, { ...credentialsConfig(url), env: { UIA_MIDSCENE: '0' } });
    await editor.login({ fixture: url });
    const site = await editor.enterSite();
    assert.equal(site.ok, true);
    await editor.openContentEditor({ kind: 'product' });
    await editor.typeText('hello');
    const inserted = await editor.insertComponent('FAQ');
    assert.equal(inserted.keyboardFallbacks, 0);
    assert.equal(inserted.rescued, 0);
    await editor.save();
    await editor.readBack({ value: 'hello' });
    await editor.selectMenuItem('标题');
  });
});

test('missing editor, missing card, and midscene rescue have typed results', async () => {
  await withBrowser(async page => {
    await page.setContent('<main></main>');
    await assert.rejects(() => waitForEditorReady(page, { timeout: 600 }), error => error instanceof SkeletonError && error.code === CODES.EDITOR_NOT_READY);
    const url = fixtureUrl();
    const editor = createContentEditor(() => page, { ...credentialsConfig(url), env: { UIA_MIDSCENE: '0' } });
    await editor.login({ fixture: url });
    await editor.enterSite();
    await editor.openContentEditor({ kind: 'product' });
    await assert.rejects(() => insertComponent(page, 'FAQ', { cardSelector: '.missing-card', env: { UIA_MIDSCENE: '0' } }),
      error => error.code === 'CONTROL_MISSING');
    const rescued = await insertComponent(page, 'FAQ', {
      cardSelector: '.missing-card',
      env: { UIA_MIDSCENE: '0' },
      adapter: { locate: async current => {
        let target;
        for (const frame of current.frames()) {
          if (await frame.locator('.ProseMirror').isVisible().catch(() => false)) target = frame;
        }
        await target.locator('#slash-menu').evaluate(node => { node.hidden = false; });
        return target.locator('.slash-card[data-component="FAQ"]');
      } },
    });
    assert.equal(rescued.rescued, 1);
    const visual = await visualAssert(page, 'a saved chip is visible', { env: { UIA_MIDSCENE: '0' } });
    assert.equal(visual.skipped, true);
    assert.equal(visual.reason, 'no-model-key');
  });
});

test('site entry dismisses the observed acknowledgement modal without clicking unrelated actions', async () => {
  await withBrowser(async page => {
    await page.setContent(`<main>
      <div class="announcement-overlay">
        <section><h2>本周功能上线</h2>
          <button class="buttonKnow ldClickBtn hasMessage_url" onclick="this.closest('.announcement-overlay').remove()">我知道了</button>
          <button onclick="document.body.dataset.details = 'opened'">查看详情</button>
        </section>
      </div>
      <a>内容管理</a>
    </main>`);
    await dismissShellNotices(page);
    assert.equal(await page.locator('.announcement-overlay').count(), 0);
    assert.equal(await page.locator('body').getAttribute('data-details'), null);
    assert.equal(await page.getByText('内容管理', { exact: true }).isVisible(), true);
  });
});

test('site area hovers a hidden card entry, dismisses known notices, and follows a cross-origin popup', async () => {
  await withBrowser(async page => {
    const server = createServer((_request, response) => {
      response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
      response.end('<main id="topNavigator">内容管理后台</main>');
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    try {
      const address = server.address();
      await page.setContent(`<main>
        <div class="member-warning-box"><button class="member-warning-close" onclick="this.parentElement.remove()">关闭</button></div>
        <div class="contentShow"><a href="https://site.test/">site</a>
          <a class="contentShow-des-a userEditSite" href="http://127.0.0.1:${address.port}/management" target="_blank">内容管理</a>
        </div></main><style>.contentShow-des-a{display:none}.contentShow:hover .contentShow-des-a{display:inline}</style>`);
      const destination = await openSiteArea(page, { site: 'site.test' }, '内容管理');
      assert.equal(new URL(destination.url()).origin, `http://127.0.0.1:${address.port}`);
      assert.equal(await destination.locator('#topNavigator').isVisible(), true);
      assert.equal(await page.locator('.member-warning-box').count(), 0);
    } finally {
      await new Promise(resolve => server.close(resolve));
    }
  });
});

test('save accepts the product editor success dialog when no automation marker exists', async () => {
  await withBrowser(async page => {
    await page.setContent(`<button id="save" onclick="document.querySelector('#result').hidden = false">保存</button>
      <div id="result" class="layui-layer" hidden><h2>保存成功</h2><p>产品保存成功！</p></div>`);
    const result = await saveEditor(page);
    assert.deepEqual(result, { ok: true, signal: 'success-notice' });
  });
});

test('guided exploration converts visible editor controls into stable locators', async () => {
  await withBrowser(async page => {
    await page.goto(fixtureUrl() + '?autodrive=1');
    const prod = page.frameLocator('iframe[name="prod"]');
    await prod.getByText('产品', { exact: true }).click();
    await prod.locator('a[href*="invokeAction=prod_new_update"]').click();
    await prod.getByText('产品描述', { exact: true }).click();
    await waitForEditorReady(page, { timeout: 10000 });
    let canvas;
    for (const frame of page.frames()) {
      if (frame.url().includes('canvas.html') && await frame.locator('.ProseMirror').isVisible().catch(() => false)) canvas = frame;
    }
    await canvas.locator('.ProseMirror').click();
    await canvas.locator('.ProseMirror').click();
    await page.keyboard.type('/');
    await canvas.locator('.slash-card').first().waitFor({ state: 'visible' });
    const report = await collectEditorControls(page, { env: { UIA_MIDSCENE: '0' } });
    assert.equal(report.midscene, 'skipped');
    const save = report.controls.find(item => item.selector === '#save');
    const card = report.controls.find(item => item.selector === '[data-component="FAQ"]');
    assert.equal(save.match_count, 1);
    assert.equal(card.strategy, 'data-component');
    assert.ok(card.nested_frames.includes('#tiptap-iframe') || card.frame === '#tiptap-iframe');
  });
});
