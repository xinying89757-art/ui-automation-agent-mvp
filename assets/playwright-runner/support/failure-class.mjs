/** Failure classes shared with scripts/uia_core/failures.py. */
const ENVIRONMENT = /SITE_NOT_ACCESSIBLE|未找到目标网站|LOGIN_FAILED|LOGIN_FORM_MISSING|INVALID_CREDENTIALS|AUTH_REQUIRED|CAPTCHA_REQUIRED|CREDENTIALS_REQUIRED|ACCOUNT_CHANGED|MANUAL_LOGIN_TIMEOUT|ENVIRONMENT_UNREACHABLE|ENVIRONMENT_MISMATCH|ENVIRONMENT_HTTP_ERROR|GRAY_NOT_CONFIRMED|ENVIRONMENT_REQUIRED|SITE_PERMISSION_DENIED|SITE_PERMISSION_UNVERIFIED|SITE_AMBIGUOUS|SITE_AREA_NOT_READY|SITE_REQUIRED|EDITOR_POPUP_MISSING|UIA_ENVIRONMENT_BLOCKED|net::ERR_|ERR_CONNECTION|ERR_NAME_NOT_RESOLVED|ERR_TIMED_OUT|ERR_INTERNET_DISCONNECTED|站点加载超时|网站不可达|入口不可达|登录超时|目标网站不可达|内容编辑器没有打开/iu;

export function isEnvironmentMessage(message) {
  const text = String(message ?? '').split(/\r?\n/u, 1)[0];
  if (/UIA_(?:AUTOMATION_FAILURE|LOCATOR_MISS|BUSINESS_FAILURE)|\b(?:frameLocator|locator)\.\w+:|intercepts pointer events/iu.test(text)) return false;
  if (ENVIRONMENT.test(text)) return true;
  return /timeout|timed out/iu.test(text) && /\b(?:site|website|login)\b|page\.goto|环境入口|目标网站|初始入口|内容编辑器/iu.test(text);
}

export function classifyFailure(message, playwrightStatus, locatorMiss = false) {
  const errors = Array.isArray(message) ? message : [message];
  if (errors.some(isEnvironmentMessage)) return { result: 'environment_blocked', failure_class: 'environment' };
  message = errors.join('\n');
  if (/UIA_PRODUCT_CONFIRMATION/u.test(message)) return { result: 'product_confirmation', failure_class: 'product' };
  if (/UIA_SAVE_NOT_PERSISTED/u.test(message)) return { result: 'save_not_persisted', failure_class: 'product' };
  if (/UIA_SETUP_FAILED/u.test(message)) return { result: 'automation_failure', failure_class: 'automation' };
  if (locatorMiss) return { result: 'automation_failure', failure_class: 'automation' };
  if (/UIA_BUSINESS_FAILURE/u.test(message)) return { result: 'business_failure', failure_class: 'product' };
  if (/UIA_CLEANUP_FAILED/u.test(message)) return { result: 'automation_failure', failure_class: 'automation' };
  if (playwrightStatus === 'interrupted' || playwrightStatus === 'skipped') return { result: 'interrupted', failure_class: null };
  return { result: 'automation_failure', failure_class: 'automation' };
}
