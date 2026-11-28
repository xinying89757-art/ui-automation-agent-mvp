import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';

const runner = fileURLToPath(new URL('../assets/playwright-runner/', import.meta.url));
const runnerFile = name => JSON.stringify(path.join(runner, name));

test('readiness failures and wrong observed values produce distinct Playwright receipts', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'uia-readiness-'));
  try {
    const config = path.join(directory, 'playwright.config.mjs');
    const report = path.join(directory, 'case-results.json');
    const appConfig = path.join(directory, 'uia.json');
    fs.writeFileSync(appConfig, '{}');
    fs.writeFileSync(config, `export default {
      testDir: '.', workers: 1, timeout: 15000,
      reporter: [[${runnerFile('support/uia-reporter.ts')}, {outputFile: ${JSON.stringify(report)}}]]
    };`);
    fs.writeFileSync(path.join(directory, 'readiness.spec.mjs'), `
      import {test, expect} from ${runnerFile('node_modules/@playwright/test/index.mjs')};
      import {businessAssertion} from ${runnerFile('support/test.ts')};
      import {waitForSavedLinkPanel} from ${runnerFile('flows/link-panel-readiness.mjs')};

      for (const [id, address] of [['hydrated', 'https://example.test/'], ['blank', null], ['wrong', 'https://wrong.test/']]) {
        test('[' + id + '] link panel', async ({page}, info) => {
          await info.attach('uia-lifecycle', {body: JSON.stringify({setup_verified: true, cleanup_verified: true})});
          await page.setContent('<input aria-label="link address">');
          const input = page.getByRole('textbox', {name: 'link address'});
          await test.step('uia-step:visible', () => input.waitFor({state: 'visible'}));
          const observed = await test.step('uia-step:data-ready', async () => {
            if (address) await input.evaluate((node, url) => { setTimeout(() => { node.value = url; }, 75); }, address);
            return await waitForSavedLinkPanel(input, {timeoutMs: address ? 3000 : 300, pollMs: 20});
          });
          await businessAssertion('A1', async observe => {
            observe(observed);
            expect(observed).toBe('https://example.test/');
          });
        });
      }
    `);
    const result = spawnSync(process.execPath, [path.join(runner, 'node_modules/@playwright/test/cli.js'),
      'test', '--config', config], {cwd: directory, encoding: 'utf8', timeout: 45000,
      env: {...process.env, UIA_CONFIG: appConfig, UIA_RESULTS_DIR: directory}});
    assert.ifError(result.error);
    assert.equal(result.status, 1, result.stderr);
    const receipt = JSON.parse(fs.readFileSync(report, 'utf8'));
    assert.equal(receipt.complete, true);
    const rows = Object.fromEntries(receipt.cases.map(row => [row.case_id, row]));
    assert.deepEqual(Object.keys(rows), ['hydrated', 'blank', 'wrong']);
    assert.equal(rows.hydrated.result, 'passed');
    assert.deepEqual(rows.hydrated.successful_steps, ['visible', 'data-ready']);
    assert.equal(rows.blank.result, 'automation_failure');
    assert.equal(rows.blank.failed_step, 'data-ready');
    assert.deepEqual(rows.blank.successful_steps, ['visible']);
    assert.deepEqual(rows.blank.assertions, []);
    assert.equal(rows.wrong.result, 'business_failure');
    assert.equal(rows.wrong.failed_step, null);
    assert.deepEqual(rows.wrong.assertions, [{id: 'A1', passed: false, observations: ['https://wrong.test/']}]);
  } finally {
    fs.rmSync(directory, {recursive: true, force: true});
  }
});
