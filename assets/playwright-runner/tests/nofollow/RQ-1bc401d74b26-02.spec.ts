import { test, expect, businessAssertion } from '../../support/fixtures.js';
import { waitForSavedLinkPanel } from '../../flows/link-panel-readiness.mjs';
import { openNewProduct, fillProductName, editorFrame, openPanel, selectLink, saveProduct, reopenOwnedProduct } from './product-link-helpers.js';

test('[RQ-1bc401d74b26-02] 保存并重新打开产品链接', async ({ caseContext }) => {
  const name = caseContext.ownerMarker;
  // @step S1
  // @step S17
  const page = await openNewProduct(caseContext);
  // @step S2
  await fillProductName(page,name);
  // @step S3
  let editor = await editorFrame(page);
  const editable = editor.locator('[contenteditable="true"]');
  await editable.fill('Checked link');
  // @step S4
  await selectLink(page,editor,editable.locator('p').first());
  // @step S5
  let panel = await openPanel(editor);
  await panel.checkbox.waitFor({state:'attached'});
  // @step S6
  await businessAssertion('A1', async observe => {
    const checked = await panel.checkbox.isChecked(); observe(checked);
    expect(checked).toBe(false);
  });
  // @step S7
  await panel.address.fill('https://example.com/');
  // @step S8
  await panel.checkbox.check();
  // @step S9
  await editor.getByRole('button',{name:'保存',exact:true}).click();
  // @step S10
  let link = editor.locator('[contenteditable="true"] a').filter({hasText:'Checked link'});
  await link.waitFor({state:'attached',timeout:10000});
  await businessAssertion('A2', async observe => {
    const rel = await link.getAttribute('rel'); observe(rel ?? '(absent)');
    expect((rel ?? '').split(/\s+/).includes('nofollow')).toBe(true);
  });
  // @step S11
  await saveProduct(page);
  // @step S12
  const reopened = await reopenOwnedProduct(caseContext,name);
  editor = reopened.editor;
  // @step S13
  link = editor.locator('[contenteditable="true"] a').filter({hasText:'Checked link'});
  await link.waitFor({state:'attached',timeout:20000});
  await businessAssertion('A3', async observe => {
    const rel = await link.getAttribute('rel'); observe(rel ?? '(absent)');
    expect((rel ?? '').split(/\s+/).includes('nofollow')).toBe(true);
  });
  // @step S14
  await selectLink(reopened.page,editor,link);
  // @step S15
  panel = await openPanel(editor);
  const observedAddress = await test.step('uia-step:link.panel-data-ready', () => waitForSavedLinkPanel(panel.address));
  await panel.checkbox.waitFor({state:'attached'});
  // @step S16
  await businessAssertion('A4', async observe => {
    const checked = await panel.checkbox.isChecked(); observe(observedAddress); observe(checked,1);
    expect(observedAddress).toBe('https://example.com/');
    expect(checked).toBe(true);
  });
});
