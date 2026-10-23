import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveActionTarget, navigateSnapshot, openTarget } from '../assets/playwright-runner/support/navigation.mjs';

function document(nodes, children = [], details = {}) {
  class Locator {
    constructor(items) { this.items = items; }
    async count() { return this.items.length; }
    nth(i) { return new Locator([this.items[i]]); }
    async isVisible() { return Boolean(this.items[0]?.visible); }
    async isEnabled() { return this.items[0]?.enabled !== false; }
    locator() { return new Locator(this.items[0]?.row ? [this.items[0].row] : []); }
    async hover() { for (const n of this.items[0]?.reveals ?? []) n.visible = true; }
    async click() { this.items[0].clicked = true; }
    async evaluate(fn) {
      if (fn.toString().includes('navigation')) return this.items[0]?.routeInfo ?? { navigation: false, destination: '', enabled: true };
      if (fn.toString().includes('aria-current')) return false;
      return Boolean(this.items[0]?.preferred || ['link', 'button'].includes(this.items[0]?.role));
    }
  }
  const match = (text, name, exact) => name === undefined || (name instanceof RegExp ? name.test(text) : exact ? name === text : text.includes(name));
  return {
    getByText(name, { exact }) { return new Locator(nodes.filter(n => match(n.text, name, exact))); },
    getByRole(role, { name, exact }) { return new Locator(nodes.filter(n => n.role === role && match(n.text, name, exact))); },
    getByTitle(name, { exact }) { return new Locator(nodes.filter(n => n.title && match(n.title, name, exact))); },
    childFrames: () => children, mainFrame() { return this; },
    isDetached: () => Boolean(details.detached),
    evaluate: async () => { if (details.crossOrigin) throw new Error('denied'); return true; },
    frameElement: async () => ({ isVisible: async () => true, evaluate: async () => details.selector ?? '#frame' }),
    name: () => details.name ?? '', url: () => 'https://backend.test' + (details.path ?? '/list'),
    context: () => ({ on() {}, off() {} }),
  };
}

test('exact visible matches search main first then depth-first same-origin nested frames', async () => {
  const top = { text: '编辑', role: 'link', visible: true };
  const hidden = { text: '编辑', role: 'link', visible: false };
  const nested = { text: '编辑', role: 'link', visible: true };
  const sibling = { text: '编辑', role: 'link', visible: true };
  const child = document([], [document([nested], [], { selector: '#nested', path: '/edit' })]);
  const page = document([hidden, top], [document([sibling], [], { crossOrigin: true }), child, document([sibling])]);
  assert.equal((await resolveActionTarget(page, 'text=编辑', { map: {} })).locator.items[0], top);
  top.visible = false;
  const result = await resolveActionTarget(page, 'role=link[name=编辑]', { map: {} });
  assert.equal(result.locator.items[0], nested);
  assert.deepEqual(result.frame, { selector: '#nested', name: '', path: '/edit' });
});

test('short case-insensitive substring prefers links/buttons and long text stays exact', async () => {
  const label = { text: 'PRODUCT overview', visible: true };
  const link = { text: 'Product list', role: 'link', visible: true, preferred: true };
  const page = document([label, link]);
  assert.equal((await resolveActionTarget(page, 'text=product', { map: {} })).locator.items[0], link);
  assert.equal(await resolveActionTarget(page, 'text=PRODUCT overview extra', { map: {} }), null);
});

test('navigation route resolves duplicate text to the visible enabled navigation link', async () => {
  const content = { text: '文章', role: 'link', visible: true, routeInfo: { navigation: false, destination: '/article/body', enabled: true } };
  const nav = { text: '文章', role: 'link', visible: true, routeInfo: { navigation: true, destination: '/articles', enabled: true } };
  const page = document([content, nav]);
  page.mainFrame = () => page;
  page.context = () => ({ on() {}, off() {} });
  const result = await navigateSnapshot(page, {}, { map: {}, routeReplay: true, steps: ['click:text=文章'] });
  assert.equal(result.failed_step, null);
  assert.equal(nav.clicked, true);
  assert.equal(content.clicked, undefined);
});

test('navigation route reports ambiguity when duplicate candidates have different destinations', async () => {
  const first = { text: '文章', role: 'link', visible: true, routeInfo: { navigation: true, destination: '/articles', enabled: true } };
  const second = { text: '文章', role: 'link', visible: true, routeInfo: { navigation: true, destination: '/news', enabled: true } };
  const page = document([first, second]);
  page.mainFrame = () => page;
  page.context = () => ({ on() {}, off() {} });
  const result = await navigateSnapshot(page, {}, { map: {}, routeReplay: true, steps: ['click:text=文章'] });
  assert.match(result.failed_step.reason, /UIA_LOCATOR_AMBIGUOUS: 2/u);
  assert.equal(first.clicked, undefined);
  assert.equal(second.clicked, undefined);
});

test('openTarget replays a confirmed knowledge entry route', async () => {
  const labels = ['内容管理', '文章', '编辑', '导入', 'Markdown'];
  const nodes = labels.map((text, index) => ({ text, role: 'link', visible: true,
    routeInfo: { navigation: true, destination: '/route/' + index, enabled: true } }));
  const page = document(nodes);
  page.mainFrame = () => page;
  page.context = () => ({ on() {}, off() {} });
  await openTarget(page, 'article-editor-markdown-import', { map: {}, cfg: { environment: { entry_url: 'https://backend.test/' } } });
  assert.deepEqual(nodes.map(node => Boolean(node.clicked)), labels.map(() => true));
});

test('hidden row action is revealed by hover and step reports matched frame', async () => {
  const edit = { text: '编辑', preferred: true, visible: false };
  edit.row = { visible: true, reveals: [edit] };
  const passive = { text: '编辑', visible: true };
  const page = document([], [document([passive, edit], [], { selector: '#prod', name: 'prod', path: '/products' })]);
  const result = await navigateSnapshot(page, {}, { map: {}, steps: ['click:text=编辑'] });
  assert.equal(result.failed_step, null);
  assert.equal(edit.clicked, true);
  assert.equal(passive.clicked, undefined);
  assert.deepEqual(result.steps[0], { index: 1, frame: { selector: '#prod', name: 'prod', path: '/products' } });
});

test('explicit frames apply only after entry actions', async () => {
  const edit = { text: '编辑', role: 'link', visible: true };
  const tool = { text: '工具', role: 'button', visible: true };
  const page = document([edit]);
  const frames = [];
  const targetRoot = { getByText: () => ({ filter: () => ({ first: () => ({ click: async () => { tool.clicked = true; } }) }) }) };
  page.frameLocator = selector => { frames.push(selector); return targetRoot; };
  const result = await navigateSnapshot(page, {}, { map: {}, frame: '#inner', entrySteps: 1, steps: ['click:text=编辑', 'click:text=工具'] });
  assert.equal(result.failed_step, null);
  assert.equal(edit.clicked, true);
  assert.equal(tool.clicked, true);
  assert.deepEqual(frames, ['#inner']);
});
