import { test, expect, businessAssertion } from '../support/test.js';
import { inspectPreview, locate, markedDisabled, openLlms, openSettings, cancelDialog, waitForPublic } from '../flows/llms-txt.mjs';

test('[TC-0001] 设置面板显示管理txt文件', async ({ caseContext }) => {
  const editor = await caseContext.openAdmin('编辑网站');
  await openSettings(editor);
  const preview = await inspectPreview(editor);
  await businessAssertion('entry', async () => {
    await expect((await locate(editor, 'manageTxt')).locator).toBeVisible();
    expect(preview.iframeCount).toBeGreaterThan(0);
  });
});

test('[TC-0004] 管理txt文件弹窗默认页签和按钮', async ({ caseContext }) => {
  const editor = await caseContext.openAdmin('编辑网站');
  const dialog = await openLlms(editor);
  await businessAssertion('dialog-chrome', async () => {
    await expect(dialog).toContainText('管理txt文件');
    await expect(dialog.locator('a.customize-file-tab.on')).toHaveText('llms.txt');
    await expect((await locate(editor, 'cancel')).locator).toBeVisible();
    await expect((await locate(editor, 'save')).locator).toBeVisible();
  });
  await cancelDialog(editor);
});

test('[TC-0005] 自定义txt页签切换底部按钮', async ({ caseContext }) => {
  const editor = await caseContext.openAdmin('编辑网站');
  const dialog = await openLlms(editor);
  await (await locate(editor, 'tab.custom')).locator.click();
  await businessAssertion('custom-button', async () => {
    await expect((await locate(editor, 'addNow')).locator).toBeVisible();
  });
  await (await locate(editor, 'tab.llms')).locator.click();
  await businessAssertion('llms-button', async () => {
    await expect((await locate(editor, 'save')).locator).toBeVisible();
  });
  await cancelDialog(editor);
});

test('[TC-0006] 自定义文件名 llms.txt 被拦截', async ({ caseContext }) => {
  const editor = await caseContext.openAdmin('编辑网站');
  await openLlms(editor);
  await (await locate(editor, 'tab.custom')).locator.click();
  await (await locate(editor, 'addNow')).locator.click();
  await editor.locator('#backstage-dialog-viewCustomizeFile #filename').waitFor({ state: 'visible', timeout: 15000 });
  await (await locate(editor, 'addFileName')).locator.fill('llms.txt');
  await (await locate(editor, 'addFileContent')).locator.fill('probe');
  await (await locate(editor, 'addFileSave')).locator.click();
  await businessAssertion('reserved-name', async () => {
    await expect(editor.locator('body')).toContainText('请在「llms.txt」页签中配置');
  });
  await cancelDialog(editor);
});

test('[TC-0015] 系统自动生成显示配置结构', async ({ caseContext }) => {
  const editor = await caseContext.openAdmin('编辑网站');
  const dialog = await openLlms(editor);
  await businessAssertion('system-structure', async () => {
    await expect((await locate(editor, 'source.system')).locator).toBeVisible();
    await expect(dialog).toContainText('根据下方配置及网站数据自动生成 llms.txt 文件内容');
    await expect(dialog).toContainText('网站概述');
    await expect(dialog).toContainText('扩展内容字段');
    await expect((await locate(editor, 'overview')).locator).toBeVisible();
    await expect((await locate(editor, 'addField')).locator).toBeVisible();
  });
  await cancelDialog(editor);
});

test('[TC-0017] 自定义内容显示警示和文本域', async ({ caseContext }) => {
  const editor = await caseContext.openAdmin('编辑网站');
  const dialog = await openLlms(editor);
  await (await locate(editor, 'source.custom')).locator.click();
  await businessAssertion('custom-source', async () => {
    await expect(dialog).toContainText('自定义后，系统自动生成的 llms.txt 将不再生效');
    await expect((await locate(editor, 'customContent')).locator).toBeVisible();
    await expect((await locate(editor, 'customContent')).locator).toHaveAttribute('placeholder', '请输入完整的 llms.txt 文件内容');
  });
  await (await locate(editor, 'source.system')).locator.click();
  await cancelDialog(editor);
});

