import { test as lifecycleTest, expect, businessAssertion } from './test.js';
import path from 'node:path';
import { loadConfig, runtimeRoot } from './environment.mjs';
import { cancelDialog } from '../flows/llms-txt.mjs';

/** Single seed entry for templates and AI-written specs. Visitor pages stay clean. */
export const test = lifecycleTest.extend({
  page: async ({ siteSession, context }, use, info) => {
    // Read run-local bindings; never load credentials or refresh login under tracing.
    const fs = await import('node:fs');
    const id = /^\[([^\]]+)\]/u.exec(info.title)?.[1];
    const entries = JSON.parse(fs.readFileSync(process.env.UIA_CASES_FILE ?? path.join(runtimeRoot, 'cases.json'), 'utf8'));
    const start = entries[id!]?.start_page ?? 'editor';
    if (start === 'public') {
      const visitor = await context.newPage();
      await visitor.goto(loadConfig().targets.public, { waitUntil: 'domcontentloaded' });
      await use(visitor);
      await visitor.close();
      return;
    }
    const page = await siteSession.openArea(start === 'content-admin' ? '内容管理' : '编辑网站');
    try { await use(page); }
    finally { await cancelDialog(page); }
  },
});
export { expect, businessAssertion };
