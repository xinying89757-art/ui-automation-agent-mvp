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
  timeout: cfg.execution?.timeout_ms ?? 180_000,
  expect: { timeout: 10_000 },
  outputDir: path.join(results, 'artifacts'),
  reporter: [
    ['./support/uia-reporter.ts', { outputFile: path.join(results, 'case-results.json') }],
    ['json', { outputFile: path.join(results, 'playwright-results.json') }],
    ['html', { outputFolder: path.join(results, 'playwright-report'), open: 'never' }],
  ],
  use: {
    baseURL: cfg.targets?.public ?? process.env.UI_BASE_URL,
    // Profile-based admin authentication is explicit; public/visitor pages stay clean.
    storageState: cfg.auth?.provider === 'leadong' ? undefined : cfg.auth?.storage_state ?? process.env.UI_STORAGE_STATE,
    launchOptions: networkLaunch,
    ...contextOptions(cfg),
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'off',
  },
});
