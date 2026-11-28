import { test, expect, businessAssertion } from '../../support/fixtures.js';
import { waitForSavedLinkPanel } from '../../flows/link-panel-readiness.mjs';
import { openNewProduct, fillProductName, editorFrame, openPanel, selectLink, saveProduct, reopenOwnedProduct } from './product-link-helpers.js';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

test('[RQ-1bc401d74b26-04] 创建并重新打开产品中的链接', async ({ caseContext }) => {
  const name=caseContext.ownerMarker;
  // @step S1
  // @step S17
  const page=await openNewProduct(caseContext);
  // @step S2
  await fillProductName(page,name);
  let editor=await editorFrame(page);
  const editable=editor.locator('[contenteditable="true"]');
  // @step S3
  let menuFrame;
  for (const candidate of page.frames()) if (candidate !== editor && await candidate.locator('.markdown-import-button').count().catch(()=>0)) {menuFrame=candidate;break;}
  if (!menuFrame) throw new Error('UIA_AUTOMATION_FAILURE: Markdown import button missing');
  await menuFrame.locator('.markdown-import-button').first().click();
  // @step S4
  const option = menuFrame.getByText('Markdown',{exact:true}).first();
  const chooserPromise = page.waitForEvent('filechooser',{timeout:10000});
  await option.click();
  const chooser = await chooserPromise;
  const snapshot = process.env.UIA_BATCH_FILES_DIR && path.join(process.env.UIA_BATCH_FILES_DIR,'tests/nofollow/fixtures/nofollow-import.md');
  const sample = snapshot && fs.existsSync(snapshot) ? snapshot : path.resolve(path.dirname(fileURLToPath(import.meta.url)),'fixtures/nofollow-import.md');
  await chooser.setFiles(sample);

  let link=editor.locator('[contenteditable="true"] a').filter({hasText:'Imported link'});
  await link.waitFor({state:'attached',timeout:15000});
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
  link=editor.locator('[contenteditable="true"] a').filter({hasText:'Imported link'});
  await link.waitFor({state:'attached',timeout:10000});
  await businessAssertion('A2',async observe=>{const rel=await link.getAttribute('rel');observe(rel??'(absent)');observe(initialChecked,1);expect((rel??'').split(/\s+/).includes('nofollow')).toBe(initialChecked);});
  // @step S10
  await saveProduct(page);
  // @step S11
  const reopened=await reopenOwnedProduct(caseContext,name);
  editor=reopened.editor;
  // @step S12
  link=editor.locator('[contenteditable="true"] a').filter({hasText:'Imported link'});
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
