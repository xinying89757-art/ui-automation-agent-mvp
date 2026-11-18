/** Shared, bounded interaction patterns selected from knowledge/patterns.yaml. */
export async function performWithPatterns(page, locate, patterns = [], action) {
  const retries = Math.max(patterns.includes('RERENDER_RELOCATE') ? 3 : 1,
    patterns.includes('OCCLUDED_SCROLL_OR_COLLAPSE') ? 2 : 1);
  for (let attempt = 0; attempt < retries; attempt++) {
    let target = locate();
    try {
      await target.waitFor({ state: 'visible' });
      if (patterns.includes('OCCLUDED_SCROLL_OR_COLLAPSE')) await target.scrollIntoViewIfNeeded();
      if (patterns.includes('RERENDER_RELOCATE')) {
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      }
      target = locate(); // resolve again after scrolling/layout changes
      await action(target);
      return;
    } catch (error) {
      if (patterns.includes('MENU_KEYBOARD') &&
          /intercepts pointer events|not receiving pointer events|not clickable|outside of the viewport|timed? ?out|timeout|not visible|hidden|not stable|unstable|not enabled|disabled/i.test(String(error))) {
        // Keep focus on the editor/trigger that opened the menu; option nodes often cannot focus.
        try {
          const aria = await target.getAttribute('aria-label').catch(() => null);
          const label = String(aria || await target.textContent().catch(() => '') || '').trim();
          if (label) {
            await page.keyboard.type(label);
            await page.keyboard.press('Enter');
            return;
          }
          throw new Error('Menu target has no typeahead label');
        } catch {
          await page.keyboard.press('ArrowDown');
          await page.keyboard.press('Enter');
          return;
        }
      }
      const intercepted = /intercepts pointer events|not receiving pointer events|outside of the viewport/i.test(String(error));
      const detached = /detached|not attached|not connected|target closed/i.test(String(error));
      if (intercepted && patterns.includes('OCCLUDED_SCROLL_OR_COLLAPSE') && attempt < 1) {
        const covering = page.locator('[aria-expanded="true"]').last();
        if (await covering.count()) {
          const collapse = covering.locator('..').locator('button,a,[role="button"],[role="link"]').first();
          if (await collapse.count()) await collapse.click({ timeout: 3000 }).catch(() => {});
        }
        continue;
      }
      if (!detached || attempt + 1 >= retries) throw error;
    }
  }
  throw new Error('Interaction pattern retries exhausted');
}

export async function clickWithPatterns(page, locate, patterns = []) {
  return performWithPatterns(page, locate, patterns, target => target.click({ timeout: 5000 }));
}
