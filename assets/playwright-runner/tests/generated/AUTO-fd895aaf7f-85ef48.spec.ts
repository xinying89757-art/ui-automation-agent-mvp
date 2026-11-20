import { test, expect, businessAssertion } from '../../support/fixtures.js';
import { navigateSnapshot } from '../../support/navigation.mjs';
import { loadConfig } from '../../support/environment.mjs';

test('[AUTO-fd895aaf7f-85ef48] 从网页组件入口添加 FAQ 并显示默认问答表单', async ({ page }, info) => {
  // The reviewed entry is a run-local precondition: content management → product → add product.
  const reached = await navigateSnapshot(page, loadConfig(), { steps: ['click:text=产品', 'click:text=添加产品'], entrySteps: 2 });
  if (reached.failed_step) throw new Error('未到达添加产品页面');
  const active = reached.page;
  await expect.poll(() => active.frames().some((frame: any) => frame.url().includes('/js/tiptapEditor/editor.html')), { timeout: 15000 }).toBe(true);
  const editor = active.frames().find((frame: any) => frame.url().includes('/js/tiptapEditor/editor.html'))!;
  const editable = editor.locator('[contenteditable="true"]').first();

  // @step S1
  await editable.click();
  await editable.press('/');
  await businessAssertion('A1', async () => {
    await expect(editor.getByText('网页组件', { exact: true }).first()).toBeVisible();
  });

  // @step S2
  await businessAssertion('A2', async () => {
    await expect(editor.getByText('FAQ', { exact: true }).first()).toBeVisible();
  });

  // @step S3
  await editor.getByText('FAQ', { exact: true }).first().click();
  const card = editor.locator('.faq-editor-card').first();
  await businessAssertion('A3', async () => {
    await expect(card.getByText('FAQ', { exact: true }).first()).toBeVisible();
    await expect(card.getByText('快速录入FAQ，自动生成 FAQPage 结构化数据。', { exact: true })).toBeVisible();
    await expect(card.getByText('问题1', { exact: true })).toBeVisible();
    await expect(card.getByPlaceholder('请输入FAQ标题', { exact: true })).toBeVisible();
    await expect(card.getByPlaceholder('请输入FAQ内容', { exact: true })).toBeVisible();
    await expect(card.getByText('添加FAQ', { exact: true })).toBeVisible();
    await expect(card.getByText('保存', { exact: true })).toBeVisible();
    await expect(card.getByText('取消', { exact: true })).toBeVisible();
    await expect(card.locator('button.faq-editor-close')).toBeVisible();
  });
  // Evidence is useful but an incidental screenshot failure is not a business failure.
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const image = await editor.locator('.faq-editor-card').first().screenshot({ timeout: 5000 });
      await info.attach('faq-default-form', { body: image, contentType: 'image/png' });
      break;
    } catch { if (attempt === 1) await info.attach('faq-screenshot-unavailable', { body: 'Screenshot unavailable after page redraw', contentType: 'text/plain' }); }
  }
});
