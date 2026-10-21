/** Text scrub for tokens that show up in page snapshots. Files are removed separately. */

const JWT = /eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g;
const QUERY_SECRET = /(authorization|token|access_token|password)=[^&\s"']+/gi;
const EMAIL = /[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g;
const PIN = /(PIN码[:：]\s*)\S+/g;
const PHONE = /(?<!\d)1[3-9]\d{9}(?!\d)/g;

export function scrubText(value) {
  return String(value)
    .replace(JWT, '[REDACTED]')
    .replace(QUERY_SECRET, '$1=[REDACTED]')
    .replace(EMAIL, '[email]')
    .replace(PIN, '$1[REDACTED]')
    .replace(PHONE, '[phone]');
}

export function unsafeArtifact(name) {
  const base = String(name).split(/[\\/]/u).pop();
  if (['error-context.md', 'trace.zip', 'playwright-results.json'].includes(base)) return true;
  return /\.(png|jpe?g|webp|webm)$/iu.test(base);
}
