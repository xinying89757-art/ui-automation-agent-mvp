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

export function classifyFailure(message) {
  const text = String(message || '');
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
  return text.split('\n').filter(line => /expect\(|businessAssertion|toHaveText|toContainText|toBe\(/.test(line)).join('\n');
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
