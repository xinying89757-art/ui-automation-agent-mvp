#!/usr/bin/env node
// Local browser fallback: one JSON command per stdin line, no model API dependency.
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import crypto from 'node:crypto';

const args = process.argv.slice(2);
const option = name => args[args.indexOf(name) + 1];
const emit = value => process.stdout.write(JSON.stringify(value) + '\n');
if (!args.includes('--config') || !args.includes('--evidence-dir')) {
  emit({ ok: false, error: 'Use --config config.json --evidence-dir <local-directory>' });
  process.exit(2);
}
const cfg = JSON.parse(fs.readFileSync(option('--config'), 'utf8'));
const evidenceDir = path.resolve(option('--evidence-dir'));
fs.mkdirSync(evidenceDir, { recursive: true });
const allowedHosts = new Set(Object.values(cfg.targets ?? {}).map(url => new URL(url).host));
const proxy = process.env[cfg.proxy_env ?? 'UI_PROXY'];
const browser = await chromium.launch({ headless: args.includes('--headless'), proxy: proxy ? { server: proxy } : undefined });
const context = await browser.newContext({ storageState: cfg.auth?.storage_state ?? undefined });
await context.newPage();
let sequence = 0;
const secretNames = new Set(cfg.auth?.secret_env ?? []);
function collectSecrets(value, sensitive = false) {
  if (Array.isArray(value)) value.forEach(child => collectSecrets(child, sensitive));
  else if (value && typeof value === 'object') {
    if (sensitive && typeof value.env === 'string') secretNames.add(value.env);
    Object.entries(value).forEach(([key, child]) => collectSecrets(child, sensitive || /password|passwd|secret|token|credential|api_key/iu.test(key)));
  }
}
collectSecrets(cfg.data_rules);
const secrets = [...secretNames].map(key => process.env[key]).filter(Boolean);
const sanitize = text => secrets.reduce((value, secret) => value.split(secret).join('[REDACTED]'), String(text));
const allowed = url => { if (!allowedHosts.has(new URL(url).host)) throw new Error('Target is outside configured hosts'); };

function locate(page, command) {
  let root = page;
  for (const frame of Array.isArray(command.frame) ? command.frame : command.frame ? [command.frame] : []) root = root.frameLocator(frame);
  if (command.within) root = root.locator(command.within);
  const t = command.target ?? {};
  if (t.role) return root.getByRole(t.role, { name: t.name, exact: t.exact ?? true });
  if (t.label) return root.getByLabel(t.label, { exact: t.exact ?? true });
  if (t.placeholder) return root.getByPlaceholder(t.placeholder, { exact: t.exact ?? true });
  if (t.testId) return root.getByTestId(t.testId);
  if (t.text) return root.getByText(t.text, { exact: t.exact ?? true });
  if (t.css) return root.locator(t.css);
  throw new Error('An observed semantic target or scoped CSS is required');
}

emit({ ok: true, session: 'ready', commands: ['pages', 'navigate', 'snapshot', 'click', 'fill', 'select', 'check', 'screenshot', 'save_auth', 'close'] });
try {
  for await (const line of readline.createInterface({ input: process.stdin, crlfDelay: Infinity })) {
    if (!line.trim()) continue;
    try {
      const command = JSON.parse(line);
      const page = context.pages()[command.page ?? 0];
      if (!page) throw new Error('Unknown page index');
      if (command.op === 'close') { emit({ ok: true, closed: true }); break; }
      if (command.op === 'pages') {
        emit({ ok: true, pages: context.pages().map((p, index) => ({ index, url: p.url() })) });
        continue;
      }
      if (command.op === 'navigate') allowed(command.url);
      else if (page.url() !== 'about:blank') allowed(page.url());
      if (command.mutates && (!cfg.mutation?.allowed || !command.scope || !cfg.mutation.scope?.includes(command.scope))) {
        throw new Error('Operation needs an authorized mutation scope');
      }
      const started = Date.now();
      const name = `${String(++sequence).padStart(4, '0')}-${crypto.randomUUID()}`;
      let observation;
      if (command.op === 'navigate') await page.goto(command.url, { waitUntil: 'domcontentloaded' });
      else if (command.op === 'snapshot') observation = await page.locator('body').ariaSnapshot();
      else if (command.op === 'screenshot') {
        await page.screenshot({ path: path.join(evidenceDir, name + '.png'), fullPage: true });
        fs.chmodSync(path.join(evidenceDir, name + '.png'), 0o600);
        observation = { screenshot: name + '.png' };
      } else if (command.op === 'save_auth') {
        if (!args.includes('--auth-out')) throw new Error('Start with a protected --auth-out path');
        const authPath = path.resolve(option('--auth-out'));
        fs.mkdirSync(path.dirname(authPath), { recursive: true });
        await context.storageState({ path: authPath });
        fs.chmodSync(authPath, 0o600);
        observation = { auth_state_file: authPath };
      } else {
        const target = locate(page, command);
        if (await target.count() !== 1) throw new Error('Target must resolve to exactly one element');
        if (command.op === 'click') await target.click();
        else if (command.op === 'fill') {
          if (command.value_env && process.env[command.value_env] === undefined) throw new Error('Required environment variable missing');
          await target.fill(command.value_env ? process.env[command.value_env] : command.value ?? '');
        } else if (command.op === 'select') await target.selectOption(command.value);
        else if (command.op === 'check') await target.setChecked(command.checked ?? true);
        else throw new Error('Unknown operation');
      }
      const evidence = { op: command.op, target: command.target, url: page.url(), scope: command.scope,
        mutates: Boolean(command.mutates), duration_ms: Date.now() - started,
        observation: observation ?? await page.locator('body').ariaSnapshot(), at: new Date().toISOString() };
      const artifact = path.join(evidenceDir, name + '.json');
      fs.writeFileSync(artifact, sanitize(JSON.stringify(evidence, null, 2)), { mode: 0o600 });
      emit({ ok: true, evidence: artifact, ...JSON.parse(sanitize(JSON.stringify(evidence))) });
    } catch (error) { emit({ ok: false, error: sanitize(error.message) }); }
  }
} finally { await context.close(); await browser.close(); }
