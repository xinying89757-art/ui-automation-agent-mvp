import { test as base } from '../support/fixtures.js';

// Exploration has no case binding or data preparation/cleanup lifecycle.
const test = base.extend({
  lifecycle: async ({}, use) => { await use(); },
});
test('authenticated editor exploration seed', async ({ page }) => { void page; });
