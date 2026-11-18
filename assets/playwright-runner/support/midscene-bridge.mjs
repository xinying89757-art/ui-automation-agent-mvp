/**
 * Midscene is optional. The default path never imports it.
 * A model key enables fallback locate / aiAssert; tests inject an adapter instead.
 * This module never logs key material.
 */
import { SkeletonError } from './skeleton-errors.mjs';

const KEY_NAMES = ['MIDSCENE_MODEL_API_KEY', 'OPENAI_API_KEY', 'DEEPSEEK_API_KEY'];

/** @param {NodeJS.ProcessEnv} [env] */
export function midsceneKeyName(env = process.env) {
  for (const name of KEY_NAMES) {
    const value = env[name];
    if (typeof value === 'string' && value.trim()) return name;
  }
  return '';
}

/** @param {NodeJS.ProcessEnv} [env] */
export function midsceneEnabled(env = process.env) {
  const flag = String(env.UIA_MIDSCENE ?? '').toLowerCase();
  if (flag === '0' || flag === 'off' || flag === 'false') return false;
  return Boolean(midsceneKeyName(env));
}

/** @type {{ locate?: Function, locateSelector?: Function, aiAssert?: Function } | null} */
let adapter = null;

/** Test seam. Production runs leave this unset and use the package only when a key exists. */
export function setMidsceneAdapter(next) {
  adapter = next;
}

export function currentMidsceneAdapter() {
  return adapter;
}

async function loadAgent(page) {
  const mod = await import('@midscene/web/playwright');
  const Agent = mod.PlaywrightAgent || mod.default;
  if (!Agent) throw new SkeletonError('CONTROL_MISSING', 'Midscene agent export missing');
  return new Agent(page);
}

/** @param {import('@playwright/test').Page} page @param {string} description @param {{ adapter?: any, env?: NodeJS.ProcessEnv }} [options] */
export async function locateControl(page, description, options = {}) {
  const chosen = options.adapter || adapter;
  if (chosen?.locate) return chosen.locate(page, description);
  if (chosen?.locateSelector) {
    const selector = await chosen.locateSelector(page, description);
    if (!selector) return null;
    return page.locator(selector).first();
  }
  if (!midsceneEnabled(options.env)) return null;
  try {
    const agent = await loadAgent(page);
    if (typeof agent.aiLocate === 'function') return agent.aiLocate(description);
    const selector = await agent.aiQuery?.(`CSS selector only for ${description}`);
    if (typeof selector === 'string' && selector.trim() && !/[\r\n]/.test(selector) && selector.length < 200)
      return page.locator(selector.trim()).first();
    return null;
  } catch (error) {
    if (error?.code === 'ERR_MODULE_NOT_FOUND') return null;
    return null;
  }
}

/** @param {import('@playwright/test').Page} page @param {string} expectation @param {{ adapter?: any, env?: NodeJS.ProcessEnv }} [options] */
export async function visualAssert(page, expectation, options = {}) {
  const chosen = options.adapter || adapter;
  if (!midsceneEnabled(options.env) && !chosen?.aiAssert) return { skipped: true, reason: 'no-model-key' };
  if (chosen?.aiAssert) {
    await chosen.aiAssert(page, expectation);
    return { skipped: false, reason: 'adapter' };
  }
  try {
    const agent = await loadAgent(page);
    if (typeof agent.aiAssert !== 'function') return { skipped: true, reason: 'package-not-installed' };
    await agent.aiAssert(expectation);
    return { skipped: false, reason: 'midscene' };
  } catch (error) {
    if (error?.code === 'ERR_MODULE_NOT_FOUND') return { skipped: true, reason: 'package-not-installed' };
    throw new SkeletonError('CONTROL_MISSING', '视觉断言未通过');
  }
}
