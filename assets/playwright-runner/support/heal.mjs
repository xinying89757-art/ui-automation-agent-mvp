/** Local locator scoring and the assertion gate. No model calls. */

export function lcsLength(left, right) {
  const rows = left.length;
  const cols = right.length;
  const dp = Array.from({ length: rows + 1 }, () => new Array(cols + 1).fill(0));
  for (let i = 1; i <= rows; i += 1) {
    for (let j = 1; j <= cols; j += 1) {
      dp[i][j] = left[i - 1] === right[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);
    }
  }
  return dp[rows][cols];
}

export function scoreCandidate(candidate, fingerprint) {
  let score = 0;
  let weight = 0;
  const add = (points, matched) => {
    weight += points;
    if (matched) score += points;
  };
  if (fingerprint.tag) add(3, candidate.tag === fingerprint.tag);
  if (fingerprint.name) add(5, candidate.text === fingerprint.name);
  if (fingerprint.role) add(3, candidate.role === fingerprint.role);
  if (fingerprint.classes?.length) {
    const have = new Set(candidate.classes || []);
    const overlap = fingerprint.classes.filter(item => have.has(item)).length;
    add(3, overlap / fingerprint.classes.length >= 0.5);
  }
  if (fingerprint.ancestors?.length && candidate.ancestors) {
    add(3, lcsLength(fingerprint.ancestors, candidate.ancestors) / fingerprint.ancestors.length >= 0.5);
  }
  for (const [key, value] of Object.entries(fingerprint.attributes || {})) {
    if (value) add(2, candidate.attributes?.[key] === value);
  }
  return weight ? score / weight : 0;
}

/** Highest unique candidate at or above the threshold. Ties are not healed. */
export function bestCandidate(candidates, fingerprint, threshold = 0.72) {
  const ranked = (candidates || [])
    .filter(item => item && item.visible !== false && item.selector)
    .map(item => ({ item, score: scoreCandidate(item, fingerprint) }))
    .sort((a, b) => b.score - a.score || a.item.selector.localeCompare(b.item.selector));
  const top = ranked[0];
  if (!top || top.score < threshold) return null;
  const second = ranked[1];
  if (second && top.score - second.score < 0.08) return null;
  return { selector: top.item.selector, score: top.score, text: top.item.text, tag: top.item.tag };
}

const ENVIRONMENT_TEXT = /UIA_ENVIRONMENT_BLOCKED|SITE_NOT_ACCESSIBLE|未找到目标网站|当前账号下未找到目标网站|LOGIN_FAILED|AUTH_REQUIRED|INVALID_CREDENTIALS|CAPTCHA_REQUIRED|LOGIN_FORM_MISSING|CREDENTIALS_REQUIRED|MANUAL_LOGIN_TIMEOUT|ACCOUNT_CHANGED|ENVIRONMENT_UNREACHABLE|ENVIRONMENT_MISMATCH|ENVIRONMENT_HTTP_ERROR|GRAY_NOT_CONFIRMED|SITE_PERMISSION_DENIED|SITE_PERMISSION_UNVERIFIED|SITE_AMBIGUOUS|SITE_REQUIRED|SITE_AREA_NOT_READY|EDITOR_POPUP_MISSING|登录未完成|登录态已过期|账号或密码错误|环境不可达|站点加载超时|net::ERR_|page\.goto:.*Timeout/iu;

/** environment is distinct from automation, product, and suspended. */
export function failureClass(message) {
  const text = String(message || '');
  const locator = /waiting for locator|locator resolved|strict mode violation|UIA_LOCATOR_MISS/iu.test(text);
  if (ENVIRONMENT_TEXT.test(text) && !locator) return 'environment';
  if (/UIA_PRODUCT_CONFIRMATION|UIA_SAVE_NOT_PERSISTED|UIA_BUSINESS_FAILURE/.test(text)) return 'product';
  if (/\bsuspended\b|缺知识|缺控件/.test(text)) return 'suspended';
  if (locator || /UIA_SETUP_FAILED|UIA_CLEANUP_FAILED/.test(text)) return 'automation';
  return null;
}

export function classifyFailure(message) {
  const text = String(message || '');
  if (failureClass(text) === 'environment') {
    return { kind: 'environment', accept: false, change: 'none', action: '环境或登录阻塞，不改脚本' };
  }
  const resolved = /locator resolved to (?:<|\d+ elements?)/iu.test(text);
  if (/UIA_LOCATOR_MISS|strict mode violation|resolved to 0 elements/iu.test(text) ||
      (/waiting for locator/iu.test(text) && !resolved)) {
    return { kind: 'locator_or_wait', accept: true, change: 'locator', action: '只允许更换定位器或等待，不改断言' };
  }
  if (/UIA_BUSINESS_FAILURE|UIA_PRODUCT_CONFIRMATION|Expected substring|Expected string/.test(text)) {
    return { kind: 'suspected_product_bug', accept: false, change: 'assertion',
      action: '不修改断言或期望值，保留失败并提交审核' };
  }
  if (/UIA_ENVIRONMENT_BLOCKED|CAPTCHA_REQUIRED|AUTH_REQUIRED/.test(text)) {
    return { kind: 'environment', accept: false, change: 'none', action: '环境或登录阻塞，不改脚本' };
  }
  return { kind: 'unknown', accept: false, change: 'none', action: '不自动修改脚本' };
}

function assertionLines(text) {
  return text.split('\n')
    .filter(line => /expect\(|businessAssertion|toHaveText|toContainText|toBe\(/.test(line))
    // Locator expressions identify the observed element; they are the only part
    // a locator-only repair may change. Keep the assertion label, matcher and
    // expected value in the signature.
    .map(line => line.replace(/\.locator\(\s*(['"])[\s\S]*?\1\s*\)/g, '.locator(<locator>)'))
    .join('\n');
}

export function lineDiff(before, after) {
  const left = before.split('\n');
  const right = after.split('\n');
  const out = [];
  const max = Math.max(left.length, right.length);
  for (let i = 0; i < max; i += 1) {
    if (left[i] !== right[i]) {
      if (left[i] !== undefined) out.push('- ' + left[i]);
      if (right[i] !== undefined) out.push('+ ' + right[i]);
    }
  }
  return out.join('\n');
}

/**
 * A proposal is reviewable only. This function never writes a file.
 * Locator-only proposals can be accepted as a diff. Any assertion change is rejected.
 */
export function gateProposal(specText, proposalText, message) {
  const decision = classifyFailure(message);
  const sameAssertions = assertionLines(specText) === assertionLines(proposalText);
  const diff = lineDiff(specText, proposalText);
  if (!decision.accept || !sameAssertions) {
    return {
      kind: sameAssertions ? decision.kind : 'suspected_product_bug',
      accept: false,
      applied: false,
      spec_unchanged: true,
      action: sameAssertions ? decision.action : '提案改了断言或期望值，已拒绝',
      accepted_diff: '',
      rejected_diff: diff,
    };
  }
  return {
    ...decision,
    applied: false,
    spec_unchanged: true,
    action: decision.action + '；diff 仅供审核，不写回脚本',
    accepted_diff: diff,
    rejected_diff: '',
  };
}
