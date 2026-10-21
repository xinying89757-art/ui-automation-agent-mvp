import type { Browser, BrowserContext, Page } from '@playwright/test';

export interface CaseContext {
  caseId: string;
  batchId: string;
  ownerMarker: string;
  targets: Record<string, string>;
  dataRules: Record<string, unknown>;
  browser: Browser;
  context: BrowserContext;
  page: Page;
  openAdmin(area?: '内容管理' | '编辑网站'): Promise<Page>;
  fixtureState?: unknown;
  spec?: Record<string, any>;
}

/** Each case supplies real UI setup and verification, including read-only prerequisites. */
export interface FixtureHooks {
  prepare(ctx: CaseContext): Promise<unknown>;
  verifyPrepared(ctx: CaseContext, state: unknown): Promise<boolean>;
  cleanup(ctx: CaseContext, state: unknown): Promise<void>;
  verifyCleanup(ctx: CaseContext, state: unknown): Promise<boolean>;
}
