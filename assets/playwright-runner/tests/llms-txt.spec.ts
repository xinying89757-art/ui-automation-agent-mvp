import { test, expect, businessAssertion } from '../support/test.js';
import { inspectPreview, locate, markedDisabled, openLlms, openSettings, cancelDialog, noteDeferredPublic, waitIdle } from '../flows/llms-txt.mjs';

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
  let dialog = await openLlms(editor);
  await businessAssertion('empty-meta-hint', async () => {
    await expect(dialog).toContainText('首页 Meta Description 为空，未填写网站概述时该模块不会写入 llms.txt');
  });
  await (await locate(editor, 'overview')).locator.fill('');
  await (await locate(editor, 'save')).locator.click();
  dialog = await openLlms(editor);
  await businessAssertion('overview-still-empty', async () => {
    await expect((await locate(editor, 'overview')).locator).toHaveValue('');
    await expect(dialog).toContainText('首页 Meta Description 为空，未填写网站概述时该模块不会写入 llms.txt');
  });
  await noteDeferredPublic(caseContext.context.request, caseContext.targets, 'overview-omitted');
  await cancelDialog(editor);
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

test('[TC-0036] 保存概述后编辑器保持该值并可恢复原值', async ({ caseContext }) => {
  // uia-mutates
  const state = caseContext.fixtureState as { touchedOverview: boolean; marker: string; originalOverview: string };
  const editor = await caseContext.openAdmin('编辑网站');
  await openLlms(editor);
  await (await locate(editor, 'source.system')).locator.click();
  const overview = (await locate(editor, 'overview')).locator;
  await overview.waitFor({ state: 'visible', timeout: 15000 });
  const original = await overview.inputValue();
  state.originalOverview = original;
  state.touchedOverview = true;
  const marker = `uia-${caseContext.caseId}-${caseContext.batchId.slice(0, 8)}`;
  state.marker = marker;
  await overview.fill(marker);
  const savedToast = editor.getByText('llms.txt 配置已保存').waitFor({ timeout: 15000 }).then(() => true).catch(() => false);
  await (await locate(editor, 'save')).locator.click({ timeout: 10000 });
  await waitIdle(editor);
  await savedToast;
  await openLlms(editor);
  await (await locate(editor, 'source.system')).locator.click();
  await businessAssertion('editor-saved', async () => {
    await expect((await locate(editor, 'overview')).locator).toHaveValue(marker);
  });
  await noteDeferredPublic(caseContext.context.request, caseContext.targets, 'editor-saved');
  await (await locate(editor, 'overview')).locator.fill(original);
  const restoredToast = editor.getByText('llms.txt 配置已保存').waitFor({ timeout: 15000 }).then(() => true).catch(() => false);
  await (await locate(editor, 'save')).locator.click({ timeout: 10000 });
  await waitIdle(editor);
  await restoredToast;
  await openLlms(editor);
  await (await locate(editor, 'source.system')).locator.click();
  await businessAssertion('editor-restored', async () => {
    await expect((await locate(editor, 'overview')).locator).toHaveValue(original);
  });
  state.touchedOverview = false;
  await cancelDialog(editor);
});

test('[TC-0019] 往返切换内容来源保留两侧已填内容', async ({ caseContext }) => {
  // uia-mutates
  const state = caseContext.fixtureState as { prepared: { overview: string; custom: string } };
  const editor = await caseContext.openAdmin('编辑网站');
  const dialog = await openLlms(editor);
  await (await locate(editor, 'source.custom')).locator.click();
  const custom = (await locate(editor, 'customContent')).locator;
  await businessAssertion('custom-kept', async () => {
    await expect(custom).toHaveValue(state.prepared.custom);
    await expect(dialog).toContainText('自定义后，系统自动生成的 llms.txt 将不再生效');
  });
  const edited = `${state.prepared.custom}-edited`;
  await custom.fill(edited);
  await (await locate(editor, 'source.system')).locator.click();
  await businessAssertion('system-kept', async () => {
    await expect((await locate(editor, 'overview')).locator).toHaveValue(state.prepared.overview);
    await expect(dialog.locator('input.llms-extra-name:visible').last()).toHaveValue('Probe');
    await expect(dialog.locator('input.llms-extra-value:visible').last()).toHaveValue('field-tc0019');
  });
  await (await locate(editor, 'source.custom')).locator.click();
  await businessAssertion('custom-edit-kept', async () => {
    await expect(custom).toHaveValue(edited);
  });
  await cancelDialog(editor);
});

test('[TC-0050] 保存自定义内容时保留系统侧超限数据', async ({ caseContext }) => {
  // uia-mutates
  const editor = await caseContext.openAdmin('编辑网站');
  const dialog = await openLlms(editor);
  await (await locate(editor, 'source.system')).locator.click({ timeout: 10000 });
  await (await locate(editor, 'overview')).locator.fill('o'.repeat(1001));
  await (await locate(editor, 'source.custom')).locator.click({ timeout: 10000 });
  await editor.locator('#backstage-dialog-customizeFile textarea.llms-custom-content').fill('probe-custom-tc0050', { force: true });
  const save = (await locate(editor, 'save')).locator;
  const blocked = await markedDisabled(save);
  if (!blocked) await save.click({ timeout: 10000 });
  await businessAssertion('custom-saved', async () => {
    expect(blocked, '超限的系统概述不应阻止当前自定义内容保存').toBeFalsy();
    await expect(dialog).toBeHidden({ timeout: 20000 });
  });
  await openLlms(editor);
  await (await locate(editor, 'source.system')).locator.click();
  await businessAssertion('over-limit-kept', async () => {
    await expect(dialog).toContainText('网站概述不能超过 1000 个字符');
    expect(await markedDisabled((await locate(editor, 'save')).locator)).toBeTruthy();
  });
  await cancelDialog(editor);
});

test('[TC-0023] 概述留空时编辑器改用首页 Meta Description', async ({ caseContext }) => {
  // uia-mutates
  const editor = await caseContext.openAdmin('编辑网站');
  let dialog = await openLlms(editor);
  const overview = (await locate(editor, 'overview')).locator;
  if ((await overview.inputValue()) !== '') {
    await overview.fill('');
    await (await locate(editor, 'save')).locator.click();
    await businessAssertion('save-allowed', async () => {
      await expect(editor.getByText('llms.txt 配置已保存')).toBeVisible();
    });
    dialog = await openLlms(editor);
  }
  await businessAssertion('meta-fills-overview', async () => {
    await expect((await locate(editor, 'overview')).locator).toHaveValue('');
    await expect(dialog).not.toContainText('首页 Meta Description 为空，未填写网站概述时该模块不会写入 llms.txt');
  });
  await noteDeferredPublic(caseContext.context.request, caseContext.targets, 'homepage-meta');
  await cancelDialog(editor);
});
