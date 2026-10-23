// Generated deterministically from case-spec.v1; edit the spec or explicitly review an AI repair.
import { test, expect, businessAssertion } from '../../support/fixtures.js';
import { openTarget } from '../../support/case-spec.js';
import { delayRequests, doubleClick, attemptClick, observeOccurrences } from '../../flows/network-control.mjs';
import { deferPublic, trackSave } from '../../support/remote-checks.mjs';

test("[TC-0048] 自定义内容为空或仅空格时被拦截", async ({ page, caseContext }) => {
  const networks: Record<string, any> = {};
  const observations: Record<string, any> = {};
  try {
  // @step S1
  await page.locator("#backstage-dialog-customizeFile").locator("textarea.llms-custom-content").fill("");
  // @step S2
  await expect(page.locator("#backstage-dialog-customizeFile").locator("a[class*='customize_file_llms']")).toBeVisible();
  // Excel: 1. 文本域下方显示“请填写自定义 llms.txt 内容”，弹窗保持打开。
  await businessAssertion('A1', async () => {
    await expect(page.locator("#backstage-dialog-customizeFile").locator(".llms-custom-row .llms-error")).toHaveText("请填写自定义 llms.txt 内容");
    await expect(page.locator("#backstage-dialog-customizeFile")).toBeVisible();
    await expect(page.locator("#backstage-dialog-customizeFile").locator("a[class*='customize_file_llms']")).toBeDisabled();
  });
  // @step S3
  await page.locator("#backstage-dialog-customizeFile").locator("textarea.llms-custom-content").fill("  \n  ");
  // @step S4
  await expect(page.locator("#backstage-dialog-customizeFile").locator("a[class*='customize_file_llms']")).toBeVisible();
  // Excel: 2. 文本域下方仍显示相同错误，弹窗保持打开。
  await businessAssertion('A2', async () => {
    await expect(page.locator("#backstage-dialog-customizeFile").locator(".llms-custom-row .llms-error")).toHaveText("请填写自定义 llms.txt 内容");
    await expect(page.locator("#backstage-dialog-customizeFile")).toBeVisible();
    await expect(page.locator("#backstage-dialog-customizeFile").locator("a[class*='customize_file_llms']")).toBeDisabled();
  });
  // @step S5
  await page.locator("#backstage-dialog-customizeFile").locator("textarea.llms-custom-content").fill("x");
  // Excel: 3. 必填错误消失，保存按钮可用。
  await businessAssertion('A3', async () => {
    await expect(page.locator("#backstage-dialog-customizeFile").locator(".llms-custom-row .llms-error")).toBeHidden();
    await expect(page.locator("#backstage-dialog-customizeFile").locator("a[class*='customize_file_llms']")).toBeEnabled();
  });
  } finally {
    for (const network of Object.values(networks)) await network.dispose();
    for (const observation of Object.values(observations)) await observation.dispose();
  }
});
