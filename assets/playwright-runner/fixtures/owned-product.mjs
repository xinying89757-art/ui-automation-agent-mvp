import fs from 'node:fs';
import path from 'node:path';
import { loadConfig } from '../support/environment.mjs';
import { navigateSnapshot } from '../support/navigation.mjs';

// A product belongs to this attempt only after an exact-name search proves absence.
// The test creates it later using state.name. Never touch an existing product.
async function productList(ctx) {
  let page = await ctx.openAdmin('内容管理');
  const route = await navigateSnapshot(page, loadConfig(), {steps: ['click:text=产品']});
  if (route.failed_step) throw new Error('Product list route could not be opened');
  page = route.page;
  const find = () => page.frames().find(frame => {
    try { return new URL(frame.url()).pathname === '/prod'; } catch { return false; }
  });
  await page.waitForFunction(() => Boolean(document.querySelector('iframe')), null, {timeout: 15000});
  for (let i = 0; i < 30 && !find(); i++) await page.waitForTimeout(500);
  const frame = find();
  if (!frame) throw new Error('Product list frame not available');
  await frame.locator('#searchProdName').waitFor({state:'visible', timeout:15000});
  return {page, frame};
}

async function searchExact(list, name) {
  const {page, frame} = list;
  await frame.locator('#searchProdName').fill(name);
  await frame.evaluate(() => {
    const container = document.querySelector('#conBox');
    if (!container || !container.querySelector('#content')) throw new Error('Product results table missing');
    window.__uiaProductSearchChanged = new Promise((resolve, reject) => {
      const observer = new MutationObserver(records => {
        if (!records.some(record => {
          const target = record.target.nodeType === Node.ELEMENT_NODE ? record.target : record.target.parentElement;
          return target?.closest?.('#content') || [...record.addedNodes, ...record.removedNodes].some(node =>
            node.nodeType === Node.ELEMENT_NODE && (node.id === 'content' || node.querySelector?.('#content')));
        })) return;
        clearTimeout(timer); observer.disconnect(); resolve(true);
      });
      const timer = setTimeout(() => { observer.disconnect(); reject(new Error('Product results did not refresh')); }, 15000);
      observer.observe(container, {childList:true, subtree:true, characterData:true});
    });
  });
  const response = page.waitForResponse(r => {
    try { return new URL(r.url()).pathname === '/prod/new/list/sub'; } catch { return false; }
  }, {timeout:15000});
  await frame.getByText('查询', {exact:true}).click();
  const result = await response;
  if (!result.ok()) throw new Error('Product search request failed');
  await frame.evaluate(() => window.__uiaProductSearchChanged);
  const links = frame.getByRole('link', {name, exact:true});
  return links;
}

function checkpoint(ctx, state) {
  const directory = process.env.UIA_STATE_DIR;
  if (!directory) return;
  fs.mkdirSync(directory, {recursive:true, mode:0o700});
  fs.writeFileSync(path.join(directory, `${ctx.batchId}-${ctx.caseId}.json`),
    JSON.stringify({name:state.name, owned:state.owned}), {mode:0o600});
}

async function prepare(ctx) {
  if (!/^uia-[A-Za-z0-9._-]+$/.test(ctx.ownerMarker)) throw new Error('Invalid product owner marker');
  const state = {name:ctx.ownerMarker, owned:false};
  ctx.fixtureState = state;
  const list = await productList(ctx);
  const links = await searchExact(list, state.name);
  if (await links.count() !== 0) throw new Error('Owned product marker already exists');
  state.owned = true;
  checkpoint(ctx, state);
  return state;
}
async function verifyPrepared(_ctx, state) { return state?.owned === true; }
async function cleanup(ctx, state) {
  state ??= ctx.fixtureState;
  if (!state?.owned) return;
  const list = await productList(ctx);
  const links = await searchExact(list, state.name);
  const count = await links.count();
  if (count > 1) throw new Error('Product owner marker is not unique');
  if (count === 1) {
    const row = links.locator('xpath=ancestor::tr');
    await row.locator('.edDel').click();
    const confirm = list.frame.getByTitle('Yes', {exact:true}).filter({visible:true});
    if (await confirm.count() !== 1) throw new Error('Product deletion confirmation is not unique');
    await confirm.click();
    await links.waitFor({state:'detached',timeout:15000});
  }
}
async function verifyCleanup(ctx, state) {
  state ??= ctx.fixtureState;
  if (!state?.owned) return true; // Preparation made no mutation and never delegated a product to the test.
  const list = await productList(ctx);
  return await (await searchExact(list, state.name)).count() === 0;
}
export default {prepare, verifyPrepared, cleanup, verifyCleanup};
