/** Wait for a saved, nonempty link value to hydrate before asserting its value.
 * Use only when a newly opened panel starts blank or the caller has independently
 * established that a nonempty value belongs to this link; this cannot detect stale data.
 * A timeout is an automation/readiness failure, not proof of a product defect.
 * Invoke this outside businessAssertion so a readiness timeout is not reclassified
 * as a business failure. Callers must assert the returned value and checkbox state.
 */
export async function waitForSavedLinkPanel(input, {timeoutMs = 10000, pollMs = 100} = {}) {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || !Number.isFinite(pollMs) || pollMs <= 0) {
    throw new Error('Invalid link panel readiness timeout');
  }
  const deadline = Date.now() + timeoutMs;
  let wasVisible = false;
  while (Date.now() < deadline) {
    const remaining = Math.max(1, deadline - Date.now());
    try {
      await input.waitFor({state: 'visible', timeout: Math.min(remaining, 500)});
      wasVisible = true;
      const value = await input.inputValue({timeout: Math.min(remaining, 500)});
      if (value.trim()) return value;
    } catch {
      // Locator or frame may be replaced while the editor hydrates; resolve again.
    }
    const delay = Math.min(pollMs, Math.max(0, deadline - Date.now()));
    if (delay) await new Promise(resolve => setTimeout(resolve, delay));
  }
  throw new Error(wasVisible
    ? 'UIA_AUTOMATION_FAILURE: saved link panel did not populate before the readiness deadline'
    : 'UIA_AUTOMATION_FAILURE: saved link panel was not visible before the readiness deadline');
}
