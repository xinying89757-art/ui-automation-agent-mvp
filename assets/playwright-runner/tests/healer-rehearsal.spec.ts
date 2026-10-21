import { test, expect } from '@playwright/test';
import { loadConfig } from '../support/environment.mjs';
import { authenticatedSession, openSiteArea } from '../support/auth.mjs';
import { locate, openSettings } from '../flows/llms-txt.mjs';

test('healer rehearsal keeps a wrong expectation red', async ({ browser }) => {
  const cfg = loadConfig();
  const session = await authenticatedSession(browser, cfg, { allowLogin: false });
  try {
    const editor = await openSiteArea(session.page, cfg, '编辑网站');
    await openSettings(editor);
    const found = await locate(editor, 'rehearse.stale');
    expect(found.via).toBe('fingerprint');
    await found.locator.click();
    await editor.getByText('llms.txt 功能').first().waitFor({ timeout: 20000 });
    const dialogText = await editor.locator('#backstage-dialog-customizeFile').innerText();
    if (!dialogText.includes('故意写错的标题')) {
      throw new Error('UIA_BUSINESS_FAILURE [rehearse-title]: injected expectation does not match the visible dialog');
    }
  } finally {
    await session.context.close();
  }
});
