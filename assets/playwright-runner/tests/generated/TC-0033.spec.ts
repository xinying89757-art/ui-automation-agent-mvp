// Generated deterministically from case-spec.v1; edit the spec or explicitly review an AI repair.
import { test, expect, businessAssertion } from '../../support/fixtures.js';
import { openTarget } from '../../support/case-spec.js';
import { delayRequests, doubleClick, attemptClick, observeOccurrences } from '../../flows/network-control.mjs';
import { deferPublic, trackSave } from '../../support/remote-checks.mjs';

test("[TC-0033] FAQ有5条时全部按列表顺序输出", async ({ page, caseContext }) => {
  const networks: Record<string, any> = {};
  const observations: Record<string, any> = {};
  try {
  observations["save-clock:public.llms"] = trackSave(page, caseContext, {"method": "POST", "path": "/phoenix/customizeFile/llms/save", "capabilities": ["delay", "count", "release"], "evidence": "docs/phase4-verification.md"});
  // @step S1
  await page.locator("#backstage-dialog-customizeFile").locator("a[class*='customize_file_llms']").click();
  // Excel: 1. 页面显示保存成功提示。
  await businessAssertion('A1', async () => {
    await expect(page.locator("text=llms.txt \u914d\u7f6e\u5df2\u4fdd\u5b58")).toBeVisible();
  });
  // @step S2
  // Public assertions are handed off after the editor save.
  // Excel: 2. FAQ模块显示5条问答且顺序与FAQ列表一致，每条均使用问题和答案两行格式。
  deferPublic(caseContext, {"id": "A2", "excel": "2. FAQ模块显示5条问答且顺序与FAQ列表一致，每条均使用问题和答案两行格式。"}, {"path": "/llms.txt", "saved_by": "network.llms.save"}, [{"op": "ordered_pairs", "section": "FAQ", "value": "$fixture.faq.pairs"}]);
  // Deferred marker; not a local businessAssertion PASS.
  // @deferred A2
  } finally {
    for (const network of Object.values(networks)) await network.dispose();
    for (const observation of Object.values(observations)) await observation.dispose();
  }
});
