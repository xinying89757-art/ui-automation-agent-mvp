import { test as base } from '../support/fixtures.js';
import { loadConfig } from '../support/environment.mjs';

// Exploration has no case binding or data preparation/cleanup lifecycle.
const test = base.extend({
  lifecycle: async ({}, use) => { await use(); },
  // Test Agents retains the built-in page; navigate that page explicitly rather
  // than relying on a lifecycle fixture to open a separate editor tab.
  page: async ({ siteSession, context }, use) => {
    const page = await context.newPage();
    const entry = process.env.UIA_SEED_ENTRY;
    const source = await siteSession.openArea(entry === 'content-admin' ? '内容管理' : entry === 'editor' ? '编辑网站' : undefined);
    await page.context().addCookies(await source.context().cookies());
    const cfg = loadConfig();
    await page.goto(source.url() === 'about:blank' ? cfg.environment.cloud_url ?? cfg.environment.entry_url : source.url(),
      { waitUntil: 'domcontentloaded' });
    await use(page);
  },
});
test('authenticated backend exploration seed', async ({ page }) => {
  if (!/^https?:/u.test(page.url())) throw new Error('UIA_ENVIRONMENT_BLOCKED: seed did not reach backend');
});
