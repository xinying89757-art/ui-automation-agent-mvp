import test from 'node:test';
import assert from 'node:assert/strict';
import { scrubText, unsafeArtifact } from '../assets/playwright-runner/support/redact.mjs';

test('trace text drops tokens and keeps package names', () => {
  const cleaned = scrubText([
    (['ey', (['JhbGciOiJIUzI1NiJ9.', 'ey', 'JzdWIiOiJ0ZXN0In0.signaturevalue'].join(''))].join('')),
    'PIN码：ABC12',
    'person@example.com',
    '13800138000',
    'token=abc.def',
    '@playwright/test',
  ].join('\n'));
  assert.equal(cleaned.includes((['ey', 'J'].join(''))), false);
  assert.equal(cleaned.includes('ABC12'), false);
  assert.equal(cleaned.includes('person@example.com'), false);
  assert.equal(cleaned.includes('13800138000'), false);
  assert.equal(cleaned.includes('token=abc.def'), false);
  assert.equal(cleaned.includes('@playwright/test'), true);
});

test('snapshot files are unsafe and result json is not', () => {
  assert.equal(unsafeArtifact('error-context.md'), true);
  assert.equal(unsafeArtifact('trace.zip'), true);
  assert.equal(unsafeArtifact('shot.png'), true);
  assert.equal(unsafeArtifact('case-results.json'), false);
});
