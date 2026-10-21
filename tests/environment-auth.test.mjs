import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import { resolveConfig, environments, launchOptions, checkEnvironment, networkFingerprint, hash, runtimeRoot } from '../assets/playwright-runner/support/environment.mjs';
import { runSession } from '../assets/playwright-runner/scripts/session.mjs';
import { chooseSite, authenticatedSession, reusableState, privateWrite, sessionBinding } from '../assets/playwright-runner/support/auth.mjs';

function privateConfig(environment = 'p') {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'uia-auth-'));
  const credential = path.join(directory, 'credentials.json');
  privateWrite(credential, { account: 'offline-user', password: 'offline-password' });
  const cfg = resolveConfig({ environment, site: 'en.example.test', auth: { provider: 'leadong',
    identity: hash('offline-user'), credentials_file: credential, storage_state: path.join(directory, 'session.json') } });
  return { directory, cfg, close: () => fs.rmSync(directory, { recursive: true, force: true }) };
}
function fakeBrowser({ outcome = 'success', cachedValid = false, wrongDomain = false, captcha = false, manual = false } = {}) {
  const state = { submissions: 0, contexts: [], closed: 0 };
  return { state, async newContext(options) {
    state.contexts.push(options);
    let loggedIn = Boolean(options.storageState && cachedValid);
    let current = 'about:blank';
    const locator = selector => ({
      first() { return this; }, last() { return this; },
      async isVisible() { return selector === '#loginName' ? !loggedIn : selector.includes('captcha') ? captcha : false; },
      async hover() {}, async waitFor() {},
      async fill() {},
      async click() { if (selector === '#loginSubmit') { state.submissions++; loggedIn = outcome === 'success'; if (loggedIn) current = new URL('/website.html', current).href; } },
      async innerText() { return selector === 'body' ? '账号或密码错误' : ''; },
      async evaluateAll() { return loggedIn ? [{ host: wrongDomain ? 'other.example.test' : 'en.example.test', key: 'card:0', cardIndex: 0, kind: 'card' }] : []; },
    });
    const page = {
      async goto(url) { current = loggedIn ? url : new URL('/login.html', url).href;
        return { status: () => 200, allHeaders: async () => ({ 'x-via': 'Ld-Gray' }) }; },
      url: () => current, locator, getByText: () => locator('cloud-link'), async waitForFunction() { if (manual) { loggedIn = true; current = new URL('/website.html', current).href; } },
    };
    return { async newPage() { return page; }, async storageState() { return { cookies: [], origins: [] }; },
      async close() { state.closed++; } };
  } };
}

test('three independent initial URLs; explicit production ignores ambient proxy', () => {
  assert.equal(environments.p.entry_url, 'http://jianzhan.leadong.com/website.html');
  assert.equal(environments.gray.entry_url, 'http://www.leadong.com/website.html');
  assert.equal(environments.production.entry_url, 'https://www.leadong.com/website.html');
  const cfg = resolveConfig({ environment: 'production' }, undefined, { UI_PROXY: 'http://unexpected:9999' });
  assert.equal(cfg.network.mode, 'direct');
  assert.equal(launchOptions(cfg).proxy, undefined);
  assert.deepEqual(launchOptions(cfg).args, ['--no-proxy-server']);
  assert.equal(resolveConfig({ environment: 'p' }).network.server, 'http://101.43.28.166:7128');
  assert.throws(() => resolveConfig({ environment: 'production', network: { mode: 'proxy', server: 'http://bad' } }), { code: 'INVALID_NETWORK' });
});

test('legacy proxy env supports explicit no-proxy sentinel', () => {
  assert.equal(resolveConfig({}, undefined, { UI_PROXY: 'none' }).network.mode, 'direct');
  assert.equal(resolveConfig({}, undefined, { UI_PROXY: 'http://old:7128' }).network.mode, 'proxy');
});

test('bundled PAC preserves HTTPS, HTTP, bypasses, and AWS monitoring routes', () => {
  const cfg = resolveConfig({ environment: 'gray' });
  assert.equal(new URL(launchOptions(cfg).args[0].split('=')[1]).protocol, 'file:');
  const sandbox = {};
  vm.runInNewContext(fs.readFileSync(cfg.network.pac_file, 'utf8'), sandbox, { timeout: 1000 });
  assert.equal(sandbox.FindProxyForURL('https://www.leadong.com', 'www.leadong.com'), 'HTTPS 110.42.247.224:443');
  assert.equal(sandbox.FindProxyForURL('http://en.test.ldyjz.com', 'en.test.ldyjz.com'), 'PROXY 110.42.247.224:80');
  assert.equal(sandbox.FindProxyForURL('http://localhost', 'localhost'), 'DIRECT');
  assert.equal(sandbox.FindProxyForURL('https://example.org', 'example.org'), 'DIRECT');
  assert.equal(sandbox.FindProxyForURL('http://monitor.apisix.leadong.com', 'monitor.apisix.leadong.com'), 'PROXY 52.83.173.246:7128');
  assert.equal(launchOptions(cfg).proxy, undefined, 'fixed proxy must not override the PAC');
});

test('gray preflight allows same-host HTTPS redirect and requires actual marker', async () => {
  const cfg = resolveConfig({ environment: 'gray' });
  let start;
  const page = { goto: async url => { start = url; return { status: () => 200, allHeaders: async () => ({ 'x-via': 'Ld-Gray' }) }; },
    url: () => 'https://www.leadong.com/login.html' };
  const evidence = await checkEnvironment(page, cfg);
  assert.equal(start, environments.gray.entry_url);
  assert.equal(evidence.verified, true);
  assert.equal(evidence.network_fingerprint, networkFingerprint(cfg));
  page.goto = async () => ({ status: () => 200, allHeaders: async () => ({}) });
  await assert.rejects(checkEnvironment(page, cfg), { code: 'GRAY_NOT_CONFIRMED' });
  page.url = () => 'https://unexpected.example/login.html';
  await assert.rejects(checkEnvironment(page, cfg), { code: 'ENVIRONMENT_MISMATCH' });
});

