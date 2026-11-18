import fs from 'node:fs';
import path from 'node:path';
import { cancelDialog, locate, markedDisabled, openLlms, waitIdle } from './llms-txt.mjs';

const visible = locator => locator.isVisible().catch(() => false);

function remember(caseId, fields) {
  const dir = process.env.UIA_RESULTS_DIR;
  if (!dir) return;
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'data-snapshots.json');
  let all = {};
  try { all = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { all = {}; }
  all[caseId] = { at: new Date().toISOString(), fields };
  fs.writeFileSync(file, JSON.stringify(all, null, 2));
}

async function readExtras(page) {
  return page.locator('#backstage-dialog-customizeFile .llms-extra-item:visible').evaluateAll(rows => rows.map(row => ({
    name: row.querySelector('input.llms-extra-name')?.value || '',
    value: row.querySelector('input.llms-extra-value')?.value || '',
  })).filter(row => row.name || row.value));
}

async function replaceExtras(page, rows) {
  for (let i = 0; i < 8; i += 1) {
    const remove = page.locator('#backstage-dialog-customizeFile .llms-remove-field:visible').first();
    if (!(await visible(remove))) break;
    await remove.click();
  }
  for (const row of rows) {
    await (await locate(page, 'addField')).locator.click();
    await page.locator('#backstage-dialog-customizeFile input.llms-extra-name:visible').last().fill(row.name);
    await page.locator('#backstage-dialog-customizeFile input.llms-extra-value:visible').last().fill(row.value);
  }
}

async function saveDialog(page) {
  await waitIdle(page);
  const save = (await locate(page, 'save')).locator;
  const ready = await page.waitForFunction(() => {
    const button = document.querySelector("#backstage-dialog-customizeFile a[class*='customize_file_llms']");
    if (!button) return false;
    return !/disabled/i.test(String(button.className)) && button.getAttribute('aria-disabled') !== 'true';
  }, null, { timeout: 3000 }).then(() => true).catch(() => false);
  if (!ready || await markedDisabled(save)) {
    await cancelDialog(page);
    return false;
  }
  await save.click({ timeout: 10000 });
  await waitIdle(page);
  await page.getByText('llms.txt 配置已保存').waitFor({ timeout: 20000 }).catch(() => {});
  await page.locator('#backstage-dialog-customizeFile').waitFor({ state: 'hidden', timeout: 15000 }).catch(async () => {
    await cancelDialog(page);
  });
  return true;
}

async function readSavedCustom(page) {
  return page.locator('#backstage-dialog-customizeFile textarea.llms-custom-content').first().inputValue().catch(() => '');
}

/** First switch to 自定义内容 auto-fills generated text. Wait until that write settles, then overwrite. */
async function fillCustom(page, value) {
  await waitIdle(page);
  await (await locate(page, 'source.custom')).locator.click({ timeout: 10000 });
  const field = page.locator('#backstage-dialog-customizeFile textarea.llms-custom-content').first();
  await field.waitFor({ state: 'attached', timeout: 15000 });
  let last = null;
  let stable = 0;
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline && stable < 2) {
    const disabled = await field.isDisabled().catch(() => true);
    const current = disabled ? null : await field.inputValue().catch(() => null);
    stable = !disabled && current === last ? stable + 1 : 0;
    last = current;
    if (stable < 2) await page.waitForTimeout(250);
  }
  await field.fill(value ?? '', { force: true });
  return field;
}

export async function readEditorState(page) {
  await openLlms(page);
  await (await locate(page, 'source.system')).locator.click();
  const overview = await (await locate(page, 'overview')).locator.inputValue();
  const extras = await readExtras(page);
  // Stored textarea value. Clicking 自定义内容 auto-fills a generated file that was never saved.
  const custom = await readSavedCustom(page);
  await cancelDialog(page);
  return { overview, extras, custom };
}

async function readLlms(page) {
  return readEditorState(page);
}

async function saveSystem(page, value) {
  await openLlms(page);
  await (await locate(page, 'source.system')).locator.click();
  const overview = (await locate(page, 'overview')).locator;
  if ((await overview.inputValue()) !== (value.overview ?? '')) await overview.fill(value.overview ?? '');
  await replaceExtras(page, value.extras || []);
  await saveDialog(page);
}