test('[TC-0024] 概述和 Meta 都为空时说明并省略概述行', async ({ caseContext }) => {
  const editor = await caseContext.openAdmin('编辑网站');
  const dialog = await openLlms(editor);
  await businessAssertion('empty-meta-hint', async () => {
    await expect(dialog).toContainText('首页 Meta Description 为空，未填写网站概述时该模块不会写入 llms.txt');
  });
  const pending = editor.getByText('llms.txt 配置已保存').waitFor({ timeout: 15000 });
  await (await locate(editor, 'save')).locator.click();
  await businessAssertion('save-toast', async () => { await pending; });
  await businessAssertion('overview-omitted', async () => {
    await waitForPublic(caseContext.context.request, caseContext.targets, (body: string) => !body.split(/\r?\n/).some((line: string) => line.startsWith('>')));
  });
});

test('[TC-0041] 网站概述拒绝 HTML', async ({ caseContext }) => {
  const editor = await caseContext.openAdmin('编辑网站');
  const dialog = await openLlms(editor);
  const overview = (await locate(editor, 'overview')).locator;
  await overview.fill('<b>text</b>');
  await businessAssertion('html-rejected', async () => {
    await expect(dialog).toContainText('网站概述不支持 HTML 标签，请输入纯文本');
    expect(await markedDisabled((await locate(editor, 'save')).locator)).toBeTruthy();
  });
  await overview.fill('<script>alert(1)</script>');
  await businessAssertion('script-rejected', async () => {
    await expect(dialog).toContainText('网站概述不支持 HTML 标签，请输入纯文本');
    expect(await markedDisabled((await locate(editor, 'save')).locator)).toBeTruthy();
  });
  await cancelDialog(editor);
});

test('[TC-0043] 扩展字段只填一半时拦截', async ({ caseContext }) => {
  const editor = await caseContext.openAdmin('编辑网站');
  const dialog = await openLlms(editor);
  await (await locate(editor, 'addField')).locator.click();
  const name = (await locate(editor, 'extraName')).locator;
  const value = (await locate(editor, 'extraValue')).locator;
  await name.fill('probe-name');
  await businessAssertion('name-only', async () => {
    await expect(dialog).toContainText('请补全该字段的名称与内容，或删除该行');
    expect(await markedDisabled((await locate(editor, 'save')).locator)).toBeTruthy();
  });
  await name.fill('');
  await value.fill('probe-value');
  await businessAssertion('value-only', async () => {
    await expect(dialog).toContainText('请补全该字段的名称与内容，或删除该行');
  });
  await value.fill('');
  await businessAssertion('empty-row', async () => {
    await expect(dialog).not.toContainText('请补全该字段的名称与内容，或删除该行');
  });
  await cancelDialog(editor);
});

test('[TC-0036] 保存概述后公开文件立即更新', async ({ caseContext }) => {
  // uia-mutates
  const state = caseContext.fixtureState as { touchedOverview: boolean; marker: string };
  const marker = `uia-${caseContext.caseId}-${caseContext.batchId.slice(0, 8)}`;
  state.touchedOverview = true;
  state.marker = marker;
  const editor = await caseContext.openAdmin('编辑网站');
  const dialog = await openLlms(editor);
  await (await locate(editor, 'overview')).locator.fill(marker);
  const pending = editor.getByText('llms.txt 配置已保存').waitFor({ timeout: 20000 });
  await (await locate(editor, 'save')).locator.click();
  await businessAssertion('saved', async () => { await pending; });
  await businessAssertion('public-updated', async () => {
    await waitForPublic(caseContext.context.request, caseContext.targets, (body: string) => body.includes(marker));
  });
  await openLlms(editor);
  await (await locate(editor, 'overview')).locator.fill('');
  const cleared = editor.getByText('llms.txt 配置已保存').waitFor({ timeout: 20000 });
  await (await locate(editor, 'save')).locator.click();
  await cleared;
  await businessAssertion('public-cleared', async () => {
    await waitForPublic(caseContext.context.request, caseContext.targets, (body: string) => !body.includes(marker));
  });
  await expect(dialog).toBeHidden({ timeout: 20000 }).catch(() => {});
});