test('site identity uses exact language hostname and rejects ambiguous cards', () => {
  const candidates = [{ host: 'en.example.test', key: 'one' }, { host: 'example.test', key: 'two' }];
  assert.equal(chooseSite(candidates, 'https://en.example.test/').key, 'one');
  assert.throws(() => chooseSite(candidates, 'other.test'), { code: 'SITE_NOT_ACCESSIBLE' });
  assert.throws(() => chooseSite([...candidates, { host: 'en.example.test', key: 'three' }], 'en.example.test'), { code: 'SITE_AMBIGUOUS' });
});

test('successful shared login submits once and saves private isolated state', async () => {
  const f = privateConfig();
  try {
    const browser = fakeBrowser();
    const session = await authenticatedSession(browser, f.cfg);
    assert.equal(browser.state.submissions, 1);
    assert.equal(session.refreshed, true);
    assert.equal(fs.statSync(f.cfg.auth.storage_state).mode & 0o777, 0o600);
    assert.equal(reusableState(f.cfg), f.cfg.auth.storage_state);
    assert.equal(reusableState(resolveConfig({ ...f.cfg, environment: 'gray' })), undefined);
    assert.equal(reusableState({ ...f.cfg, site: 'fr.example.test' }), undefined);
    await session.context.close();
  } finally { f.close(); }
});

test('expired cache relogs once; wrong password never retries and closes context', async () => {
  const f = privateConfig();
  try {
    privateWrite(f.cfg.auth.storage_state, { cookies: [], origins: [] });
    privateWrite(`${f.cfg.auth.storage_state}.meta.json`, { binding: sessionBinding(f.cfg) });
    const expired = fakeBrowser();
    const refreshed = await authenticatedSession(expired, f.cfg);
    assert.equal(expired.state.submissions, 1);
    assert.equal(refreshed.reused, false);
    await refreshed.context.close();
    const invalid = fakeBrowser({ outcome: 'invalid' });
    await assert.rejects(authenticatedSession(invalid, f.cfg), { code: 'INVALID_CREDENTIALS' });
    assert.equal(invalid.state.submissions, 1);
    assert.equal(invalid.state.closed, 1);
    const testExecution = fakeBrowser();
    await assert.rejects(authenticatedSession(testExecution, f.cfg, { allowLogin: false }), { code: 'AUTH_REQUIRED' });
    assert.equal(testExecution.state.submissions, 0, 'test execution must not record password fills');
  } finally { f.close(); }
});

test('cached session still requires current target-site permission', async () => {
  const f = privateConfig();
  try {
    privateWrite(f.cfg.auth.storage_state, { cookies: [], origins: [] });
    privateWrite(`${f.cfg.auth.storage_state}.meta.json`, { binding: sessionBinding(f.cfg) });
    const browser = fakeBrowser({ cachedValid: true, wrongDomain: true });
    await assert.rejects(authenticatedSession(browser, f.cfg), { code: 'SITE_NOT_ACCESSIBLE' });
    assert.equal(browser.state.submissions, 0);
  } finally { f.close(); }
});

test('captcha requests human input before submitting any password', async () => {
  const f = privateConfig();
  try {
    const browser = fakeBrowser({ captcha: true });
    await assert.rejects(authenticatedSession(browser, f.cfg), { code: 'CAPTCHA_REQUIRED' });
    assert.equal(browser.state.submissions, 0);
    assert.equal(browser.state.closed, 1);
  } finally { f.close(); }
});

test('login preflight checks public site in a separate clean context', async () => {
  const f = privateConfig();
  try {
    const browser = fakeBrowser();
    const result = await runSession(f.cfg, browser);
    assert.equal(result.targets.admin.authenticated, true);
    assert.equal(result.targets.public.authenticated, false);
    assert.equal(browser.state.contexts.length, 2);
    assert.equal(browser.state.contexts[1].storageState, undefined);
    assert.equal(browser.state.closed, 2);
  } finally { f.close(); }
});

test('per-environment URL overrides preserve independent entries and scheme constraints', () => {
  const cfg = resolveConfig({ environment: { id: 'p', entry_url: 'http://p.example.test/start',
    login_url: 'http://p.example.test/login', cloud_url: 'http://p.example.test/cloud' } });
  assert.equal(cfg.environment.entry_url, 'http://p.example.test/start');
  assert.equal(cfg.environment.login_url, 'http://p.example.test/login');
  assert.equal(cfg.targets.admin, 'http://p.example.test/cloud');
  assert.throws(() => resolveConfig({ environment: { id: 'gray', entry_url: 'https://www.leadong.com/website.html' } }), { code: 'INVALID_ENVIRONMENT' });
  assert.throws(() => resolveConfig({ environment: { id: 'production', login_url: 'http://www.leadong.com/login.html' } }), { code: 'INVALID_ENVIRONMENT' });
});

test('explicit manual login waits for user and never fills/submits credentials', async () => {
  const f = privateConfig();
  try {
    const browser = fakeBrowser({ manual: true });
    const session = await authenticatedSession(browser, f.cfg, { manual: true });
    assert.equal(browser.state.submissions, 0);
    assert.equal(session.refreshed, true);
    assert.equal(reusableState(f.cfg), f.cfg.auth.storage_state);
    await session.context.close();
  } finally { f.close(); }
});
