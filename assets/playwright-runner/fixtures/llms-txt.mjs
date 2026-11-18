import { writeOverview, openLlms, locate, cancelDialog } from '../flows/llms-txt.mjs';
import { prepareCaseData, readEditorState, restoreCaseData } from '../flows/data-prep.mjs';

async function prepare(ctx) {
  const prepared = await prepareCaseData(ctx);
  if (prepared) return { touchedOverview: false, dataPrep: true, ...prepared };
  return { touchedOverview: false, marker: '', originalOverview: '' };
}

async function verifyPrepared(ctx, state) {
  if (!state?.dataPrep) return true;
  if (ctx.caseId === 'TC-0019' || ctx.caseId === 'TC-0050') {
    const editor = await ctx.openAdmin('编辑网站');
    const current = await readEditorState(editor);
    if (ctx.caseId === 'TC-0019') {
      return current.overview === state.prepared.overview && current.custom === state.prepared.custom;
    }
    return true;
  }
  if (ctx.caseId === 'TC-0023') return state.metaMarker === 'probe-meta-tc0023';
  return Boolean(state.prepared);
}

async function cleanup(ctx, state) {
  if (state?.dataPrep) {
    await restoreCaseData(ctx, state);
    return;
  }
  if (!state?.touchedOverview) return;
  const editor = await ctx.openAdmin('编辑网站');
  await writeOverview(editor, state.originalOverview ?? '');
}

async function verifyCleanup(ctx, state) {
  if (state?.dataPrep && typeof state.verify === 'function') {
    const restored = await state.verify();
    if (!restored) return false;
  }
  if (state?.dataPrep && (ctx.caseId === 'TC-0019' || ctx.caseId === 'TC-0050')) {
    const editor = await ctx.openAdmin('编辑网站');
    const current = await readEditorState(editor);
    const probe = ctx.caseId === 'TC-0019' ? 'probe-custom-tc0019' : 'probe-custom-tc0050';
    return current.overview === (state.original?.overview ?? '')
      && current.custom === (state.original?.custom ?? '')
      && !current.custom.includes(probe)
      && !current.overview.includes('probe-overview');
  }
  if (state?.dataPrep) return true;
  if (!state?.touchedOverview) return true;
  const editor = await ctx.openAdmin('编辑网站');
  await openLlms(editor);
  const value = await (await locate(editor, 'overview')).locator.inputValue();
  await cancelDialog(editor);
  return value === (state.originalOverview ?? '');
}

export default { prepare, verifyPrepared, cleanup, verifyCleanup };
