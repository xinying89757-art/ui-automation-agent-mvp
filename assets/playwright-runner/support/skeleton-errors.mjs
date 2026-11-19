/** Typed failures for the shared editor skeleton. The code is the runner's classification key. */

export const CODES = Object.freeze({
  NAV_FAILED: 'NAV_FAILED',
  EDITOR_NOT_READY: 'EDITOR_NOT_READY',
  CONTROL_MISSING: 'CONTROL_MISSING',
  LOGIN_FAILED: 'LOGIN_FAILED',
  SAVE_FAILED: 'SAVE_FAILED',
  READBACK_MISMATCH: 'READBACK_MISMATCH',
  OVERLAY_BLOCKING: 'OVERLAY_BLOCKING',
});

export class SkeletonError extends Error {
  /**
   * @param {keyof typeof CODES | string} code
   * @param {string} message
   * @param {Record<string, unknown>} [details]
   */
  constructor(code, message, details = {}) {
    super(`${code}: ${message}`);
    this.name = 'SkeletonError';
    this.code = code;
    this.details = details;
  }
}

/** @param {unknown} error @param {string} fallback */
export function publicReason(error, fallback) {
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code) : '';
  return code || fallback;
}
