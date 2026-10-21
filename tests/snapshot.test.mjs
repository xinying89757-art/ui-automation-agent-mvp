import test from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from '../assets/playwright-runner/node_modules/@playwright/test/index.mjs';
import { scopedStructure } from '../assets/playwright-runner/support/auth.mjs';

test('bounded snapshots scope containers and iframe, hide invisible nodes and identify duplicate names', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <a href="#">Contact Us</a><a href="#">Contact Us</a>
      <div id="dialog"><button>Known action</button>
        <div style="display:none"><button>Hidden library</button></div>
        <div style="opacity:0"><button>Transparent library</button></div>
        <div aria-hidden="true"><button>Aria hidden</button></div>
        <input type="password" value="fake-local-value">
      </div>
      <iframe id="backstage-innerpage" srcdoc="<button>Frame action</button>"></iframe>`);
    const full = await scopedStructure(page);
    assert.deepEqual(full.duplicate_names, [{ pair: ['link', 'Contact Us'], count: 2 }]);
    const scoped = await scopedStructure(page, { scope: '#dialog' });
    const serialized = JSON.stringify(scoped);
    assert.match(serialized, /Known action/);
    for (const hidden of ['Hidden library', 'Transparent library', 'Aria hidden', 'Contact Us', 'fake-local-value']) assert.equal(serialized.includes(hidden), false, hidden);
    const frame = await scopedStructure(page, { frame: '#backstage-innerpage' });
    assert.match(JSON.stringify(frame), /Frame action/);
    assert.equal(JSON.stringify(frame).includes('Known action'), false);
  } finally { await browser.close(); }
});
