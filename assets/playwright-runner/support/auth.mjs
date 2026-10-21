import fs from 'node:fs';
import path from 'node:path';
import { checkEnvironment, contextOptions, fail, hash, host, networkFingerprint, WorkflowError } from './environment.mjs';

const visible = locator => locator.isVisible().catch(() => false);
export function credentials(cfg) {
  if (!cfg.auth?.credentials_file) fail('CREDENTIALS_REQUIRED', '请先通过 setup 配置账号，或提供本地凭据文件');
  let value;
  try { value = JSON.parse(fs.readFileSync(cfg.auth.credentials_file, 'utf8')); }
  catch { fail('CREDENTIALS_REQUIRED', '无法读取本地凭据文件'); }
  if (typeof value.account !== 'string' || !value.account.trim() || typeof value.password !== 'string' || !value.password) {
    fail('CREDENTIALS_REQUIRED', '本地凭据文件需要 account 和 password');
  }
  return value;
}
export function sessionBinding(cfg) {
  const accountHash = cfg.auth?.credentials_file ? hash(credentials(cfg).account.trim()) : cfg.auth?.identity;
  if (cfg.auth?.identity && accountHash !== cfg.auth.identity) fail('ACCOUNT_CHANGED', '账号已变化，请重新运行 setup 更新配置');
  return hash(JSON.stringify([cfg.environment, networkFingerprint(cfg), accountHash, cfg.site]));
}
export function reusableState(cfg) {
  const file = cfg.auth?.storage_state;
  if (!file || !fs.existsSync(file)) return undefined;
  if (cfg.auth.provider !== 'leadong') return file;
  try {
    const meta = JSON.parse(fs.readFileSync(`${file}.meta.json`, 'utf8'));
    return meta.binding === sessionBinding(cfg) ? file : undefined;
  } catch (error) { if (error instanceof WorkflowError) throw error; return undefined; }
}
export function privateWrite(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.tmp-${process.pid}`;
  fs.writeFileSync(temporary, JSON.stringify(value, null, 2), { mode: 0o600 });
  fs.chmodSync(temporary, 0o600);
  fs.renameSync(temporary, file);
}
export async function saveSession(context, cfg) {
  const file = cfg.auth?.storage_state;
  if (!file) fail('STATE_PATH_REQUIRED', '请配置受保护的登录态输出路径');
  // Credentials and storage state are never copied into test reports.
  privateWrite(file, await context.storageState());
  privateWrite(`${file}.meta.json`, { binding: sessionBinding(cfg), saved_at: new Date().toISOString() });
}
export async function isLoginPage(page) {
  const field = page.locator('#loginName');
  if (await visible(field)) return true;
  try { await field.waitFor({ state: 'visible', timeout: 5000 }); } catch { /* the entry URL can render the form late */ }
  if (await visible(field)) return true;
  return /\/(?:login|signin)(?:[./?]|$)/iu.test(new URL(page.url()).pathname);
}
export async function enterCloudPlatform(page) {
  if (page.url().includes('phoenix2')) return;
  const avatar = page.locator('.wrap-login-container, .wrap-login-dropdown').first();
  // The post-login page can cover this control with a promo video. The cloud URL is opened next either way.
  if (await visible(avatar)) await avatar.hover({ timeout: 3000 }).catch(() => {});
  const cloud = page.getByText(/(?:返回)?领动云平台/u).last();
  if (await visible(cloud)) await cloud.click({ timeout: 5000 }).catch(() => {});
}
export async function loginOnce(page, cfg) {
  const value = credentials(cfg);
  await page.goto(cfg.environment.login_url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  if (new URL(page.url()).host !== new URL(cfg.environment.login_url).host) fail('ENVIRONMENT_MISMATCH', '登录页跳转到了其他主机');
  const captcha = page.locator('#faptcha_response_field, input[name*="captcha"], input[id*="captcha"], .geetest_panel, .h-captcha').first();
  if (await visible(captcha)) fail('CAPTCHA_REQUIRED', '登录需要人工完成验证码', ['使用 --manual 手动完成验证码', '暂停相关用例']);
  try { await page.locator('#loginName').waitFor({ state: 'visible', timeout: 15000 }); }
  catch (error) {
    if (error instanceof WorkflowError) throw error;
    if (await visible(captcha)) fail('CAPTCHA_REQUIRED', '登录需要人工完成验证码', ['使用 --manual 手动完成验证码', '暂停相关用例']);
    fail('LOGIN_FORM_MISSING', '没有找到已知登录表单，请检查环境入口');
  }
  try {
    await page.locator('#loginName').fill(value.account);
    await page.locator('#password').fill(value.password);
    await page.locator('#loginSubmit').click();
    await page.waitForFunction(() => {
      const input = document.querySelector('#loginName');
      const loggedOut = input && input.getClientRects().length > 0;
      const errors = [...document.querySelectorAll('.login-error, #loginError, .error, .geetest_panel')]
        .some(node => node.getClientRects().length && node.textContent?.trim());
      const onPlatform = location.href.includes('phoenix2');
      const dashboard = document.querySelector('.contentShow, .wrap-webSite');
      const moved = !/\/(?:login|signin)(?:[./?]|$)/iu.test(location.pathname);
      return errors || (!loggedOut && (moved || onPlatform || Boolean(dashboard && dashboard.getClientRects().length)));
    }, null, { timeout: 25000 });
  } catch {
    const text = await page.locator('body').innerText().catch(() => '');
    if (/密码.*错误|账号.*错误|用户名.*错误|账户.*锁|password.*incorrect/iu.test(text)) fail('INVALID_CREDENTIALS', '账号或密码错误，未重复提交', ['更新本地凭据', '暂停相关用例']);
    fail('LOGIN_FAILED', '登录未完成，已停止自动尝试', ['检查账号密码', '使用 --manual 手动登录', '暂停相关用例']);
  }
  if (await isLoginPage(page)) {
    if (await visible(captcha)) fail('CAPTCHA_REQUIRED', '登录出现验证码，请人工完成验证', ['使用 --manual 手动完成验证码', '暂停相关用例']);
    const body = await page.locator('body').innerText().catch(() => '');
    if (/密码.*错误|账号.*错误|用户名.*错误|账户.*锁|password.*incorrect/iu.test(body)) fail('INVALID_CREDENTIALS', '账号或密码错误，未重复提交', ['更新本地凭据', '暂停相关用例']);
    fail('LOGIN_FAILED', '提交后仍停留在登录页，未重复提交', ['检查账号与权限', '手动登录后重试', '暂停相关用例']);
  }
  await enterCloudPlatform(page);
  await page.goto(cfg.environment.cloud_url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  if (await isLoginPage(page)) fail('LOGIN_FAILED', '登录态未能进入云平台');
}

// Compare complete normalized hosts, including language subdomains and explicit ports.
export function chooseSite(candidates, target) {
  const matching = candidates.filter(item => item.host === host(target));
  const unique = [...new Map(matching.map(item => [item.key, item])).values()];
  if (!unique.length) fail('SITE_NOT_ACCESSIBLE', '当前账号下未找到目标网站', ['检查目标域名', '切换账号', '暂停相关用例']);
  if (unique.length > 1) fail('SITE_AMBIGUOUS', '发现多个同域名站点，请先确认目标记录', ['确认站点及语言版本', '暂停相关用例']);
  return unique[0];
}
async function selectedDomain(page) {
  const selected = page.locator('.webSite-show-bottom').first();
  if (!(await visible(selected))) return null;
  const text = await selected.innerText().catch(() => '');
  try { return host(text.trim()); } catch { return null; }
}
export async function selectTargetSite(page, cfg) {
  if (!cfg.site) fail('SITE_REQUIRED', '请提供目标网站域名');
  const targetHost = host(cfg.site);
  // Slow accounts may render the shell before asynchronously loading site cards.
  await page.waitForFunction(target => [...document.querySelectorAll('.contentShow a[href]')].some(link => {
    try { return new URL(link.href).host.toLowerCase() === target; } catch { return false; }
  }), targetHost, { timeout: 90000 }).catch(() => {});
  const cardMatches = await page.locator('.contentShow').evaluateAll((cards, target) => cards.flatMap((card, cardIndex) => {
    const domains = [...card.querySelectorAll('a[href]')].flatMap(link => {
      try { return [new URL(link.href).host.toLowerCase().replace(/\.$/u, '')]; } catch { return []; }
    });
    return domains.filter(domain => domain === target).map(domain => ({ cardIndex, host: domain }));
  }), targetHost);
  // Validate the returned host as well as the card index before treating it as permission evidence.
  const exactCards = [...new Set(cardMatches.filter(item => item?.host === targetHost).map(item => item.cardIndex))];
  if (exactCards.length === 1) return { kind: 'card', host: targetHost, cardIndex: exactCards[0] };
  if (exactCards.length > 1) fail('SITE_AMBIGUOUS', '发现多个同域名站点，请先确认目标记录', ['确认站点及语言版本', '暂停相关用例']);
  // The current cloud shell lists the site and “网页编辑” directly; the older site cards are absent.
  const editorEntry = page.getByText('网页编辑', { exact: true }).first();
  if (!(await visible(editorEntry))) {
    await editorEntry.waitFor({ state: 'visible', timeout: 25000 }).catch(() => {});
  }
  if (await visible(editorEntry)) {
    const body = await page.locator('body').innerText().catch(() => '');
    if (body.toLowerCase().includes(String(cfg.site).toLowerCase())) return { kind: 'platform', host: cfg.site };
  }
  if (await selectedDomain(page) === cfg.site) return { kind: 'selected', host: cfg.site };
  const switcher = page.locator('.wrap-webSite').first();
  if (await visible(switcher)) {
    await switcher.hover();
    const menu = page.locator('.webSite-content').first();
    if (!(await visible(menu))) await page.locator('.webSite-show-top').first().click();
    await menu.waitFor({ state: 'visible', timeout: 10000 });
  }
  // IDs are read from the current DOM only; no historical tenant or tab IDs are embedded.
  const links = page.locator('a[href], [data-url], [data-href], .webSite-content span');
  const discover = () => links.evaluateAll(nodes => nodes.flatMap((node, index) => {
    if (!node.getClientRects().length) return [];
    const values = [node.textContent?.trim(), node.getAttribute('href'), node.getAttribute('data-url'), node.getAttribute('data-href')];
    const card = node.closest('.contentShow');
    const cardIndex = card ? [...document.querySelectorAll('.contentShow')].indexOf(card) : -1;
    const menuItem = node.closest('.webSite-content li');
    const menuKey = menuItem ? [...document.querySelectorAll('.webSite-content li')].indexOf(menuItem) : null;
    return values.flatMap(value => {
      if (!value || !/^(https?:\/\/|[\w-]+(?:\.[\w-]+)+(?::\d+)?\/?$)/iu.test(value)) return [];
      try {
        const url = new URL(/^https?:\/\//iu.test(value) ? value : `https://${value}`);
        return [{ host: url.host.toLowerCase().replace(/\.$/u, ''), index, cardIndex,
          kind: cardIndex >= 0 ? 'card' : 'link', key: cardIndex >= 0 ? `card:${cardIndex}` : menuKey !== null ? `menu:${menuKey}` : `link:${index}` }];
      } catch { return []; }
    });
  }));
  let candidates = await discover();
  if (!candidates.some(item => item.host === cfg.site) && await visible(switcher)) {
    const tabs = page.locator('.webSite-content [role="tab"]');
    for (let i = 0; i < await tabs.count(); i += 1) {
      await tabs.nth(i).click();
      candidates = await discover();
      if (candidates.some(item => item.host === cfg.site)) break;
    }
  }
  if (!candidates.some(item => item.host === targetHost)) {
    const cards = await page.locator('.contentShow').evaluateAll(nodes => nodes.map((card, index) => ({
      index, hosts: [...card.querySelectorAll('a[href]')].flatMap(link => { try { return [new URL(link.href).host]; } catch { return []; } })
    })));
    fail('SITE_NOT_ACCESSIBLE', '未找到目标网站，请核对当前账号可见站点', cards.map(card => ({
      index: card.index, domains: (Array.isArray(card.hosts) ? card.hosts : []).map(value => { try { return host(value); } catch { return '[invalid-domain]'; } })
    })));
  }
  const selected = chooseSite(candidates, targetHost);
  if (selected.kind === 'link') {
    const link = links.nth(selected.index);
    // A backend language switch is selected only inside its site menu.
    if (await link.evaluate(node => Boolean(node.closest('.webSite-content')))) {
      await link.click();
      await page.waitForFunction(domain => {
        const text = document.querySelector('.webSite-show-bottom')?.textContent?.trim() ?? '';
        try { return new URL(/^https?:\/\//iu.test(text) ? text : `https://${text}`).host.toLowerCase() === domain; }
        catch { return false; }
      }, cfg.site, { timeout: 15000 });
      return { kind: 'selected', host: cfg.site };
    }
    // A public link without a site card does not prove management permission.
    fail('SITE_PERMISSION_UNVERIFIED', '找到了域名链接，但未找到其后台管理入口', ['检查站点权限', '提供站点选择演示']);
  }
  return selected;
}
export async function openSiteArea(page, cfg, area) {
  if (!['内容管理', '编辑网站'].includes(area)) fail('UNKNOWN_SITE_AREA', '站点入口仅支持内容管理或编辑网站');
  const selected = await selectTargetSite(page, cfg);
  const root = selected.kind === 'card' ? page.locator('.contentShow').nth(selected.cardIndex) : page;
  const label = selected.kind === 'card' || area === '内容管理' ? area : '网页编辑';
  const action = root.getByText(label, { exact: true }).first();
  if (!(await visible(action))) fail('SITE_PERMISSION_DENIED', '当前账号没有所需站点管理入口', ['切换有权限账号', '暂停相关用例']);
  if (selected.kind === 'platform') {
    const popupPromise = page.context().waitForEvent('page', { timeout: 30000 });
    await action.click();
    let destination;
    try { destination = await popupPromise; }
    catch { fail('EDITOR_POPUP_MISSING', '网页编辑没有打开编辑器窗口', ['确认账号有编辑权限', '暂停相关用例']); }
    await destination.waitForLoadState('domcontentloaded');
    return destination;
  }
  const popup = page.context().waitForEvent('page', { timeout: 10000 }).catch(() => null);
  const before = page.url();
  const navigation = page.waitForURL(url => url.href !== before, { timeout: 10000 }).then(() => page).catch(() => null);
  await action.click();
  const destination = await Promise.race([popup, navigation]) ?? page;
  if (destination !== page) await destination.waitForURL(url => ['http:', 'https:'].includes(url.protocol), { timeout: 30000 });
  await destination.waitForLoadState('domcontentloaded');
  // Recheck language/domain after entering a card's default management area.
  if (await visible(destination.locator('.wrap-webSite').first())) await selectTargetSite(destination, cfg);
  return destination;
}
export async function authenticatedSession(browser, cfg, { force = false, allowLogin = true, manual = false } = {}) {
  const state = force || manual ? undefined : reusableState(cfg);
  const context = await browser.newContext({ ...contextOptions(cfg), ...(state ? { storageState: state } : {}) });
  const page = await context.newPage();
  try {
    const environment = await checkEnvironment(page, cfg);
    let refreshed = false;
    const authenticate = async () => {
      if (!manual) return loginOnce(page, cfg);
      try {
        await page.waitForFunction(() => !document.querySelector('#loginName')?.getClientRects().length &&
          !/\/(?:login|signin)(?:[./?]|$)/iu.test(location.pathname), null, { timeout: 600000 });
      }
      catch { fail('MANUAL_LOGIN_TIMEOUT', '等待人工登录超时，请完成登录后重试'); }
    };
    if (await isLoginPage(page)) {
      if (!allowLogin) fail('AUTH_REQUIRED', '登录态已过期，请在执行前重新运行 login', ['重新登录', '暂停相关用例']);
      await authenticate(); refreshed = true;
    }
    await enterCloudPlatform(page);
    await page.goto(cfg.environment.cloud_url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    if (new URL(page.url()).host !== new URL(cfg.environment.cloud_url).host) fail('ENVIRONMENT_MISMATCH', '云平台跳转到了其他主机');
    if (await isLoginPage(page)) {
      if (!allowLogin || refreshed) fail('AUTH_REQUIRED', '云平台要求重新登录');
      await authenticate(); refreshed = true;
    }
    const shellReady = page.locator('.contentShow, .wrap-webSite').first().waitFor({ state: 'visible', timeout: 25000 }).catch(() => {});
    const editorReady = page.getByText('网页编辑', { exact: true }).first().waitFor({ state: 'visible', timeout: 25000 }).catch(() => {});
    await Promise.race([shellReady, editorReady]);
    let site;
    try { site = await selectTargetSite(page, cfg); }
    catch (error) {
      if (error?.code !== 'SITE_NOT_ACCESSIBLE') throw error;
      // One bounded retry handles delayed card hydration after shell readiness.
      await new Promise(resolve => setTimeout(resolve, 1500));
      site = await selectTargetSite(page, cfg);
    }
    if (allowLogin && (!state || refreshed || force)) await saveSession(context, cfg);
    return { context, page, environment, site, reused: Boolean(state) && !refreshed, refreshed };
  } catch (error) { await context.close(); throw error; }
}

export async function snapshotSession(browser, cfg, { area, manual = false } = {}) {
  const session = await authenticatedSession(browser, cfg, { allowLogin: true, manual });
  try {
    let page = session.page;
    if (area) page = await openSiteArea(page, cfg, area);
    await page.waitForLoadState('domcontentloaded').catch(() => {});
    const structure = await page.evaluate(() => {
      const describe = root => [...root.querySelectorAll('body, body *')].slice(0, 300).map(node => ({
        tag: node.tagName.toLowerCase(), role: node.getAttribute('role'),
        name: (node.getAttribute('aria-label') || node.getAttribute('title') || node.textContent || '').trim().replace(/\\s+/gu, ' ').slice(0, 120),
        id: node.id || undefined, classes: typeof node.className === 'string' ? node.className.split(/\\s+/u).filter(Boolean).slice(0, 4) : []
      }));
      const frame = document.querySelector('#backstage-innerpage');
      let frameStructure = [];
      try { if (frame?.contentDocument) frameStructure = describe(frame.contentDocument); } catch { /* cross-origin frame omitted */ }
      return { url: location.origin + location.pathname, title: document.title, nodes: describe(document),
        iframe: frame ? { id: frame.id, same_origin: Boolean(frame.contentDocument), nodes: frameStructure } : null };
    });
    const { scrubText } = await import('./redact.mjs');
    let safe = scrubText(JSON.stringify(structure));
    const privateValues = credentials(cfg);
    for (const value of Object.values(privateValues)) {
      if (typeof value === 'string' && value) safe = safe.split(value).join('[REDACTED]');
    }
    return JSON.parse(safe);
  } finally { await session.context.close(); }
}
