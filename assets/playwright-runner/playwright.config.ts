import { defineConfig } from '@playwright/test';
import path from 'node:path';
import { loadConfig, launchOptions, contextOptions, runtimeRoot } from './support/environment.mjs';

const cfg = loadConfig();
const { headless: _headless, ...networkLaunch } = launchOptions(cfg);
const results = path.resolve(process.env.UIA_RESULTS_DIR ?? path.join(runtimeRoot, 'results/manual'));

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: cfg.execution?.workers ?? 1,
  retries: 0,
  forbidOnly: true,
  // One case cannot hold the batch. Public-file polling has its own shorter budget.
  timeout: Math.min(cfg.execution?.timeout_ms ?? 180_000, 240_000),
  testIgnore: [
    ...(process.env.UIA_HEALER_REHEARSAL ? [] : ['**/healer-rehearsal.spec.ts']),
    ...(process.env.UIA_BATCH_ID ? ['**/seed.spec.ts'] : []),
  ],
  expect: { timeout: 15_000 },
  outputDir: path.join(results, 'artifacts'),
  reporter: [
    ['./support/uia-reporter.ts', { outputFile: path.join(results, 'case-results.json') }],
  ],
  use: {
    baseURL: cfg.targets?.public ?? process.env.UI_BASE_URL,
    // Profile-based admin authentication is explicit; public/visitor pages stay clean.
    storageState: cfg.auth?.provider === 'leadong' ? undefined : cfg.auth?.storage_state ?? process.env.UI_STORAGE_STATE,
    launchOptions: networkLaunch,
    ...contextOptions(cfg),
    actionTimeout: 20_000,
    screenshot: 'off',
    trace: 'off',
    video: 'off',
  },
});
