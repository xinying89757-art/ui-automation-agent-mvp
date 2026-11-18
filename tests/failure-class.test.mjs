import test from 'node:test';
import assert from 'node:assert/strict';
import { classifyFailure, isEnvironmentMessage } from '../assets/playwright-runner/support/failure-class.mjs';

test('site not found and login timeouts are environment, not automation', () => {
  assert.equal(isEnvironmentMessage('SITE_NOT_ACCESSIBLE: 未找到目标网站'), true);
  assert.equal(classifyFailure('Error: SITE_NOT_ACCESSIBLE', 'failed').failure_class, 'environment');
  assert.equal(classifyFailure('Error: SITE_NOT_ACCESSIBLE', 'failed').result, 'environment_blocked');
  assert.equal(classifyFailure('page.goto: Timeout 30000ms exceeded at login', 'timedOut').failure_class, 'environment');
  assert.equal(classifyFailure('waiting for locator .save', 'failed', true).failure_class, 'automation');
  assert.equal(classifyFailure('UIA_BUSINESS_FAILURE: wrong title', 'failed').failure_class, 'product');
  assert.equal(classifyFailure('UIA_PRODUCT_CONFIRMATION: which product', 'failed').failure_class, 'product');
});
