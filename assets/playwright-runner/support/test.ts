import { test as base, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import type { CaseContext, FixtureHooks } from './contracts.js';
import type { Page, BrowserContext } from '@playwright/test';
import { loadConfig, runtimeRoot } from './environment.mjs';
import { authenticatedSession, openSiteArea } from './auth.mjs';
import { cancelDialog } from '../flows/llms-txt.mjs';
import { redactedDialogScreenshot } from './review-screenshot.mjs';

export { expect };

function dataRules(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(dataRules);
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    if (typeof record.env === 'string') {
      const resolved = process.env[record.env];
      if (resolved === undefined && record.required !== false) throw new Error(`UIA_ENVIRONMENT_BLOCKED: missing data variable ${record.env}`);
      return resolved;
    }
    return Object.fromEntries(Object.entries(record).map(([key, child]) => [key, dataRules(child)]));
  }
  return value;
}

export type SiteSession = {
  openArea(area?: '内容管理' | '编辑网站'): Promise<Page>;
};

export const test = base.extend<{ caseContext: CaseContext; lifecycle: void; adminPage: Page; adminContext: BrowserContext }, { siteSession: SiteSession }>({
  siteSession: [async ({ browser }, use) => {
    const cfg = loadConfig();
    const session = await authenticatedSession(browser, cfg, { allowLogin: false });
    let editor: Page | undefined;
    const openArea = async (area?: '内容管理' | '编辑网站'): Promise<Page> => {
      if (!area) return session.page;
      if (area === '编辑网站' && editor && !editor.isClosed()) {
        await cancelDialog(editor).catch(() => {});
        return editor;
      }
      const opened = await openSiteArea(session.page, cfg, area);
      if (area === '编辑网站') editor = opened;
      return opened;
    };
    try {
      await use({ openArea });
    } finally {
      if (editor && !editor.isClosed()) await cancelDialog(editor).catch(() => {});
      await session.context.close();
    }
  }, { scope: 'worker' }],
  caseContext: async ({ siteSession, browser, context, page }, use, info) => {
    const caseId = /^\[([^\]]+)\]/u.exec(info.title)?.[1];
    if (!caseId) throw new Error('UIA_ENVIRONMENT_BLOCKED: test title must start with [case_id]');
    const cfg = loadConfig();
    const bindingFile = process.env.UIA_CASES_FILE ?? path.join(runtimeRoot, 'cases.json');
    const binding = JSON.parse(fs.readFileSync(bindingFile, 'utf8'))[caseId];
    const rules = binding?.fixture_ids?.length
      ? Object.fromEntries(binding.fixture_ids.map((id: string) => [id, cfg.data_rules?.[id]]))
      : cfg.data_rules ?? {};
    const batchId = process.env.UIA_BATCH_ID ?? `manual-${Date.now()}`;
    process.env.UIA_CASE_ID = caseId;
    info.annotations.push({ type: 'uia_case', description: caseId });
    const openAdmin = async (area?: '内容管理' | '编辑网站'): Promise<Page> => {
      try {
        return await siteSession.openArea(area);
      } catch (error) {
        const code = (error as { code?: string }).code;
        const blocked = new Set(['AUTH_REQUIRED', 'CAPTCHA_REQUIRED', 'LOGIN_FAILED', 'LOGIN_FORM_MISSING', 'CREDENTIALS_REQUIRED', 'ENVIRONMENT_UNREACHABLE', 'ENVIRONMENT_MISMATCH', 'ENVIRONMENT_HTTP_ERROR', 'GRAY_NOT_CONFIRMED', 'INVALID_CREDENTIALS', 'SITE_NOT_ACCESSIBLE', 'SITE_PERMISSION_DENIED', 'SITE_PERMISSION_UNVERIFIED', 'SITE_AMBIGUOUS', 'ACCOUNT_CHANGED', 'MANUAL_LOGIN_TIMEOUT']);
        if (code && blocked.has(code)) throw new Error(`UIA_ENVIRONMENT_BLOCKED: ${(error as Error).message}`);
        throw error;
      }
    };
    await use({ caseId, batchId, ownerMarker: `uia-${batchId}-${caseId}`,
      spec: binding?.spec, networkCatalog: binding?.network_catalog, targets: cfg.targets ?? {}, dataRules: dataRules(rules) as Record<string, unknown>, browser, context, page, openAdmin });
  },
  adminPage: async ({ caseContext }, use) => { await use(await caseContext.openAdmin()); },
  adminContext: async ({ adminPage }, use) => { await use(adminPage.context()); },
  lifecycle: [async ({ caseContext }, use, info) => {
    const bindingFile = process.env.UIA_CASES_FILE ?? path.join(runtimeRoot, 'cases.json');
    const entries = JSON.parse(fs.readFileSync(bindingFile, 'utf8'));
    const entry = entries[caseContext.caseId];
    if (!entry?.hooks) throw new Error('UIA_ENVIRONMENT_BLOCKED: registered fixture hooks missing');
    const fixtureIds: string[] = entry.fixture_ids?.length ? entry.fixture_ids : [`case:${caseContext.caseId}`];
    const contaminationDir = process.env.UIA_CONTAMINATION_DIR ?? path.join(runtimeRoot, 'results/contaminated');
    const marker = (id: string) => path.join(contaminationDir, `${createHash('sha256').update(id).digest('hex')}.json`);
    if (fixtureIds.some(id => fs.existsSync(marker(id)))) {
      throw new Error('UIA_ENVIRONMENT_BLOCKED: a dependent fixture requires verified cleanup');
    }
    const module = await import(pathToFileURL(path.resolve(runtimeRoot, entry.hooks)).href);
    const hooks: FixtureHooks = module.default;
    for (const method of ['prepare', 'verifyPrepared', 'cleanup', 'verifyCleanup'] as const) {
      if (typeof hooks?.[method] !== 'function') throw new Error(`UIA_ENVIRONMENT_BLOCKED: fixture lacks ${method}`);
    }
    let state: unknown;
    let setupVerified = false;
    let cleanupVerified = false;
    let cleanupError: unknown;
    await info.attach('uia-setup-started', { contentType: 'application/json',
      body: Buffer.from(JSON.stringify({ case_id: caseContext.caseId, batch_id: caseContext.batchId })) });
    try {
      try {
        state = await hooks.prepare(caseContext);
        caseContext.fixtureState = state;
        setupVerified = await hooks.verifyPrepared(caseContext, state);
        if (!setupVerified) throw new Error('Prepared state was not verified');
      } catch (error) {
        throw new Error(`UIA_SETUP_FAILED: ${String(error)}`);
      }
      await use();
    } finally {
      if (info.status !== info.expectedStatus && info.errors.some(error => /UIA_BUSINESS_FAILURE/u.test(error.message ?? '')) &&
          !info.attachments.some(attachment => attachment.name === 'uia-redacted-dialog')) {
        const directory = path.join(process.env.UIA_RESULTS_DIR ?? info.outputDir, 'review-screenshots');
        fs.mkdirSync(directory, { recursive: true });
        for (const candidate of caseContext.browser.contexts().flatMap(context => context.pages())) {
          const destination = path.join(directory, `${caseContext.caseId}.redacted.png`);
          const proof = await redactedDialogScreenshot(candidate, destination).catch(() => null);
          if (proof?.redacted) {
            await info.attach('uia-redacted-dialog', { path: destination, contentType: 'image/png' });
            break;
          }
        }
      }
      try {
        await hooks.cleanup(caseContext, state ?? caseContext.fixtureState);
        cleanupVerified = await hooks.verifyCleanup(caseContext, state ?? caseContext.fixtureState);
        if (!cleanupVerified && !(caseContext as any).cleanupPending) throw new Error('Restored baseline was not verified');
      } catch (error) {
        cleanupError = error;
        if (entry.mutates) {
          fs.mkdirSync(contaminationDir, { recursive: true });
          for (const id of fixtureIds) fs.writeFileSync(marker(id), JSON.stringify({
            fixture_id: id, batch_id: caseContext.batchId, case_id: caseContext.caseId,
          }), { mode: 0o600 });
        }
      }
      await info.attach('uia-lifecycle', { contentType: 'application/json', body: Buffer.from(JSON.stringify({
        case_id: caseContext.caseId, batch_id: caseContext.batchId,
        setup_verified: setupVerified, cleanup_verified: cleanupVerified, cleanup_pending: Boolean((caseContext as any).cleanupPending),
        owner_marker: caseContext.ownerMarker, fixture_ids: entry.fixture_ids,
      })) });
      if (cleanupError) throw new Error(`UIA_CLEANUP_FAILED: ${String(cleanupError)}`);
    }
  }, { auto: true }],
});

/** Keep business expectations separate from setup and automation failures. */
export async function businessAssertion(id: string, assertion: () => Promise<void>): Promise<void> {
  await test.step(`assert:${id}`, async () => {
    try { await assertion(); }
    catch (error) { throw new Error(`UIA_BUSINESS_FAILURE [${id}]: ${String(error)}`); }
  });
}
