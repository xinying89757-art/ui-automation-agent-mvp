import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ENTRY_NAV_TIMEOUT_MS, operationColumnIndex, previewURLFromAction,
  selectRowAction, clickPreviewForURL,
} from '../assets/playwright-runner/support/row-actions.mjs';

const toolbar = () => [
  { className: 'icon-edit blue' },
  { className: 'icon-copy blue' },
  { className: 'icon-eye green', href: '/products/item-42.html' },
  { className: 'icon-share orange' },
  { className: 'icon-trash red', title: '删除' },
];

test('operation column uses header, then confirmed last-column fallback', () => {
  assert.equal(operationColumnIndex(['名称', '状态', '操作'], 3), 2);
  assert.equal(operationColumnIndex(['名称', '状态'], 3), 2);
  assert.equal(operationColumnIndex([], 0), -1);
});

test('confirmed five-button row selects the first pencil for edit', () => {
  const chosen = selectRowAction(toolbar(), 'edit');
  assert.equal(chosen.index, 0);
  assert.match(chosen.action.className, /icon-edit/u);
});

test('delete guard refuses a candidate identified as delete or trash', () => {
  assert.throws(() => selectRowAction([
    { className: 'icon-trash red', title: '删除' }, ...toolbar().slice(1),
  ], 'edit'), error => error.code === 'DELETE_GUARD');
});

test('preview entry captures its frontend URL without navigating', () => {
  const chosen = selectRowAction(toolbar(), 'preview');
  assert.equal(chosen.index, 2);
  assert.equal(previewURLFromAction(chosen.action, 'https://admin.example.test/products'),
    'https://admin.example.test/products/item-42.html');
  assert.equal(previewURLFromAction({ href: 'https://public.example.test/item?s=opaque&lang=en' }, 'https://admin.example.test/'),
    'https://public.example.test/item?lang=en');
  assert.equal(previewURLFromAction({ href: 'javascript:delete()' }, 'https://admin.example.test/'), null);
  assert.equal(previewURLFromAction({ href: 'void(0)' }, 'https://admin.example.test/'), null);
});

test('preview popup URL is captured while document requests are aborted', async () => {
  let resolvePage;
  const popup = { url: () => 'https://public.example.test/product.html', waitForURL: async () => {}, close: async () => {} };
  const context = {
    handler: null,
    async route(_pattern, handler) { this.handler = handler; },
    async unroute() { this.handler = null; },
    waitForEvent() { return new Promise(resolve => { resolvePage = resolve; }); },
  };
  const page = { context: () => context, url: () => 'https://admin.example.test/list' };
  const locator = { click: async options => {
    assert.equal(options.noWaitAfter, true);
    assert.equal(typeof context.handler, 'function');
    resolvePage(popup);
  } };
  assert.equal(await clickPreviewForURL(page, locator), 'https://public.example.test/product.html');
  assert.equal(context.handler, null);
});

test('entry navigation has a hard sixty second ceiling', () => {
  assert.equal(ENTRY_NAV_TIMEOUT_MS, 60_000);
});
