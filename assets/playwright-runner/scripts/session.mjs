import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { checkEnvironment, contextOptions, loadConfig, launchOptions, resolveConfig, WorkflowError } from '../support/environment.mjs';
import { authenticatedSession, openSiteArea, privateWrite, snapshotSession } from '../support/auth.mjs';
import { scrubText } from '../support/redact.mjs';

function safeError(error, cfg) {
  let text = scrubText(error instanceof Error ? error.message : String(error));
  try {
    if (cfg?.auth?.credentials_file && fs.existsSync(cfg.auth.credentials_file)) {
      const secrets = Object.values(JSON.parse(fs.readFileSync(cfg.auth.credentials_file, 'utf8')));
      for (const secret of secrets) {
        if (typeof secret === 'string' && secret) text = text.split(secret).join('[REDACTED]');
      }
    }
  } catch { /* A missing credential file must not hide the underlying error. */ }
  return text.replace(/\s+/g, ' ').slice(0, 400);
}

async function publicTarget(browser, cfg) {
  if (!cfg.targets.public) return null;
  const visitor = await browser.newContext(contextOptions(cfg));
  try {
    const page = await visitor.newPage();
    const response = await page.goto(cfg.targets.public, { waitUntil: 'domcontentloaded', timeout: 30000 });
    const visible = Boolean((await page.locator('body').innerText()).trim());
    let host = '';
    try { host = new URL(page.url()).host; } catch { host = ''; }
    const reachable = Boolean(response && response.status() < 400);
    return { url: cfg.targets.public, reachable, target_visible: visible && host === cfg.site, authenticated: false,
      ...(reachable ? {} : { error: `HTTP ${response ? response.status() : 'no-response'}` }) };
  } catch (error) {
    return { url: cfg.targets.public, reachable: false, target_visible: false, authenticated: false, error: safeError(error, cfg) };
  } finally { await visitor.close(); }
}

export async function runPreflight(cfg, browser, { force = false, manual = false, onProgress } = {}) {
  const started = Date.now();
  const session = await authenticatedSession(browser, cfg, { force, allowLogin: true, manual, onProgress });
  const authenticatedMs = Date.now() - started;
  const editorStarted = Date.now();
  try {
    onProgress?.('open_area');
    await openSiteArea(session.page, cfg, '编辑网站');
    const editorMs = Date.now() - editorStarted;
    const targets = { admin: { url: cfg.targets.admin, reachable: true, target_visible: true, authenticated: true,
      selected_site: session.site?.host ?? null, selection: session.site?.kind ?? null } };
    onProgress?.('public_frontend');
    const publicResult = await publicTarget(browser, cfg);
    if (publicResult) targets.public = publicResult;
    return { status: 'authenticated', environment: session.environment, targets,
      editor: { opened: true, area: '编辑网站' },
      reused: session.reused, refreshed: session.refreshed,
      timings: { authenticated_ms: authenticatedMs, editor_ms: editorMs, total_ms: Date.now() - started } };
  } finally { await session.context.close(); }
}

export async function runSession(cfg, browser, { checkOnly = false, force = false, manual = false, onProgress } = {}) {
  if (checkOnly) {
    const context = await browser.newContext(contextOptions(cfg));
    try { return { status: 'environment_verified', environment: await checkEnvironment(await context.newPage(), cfg) }; }
    finally { await context.close(); }
  }
  const session = await authenticatedSession(browser, cfg, { force, manual, onProgress });
  try {
    const targets = { admin: { url: cfg.targets.admin, reachable: true, target_visible: true, authenticated: true,
      selected_site: session.site?.host ?? null, selection: session.site?.kind ?? null } };
    onProgress?.('public_frontend');
    const publicResult = await publicTarget(browser, cfg);
    if (publicResult) targets.public = publicResult;
    return { status: 'authenticated', environment: session.environment, targets,
      reused: session.reused, refreshed: session.refreshed, storage_state: cfg.auth.storage_state };
  } finally { await session.context.close(); }
}
export async function main(args = process.argv.slice(2)) {
  const option = name => args.includes(name) ? args[args.indexOf(name) + 1] : undefined;
  let browser;
  let cfg;
  try {
    const configPath = option('--config') ?? process.env.UIA_CONFIG;
    cfg = configPath ? loadConfig(configPath) : resolveConfig({ environment: option('--environment') });
    if (!cfg.environment) throw new WorkflowError('ENVIRONMENT_REQUIRED', '请选择 p、gray 或 production 环境');
    const { chromium } = await import('@playwright/test');
    browser = await chromium.launch(launchOptions(cfg, !args.includes('--headed') && !args.includes('--manual')));
    const snapshotAt = args.indexOf('--snapshot');
    const started = Date.now();
    let stage = 'browser_start';
    let step = null;
    const progress = (next, current = null) => { stage = next; step = current; process.stderr.write(JSON.stringify({stage, step, elapsed_ms: Date.now() - started}) + '\n'); };
    const heartbeat = setInterval(() => progress(stage, step), 5000);
    heartbeat?.unref();
    const snapshotArea = snapshotAt >= 0 && args[snapshotAt + 1] && !args[snapshotAt + 1].startsWith('--')
      ? args[snapshotAt + 1] : undefined;
    const result = snapshotAt >= 0
      ? { status: 'snapshot', structure: await snapshotSession(browser, cfg, { onProgress: progress,
        entrySteps: Number(option('--entry-steps') ?? 0), area: snapshotArea, manual: args.includes('--manual'), frame: option('--frame'), scope: option('--scope'), openTarget: option('--open-target'), goto: option('--goto'), steps: args.flatMap((arg, index) => arg === '--step' ? [args[index + 1]] : []), hover: option('--hover'), clicks: args.flatMap((arg, index) => arg === '--click' ? [args[index + 1]] : []) }) }
      : args.includes('--open-editor')
        ? await runPreflight(cfg, browser, { force: args.includes('--force'), manual: args.includes('--manual'), onProgress: progress })
        : await runSession(cfg, browser, { checkOnly: args.includes('--check-only'), force: args.includes('--force'), manual: args.includes('--manual'), onProgress: progress });
    if (heartbeat) clearInterval(heartbeat);
    if (option('--output')) privateWrite(path.resolve(option('--output')), result);
    console.log(JSON.stringify({ ok: true, ...result }));
  } catch (error) {
    const known = error instanceof WorkflowError;
    console.log(JSON.stringify({ ok: false, code: known ? error.code : 'BROWSER_OPERATION_FAILED',
      error: safeError(error, cfg), choices: known ? error.choices : ['检查运行依赖', '重新执行预检', '暂停相关用例'] }));
    process.exitCode = 2;
  } finally { await browser?.close(); }
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) await main();
