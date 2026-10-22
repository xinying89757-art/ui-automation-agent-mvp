import test from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from '../assets/playwright-runner/node_modules/@playwright/test/index.mjs';
import { scopedStructure } from '../assets/playwright-runner/support/auth.mjs';

test('bounded snapshots scope containers and iframe, hide invisible nodes and identify duplicate names', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <a href="#">Contact Us</a><a href="#">Contact Us</a>
      <div id="dialog"><button>Known action</button>
        <div style="display:none"><button>Hidden library</button></div>
        <div style="opacity:0"><button>Transparent library</button></div>
        <div aria-hidden="true"><button>Aria hidden</button></div>
        <input type="password" value="fake-local-value">
      </div>
      <iframe id="backstage-innerpage" srcdoc="<button>Frame action</button>"></iframe>`);
    const full = await scopedStructure(page);
    assert.deepEqual(full.duplicate_names, [{ pair: ['link', 'Contact Us'], count: 2 }]);
    const scoped = await scopedStructure(page, { scope: '#dialog' });
    const serialized = JSON.stringify(scoped);
    assert.match(serialized, /Known action/);
    for (const hidden of ['Hidden library', 'Transparent library', 'Aria hidden', 'Contact Us', 'fake-local-value']) assert.equal(serialized.includes(hidden), false, hidden);
    const frame = await scopedStructure(page, { frame: '#backstage-innerpage' });
    assert.match(JSON.stringify(frame), /Frame action/);
    assert.equal(JSON.stringify(frame).includes('Known action'), false);
  } finally { await browser.close(); }
});

import { allowedURL, navigateSnapshot, targetLocator, openTarget, parseStep } from '../assets/playwright-runner/support/navigation.mjs';
const cfg = { environment: { entry_url: 'https://backend.test/entry', cloud_url: 'https://backend.test/cloud',
  allowed_hosts: ['https://other.test'] } };

test('goto permits only configured origins and excludes userinfo and unsafe schemes', () => {
  assert.equal(allowedURL('/new', cfg), 'https://backend.test/new');
  assert.equal(allowedURL('https://other.test/new', cfg), 'https://other.test/new');
  for (const value of ['https://outside.test/new', '//outside.test/new', 'javascript:alert(1)', 'https://user:pass@backend.test/new', 'http://backend.test/new'])
    assert.throws(() => allowedURL(value, cfg), /origin/u);
  assert.throws(() => parseStep('wait:10001'), /10000/u);
  assert.throws(() => parseStep('wait:-1'), /10000/u);
  assert.throws(() => parseStep('fill:broken'), /requires/u);
  assert.deepEqual(parseStep('fill:input[name=field]=one=two'), { verb: 'fill', target: 'input[name=field]', value: 'one=two' });
  assert.deepEqual(parseStep('fill:role=textbox[name=Field]=value'), { verb: 'fill', target: 'role=textbox[name=Field]', value: 'value' });
});

test('ordered actions use visible exact text, role, named targets, CSS, frames and scopes', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`<button style="display:none">Open</button><button>Open</button><button>Open more</button>
      <input id="field"><div id="scope"><button id="scoped">Scoped</button></div>
      <iframe id="child" srcdoc="<button id='inside'>Inside</button>"></iframe>`);
    const map = { targets: { field: { selector: '#field' }, inside: { selector: '#inside', frame: '#child' } } };
    const result = await navigateSnapshot(page, cfg, { map, steps: ['click:text=Open', 'hover:role=button[name=Open]',
      'fill:field=hello', 'press:End', 'wait:1', 'click:#scoped', 'click:inside'] });
    assert.equal(result.failed_step, null);
    assert.equal(await page.locator('#field').inputValue(), 'hello');
    await targetLocator(page, 'text=Inside', { frame: '#child', map }).click();
    await targetLocator(page, 'role=button[name=Scoped]', { scope: '#scope', map }).click();
    assert.equal(await targetLocator(page, 'text=Open', { map }).count(), 1);
    await openTarget(page, 'field', { map });
    const legacy = await navigateSnapshot(page, cfg, { frame: '#child', clicks: ['#scoped'], hover: '#scoped', steps: ['click:text=Inside'] });
    assert.equal(legacy.failed_step, null);
  } finally { await browser.close(); }
});

test('failed navigation returns reached state, bounded reason and does not run later actions', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent('<input id="field">');
    const result = await navigateSnapshot(page, cfg, { steps: ['fill:#field=before', 'wait:10001', 'fill:#field=after'] });
    assert.equal(result.failed_step.index, 2);
    assert.match(result.failed_step.reason, /10000/u);
    assert.equal(await result.page.locator('#field').inputValue(), 'before');
    const denied = await navigateSnapshot(page, cfg, { goto: 'https://outside.test/private?secret=hide' });
    assert.equal(denied.failed_step.action, 'goto:/private');
    assert.equal(denied.failed_step.reason.includes('secret'), false);
  } finally { await browser.close(); }
});

test('newest popup is followed and reports only pathname', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.context().route('https://backend.test/**', route => route.fulfill({ body: '<button>Popup action</button>', contentType: 'text/html' }));
    await page.setContent('<button onclick="window.open(\'https://backend.test/new?private=hide\')">Popup</button>');
    const result = await navigateSnapshot(page, cfg, { steps: ['click:text=Popup', 'click:text=Popup action'] });
    assert.equal(result.failed_step, null);
    assert.notEqual(result.page, page);
    assert.deepEqual(result.popups, [{ path: '/new' }]);
  } finally { await browser.close(); }
});

test('named page paths and target aliases share the generated-test opener', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.context().route('https://backend.test/**', route => route.fulfill({ body: '<button id="entry">Entry</button>', contentType: 'text/html' }));
    const map = { pages: { unseen: { path: '/new' } }, targets: { alias: { open: 'unseen' } } };
    await openTarget(page, 'alias', { map, cfg });
    assert.equal(new URL(page.url()).pathname, '/new');
    const result = await navigateSnapshot(page, cfg, { openTarget: 'missing', map });
    assert.match(result.failed_step.reason, /unknown named/u);
  } finally { await browser.close(); }
});

test('semantic text action reveals a nested row link before clicking passive duplicate text', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent('<iframe id="outer"></iframe>');
    const outer = page.frames().find(frame => frame !== page.mainFrame());
    await outer.setContent('<iframe id="list"></iframe>');
    const inner = page.frames().find(frame => frame.parentFrame() === outer);
    for (const label of ['title="编辑">✎', '><i>✎</i><span>编辑</span>']) {
      await inner.setContent(`<style>tr a {visibility:hidden} tr:hover a {visibility:visible}</style>
        <span>编辑</span><table><tr><td><a href="#" onclick="this.dataset.clicked='yes';return false" ${label}</a></td></tr></table>`);
      const result = await navigateSnapshot(page, cfg, { map: {}, steps: ['click:text=编辑'] });
      assert.equal(result.failed_step, null);
      assert.equal(await inner.locator('a').getAttribute('data-clicked'), 'yes');
      assert.equal(result.steps[0].frame.selector, '#list');
    }
    const structure = await scopedStructure(page, { frame: '#list' });
    assert.equal(structure.nodes.some(node => node.tag === 'a'), true);
  } finally { await browser.close(); }
});

test('entry replay treats a navigation click as satisfied when the next target is already showing', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent('<button id="target">Edit</button><button onclick="document.body.innerHTML=\'reloaded\'">Products</button>');
    const pre = await navigateSnapshot(page, cfg, { steps: ['click:text=Products', 'click:#target'], entrySteps: 3 });
    assert.equal(pre.failed_step, null);
    assert.deepEqual(pre.steps[0], { index: 1, skipped: 'already_satisfied' });
    await page.setContent('<button id="target">Edit</button>');
    const ok = await navigateSnapshot(page, cfg, { steps: ['click:text=Products', 'click:#target'], entrySteps: 2 });
    assert.equal(ok.failed_step, null);
    assert.deepEqual(ok.steps[0], { index: 1, skipped: 'already_satisfied' });
    const strict = await navigateSnapshot(page, cfg, { steps: ['click:text=Products', 'click:#target'] });
    assert.equal(strict.failed_step.index, 1);
  } finally { await browser.close(); }
});
