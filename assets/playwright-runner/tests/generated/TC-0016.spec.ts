// Generated deterministically from case-spec.v1; edit the spec or explicitly review an AI repair.
import { test, expect, businessAssertion } from '../../support/fixtures.js';
import { openTarget } from '../../support/case-spec.js';

test("[TC-0016] 悬停问号显示自动生成规则说明", async ({ page }) => {
  // @step S1
  await page.locator("#backstage-dialog-customizeFile").locator(".llms-rule-help").hover();
  // Excel: 1. 页面浮出说明面板。
  await businessAssertion('A1', async () => {
    await expect(page.locator("#backstage-dialog-customizeFile").locator("#llms-rule-tooltip")).toBeVisible();
  });
  // @step S2
  await expect(page.locator("#backstage-dialog-customizeFile").locator("#llms-rule-tooltip")).toBeVisible();
  // Excel: 2. 面板显示“自动生成规则”“文件按以下模块顺序生成，各模块取值规则如下：”，并列出网站标题、网站概述、扩展内容字段、Contact Us、Social Media、Website Language Versions、Website Navigation、Product Category和FAQ九项说明。
  await businessAssertion('A2', async () => {
    await expect(page.locator("#backstage-dialog-customizeFile").locator("#llms-rule-tooltip .llms-rule-title")).toHaveText("自动生成规则");
    await expect(page.locator("#backstage-dialog-customizeFile").locator("#llms-rule-tooltip .llms-rule-intro")).toHaveText("文件按以下模块顺序生成，各模块取值规则如下：");
    await expect(page.locator("#backstage-dialog-customizeFile").locator("#llms-rule-tooltip .llms-rule-list strong")).toHaveText(["网站标题", "网站概述", "扩展内容字段", "Contact Us", "Social Media", "Website Language Versions", "Website Navigation", "Product Category", "FAQ"]);
    await expect(page.locator("#backstage-dialog-customizeFile").locator("#llms-rule-tooltip .llms-rule-list strong")).toHaveCount(9);
  });
});
