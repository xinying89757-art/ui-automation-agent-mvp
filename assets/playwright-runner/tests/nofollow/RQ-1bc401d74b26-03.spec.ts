import { test, expect, businessAssertion } from '../../support/fixtures.js';
import { waitForSavedLinkPanel } from '../../flows/link-panel-readiness.mjs';
import { openNewProduct, fillProductName, editorFrame, openPanel, selectLink, saveProduct, reopenOwnedProduct } from './product-link-helpers.js';

test('[RQ-1bc401d74b26-03] 创建并重新打开产品中的链接', async ({ caseContext }) => {
  const name=caseContext.ownerMarker;
  // @step S1
  // @step S17
  const page=await openNewProduct(caseContext);
  // @step S2
  await fillProductName(page,name);
  let editor=await editorFrame(page);
  const editable=editor.locator('[contenteditable="true"]');
  // @step S3
  await page.context().grantPermissions(['clipboard-read','clipboard-write']);
  await page.evaluate(async (text: string) => navigator.clipboard.writeText(text),'https://example.com/');
  await editable.click();
  await editable.press('ControlOrMeta+V');
  await editable.press('Space');
  // @step S4
  await editor.locator('[contenteditable="true"] a').first().waitFor({state:'attached',timeout:15000});

  let link=editor.locator('[contenteditable="true"] a').filter({hasText:'https://example.com/'});
  await link.waitFor({state:'attached',timeout:15000});
  await expect.poll(async () => Boolean(await link.getAttribute('href')),{timeout:10000}).toBe(true);
  await test.info().attach('uia-pasted-link-context', {contentType:'application/json',body:Buffer.from(JSON.stringify({href_present:Boolean(await link.getAttribute('href')),href_matches:(await link.getAttribute('href'))==='https://example.com/'}))});
  // @step S5
  await selectLink(page,editor,link);
  // @step S6
  let panel=await openPanel(editor);
  const firstAddress=await test.step('uia-step:link.panel-data-ready', () => waitForSavedLinkPanel(panel.address));
  await panel.checkbox.waitFor({state:'attached'});
  const initialChecked=await panel.checkbox.isChecked();
  // @step S7
  await businessAssertion('A1',async observe=>{observe(firstAddress);observe(initialChecked,1);expect(firstAddress).toBe('https://example.com/');});
  // @step S8
  await editor.getByRole('button',{name:'保存',exact:true}).click();
  // @step S9
  link=editor.locator('[contenteditable="true"] a').filter({hasText:'https://example.com/'});
  await link.waitFor({state:'attached',timeout:10000});
  await businessAssertion('A2',async observe=>{const rel=await link.getAttribute('rel');observe(rel??'(absent)');observe(initialChecked,1);expect((rel??'').split(/\s+/).includes('nofollow')).toBe(initialChecked);});
  // @step S10
  await saveProduct(page);
  // @step S11
  const reopened=await reopenOwnedProduct(caseContext,name);
  editor=reopened.editor;
  // @step S12
  link=editor.locator('[contenteditable="true"] a').filter({hasText:'https://example.com/'});
  await link.waitFor({state:'attached',timeout:20000});
  await businessAssertion('A3',async observe=>{const rel=await link.getAttribute('rel');observe(rel??'(absent)');observe(initialChecked,1);expect((rel??'').split(/\s+/).includes('nofollow')).toBe(initialChecked);});
  // @step S13
  await selectLink(reopened.page,editor,link);
  // @step S14
  panel=await openPanel(editor);
  const finalAddress=await test.step('uia-step:link.panel-data-ready', () => waitForSavedLinkPanel(panel.address));
  await panel.checkbox.waitFor({state:'attached'});
  // @step S15
  await businessAssertion('A4',async observe=>{const checked=await panel.checkbox.isChecked();observe(finalAddress);observe(checked,1);expect(finalAddress).toBe('https://example.com/');expect(checked).toBe(initialChecked);});
});
