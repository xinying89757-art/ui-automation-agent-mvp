// Generated deterministically from case-spec.v1; edit the spec or explicitly review an AI repair.
import { test, expect, businessAssertion } from '../../support/fixtures.js';
import { openTarget } from '../../support/case-spec.js';

test("[TC-0019] 往返切换内容来源保留两侧已填内容且不覆盖自定义文本", async ({ page }) => {
  // @step S1
  await page.locator("#backstage-dialog-customizeFile").locator("label.llms-source-custom").click();
  // Excel: 1. 文本域显示已有自定义内容，不被自动生成内容覆盖。
  await businessAssertion('A1', async () => {
    await expect(page.locator("#backstage-dialog-customizeFile").locator("textarea.llms-custom-content")).toHaveValue("phase2-original-custom");
  });
  // @step S2
  await page.locator("#backstage-dialog-customizeFile").locator("textarea.llms-custom-content").fill("phase2-edited-custom");
  // @step S3
  await page.locator("#backstage-dialog-customizeFile").locator("label.llms-source-system").click();
  // Excel: 2. 系统生成区域仍显示原网站概述和扩展字段。
  await businessAssertion('A2', async () => {
    await expect(page.locator("#backstage-dialog-customizeFile").locator("input.llms-overview")).toHaveValue("phase2-original-overview");
    await expect(page.locator("#backstage-dialog-customizeFile").locator("input.llms-extra-name:visible")).toHaveValue("phase2-field");
    await expect(page.locator("#backstage-dialog-customizeFile").locator("input.llms-extra-value:visible")).toHaveValue("phase2-value");
  });
  // @step S4
  await page.locator("#backstage-dialog-customizeFile").locator("label.llms-source-custom").click();
  // Excel: 3. 文本域显示刚修改的自定义内容。
  await businessAssertion('A3', async () => {
    await expect(page.locator("#backstage-dialog-customizeFile").locator("textarea.llms-custom-content")).toHaveValue("phase2-edited-custom");
  });
});
