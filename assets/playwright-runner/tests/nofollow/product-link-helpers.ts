import { test, expect } from '../../support/fixtures.js';
import { navigateSnapshot } from '../../support/navigation.mjs';
import { loadConfig } from '../../support/environment.mjs';

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
export async function productFrame(page: any) {
  const deadline = Date.now() + 25000;
  while (Date.now() < deadline) {
    const f = page.frames().find((x: any) => { try { return new URL(x.url()).pathname === '/prod'; } catch { return false; } });
    if (f) return f;
    await delay(200);
  }
  throw new Error('UIA_AUTOMATION_FAILURE: product frame did not appear');
}
export async function editorFrame(page: any) {
  const deadline = Date.now() + 25000;
  while (Date.now() < deadline) {
    const frame = page.frames().find((x: any) => x.url().includes('/js/tiptapEditor/editor.html'));
    if (frame) {
      const editable = frame.locator('[contenteditable="true"]');
      if (await editable.isVisible().catch(() => false) &&
          await editable.isEditable({timeout: 500}).catch(() => false)) return frame;
    }
    await delay(200);
  }
  throw new Error('UIA_AUTOMATION_FAILURE: product description editor did not become ready');
}
export async function openProductList(ctx: any) {
  let page = await ctx.openAdmin('内容管理');
  const route = await navigateSnapshot(page, loadConfig(), {steps:['click:text=产品']});
  if (route.failed_step) throw new Error('UIA_AUTOMATION_FAILURE: product navigation failed');
  page = route.page;
  const frame = await productFrame(page);
  await frame.locator('#searchProdName').waitFor({state:'visible',timeout:15000});
  return { page, frame };
}
export async function openNewProduct(ctx: any) {
  const {page, frame} = await openProductList(ctx);
  await frame.getByText('添加产品',{exact:true}).first().click();
  return page;
}
export async function fillProductName(page: any, name: string) {
  const deadline = Date.now() + 25000;
  while (Date.now() < deadline) {
    const frame = await productFrame(page);
    const field = frame.locator('[id="product.prodName"]');
    try {
      await field.fill(name,{timeout:1500});
      if (await field.inputValue({timeout:1500}) === name) { await field.press('Tab'); return; }
    } catch { /* Reacquire after the product page redraws. */ }
  }
  throw new Error('UIA_AUTOMATION_FAILURE: product name field was not ready');
}
export function checkbox(editor: any) {
  return editor.getByText('nofollow（搜索引擎不跟踪此链接）',{exact:true}).locator('..').locator('input[type=checkbox]');
}
export async function openPanel(editor: any) {
  const control = editor.getByTitle('设置链接',{exact:true});
  await test.step('uia-step:link.toolbar-visible', async () => {
    await control.waitFor({state:'visible',timeout:10000});
  });
  await test.step('uia-step:link.open-panel', async () => {
    await control.click({timeout:10000});
  });
  const address = editor.getByPlaceholder('输入链接');
  await test.step('uia-step:link.panel-visible', async () => {
    await address.waitFor({state:'visible',timeout:10000});
  });
  return {address, checkbox:checkbox(editor)};
}
export async function selectLink(page: any, editor: any, link: any) {
  await test.step('uia-step:link.select-original-text', () => selectExactText(page, editor, link));
}
async function selectExactText(page: any, editor: any, link: any) {
  const frames: any[] = [];
  for (let current=editor; current.parentFrame(); current=current.parentFrame()) frames.unshift(await current.frameElement());
  for (const element of frames) await element.evaluate((el: Element) => el.scrollIntoView({block:'center',inline:'nearest'}));
  await link.evaluate((el: Element) => el.scrollIntoView({block:'center',inline:'nearest'}));
  const box = await link.boundingBox();
  if (!box) throw new Error('UIA_AUTOMATION_FAILURE: link is not visible');
  const outer = await frames[frames.length-1].boundingBox();
  if (!outer) throw new Error('UIA_AUTOMATION_FAILURE: link frame is not visible');
  const hitContainsLink = await link.evaluate((el: Element, point: {x:number,y:number}) => document.elementFromPoint(point.x,point.y)?.contains(el),
    {x:box.x+box.width/2-outer.x,y:box.y+box.height/2-outer.y});
  if (!hitContainsLink) throw new Error('UIA_AUTOMATION_FAILURE: link text is obscured');
  await page.mouse.click(box.x+box.width/2,box.y+box.height/2);
  await link.selectText();
  const selection = await editor.evaluate(() => String(window.getSelection()));
  if (selection !== await link.textContent()) throw new Error('UIA_AUTOMATION_FAILURE: original link text was not fully selected');
}
export async function saveProduct(page: any) {
  const frame = await productFrame(page);
  const save = frame.locator('a.topBts_menu_save');
  await expect(save).toBeEnabled({timeout:20000});
  await save.click({timeout:15000});
  const confirm = frame.getByTitle('Yes',{exact:true}).filter({visible:true});
  try {
    await confirm.waitFor({state:'visible',timeout:7000});
    await confirm.click();
  } catch (error) {
    if (await confirm.isVisible().catch(()=>false)) throw error;
    // Some products have no duplicate warning; saved state is verified by search below.
  }
}
export async function reopenOwnedProduct(ctx: any, name: string) {
  const {page,frame} = await openProductList(ctx);
  await frame.locator('#searchProdName').fill(name);
  const response = page.waitForResponse((r: any) => { try { return new URL(r.url()).pathname === '/prod/new/list/sub'; } catch { return false; } }, {timeout:15000});
  await frame.getByText('查询',{exact:true}).click();
  if (!(await response).ok()) throw new Error('UIA_AUTOMATION_FAILURE: product search failed');
  const item = frame.getByRole('link',{name,exact:true});
  await item.waitFor({state:'visible',timeout:15000});
  await item.click();
  const editor = await editorFrame(page);
  return {page, editor};
}
