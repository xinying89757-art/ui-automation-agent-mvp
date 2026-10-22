import test from 'node:test';
import assert from 'node:assert/strict';
import { bestCandidate, classifyFailure, gateProposal, scoreCandidate } from '../assets/playwright-runner/support/heal.mjs';

const fingerprint = { tag: 'a', name: '管理txt文件', ancestors: ['#site_customize_txt'] };

test('fingerprint score prefers the named control and rejects a tie', () => {
  const match = { selector: '#site_customize_txt a', tag: 'a', text: '管理txt文件', ancestors: ['#site_customize_txt'], visible: true };
  const other = { selector: '#nav a', tag: 'a', text: '其他', ancestors: ['#nav'], visible: true };
  assert.ok(scoreCandidate(match, fingerprint) > scoreCandidate(other, fingerprint));
  assert.equal(bestCandidate([other, match], fingerprint).selector, '#site_customize_txt a');
  assert.equal(bestCandidate([match, { ...match, selector: '#dup a' }], fingerprint), null);
  assert.equal(bestCandidate([{ ...match, visible: false }], fingerprint), null);
});

test('healer accepts a locator diff and refuses an assertion edit', () => {
  assert.equal(classifyFailure('UIA_LOCATOR_MISS [A1]: Timeout waiting for locator inside UIA_BUSINESS_FAILURE').kind, 'locator_or_wait');
  assert.equal(classifyFailure('UIA_BUSINESS_FAILURE expected text mismatch; locator resolved to 1 element').kind, 'suspected_product_bug');
  assert.equal(classifyFailure('UIA_BUSINESS_FAILURE expected text mismatch; waiting for locator; locator resolved to <div>').kind, 'suspected_product_bug');
  const spec = [
    "await page.locator('#stale').click();",
    "await businessAssertion('title', async () => {",
    "  await expect(dialog).toContainText('故意写错的标题');",
    '});',
  ].join('\n');
  const locatorFix = spec.replace('#stale', '#site_customize_txt a');
  const accepted = gateProposal(spec, locatorFix, 'UIA_LOCATOR_MISS manageTxt');
  assert.equal(accepted.accept, true);
  assert.equal(accepted.applied, false);
  assert.match(accepted.accepted_diff, /#site_customize_txt a/);
  assert.equal(accepted.rejected_diff, '');

  const greened = spec.replace('故意写错的标题', '管理txt文件');
  const rejected = gateProposal(spec, greened, 'UIA_BUSINESS_FAILURE [rehearse-title]: injected expectation');
  assert.equal(rejected.accept, false);
  assert.equal(rejected.kind, 'suspected_product_bug');
  assert.equal(rejected.applied, false);
  assert.equal(rejected.spec_unchanged, true);
  assert.equal(rejected.accepted_diff, '');
  assert.match(rejected.rejected_diff, /故意写错的标题/);

  const sneaky = locatorFix.replace('故意写错的标题', '管理txt文件');
  const blocked = gateProposal(spec, sneaky, 'UIA_LOCATOR_MISS manageTxt');
  assert.equal(blocked.accept, false);
  assert.equal(blocked.kind, 'suspected_product_bug');
});
