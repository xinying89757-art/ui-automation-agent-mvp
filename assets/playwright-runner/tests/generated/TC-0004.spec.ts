// Generated deterministically from case-spec.v1; edit the spec or explicitly review an AI repair.
import { test, expect, businessAssertion } from '../../support/fixtures.js';
import { openTarget } from '../../support/case-spec.js';
import { delayRequests, doubleClick, attemptClick, observeOccurrences } from '../../flows/network-control.mjs';
import { deferPublic, trackSave } from '../../support/remote-checks.mjs';

test("[TC-0004] 从设置面板打开管理txt文件并显示默认页签", async ({ page, caseContext }) => {
  const networks: Record<string, any> = {};
  const observations: Record<string, any> = {};
  try {
  // @step S1
  await openTarget(page, "settings");
  // Excel: 1. 网站设置面板显示“管理txt文件”。
  await businessAssertion('A1', async () => {
    await expect(page.locator("#site_customize_txt a")).toContainText("管理txt文件");
  });
  // @step S2
  await page.locator("#site_customize_txt a").click();
  // Excel: 2. 页面打开标题为“管理txt文件”的弹窗。
  await businessAssertion('A2', async () => {
    await expect(page.locator("#backstage-dialog-customizeFile").locator("strong")).toHaveText("管理txt文件");
    await expect(page.locator("#backstage-dialog-customizeFile")).toBeVisible();
  });
  // @step S3
  await expect(page.locator("#backstage-dialog-customizeFile")).toBeVisible();
  // Excel: 3. 默认选中“llms.txt”页签，左侧显示“取消”，右侧显示“保存”。
  await businessAssertion('A3', async () => {
    await expect(page.locator("#backstage-dialog-customizeFile").locator("a.customize-file-tab.on")).toHaveText("llms.txt");
    await expect(page.locator("#backstage-dialog-customizeFile").locator("a.backstage-dialog-cancel")).toHaveText("取消");
    await expect(page.locator("#backstage-dialog-customizeFile").locator("a[class*='customize_file_llms']")).toHaveText("保存");
    expect((await page.locator("#backstage-dialog-customizeFile").locator("a.backstage-dialog-cancel").boundingBox())!.x).toBeLessThan((await page.locator("#backstage-dialog-customizeFile").locator("a[class*='customize_file_llms']").boundingBox())!.x);
  });
  } finally {
    for (const network of Object.values(networks)) await network.dispose();
    for (const observation of Object.values(observations)) await observation.dispose();
  }
});