async function saveCustom(page, custom) {
  await openLlms(page);
  await fillCustom(page, custom ?? '');
  const save = (await locate(page, 'save')).locator;
  if ((custom ?? '') === '' && await markedDisabled(save)) {
    await cancelDialog(page);
    return;
  }
  await saveDialog(page);
}

async function applyLlms(page, value) {
  await saveSystem(page, value);
  await saveCustom(page, value.custom ?? '');
  // Publishing stays on system generation. Custom text remains for the round-trip assertion.
  await saveSystem(page, value);
}

async function openPageSettings(page) {
  await cancelDialog(page);
  // 当前页面设置 lives on the 页面 drawer. The reused editor often still has 设置 open, which parks this item off-screen.
  const pagesOn = page.locator('li.backstage-siteTool-pages.backstage-siteTool-on');
  if (!(await visible(pagesOn))) {
    await page.locator('li.backstage-siteTool-pages .backstage-siteTool-inner').click();
    await pagesOn.waitFor({ state: 'visible', timeout: 15000 });
  }
  await page.waitForFunction(() => {
    const node = document.querySelector('#backstage_page_set_update');
    const rect = node?.getBoundingClientRect();
    return Boolean(rect && rect.x >= 60 && rect.width > 2);
  }, null, { timeout: 15000 });
  await page.locator('#backstage_page_set_update').click({ force: true, timeout: 10000 });
  const tab = page.locator('#setting_seo');
  await tab.waitFor({ state: 'visible', timeout: 15000 });
  await tab.click({ force: true, timeout: 10000 });
  await page.locator('#seoDescription').waitFor({ state: 'visible', timeout: 15000 });
}

async function pageSettingsBox(page) {
  return page.locator('.backstage-dialog:visible').filter({ has: page.locator('#seoDescription') });
}

async function closePageSettings(page) {
  if (!(await visible(page.locator('#seoDescription')))) return;
  const box = await pageSettingsBox(page);
  const cancel = box.locator('a.backstage-dialog-cancel').first();
  if (await visible(cancel)) await cancel.click();
}

async function readMeta(page) {
  await openPageSettings(page);
  const value = await page.locator('#seoDescription').inputValue();
  await closePageSettings(page);
  return value;
}

async function writeMeta(page, value) {
  await openPageSettings(page);
  const field = page.locator('#seoDescription');
  if ((await field.inputValue()) === value) {
    await closePageSettings(page);
    return;
  }
  await field.fill(value);
  const box = await pageSettingsBox(page);
  const save = box.locator('a.backstage-dialog-submit').first();
  if (await visible(save)) await save.click();
  else await box.getByText('保存', { exact: true }).last().click();
  await page.locator('#seoDescription').waitFor({ state: 'hidden', timeout: 15000 });
}

export async function prepareCaseData(ctx) {
  if (ctx.caseId === 'TC-0019') {
    const editor = await ctx.openAdmin('编辑网站');
    const original = await readLlms(editor);
    const prepared = {
      overview: 'probe-overview-tc0019',
      extras: [{ name: 'Probe', value: 'field-tc0019' }],
      custom: 'probe-custom-tc0019',
    };
    await saveSystem(editor, prepared);
    await saveCustom(editor, prepared.custom);
    remember(ctx.caseId, ['overview', 'extras', 'custom']);
    return { prepared, original, restore: () => applyLlms(editor, original) };
  }
  if (ctx.caseId === 'TC-0050') {
    const editor = await ctx.openAdmin('编辑网站');
    const original = await readLlms(editor);
    remember(ctx.caseId, ['overview', 'custom']);
    return {
      prepared: { custom: 'probe-custom-tc0050' },
      original,
      restore: () => applyLlms(editor, original),
    };
  }
  if (ctx.caseId === 'TC-0023') {
    const editor = await ctx.openAdmin('编辑网站');
    const originalMeta = await readMeta(editor);
    const marker = 'probe-meta-tc0023';
    await writeMeta(editor, marker);
    remember(ctx.caseId, ['homepage-meta']);
    return {
      metaMarker: marker,
      originalMeta,
      restore: () => writeMeta(editor, originalMeta),
      verify: async () => (await readMeta(editor)) === originalMeta,
    };
  }
  return null;
}

export async function restoreCaseData(_ctx, state) {
  if (state?.restore) await state.restore();
}
