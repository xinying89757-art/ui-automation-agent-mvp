// Generated deterministically from case-spec.v1; edit the spec or explicitly review an AI repair.
import { test, expect, businessAssertion } from '../../support/fixtures.js';
import { openTarget } from '../../support/case-spec.js';
import { delayRequests, doubleClick, attemptClick, observeOccurrences } from '../../flows/network-control.mjs';
import { deferPublic, trackSave } from '../../support/remote-checks.mjs';

test("[TC-0055] 保存处理中禁用重复提交、取消和关闭", async ({ page, caseContext }) => {
  const networks: Record<string, any> = {};
  const observations: Record<string, any> = {};
  try {
  // @step S1
  await page.locator("#backstage-dialog-customizeFile").locator("input.llms-overview").fill("phase2-save-in-progress");
  // @step S2
  observations["txt.saved"] = await observeOccurrences(page, "llms.txt 配置已保存");
  // @step S3
  networks["network.llms.save"] = await delayRequests(page, {"method": "POST", "path": "/phoenix/customizeFile/llms/save", "capabilities": ["delay", "count", "release"], "evidence": "docs/phase4-verification.md"}, 12000);
  // @step S4
  await doubleClick(page, page.locator("#backstage-dialog-customizeFile").locator("a[class*='customize_file_llms']"));
  // Excel: 1. 保存按钮立即变为不可用并显示“保存中…”。
  await businessAssertion('A1', async () => {
    await expect(page.locator("#backstage-dialog-customizeFile").locator("a[class*='customize_file_llms']")).toBeDisabled();
    await expect.poll(() => page.locator("#backstage-dialog-customizeFile").locator("a[class*='customize_file_llms']").innerText()).toBe("保存中…");
  });
  // @step S5
  await attemptClick(page, page.locator("#backstage-dialog-customizeFile").locator("a.backstage-dialog-cancel"));
  // @step S6
  await attemptClick(page, page.locator("#backstage-dialog-customizeFile").locator("a.customize_file_manage_close"));
  // Excel: 2. 重复保存、取消和关闭均不能执行，弹窗保持显示。
  await businessAssertion('A2', async () => {
    await expect(page.locator("#backstage-dialog-customizeFile")).toBeVisible();
    await expect.poll(() => networks["network.llms.save"].count()).toBe(1);
  });
  // @step S7
  networks["network.llms.save"].release();
  // @step S8
  await expect(page.locator("text=llms.txt \u914d\u7f6e\u5df2\u4fdd\u5b58")).toBeVisible();
  // Excel: 3. 保存成功后显示提示并关闭弹窗，全程只产生一次可见保存结果。
  await businessAssertion('A3', async () => {
    await expect(page.locator("text=llms.txt \u914d\u7f6e\u5df2\u4fdd\u5b58")).toHaveText("llms.txt 配置已保存");
    await expect(page.locator("#backstage-dialog-customizeFile")).toBeHidden();
    await expect.poll(() => observations["txt.saved"].count()).toBe(1);
    await expect.poll(() => networks["network.llms.save"].count()).toBe(1);
  });
  } finally {
    for (const network of Object.values(networks)) await network.dispose();
    for (const observation of Object.values(observations)) await observation.dispose();
  }
});
