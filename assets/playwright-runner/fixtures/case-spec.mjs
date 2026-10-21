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
  const state = { original, page, data };
  ctx.fixtureState = state;
  try {
    await applyForm(page, data, { save: false });
    return state;
  } catch (error) {
    await restoreForm(page, original);
    throw error;
  }
}
async function verifyPrepared(_ctx, state) {
  return state?.readonly || await formMatches(state.page, state.data);
}
async function cleanup(ctx, state) {
  state ??= ctx.fixtureState;
  if (!state || state.readonly) return;
  // Cancel draft-only changes; restore persisted baselines when the test saved.
  await restoreForm(state.page, state.original);
}
async function verifyCleanup(ctx, state) {
  state ??= ctx.fixtureState;
  if (!state || state.readonly) return true;
  await openForm(state.page);
  const restored = await formMatches(state.page, state.original);
  await cancelDialog(state.page);
  return restored;
}
export default { prepare, verifyPrepared, cleanup, verifyCleanup };
