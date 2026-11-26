/** Text scrub for tokens that show up in page snapshots. Files are removed separately. */
import { credentials } from './auth.mjs';

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

export function evidenceRedactor(cfg) {
  const names = new Set(cfg.auth?.secret_env ?? []);
  function visit(value, sensitive = false) {
    if (Array.isArray(value)) value.forEach(child => visit(child, sensitive));
    else if (value && typeof value === 'object') {
      if (sensitive && typeof value.env === 'string') names.add(value.env);
      for (const [key, child] of Object.entries(value)) {
        visit(child, sensitive || /password|passwd|secret|token|credential|api_key/iu.test(key));
      }
    }
  }
  visit(cfg.data_rules);
  const secrets = [...names].map(name => process.env[name]).filter(Boolean);
  if (cfg.auth?.credentials_file) {
    try { const { account, password } = credentials(cfg); secrets.push(account, password); }
    catch { /* Login reports unavailable credentials separately. */ }
  }
  secrets.sort((a, b) => b.length - a.length);
  return value => scrubText(secrets.reduce((text, secret) => text.split(secret).join('[REDACTED]'), String(value)));
}

export function unsafeArtifact(name) {
  if (/(?:^|[\\/])review-screenshots[\\/][\w.-]+\.redacted\.png$/u.test(String(name))) return false;
  const base = String(name).split(/[\\/]/u).pop();
  if (['error-context.md', 'trace.zip', 'playwright-results.json'].includes(base)) return true;
  return /\.(png|jpe?g|webp|webm)$/iu.test(base);
}
