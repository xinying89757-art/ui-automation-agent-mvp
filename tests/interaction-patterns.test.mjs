import test from 'node:test';
import assert from 'node:assert/strict';
import { clickWithPatterns } from '../assets/playwright-runner/support/interaction-patterns.mjs';

test('waits through redraw and resolves the target again before clicking', async () => {
  let resolutions = 0;
  let clicks = 0;
  const locator = () => {
    resolutions++;
    return { waitFor: async () => {}, scrollIntoViewIfNeeded: async () => {}, click: async () => { clicks++; } };
  };
  const page = { evaluate: async callback => callback() };
  globalThis.requestAnimationFrame = callback => callback();
  await clickWithPatterns(page, locator, ['RERENDER_RELOCATE']);
  assert.equal(resolutions, 2);
  assert.equal(clicks, 1);
});

test('scrolls and collapses an expanded covering panel after an intercepted click', async () => {
  let attempts = 0;
  let scrolled = 0;
  let collapsed = 0;
  const target = () => ({
    waitFor: async () => {},
    scrollIntoViewIfNeeded: async () => { scrolled++; },
    click: async () => { attempts++; if (attempts === 1) throw new Error('intercepts pointer events'); }
  });
  const collapse = { count: async () => 1, click: async () => { collapsed++; } };
  const covering = { last() { return this; }, count: async () => 1,
    locator(selector) { return selector === '..' ? this : { first: () => collapse }; } };
  const page = { locator: () => covering };
  await clickWithPatterns(page, target, ['OCCLUDED_SCROLL_OR_COLLAPSE']);
  assert.equal(scrolled, 2);
  assert.equal(collapsed, 1);
  assert.equal(attempts, 2);
});
