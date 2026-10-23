import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
const same = (a,b) => JSON.stringify(a) === JSON.stringify(b);
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
export async function openFaq(page) {
  await page.locator('#nav_faq a').click();
  const frame = page.frameLocator('#faq');
  await frame.locator('.top-title').getByRole('link',{name:'添加FAQ',exact:true}).waitFor({timeout:30000});
  await frame.locator('#load').waitFor({state:'hidden'});
  return frame;
}
async function list(frame) {
  await frame.locator('#load').waitFor({state:'hidden'});
  // Refuse incomplete snapshots: never silently truncate a paginated list.
  const total = await frame.locator('#pageBox .fl').innerText();
  const rows = await frame.locator('#content tr').filter({has:frame.locator('input.news_chk')}).evaluateAll(rows=>rows.map(row=>({
    id:row.querySelector('input.news_chk').value,
    question:row.querySelectorAll('td')[1].innerText.trim(),
    cells:[...row.querySelectorAll('td')].slice(1,-1).map(td=>td.innerText.trim()),
  })));
  if(Number(/\d+/.exec(total)?.[0]) !== rows.length) throw new Error('UIA_SETUP_FAILED: FAQ pagination requires a complete snapshot');
  return rows;
}
async function back(frame) {
  await frame.locator('#faq_list a').click();
  await frame.locator('.top-title').getByRole('link',{name:'添加FAQ',exact:true}).waitFor();
  await frame.locator('#load').waitFor({state:'hidden'});
}
async function readAnswer(frame, id) {
  const row = frame.locator('#content tr').filter({has:frame.locator('input.news_chk[value="'+id+'"]')});
  await row.locator('.edItem').click();
  const stored = frame.locator('textarea#faqContent');
  await stored.waitFor({state:'attached'});
  const html = await stored.inputValue();
  const answer = await stored.evaluate(field => {
    const fragment = document.createElement('div'); fragment.innerHTML = field.value;
    return fragment.textContent.trim();
  });
  await back(frame);
  return {answer,html};
}
export async function snapshotFaq(frame) {
  const rows = await list(frame);
  for(const row of rows) Object.assign(row, await readAnswer(frame,row.id));
  return rows;
}
export async function addFaq(frame, question, answer, rule) {
  if (rule?.method !== 'POST' || !rule.fields?.content) throw new Error('UIA_SETUP_FAILED: FAQ network catalog rule missing');
  await frame.locator('.top-title').getByRole('link',{name:'添加FAQ',exact:true}).click();
  await frame.locator('#msgTitle').waitFor({state:'visible'});
  // Serialize only the current form. CSRF and tenant fields remain in memory;
  // they are never logged, snapshotted or included in the remote hand-off.
  const current = await frame.locator('#editForm').evaluate(form => ({
    origin:location.origin, fields:Object.fromEntries([...new FormData(form)].filter(([,value])=>typeof value==='string')),
  }));
  const fields=current.fields;
  if (fields[rule.fields.id]) throw new Error('UIA_SETUP_FAILED: FAQ create form still refers to an existing record');
  fields[rule.fields.id]='';fields[rule.fields.title]=question;
  const escaped=answer.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  fields[rule.fields.content]='<p>'+escaped+'</p>';
  let response;
  try {response=await frame.locator('#editForm').page().request.post(new URL(rule.path,current.origin).href,{form:fields,timeout:20000});}
  catch {throw new Error('UIA_SETUP_FAILED: FAQ create transport error');}
  if(!response.ok()) throw new Error('UIA_SETUP_FAILED: FAQ create rejected');
  await back(frame);
}
export async function removeFaq(frame, id, page) {
  const row = frame.locator('#content tr').filter({has:frame.locator('input.news_chk[value="'+id+'"]')});
  const dialogHandler = dialog => dialog.accept();
  page.once('dialog',dialogHandler);
  await row.locator('.edDel').click();
  // The observed admin uses a confirmation dialog; accept only its explicit affirmative control.
  const confirmations = [page.getByText('确定',{exact:true}), frame.getByText('确定',{exact:true})];
  await Promise.race([row.waitFor({state:'detached',timeout:10000}), ...confirmations.map(button=>button.waitFor({state:'visible',timeout:10000}))]).catch(()=>{});
  for (const confirm of confirmations) if(await confirm.isVisible().catch(()=>false)) {await confirm.click();break;}
  await row.waitFor({state:'detached',timeout:15000});
  page.off('dialog',dialogHandler);
}
export async function prepareFaq(page, count, owner, checkpoint = ()=>{}, rule) {
  if(!Number.isInteger(count) || count < 0 || count > 50) throw new Error('UIA_SETUP_FAILED: FAQ count must be 0..50');
  const frame = await openFaq(page);
  const original = await snapshotFaq(frame);
  const state = {page,frame,original,prepared:[],added:[],ownerPrefix:`UIA FAQ ${owner} `};
  // Preserve existing identities/content/ordering; reducing existing data needs another reviewed adapter.
  if(original.length > count) throw new Error('UIA_SETUP_FAILED: cannot reduce existing FAQ count while preserving record identities');
  checkpoint(state);
  try {
    for(let i=original.length;i<count;i++) {
      const question = `UIA FAQ ${owner} ${i+1}`;
      await addFaq(frame,question,`UIA answer ${i+1}`,rule);
      const created = (await list(frame)).find(row=>row.question===question);
      if(!created) throw new Error('UIA_SETUP_FAILED: added FAQ missing');
      state.added.push(created.id);checkpoint(state);
    }
    state.prepared=await snapshotFaq(frame);
    state.pairs=state.prepared.map(row=>[row.question,row.answer]);
    if(state.prepared.length!==count) throw new Error('UIA_SETUP_FAILED: FAQ count mismatch');
    checkpoint(state);return state;
  } catch(error) {
    try {await restoreFaq(state);} catch(cleanup) {throw new AggregateError([error,cleanup], `FAQ preparation failed: ${String(error)}; cleanup failed: ${String(cleanup)}`);}
    throw error;
  }
}
export async function verifyFaq(state) {return same(await snapshotFaq(state.frame),state.prepared);}
export async function restoreFaq(state) {
  await back(state.frame);
  const current=await list(state.frame);
  // Also find owner-created rows when an exception happened after save but before checkpoint.
  for(const row of current.filter(row=>!state.original.some(old=>old.id===row.id))) {
    if(!state.added.includes(row.id) && !row.question.startsWith(state.ownerPrefix)) throw new Error('UIA_CLEANUP_FAILED: unowned FAQ appeared');
    await removeFaq(state.frame,row.id,state.page);
  }
  const restored=await snapshotFaq(state.frame);
  const proof={before_count:state.original.length,prepared_count:state.prepared.length,
    restored_count:restored.length,before_sha256:hash(state.original),restored_sha256:hash(restored),
    cleanup_verified:same(restored,state.original)};
  if(process.env.UIA_RESULTS_DIR) fs.writeFileSync(path.join(process.env.UIA_RESULTS_DIR,'faq-restore.json'),JSON.stringify(proof,null,2));
  if(!proof.cleanup_verified) throw new Error('UIA_CLEANUP_FAILED: FAQ snapshot differs after restore');
  return proof;
}
