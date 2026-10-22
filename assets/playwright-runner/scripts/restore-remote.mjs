// Invoked on the box after remote observations or deadline; never shipped with check.mjs.
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from '@playwright/test';
import { loadConfig, launchOptions } from '../support/environment.mjs';
import { authenticatedSession, openSiteArea } from '../support/auth.mjs';
import { restoreForm, openForm, formMatches } from '../support/spec-data.mjs';
import { openFaq, restoreFaq } from '../flows/faq-data.mjs';
const cfg=loadConfig();const browser=await chromium.launch(launchOptions(cfg));
const proofs=[];
try {
 const session=await authenticatedSession(browser,cfg,{allowLogin:false});
 const leases=JSON.parse(fs.readFileSync(process.env.UIA_REMOTE_LEASES,'utf8'));
 for(const lease of leases) {
  const saved=JSON.parse(fs.readFileSync(lease.snapshot,'utf8'));
  const editor=await openSiteArea(session.page,cfg,'编辑网站');
  await restoreForm(editor,saved.original);await openForm(editor);
  if(!await formMatches(editor,saved.original))throw new Error('Cleanup mismatch');
  let faqProof;
  if(saved.faq) {
    const admin=await openSiteArea(session.page,cfg,'内容管理');const frame=await openFaq(admin);
    faqProof=await restoreFaq({...saved.faq,page:admin,frame});
    await admin.close();
  }
  await editor.close();proofs.push({case_id:lease.case_id,cleanup_verified:true,restored_at:new Date().toISOString(),faq:faqProof});
 }
 console.log(JSON.stringify({cleanup_verified:true,proofs}));
} catch {console.log(JSON.stringify({cleanup_verified:false,proofs}));process.exitCode=1;}
finally {await browser.close();}
