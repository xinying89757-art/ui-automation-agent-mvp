import { clearOverview, waitForPublic } from '../flows/llms-txt.mjs';

async function prepare() {
  return { touchedOverview: false, marker: '' };
}

async function verifyPrepared(ctx) {
  return Boolean(ctx.targets?.public);
}

async function cleanup(ctx, state) {
  if (!state?.touchedOverview) return;
  const editor = await ctx.openAdmin('编辑网站');
  await clearOverview(editor);
}

async function verifyCleanup(ctx, state) {
  if (!state?.touchedOverview || !state.marker) return true;
  try {
    await waitForPublic(ctx.context.request, ctx.targets, body => !body.includes(state.marker));
    return true;
  } catch {
    return false;
  }
}

export default { prepare, verifyPrepared, cleanup, verifyCleanup };
