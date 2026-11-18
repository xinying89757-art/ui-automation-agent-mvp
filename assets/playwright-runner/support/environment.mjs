import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';

export const runtimeRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const environments = JSON.parse(fs.readFileSync(path.join(runtimeRoot, 'environments.json'), 'utf8'));
export const hash = value => createHash('sha256').update(value).digest('hex');
export class WorkflowError extends Error {
  constructor(code, message, choices = []) {
    super(message); this.code = code; this.choices = choices;
  }
}
export function fail(code, message, choices = []) { throw new WorkflowError(code, message, choices); }
export function host(value) {
  const url = new URL(/^[a-z][a-z\d+.-]*:\/\//iu.test(value) ? value : `https://${value}`);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) fail('INVALID_SITE', '请提供不含凭据的 HTTP(S) 网站域名');
  return url.host.toLowerCase().replace(/\.$/u, '');
}
/** @param {Record<string, any>} raw
 * @returns {Record<string, any>} */
export function resolveConfig(raw = {}, configPath, env = process.env) {
  const directory = configPath ? path.dirname(path.resolve(configPath)) : runtimeRoot;
  const supplied = typeof raw.environment === 'string' ? { id: raw.environment } : raw.environment;
  const preset = supplied ? environments[supplied.id] : null;
  if (supplied && !preset) fail('UNKNOWN_ENVIRONMENT', '环境必须为 p、gray 或 production');
  const environment = preset ? { ...preset, ...supplied } : undefined;
  if (environment) delete environment.network;
  if (environment) {
    for (const key of ['entry_url', 'login_url', 'cloud_url']) {
      const url = new URL(environment[key]);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) fail('INVALID_ENVIRONMENT', '环境入口必须为不含凭据的 HTTP(S) URL');
      if (environment.id === 'production' && url.protocol !== 'https:') fail('INVALID_ENVIRONMENT', '正式版入口必须使用 HTTPS');
    }
    if (environment.id === 'gray' && new URL(environment.entry_url).protocol !== 'http:') fail('INVALID_ENVIRONMENT', '灰度必须从 HTTP 初始入口开始');
    if (environment.id === 'gray') environment.required_header = environments.gray.required_header;
  }
  const network = preset ? { ...preset.network, ...raw.network } : raw.network;
  let resolvedNetwork = network;
  if (!resolvedNetwork) {
    const proxy = env[raw.proxy_env ?? 'UI_PROXY'];
    resolvedNetwork = proxy && !/^(none|direct|off|false)$/iu.test(proxy)
      ? { mode: 'proxy', server: proxy } : { mode: 'direct' };
  }
  if (!['direct', 'proxy', 'pac'].includes(resolvedNetwork.mode)) fail('INVALID_NETWORK', '未知代理模式');
  if (environment?.id === 'production' && (resolvedNetwork.mode !== 'direct' || resolvedNetwork.ignore_https_errors)) {
    fail('INVALID_NETWORK', '正式版必须直连并校验证书');
  }
  const auth = { ...raw.auth };
  for (const key of ['credentials_file', 'storage_state']) if (auth[key]) auth[key] = path.resolve(directory, auth[key]);
  const cfg = { ...raw, environment, network: { ...resolvedNetwork }, auth };
  if (cfg.network.mode === 'proxy') {
    const url = new URL(cfg.network.server);
    if (!['http:', 'https:', 'socks5:'].includes(url.protocol) || url.username || url.password) fail('INVALID_NETWORK', '代理必须使用不含凭据的代理 URL');
  }
  if (cfg.network.mode === 'pac') {
    cfg.network.pac_file = cfg.network.pac_file ? path.resolve(directory, cfg.network.pac_file) : path.join(runtimeRoot, 'network/gray.pac');
    if (!fs.existsSync(cfg.network.pac_file)) fail('PAC_MISSING', '项目内 PAC 文件缺失');
  }
  cfg.targets = { ...(environment ? { admin: environment.cloud_url } : {}), ...raw.targets };
  if (raw.site && !cfg.targets.public) cfg.targets.public = new URL(/^[a-z][a-z\d+.-]*:\/\//iu.test(raw.site) ? raw.site : `${new URL(environment?.entry_url ?? 'https://example.invalid').protocol}//${raw.site}`).origin;
  cfg.site = raw.site ? host(raw.site) : cfg.targets.public ? host(cfg.targets.public) : undefined;
  return cfg;
}
export function loadConfig(configPath = process.env.UIA_CONFIG) {
  return resolveConfig(configPath ? JSON.parse(fs.readFileSync(configPath, 'utf8')) : {}, configPath);
}
export function networkFingerprint(cfg) {
  const n = cfg.network;
  return hash(JSON.stringify([n.mode, n.server ?? null, Boolean(n.ignore_https_errors),
    n.mode === 'pac' ? hash(fs.readFileSync(n.pac_file)) : null]));
}
export function launchOptions(cfg, headless = true) {
  const network = cfg.network;
  return {
    headless,
    ...(network.mode === 'proxy' ? { proxy: { server: network.server } } : {}),
    args: [...(network.mode === 'pac' ? [`--proxy-pac-url=${pathToFileURL(network.pac_file).href}`]
      : network.mode === 'direct' ? ['--no-proxy-server'] : []),
      ...(network.ignore_https_errors ? ['--ignore-certificate-errors'] : [])],
  };
}
export function contextOptions(cfg) {
  return { locale: 'zh-CN', viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: Boolean(cfg.network.ignore_https_errors),
    ...(cfg.network.mode === 'proxy' ? { proxy: { server: cfg.network.server } } : {}) };
}
export async function checkEnvironment(page, cfg) {
  const e = cfg.environment;
  const entry = e?.entry_url ?? cfg.targets.admin ?? cfg.targets.public;
  if (!entry) fail('ENVIRONMENT_REQUIRED', '请先选择环境并配置初始入口');
  let response;
  try { response = await page.goto(entry, { waitUntil: 'domcontentloaded', timeout: 30000 }); }
  catch { fail('ENVIRONMENT_UNREACHABLE', '环境初始入口不可达，请检查代理及网络', ['修正环境配置', '重试预检', '暂停相关用例']); }
  const final = new URL(page.url());
  const headers = await response?.allHeaders() ?? {};
  if (final.host !== new URL(entry).host || (new URL(entry).protocol === 'https:' && final.protocol !== 'https:')) {
    fail('ENVIRONMENT_MISMATCH', '入口跳转到了其他主机或降级为 HTTP', ['修正环境配置', '暂停相关用例']);
  }
  if (!response || response.status() >= 400) fail('ENVIRONMENT_HTTP_ERROR', '初始入口返回错误状态');
  const marker = headers['x-via'] ?? '';
  if (e?.required_header && !(headers[e.required_header.name.toLowerCase()] ?? '').toLowerCase().includes(e.required_header.value.toLowerCase())) {
    fail('GRAY_NOT_CONFIRMED', '未检测到灰度响应头 X-Via: Ld-Gray', ['检查灰度 PAC', '重试预检', '暂停相关用例']);
  }
  if (e?.id === 'production' && /ld-gray/iu.test(marker)) fail('ENVIRONMENT_MISMATCH', '正式版入口返回了灰度标记');
  return { environment: e?.id ?? 'legacy', entry_url: entry, final_url: final.origin + final.pathname,
    status: response.status(), x_via: marker, network_fingerprint: networkFingerprint(cfg), verified: true };
}
