import fs from 'node:fs';
import path from 'node:path';
import { prepareFaq, verifyFaq, restoreFaq, openFaq, snapshotFaq } from '../flows/faq-data.mjs';
import { markRestored } from '../support/remote-checks.mjs';
import { cancelDialog } from '../flows/llms-txt.mjs';
import { snapshotForm, applyForm, formMatches, openForm } from '../support/spec-data.mjs';

// Preparation is driven by catalog keys, never by case IDs. Unimplemented keys block.
async function prepare(ctx) {
  const started = Date.now();
  const spec = ctx.spec;
  const data = spec?.data_prep ?? {};
  if (!Object.keys(data).length && !spec?.mutation_scope?.length) return { readonly: true, precondition_check: 'satisfied', preparation: 'reused', prep_time_ms: 0 };
  const page = await ctx.openAdmin('编辑网站');
  await openForm(page);
  const original = await snapshotForm(page);
  // Keep the baseline before the first mutation so even partial preparation can restore it.
  const llmsData = Object.fromEntries(Object.entries(data).filter(([key]) => key.startsWith('llms.')));
  const formSatisfied = await formMatches(page, llmsData);
  let faqSatisfied = true;
  if (data['faq.count'] !== undefined) {
    const admin = await ctx.openAdmin('内容管理');
    const frame = await openFaq(admin);
    faqSatisfied = (await snapshotFaq(frame)).length === data['faq.count'];
  }
  const state = { original, page, data: llmsData, faq: null,
    precondition_check: formSatisfied && faqSatisfied ? 'satisfied' : 'not_satisfied',
    preparation: formSatisfied && faqSatisfied ? 'reused' : 'prepared' };
  const checkpoint = () => {
    const directory = process.env.UIA_STATE_DIR;
    if (!directory) return;
    fs.mkdirSync(directory, {recursive:true,mode:0o700});
    fs.writeFileSync(path.join(directory, ctx.batchId + '-' + ctx.caseId + '.json'), JSON.stringify({
      original, faq:state.faq && {original:state.faq.original, prepared:state.faq.prepared, added:state.faq.added, ownerPrefix:state.faq.ownerPrefix}
    }), {mode:0o600});
  };
  checkpoint();
  ctx.fixtureState = state;
  try {
    if (state.preparation === 'reused') {
      state.prep_time_ms = Date.now() - started;
      return state;
    }
    if (data['faq.count'] !== undefined) {
      const admin = await ctx.openAdmin('内容管理');
      state.faq = await prepareFaq(admin, data['faq.count'], ctx.ownerMarker, faq => {state.faq=faq;checkpoint();}, ctx.networkCatalog?.['faq.create']);
    }
    if (!formSatisfied) await applyForm(page, llmsData, { save: false });
    state.prep_time_ms = Date.now() - started;
    return state;
  } catch (error) {
    await cancelDialog(page);
    throw error;
  }
}
async function verifyPrepared(_ctx, state) {
  return state?.readonly || await formMatches(state.page, state.data) && (!state.faq || await verifyFaq(state.faq));
}
async function cleanup(ctx, state) {
  state ??= ctx.fixtureState;
  if (!state || state.readonly) return;
  const deferred = path.join(process.env.UIA_RESULTS_DIR ?? '', 'remote-' + ctx.caseId + '.json');
  if (fs.existsSync(deferred) && !ctx.forceRestore) {
    ctx.cleanupPending = true;
    return;
  }
  // Keep an already-satisfied or prepared precondition in place. Only remove FAQ
  // rows created by this run; do not restore pre-existing site values.
  await cancelDialog(state.page);
  if (state.faq?.added?.length) state.faq.restoreProof = await restoreFaq(state.faq);
  markRestored(ctx);
}
async function verifyCleanup(ctx, state) {
  state ??= ctx.fixtureState;
  if (!state || state.readonly) return true;
  if (ctx.cleanupPending) return false;
  return !state.faq?.added?.length || state.faq.restoreProof?.cleanup_verified === true;
}
export default { prepare, verifyPrepared, cleanup, verifyCleanup };
