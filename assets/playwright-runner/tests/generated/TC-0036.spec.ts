// Generated deterministically from case-spec.v1; edit the spec or explicitly review an AI repair.
import { test, expect, businessAssertion } from '../../support/fixtures.js';
import { openTarget } from '../../support/case-spec.js';
import { delayRequests, doubleClick, attemptClick, observeOccurrences } from '../../flows/network-control.mjs';
import { deferPublic, trackSave } from '../../support/remote-checks.mjs';

test("[TC-0036] 保存配置后无需发布即可立即更新公开文件", async ({ page, caseContext }) => {
  const networks: Record<string, any> = {};
  const observations: Record<string, any> = {};
  try {
  observations["save-clock:public.llms.immediate"] = trackSave(page, caseContext, {"method": "POST", "path": "/phoenix/customizeFile/llms/save", "capabilities": ["delay", "count", "release"], "evidence": "docs/phase4-verification.md"});
  // @step S1
  await page.locator("#backstage-dialog-customizeFile").locator("input.llms-overview").fill("phase2-immediate-public-overview");
  // @step S2
  await page.locator("#backstage-dialog-customizeFile").locator("a[class*='customize_file_llms']").click();
  // Excel: 1. 页面显示“llms.txt 配置已保存”并关闭弹窗。
  await businessAssertion('A1', async () => {
    await expect(page.locator("text=llms.txt \u914d\u7f6e\u5df2\u4fdd\u5b58")).toHaveText("llms.txt 配置已保存");
    await expect(page.locator("#backstage-dialog-customizeFile")).toBeHidden();
  });
  // @step S3
  // Public assertions are handed off after the editor save.
  // Excel: 2. 公开文件立即显示新的网站概述。
  deferPublic(caseContext, {"id": "A2", "excel": "2. 公开文件立即显示新的网站概述。"}, {"path": "/llms.txt", "max_latency_seconds": 5, "saved_by": "network.llms.save"}, [{"op": "contains", "value": "phase2-immediate-public-overview"}]);
  // Deferred marker; not a local businessAssertion PASS.
  // @deferred A2
  } finally {
    for (const network of Object.values(networks)) await network.dispose();
    for (const observation of Object.values(observations)) await observation.dispose();
  }
});
