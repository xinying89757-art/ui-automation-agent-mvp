import test from 'node:test';
import assert from 'node:assert/strict';
import {waitForSavedLinkPanel} from '../assets/playwright-runner/flows/link-panel-readiness.mjs';

test('waits for hydration after the link panel first appears', async () => {
  let reads = 0;
  const input = {waitFor: async () => {}, inputValue: async () => ++reads < 3 ? '' : 'https://example.test/'};
  assert.equal(await waitForSavedLinkPanel(input, {timeoutMs:200, pollMs:1}), 'https://example.test/');
  assert.equal(reads, 3);
});

test('returns the observed value without treating it as the expected value', async () => {
  const input = {waitFor: async () => {}, inputValue: async () => 'https://wrong.example/'};
  assert.equal(await waitForSavedLinkPanel(input, {timeoutMs:100, pollMs:1}), 'https://wrong.example/');
});

test('missing hydration and a missing panel are readiness failures', async () => {
  await assert.rejects(waitForSavedLinkPanel({waitFor: async () => {}, inputValue: async () => ''}, {timeoutMs:15, pollMs:1}), /did not populate/);
  await assert.rejects(waitForSavedLinkPanel({waitFor: async () => {throw Error('not attached');}}, {timeoutMs:15, pollMs:1}), /not visible/);
});
