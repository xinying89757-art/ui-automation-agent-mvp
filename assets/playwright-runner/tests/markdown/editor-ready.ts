import { expect } from '../../support/fixtures.js';

export async function waitForProductEditor(page: any) {
  await expect.poll(() => page.frames().some((frame: any) => frame.url().includes('/js/tiptapEditor/editor.html')), { timeout: 15000 }).toBe(true);
  for (let attempt = 0; attempt < 2; attempt++) {
    const editor = page.frames().find((frame: any) => frame.url().includes('/js/tiptapEditor/editor.html'));
    if (!editor) continue;
    const editable = editor.locator('[contenteditable="true"]').first();
    await expect(editable).toBeVisible();
    await expect(editable).toBeEditable();
    const first = await editable.elementHandle();
    if (!first) continue;
    const settled = await first.evaluate((node: Element) => new Promise<void>((resolve, reject) => {
      let idle: ReturnType<typeof setTimeout>;
      const timeout = setTimeout(() => { observer.disconnect(); reject(new Error('Editor did not become quiet')); }, 12000);
      const finish = () => { observer.disconnect(); clearTimeout(timeout); resolve(); };
      const reset = () => { clearTimeout(idle); idle = setTimeout(finish, 1500); };
      const observer = new MutationObserver(reset);
      observer.observe(node.ownerDocument.documentElement, { childList: true, subtree: true, attributes: true });
      reset();
    })).then(() => true).catch(() => false);
    if (!settled) { await first.dispose(); continue; }
    const current = await editable.elementHandle();
    const unchanged = current && await current.evaluate((node: Element, previous: Element) => node === previous, first).catch(() => false);
    await first.dispose();
    if (current) await current.dispose();
    if (unchanged) return { editor, editable };
  }
  throw new Error('UIA_LOCATOR_MISS: editor was redrawn during readiness check');
}
