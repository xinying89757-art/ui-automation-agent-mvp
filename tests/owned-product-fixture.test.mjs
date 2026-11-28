import test from 'node:test';
import assert from 'node:assert/strict';
import fixture from '../assets/playwright-runner/fixtures/owned-product.mjs';

test('rejects an unsafe marker before opening or mutating any page', async () => {
  let opened = false;
  await assert.rejects(fixture.prepare({ownerMarker:'../other-product', openAdmin:async()=>{opened=true;}}), /Invalid product owner marker/);
  assert.equal(opened, false);
});

test('a preparation that never acquired ownership cannot delete an existing product', async () => {
  let opened = false;
  const context = {openAdmin:async()=>{opened=true;}};
  const state = {name:'existing-product', owned:false};
  await fixture.cleanup(context, state);
  assert.equal(await fixture.verifyCleanup(context, state), true);
  assert.equal(opened, false);
  assert.equal(await fixture.verifyPrepared(context, state), false);
});
