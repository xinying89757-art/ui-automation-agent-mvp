// Scope observations to notices that appear or change after the file is chosen.
const notices = '[role="alert"], [role="status"], .el-message, .el-notification';

export async function watchImportNotices(frame) {
  return frame.evaluateHandle(selector => {
    const seen = new Set();
    const visibleNotices = () => new Map([...document.querySelectorAll(selector)]
      .filter(node => node.getClientRects().length && getComputedStyle(node).visibility === 'visible')
      .map(node => [node, node.textContent.trim().replace(/\s+/gu, ' ')]));
    let previous = visibleNotices();
    const observer = new MutationObserver(() => {
      const current = visibleNotices();
      for (const [node, text] of current) {
        if (text && previous.get(node) !== text && seen.size < 12) seen.add(text.slice(0, 200));
      }
      previous = current;
    });
    observer.observe(document.documentElement, {subtree: true, childList: true, characterData: true,
      attributes: true, attributeFilter: ['class', 'style', 'hidden', 'role']});
    return { seen, observer };
  }, notices);
}

export function matchingImportNotice(messages, filename) {
  return messages.find(text => text === `已导入 ${filename} 并转化为文档样式`) ?? '';
}
