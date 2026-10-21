import { test as base, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import type { CaseContext, FixtureHooks } from './contracts.js';

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

export const test = base.extend<{ caseContext: CaseContext; lifecycle: void }>({
  caseContext: async ({ browser, context, page }, use, info) => {
    const caseId = /^\[([^\]]+)\]/u.exec(info.title)?.[1];
    if (!caseId) throw new Error('UIA_ENVIRONMENT_BLOCKED: test title must start with [case_id]');
    const cfg = process.env.UIA_CONFIG ? JSON.parse(fs.readFileSync(process.env.UIA_CONFIG, 'utf8')) : {};
    const binding = JSON.parse(fs.readFileSync(path.resolve('cases.json'), 'utf8'))[caseId];
    const rules = binding?.fixture_ids?.length
      ? Object.fromEntries(binding.fixture_ids.map((id: string) => [id, cfg.data_rules?.[id]]))
      : cfg.data_rules ?? {};
    const batchId = process.env.UIA_BATCH_ID ?? `manual-${Date.now()}`;
    info.annotations.push({ type: 'uia_case', description: caseId });
    await use({ caseId, batchId, ownerMarker: `uia-${batchId}-${caseId}`,
      targets: cfg.targets ?? {}, dataRules: dataRules(rules) as Record<string, unknown>, browser, context, page });
  },
  lifecycle: [async ({ caseContext }, use, info) => {
    const entries = JSON.parse(fs.readFileSync(path.resolve('cases.json'), 'utf8'));
    const entry = entries[caseContext.caseId];
    if (!entry?.hooks) throw new Error('UIA_ENVIRONMENT_BLOCKED: registered fixture hooks missing');
    const fixtureIds: string[] = entry.fixture_ids?.length ? entry.fixture_ids : [`case:${caseContext.caseId}`];
    const contaminationDir = process.env.UIA_CONTAMINATION_DIR ?? path.resolve('results/contaminated');
    const marker = (id: string) => path.join(contaminationDir, `${createHash('sha256').update(id).digest('hex')}.json`);
    if (fixtureIds.some(id => fs.existsSync(marker(id)))) {
      throw new Error('UIA_ENVIRONMENT_BLOCKED: a dependent fixture requires verified cleanup');
    }
    const module = await import(pathToFileURL(path.resolve(entry.hooks)).href);
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
      try {
        await hooks.cleanup(caseContext, state);
        cleanupVerified = await hooks.verifyCleanup(caseContext, state);
        if (!cleanupVerified) throw new Error('Restored baseline was not verified');
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
        setup_verified: setupVerified, cleanup_verified: cleanupVerified,
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
