import fs from 'node:fs';
import path from 'node:path';
import { prepareFaq, verifyFaq, restoreFaq } from '../flows/faq-data.mjs';
import { markRestored } from '../support/remote-checks.mjs';
import { cancelDialog } from '../flows/llms-txt.mjs';
import { snapshotForm, applyForm, formMatches, openForm, restoreForm } from '../support/spec-data.mjs';

// Preparation is driven by catalog keys, never by case IDs. Unimplemented keys block.
async function prepare(ctx) {
  const spec = ctx.spec;
  const data = spec?.data_prep ?? {};
  if (!Object.keys(data).length && !spec?.mutation_scope?.length) return { readonly: true };
  const page = await ctx.openAdmin('编辑网站');
  await openForm(page);
  const original = await snapshotForm(page);
  // Keep the baseline before the first mutation so even partial preparation can restore it.
  const llmsData = Object.fromEntries(Object.entries(data).filter(([key]) => key.startsWith('llms.')));
  const state = { original, page, data: llmsData, faq: null };
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
    if (data['faq.count'] !== undefined) {
      const admin = await ctx.openAdmin('内容管理');
      state.faq = await prepareFaq(admin, data['faq.count'], ctx.ownerMarker, faq => {state.faq=faq;checkpoint();}, ctx.networkCatalog?.['faq.create']);
    }
    await applyForm(page, llmsData, { save: false });
    return state;
  } catch (error) {
    await restoreForm(page, original);
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
  // Cancel draft-only changes; restore persisted baselines when the test saved.
  try { await restoreForm(state.page, state.original); }
  finally { if (state.faq) state.faq.restoreProof = await restoreFaq(state.faq); }
  markRestored(ctx);
}
async function verifyCleanup(ctx, state) {
  state ??= ctx.fixtureState;
  if (!state || state.readonly) return true;
  if (ctx.cleanupPending) return false;
  await openForm(state.page);
  const restored = await formMatches(state.page, state.original);
  await cancelDialog(state.page);
  return restored && (!state.faq || state.faq.restoreProof?.cleanup_verified === true);
}
export default { prepare, verifyPrepared, cleanup, verifyCleanup };
