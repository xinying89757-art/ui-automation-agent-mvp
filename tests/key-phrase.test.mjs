import test from 'node:test';
import assert from 'node:assert/strict';
import { keyFromPhrase } from '../assets/playwright-runner/support/key-phrase.mjs';

test('a natural-language press Enter step is a key, not a click label', () => {
  assert.equal(keyFromPhrase('press Enter'), 'Enter');
  assert.equal(keyFromPhrase('click:text=press Enter'), 'Enter');
  assert.equal(keyFromPhrase('按回车'), 'Enter');
  assert.equal(keyFromPhrase('按下 Enter 键'), 'Enter');
  assert.equal(keyFromPhrase('设置'), null);
  assert.equal(keyFromPhrase('Enter'), null);
});
