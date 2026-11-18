import { openSettings, cancelDialog } from '../flows/llms-txt.mjs';

/** Open the saved form without changing its selected source. */
export async function openForm(page) {
  const box = page.locator('#backstage-dialog-customizeFile');
  if (!(await box.isVisible())) {
    await openSettings(page);
    for (let attempt = 0; attempt < 2; attempt++) {
      await page.locator('#site_customize_txt a').click();
      if (await box.waitFor({ state: 'visible', timeout: 8000 }).then(() => true).catch(() => false)) break;
    }
    await box.waitFor({ state: 'visible', timeout: 15000 });
  }
  // The container becomes visible before the asynchronous saved configuration arrives.
  await page.waitForFunction(() => {
    const dialog = document.querySelector('#backstage-dialog-customizeFile');
    const form = dialog?.querySelector('.llms-form');
    const enabled = dialog?.getAttribute('data-llms-enabled');
    return ['true', 'false'].includes(enabled) && form?.getAttribute('data-enabled') === enabled;
  }, null, { timeout: 20000 });
  return box;
}
export async function snapshotForm(page) {
  return page.locator('#backstage-dialog-customizeFile').evaluate(box => ({
    'llms.enabled': box.getAttribute('data-llms-enabled') === 'true',
    'llms.source': box.querySelector('.llms-custom-fields')?.getClientRects().length ? 'custom' : 'system',
    'llms.overview': box.querySelector('input.llms-overview')?.value ?? '',
    'llms.custom': box.querySelector('textarea.llms-custom-content')?.value ?? '',
    'llms.extras': [...box.querySelectorAll('.llms-extra-item')].map(row => ({
      name: row.querySelector('.llms-extra-name')?.value ?? '', value: row.querySelector('.llms-extra-value')?.value ?? '' })),
  }));
}
export async function applyForm(page, data) {
  const box = await openForm(page);
  if (data['llms.enabled'] === true && await box.getAttribute('data-llms-enabled') !== 'true') await box.locator('.llms-switch').click();
  for (const [key, value] of Object.entries(data)) {
    if (key === 'llms.source') {
      if (!['system', 'custom'].includes(value)) throw new Error('UIA_SETUP_FAILED: invalid source');
    } else if (key === 'llms.custom' || key === 'llms.overview') {
      await box.locator(key === 'llms.custom' ? 'label.llms-source-custom' : 'label.llms-source-system').click();
      await box.locator(key === 'llms.custom' ? 'textarea.llms-custom-content' : 'input.llms-overview').fill(value);
    } else if (key === 'llms.enabled') {
      // Applied first/last so fields remain editable during restoration.
    } else if (key === 'llms.extras') {
      await box.locator('label.llms-source-system').click();
      const remove = box.locator('.llms-remove-field:visible');
      for (let n = 0; await remove.count(); n += 1) {
        if (n >= 50) throw new Error('UIA_SETUP_FAILED: extras removal did not converge');
        await remove.last().click();
      }
      for (const row of value) {
        await box.locator('a.llms-add-field').click();
        await box.locator('input.llms-extra-name:visible').last().fill(row.name);
        await box.locator('input.llms-extra-value:visible').last().fill(row.value);
      }
    } else throw new Error('UIA_EXPLORATION_REQUIRED: data-prep handler ' + key);
  }
  if (data['llms.source']) await box.locator('label.llms-source-' + data['llms.source']).click();
  if (typeof data['llms.enabled'] === 'boolean') {
    const enabled = await box.getAttribute('data-llms-enabled') === 'true';
    if (enabled !== data['llms.enabled']) await box.locator('.llms-switch').click();
  }
}
export async function formMatches(page, expected) {
  const actual = await snapshotForm(page);
  return Object.entries(expected).every(([key, value]) => JSON.stringify(actual[key]) === JSON.stringify(value));
}
export async function restoreForm(page, baseline) {
  await cancelDialog(page);
  const box = await openForm(page);
  if (await formMatches(page, baseline)) return;
  // Restore persisted data only when the test actually changed it.
  await applyForm(page, baseline);
  await box.locator("a[class*='customize_file_llms']").click();
  await box.waitFor({ state: 'hidden' });
  await openForm(page);
  if (!await formMatches(page, baseline)) throw new Error('UIA_CLEANUP_FAILED: saved baseline differs after restore');
}
