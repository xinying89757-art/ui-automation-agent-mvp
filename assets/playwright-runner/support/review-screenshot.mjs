/** Capture a bounded dialog with all free text, inputs and media masked.
 * Only a small public UI vocabulary remains visible. Never capture the account shell.
 */
export async function redactedDialogScreenshot(page, destination) {
  const dialog = page.locator('[role="dialog"]:visible, #backstage-dialog-customizeFile:visible').first();
  if (!await dialog.count()) return null;
  const marker = 'data-uia-review-mask';
  const originals = await dialog.evaluate((root, attribute) => {
    const allowed = /^(?:管理txt文件|llms\.txt|robots\.txt|取消|关闭|保存|保存中[….]*|启用|自定义内容|系统生成|请填写自定义 llms\.txt 内容|内容来源|网站概述)$/u;
    const marked = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (!node.textContent?.trim() || allowed.test(node.textContent.trim())) continue;
      const element = node.parentElement;
      if (element && !element.hasAttribute(attribute)) { element.setAttribute(attribute, ''); marked.push(element); }
    }
    return marked.length;
  }, marker);
  try {
    await dialog.screenshot({ path: destination, animations: 'disabled', timeout: 5000,
      mask: [dialog.locator(`[${marker}], input, textarea, [contenteditable], img, canvas, svg, iframe, video`)],
      maskColor: '#222222' });
    return { path: destination, redacted: true, method: 'dialog-mask-public-ui-only', masked_nodes: originals };
  } finally {
    await dialog.locator(`[${marker}]`).evaluateAll((nodes, attribute) => nodes.forEach(n => n.removeAttribute(attribute)), marker).catch(() => {});
  }
}
