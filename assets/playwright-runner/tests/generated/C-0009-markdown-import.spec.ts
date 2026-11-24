import { test, expect, businessAssertion } from '../../support/fixtures.js';
import { navigateSnapshot } from '../../support/navigation.mjs';
import { loadConfig } from '../../support/environment.mjs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import { waitForProductEditor } from '../markdown/editor-ready.js';

test('[C-0009] 三种 Markdown 文件格式导入', async ({ page }) => {
  const { active, editor, editable } = await test.step('uia-preparation:product-editor', async () => {
    const route=await navigateSnapshot(page,loadConfig(),{steps:['click:text=产品','click:text=添加产品'],entrySteps:2});
    if(route.failed_step) throw Error('UIA_LOCATOR_MISS: 未到达产品描述');
    const active=route.page;
    const { editor, editable } = await waitForProductEditor(active);
    return { active, editor, editable };
  });
  const candidates=active.frames().filter((f:any)=>f!==editor);
  let menuFrame:any;
  for(const frame of candidates) if(await frame.locator('.markdown-import-button').count().catch(()=>0)) {menuFrame=frame; break;}
  if(!menuFrame) throw Error('UIA_LOCATOR_MISS: 未找到导入按钮');
  for(const frame of active.frames()) await frame.evaluate(() => {
    const w=window as any; w.__uiaImportAlerts=[];
    const remember=()=>document.querySelectorAll('[role="alert"],.el-message,.el-notification').forEach(e=>{const t=(e.textContent||'').trim();if(t&&!w.__uiaImportAlerts.includes(t)) w.__uiaImportAlerts.push(t);});
    new MutationObserver(remember).observe(document.documentElement,{subtree:true,childList:true,characterData:true});
  }).catch(()=>{});
  const importButton=menuFrame.locator('.markdown-import-button').first();
  // @step S1
  await importButton.click();
  const option=menuFrame.getByText('Markdown',{exact:true}).first();
  await businessAssertion('A1',async()=>{await expect(option).toBeVisible();});
  // @step S2
  let chooserPromise=active.waitForEvent('filechooser',{timeout:10000});
  await option.click();
  let chooser=await chooserPromise;
  await businessAssertion('A2',async()=>{expect(chooser).toBeTruthy();});
  // @step S3
  const snapshotRoot=process.env.UIA_BATCH_FILES_DIR && path.join(process.env.UIA_BATCH_FILES_DIR, 'tests/markdown/fixtures');
  const fileRoot=snapshotRoot && fs.existsSync(snapshotRoot)
    ? snapshotRoot : path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../markdown/fixtures');
  const results:string[]=[];
  const observations:{heading:string|null, items:number, toast:boolean}[]=[];
  for(const [index,extension] of ['md','markdown','txt'].entries()){
    if(index){ await editable.click(); await editable.press(process.platform==='darwin'?'Meta+A':'Control+A'); await editable.press('Backspace'); await importButton.click(); await expect(option).toBeVisible(); chooserPromise=active.waitForEvent('filechooser',{timeout:10000}); await option.click(); chooser=await chooserPromise; }
    for(const frame of active.frames()) await frame.evaluate(() => {(window as any).__uiaImportAlerts=[];}).catch(()=>{});
    await chooser.setFiles(path.join(fileRoot,`sample.${extension}`));
    await expect(editor.getByText('导入标题',{exact:true})).toBeVisible({timeout:15000});
    let alerts=0; for(const frame of active.frames()) alerts+=(await frame.evaluate(()=>(window as any).__uiaImportAlerts?.length||0).catch(()=>0));
    observations.push({heading:await editable.locator('h1').first().textContent(),items:await editable.locator('ul li').count(),toast:alerts>0});
    results.push(extension);
  }
  await businessAssertion('A3',async()=>{expect(results).toEqual(['md','markdown','txt']);});
  // @step S4
  await businessAssertion('A4',async()=>{
    expect(observations).toEqual(Array.from({length:3},()=>({heading:'导入标题',items:2,toast:true}))); 
  });
});
