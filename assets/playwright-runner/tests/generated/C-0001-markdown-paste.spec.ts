import { test, expect, businessAssertion } from '../../support/fixtures.js';
import { navigateSnapshot } from '../../support/navigation.mjs';
import { loadConfig } from '../../support/environment.mjs';
import { waitForProductEditor } from '../markdown/editor-ready.js';

test('[C-0001] 斜杠菜单粘贴 Markdown 并转换', async ({ page }) => {
  const { active, editor, editable } = await test.step('uia-preparation:product-editor', async () => {
    const route = await navigateSnapshot(page, loadConfig(), {steps: ['click:text=产品','click:text=添加产品'], entrySteps: 2});
    if (route.failed_step) throw new Error('UIA_LOCATOR_MISS: 未到达产品描述');
    const active = route.page;
    const { editor, editable } = await waitForProductEditor(active);
    return { active, editor, editable };
  });
  const input = editor.locator('textarea').first();
  const text = '# 测试标题\n\n测试段落\n\n- 测试列表';
  // @step S1
  await editable.click();
  await editable.press('/');
  const option = editor.getByText('Markdown', {exact:true}).first();
  await businessAssertion('A1', async () => { await expect(option).toBeVisible(); });
  // @step S2
  await option.click();
  await businessAssertion('A2', async () => { await expect(input).toBeVisible(); await expect(editor.getByText('Markdown', {exact:true}).first()).toBeVisible(); });
  // @step S3
  await input.fill(text);
  await businessAssertion('A3', async () => { await expect(input).toHaveValue(text); await expect(input).toHaveAttribute('placeholder', '此处粘贴您的 Markdown 内容…'); });
  // @step S4
  await editor.getByRole('button', {name:'确认转化样式'}).click();
  await businessAssertion('A4', async () => {
    await expect(editable.locator('h1')).toHaveText('测试标题');
    await expect(editable.locator('p').filter({hasText:'测试段落'})).toBeVisible();
    await expect(editable.locator('ul li')).toHaveText('测试列表');
    await expect(editable).not.toContainText('# 测试标题');
    await expect(editable).not.toContainText('- 测试列表');
  });
});
