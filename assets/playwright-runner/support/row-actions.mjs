/** Safe mapping for the confirmed content-list row action toolbar. */
const LABELS = /(?:删除|delete|trash|remove)/iu;
const EDIT = /(?:编辑|edit|pencil)/iu;
const PREVIEW = /(?:预览|preview|eye)/iu;

export function actionText(action = {}) {
  return [action.title, action.aria, action.tooltip, action.text, action.className, action.iconClass, action.href]
    .filter(Boolean).join(' ').trim();
}

export function isDeleteAction(action) {
  return LABELS.test(actionText(action));
}

export function operationColumnIndex(headers, cellCount) {
  const index = Array.isArray(headers) ? headers.findIndex(value => String(value ?? '').trim() === '操作') : -1;
  if (index >= 0 && index < cellCount) return index;
  return cellCount > 0 ? cellCount - 1 : -1;
}

/**
 * Resolve the human-confirmed edit/preview action from a row's 操作 cell.
 * Positional mapping is allowed only for the five-button toolbar and is
 * always guarded against a delete/trash label or icon.
 */
export function selectRowAction(actions, purpose = 'edit') {
  if (!Array.isArray(actions) || !actions.length) return null;
  const all = actions.map(action => ({ ...action, label: actionText(action) }));
  const index = purpose === 'preview' ? 2 : 0;
  const labelled = all.find(action => purpose === 'preview' ? PREVIEW.test(action.label) : EDIT.test(action.label));
  const candidate = labelled ?? (all.length === 5 ? all[index] : null);
  if (!candidate) return null;
  if (isDeleteAction(candidate)) {
    const error = new Error('Refusing to click a delete/trash row action');
    error.code = 'DELETE_GUARD';
    throw error;
  }
  // Do not allow a known destructive action to be mistaken for a positional
  // edit or preview action when icon classes or tooltips are available.
  if (purpose === 'edit' && PREVIEW.test(candidate.label) ||
      purpose === 'preview' && EDIT.test(candidate.label)) return null;
  return { index: candidate.index ?? all.indexOf(candidate), action: candidate };
}

/** Read a preview target without navigating to or loading its frontend page. */
export function previewURLFromAction(action, baseURL) {
  const value = action?.href || action?.dataHref || action?.dataUrl || action?.dataRoute;
  if (!value || value === '#' || /^javascript:|^void\s*\(/iu.test(value)) return null;
  try {
    const url = new URL(value, baseURL);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    for (const key of [...url.searchParams.keys()])
      if (/^(?:s|c|session|sid|token|access_token|ticket)$/iu.test(key)) url.searchParams.delete(key);
    return url.href;
  } catch { return null; }
}

/** Click Preview while aborting document navigations, then return its URL only. */
export async function clickPreviewForURL(page, locator, { timeout = 3000 } = {}) {
  const context = page.context();
  const before = page.url();
  const routeHandler = route => route.request().isNavigationRequest() ? route.abort() : route.continue();
  let popup = null;
  const popupPromise = context.waitForEvent('page', { timeout }).then(value => { popup = value; return value; }).catch(() => null);
  await context.route('**/*', routeHandler);
  try {
    await locator.click({ noWaitAfter: true, timeout: Math.min(timeout, 2500) });
    const opened = await popupPromise;
    if (opened) {
      await opened.waitForURL(url => url.href !== 'about:blank', { timeout }).catch(() => {});
      const target = safeURL(opened.url());
      await opened.close().catch(() => {});
      return target === 'about:blank' ? null : target;
    }
    const target = safeURL(page.url());
    return target !== before ? target : null;
  } finally {
    await context.unroute('**/*', routeHandler).catch(() => {});
  }
}

function safeURL(value) {
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    for (const key of [...url.searchParams.keys()])
      if (/^(?:s|c|session|sid|token|access_token|ticket)$/iu.test(key)) url.searchParams.delete(key);
    return url.href;
  } catch { return null; }
}

export const ENTRY_NAV_TIMEOUT_MS = 60_000;
