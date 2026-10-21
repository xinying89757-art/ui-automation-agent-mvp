import { defineConfig } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const cfg = process.env.UIA_CONFIG ? JSON.parse(fs.readFileSync(process.env.UIA_CONFIG, 'utf8')) : {};
const results = path.resolve(process.env.UIA_RESULTS_DIR ?? 'results/manual');
const proxy = process.env[cfg.proxy_env ?? 'UI_PROXY'];

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
    storageState: cfg.auth?.storage_state ?? process.env.UI_STORAGE_STATE,
    proxy: proxy ? { server: proxy } : undefined,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'off',
  },
});
