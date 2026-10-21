import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { checkEnvironment, contextOptions, loadConfig, launchOptions, resolveConfig, WorkflowError } from '../support/environment.mjs';
import { authenticatedSession, privateWrite } from '../support/auth.mjs';

export async function runSession(cfg, browser, { checkOnly = false, force = false, manual = false } = {}) {
  if (checkOnly) {
    const context = await browser.newContext(contextOptions(cfg));
    try { return { status: 'environment_verified', environment: await checkEnvironment(await context.newPage(), cfg) }; }
    finally { await context.close(); }
  }
  const session = await authenticatedSession(browser, cfg, { force, manual });
  try {
    const targets = { admin: { url: cfg.targets.admin, reachable: true, target_visible: true, authenticated: true } };
    if (cfg.targets.public) {
      const visitor = await browser.newContext(contextOptions(cfg));
      try {
        const page = await visitor.newPage();
        const response = await page.goto(cfg.targets.public, { waitUntil: 'domcontentloaded', timeout: 30000 });
        const visible = Boolean((await page.locator('body').innerText()).trim());
        targets.public = { url: cfg.targets.public, reachable: Boolean(response && response.status() < 400),
          target_visible: visible && new URL(page.url()).host === cfg.site, authenticated: false };
      } finally { await visitor.close(); }
    }
    return { status: 'authenticated', environment: session.environment, targets,
      reused: session.reused, refreshed: session.refreshed, storage_state: cfg.auth.storage_state };
  } finally { await session.context.close(); }
}
export async function main(args = process.argv.slice(2)) {
  const option = name => args.includes(name) ? args[args.indexOf(name) + 1] : undefined;
  let browser;
  try {
    const configPath = option('--config') ?? process.env.UIA_CONFIG;
    const cfg = configPath ? loadConfig(configPath) : resolveConfig({ environment: option('--environment') });
    if (!cfg.environment) throw new WorkflowError('ENVIRONMENT_REQUIRED', '请选择 p、gray 或 production 环境');
    const { chromium } = await import('@playwright/test');
    browser = await chromium.launch(launchOptions(cfg, !args.includes('--headed') && !args.includes('--manual')));
    const result = await runSession(cfg, browser, { checkOnly: args.includes('--check-only'), force: args.includes('--force'), manual: args.includes('--manual') });
    if (option('--output')) privateWrite(path.resolve(option('--output')), result);
    console.log(JSON.stringify({ ok: true, ...result }));
  } catch (error) {
    // Never include raw Playwright errors/call logs: fills may contain credentials.
    const known = error instanceof WorkflowError;
    console.log(JSON.stringify({ ok: false, code: known ? error.code : 'BROWSER_OPERATION_FAILED',
      error: known ? error.message : '浏览器操作未完成，请检查依赖、网络或页面状态', choices: known ? error.choices : ['检查运行依赖', '重新执行预检', '暂停相关用例'] }));
    process.exitCode = 2;
  } finally { await browser?.close(); }
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) await main();
