/** Delay only the configured method/path, and count every matching request. Never log payloads. */
export async function delayRequests(page, rule, delayMs) {
  if (!Number.isInteger(delayMs) || delayMs < 1 || delayMs > 30000) throw new Error('Invalid network delay');
  let count = 0;
  const pending = new Set();
  const matcher = url => url.pathname === rule.path;
  const handler = async route => {
    if (route.request().method() !== rule.method) return route.fallback();
    count += 1;
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    pending.add(release);
    const timer = setTimeout(release, delayMs);
    await gate;
    clearTimeout(timer); pending.delete(release);
    await route.continue();
  };
  await page.route(matcher, handler);
  return { count: () => count, release: () => { for (const done of pending) done(); },
    dispose: async () => { for (const done of pending) done(); await page.unroute(matcher, handler); } };
}
/** A physical double-click continues hitting the same position even after the first click disables it. */
export async function doubleClick(page, locator) {
  await locator.waitFor({state:'visible'});
  const box = await locator.boundingBox();
  if (!box) throw new Error('Target has no visible bounds');
  await page.mouse.click(box.x + box.width/2, box.y + box.height/2, {clickCount:2, delay:40});
}
/** Try a real pointer click on a blocked control, without overriding its actionability. */
export async function attemptClick(page, locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error('Blocked control disappeared');
  await page.mouse.click(box.x + box.width/2, box.y + box.height/2);
}

/** Count visible appearances, including transient toasts that disappear before assertions finish. */
export async function observeOccurrences(page, text) {
  await page.getByText(text,{exact:true}).first().waitFor({state:'hidden',timeout:10000});
  const id = 'uia-' + Math.random().toString(36).slice(2);
  await page.evaluate(({id,text}) => {
    const states = window.__uiaOccurrences ??= {};
    const state = states[id] = {count:0, previous:new Set(), observer:null};
    const scan = () => {
      const visible = new Set([...document.querySelectorAll('*')].filter(el=>
        el.textContent?.trim()===text && ![...el.children].some(child=>child.textContent?.trim()===text) &&
        el.getClientRects().length && el.checkVisibility({checkVisibilityCSS:true,checkOpacity:true})));
      for(const el of visible) if(!state.previous.has(el)) state.count++;
      state.previous=visible;
    };
    state.observer=new MutationObserver(scan);
    state.observer.observe(document.documentElement,{childList:true,subtree:true,characterData:true,attributes:true});
    scan();
  },{id,text});
  return {count:()=>page.evaluate(id=>window.__uiaOccurrences[id].count,id),
    dispose:()=>page.evaluate(id=>{window.__uiaOccurrences[id].observer.disconnect();delete window.__uiaOccurrences[id];},id)};
}
