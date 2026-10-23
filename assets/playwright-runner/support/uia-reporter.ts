import fs from 'node:fs';
import path from 'node:path';
import type { FullResult, Reporter, TestCase, TestResult, TestStep } from '@playwright/test/reporter';
import { credentials } from './auth.mjs';
import { scrubText, unsafeArtifact } from './redact.mjs';

export default class UiaReporter implements Reporter {
  private cases: Record<string, unknown>[] = [];
  private assertions = new Map<string, { id: string; passed: boolean }[]>();
  private successfulSteps = new Map<string, string[]>();
  private startedAt = new Date().toISOString();
  private output: string;
  private secrets: string[];
  constructor(options: { outputFile?: string } = {}) {
    this.output = options.outputFile ?? 'results/manual/case-results.json';
    const cfg = process.env.UIA_CONFIG ? JSON.parse(fs.readFileSync(process.env.UIA_CONFIG, 'utf8')) : {};
    const names = new Set<string>(cfg.auth?.secret_env ?? []);
    const visit = (value: unknown, sensitive = false): void => {
      if (Array.isArray(value)) value.forEach(child => visit(child, sensitive));
      else if (value && typeof value === 'object') {
        const item = value as Record<string, unknown>;
        if (sensitive && typeof item.env === 'string') names.add(item.env);
        Object.entries(item).forEach(([key, child]) => visit(child, sensitive || /password|passwd|secret|token|credential|api_key/iu.test(key)));
      }
    };
    visit(cfg.data_rules);
    this.secrets = [...names].map(key => process.env[key]).filter((value): value is string => Boolean(value));
    if (cfg.auth?.credentials_file) {
      try { this.secrets.push(...Object.values(credentials(cfg)) as string[]); }
      catch { /* Authentication failure is reported by the fixture without raw secrets. */ }
    }
  }
  private clean(value: string): string {
    let text = value;
    for (const secret of this.secrets) text = text.split(secret).join('[REDACTED]');
    return scrubText(text);
  }
  private keepAttachment(attachment: { name?: string; path?: string }): boolean {
    if (attachment.name === 'uia-redacted-dialog' && attachment.path && !unsafeArtifact(attachment.path)) return true;
    if (!attachment.path || unsafeArtifact(attachment.path) || unsafeArtifact(attachment.name ?? '')) return false;
    return !['screenshot', 'trace', 'error-context', 'video'].includes(attachment.name ?? '');
  }
  private locatorNeverResolved(message: string): boolean {
    const resolved = /locator resolved to (?:<|\d+ elements?)/iu.test(message);
    return /UIA_LOCATOR_MISS|strict mode violation|resolved to 0 elements/iu.test(message) ||
      (/waiting for locator/iu.test(message) && !resolved);
  }
  onStepEnd(test: TestCase, _result: TestResult, step: TestStep): void {
    const id = /^assert:(A\d+)$/u.exec(step.title)?.[1];
    if (id) {
      const rows = this.assertions.get(test.id) ?? [];
      rows.push({ id, passed: !step.error });
      this.assertions.set(test.id, rows);
    }
    const processStep = /^uia-step:([A-Za-z0-9_.-]+)$/u.exec(step.title)?.[1];
    if (processStep && !step.error) {
      const steps = this.successfulSteps.get(test.id) ?? [];
      steps.push(processStep);
      this.successfulSteps.set(test.id, steps);
    }
  }
  onTestEnd(test: TestCase, result: TestResult): void {
    const caseId = test.annotations.find(a => a.type === 'uia_case')?.description ?? /^\[([^\]]+)\]/u.exec(test.title)?.[1];
    let lifecycle: Record<string, unknown> = {};
    const attachment = result.attachments.find(a => a.name === 'uia-lifecycle');
    if (attachment) {
      try { lifecycle = JSON.parse(attachment.body?.toString() ?? fs.readFileSync(attachment.path!, 'utf8')); }
      catch { lifecycle = {}; }
    }
    const errors = result.errors.map(error => this.clean(error.message ?? String(error)));
    const message = errors.join('\n');
    const passed = result.status === 'passed' && lifecycle.setup_verified === true && (lifecycle.cleanup_verified === true || lifecycle.cleanup_pending === true);
    const status = passed ? 'passed' : /UIA_ENVIRONMENT_BLOCKED/u.test(message) ? 'environment_blocked'
      : /UIA_PRODUCT_CONFIRMATION/u.test(message) ? 'product_confirmation'
      : /UIA_SAVE_NOT_PERSISTED/u.test(message) ? 'save_not_persisted'
      : /UIA_SETUP_FAILED/u.test(message) ? 'automation_failure'
      : this.locatorNeverResolved(message) ? 'automation_failure'
      : /UIA_BUSINESS_FAILURE/u.test(message) ? 'business_failure'
      : /UIA_CLEANUP_FAILED/u.test(message) ? 'automation_failure'
      : result.status === 'interrupted' || result.status === 'skipped' ? 'interrupted' : 'automation_failure';
    this.cases.push({ case_id: caseId, result: status, playwright_status: result.status,
      setup_started: result.attachments.some(a => a.name === 'uia-setup-started'),
      duration_ms: result.duration, retry: result.retry, errors, lifecycle,
      assertions: this.assertions.get(test.id) ?? [],
      successful_steps: this.successfulSteps.get(test.id) ?? [],
      failure_stage: passed ? null : /UIA_SAVE_NOT_PERSISTED/u.test(message) ? "save_not_persisted" : /UIA_ENVIRONMENT_BLOCKED/u.test(message) ? "environment_or_session" : /UIA_SETUP_FAILED/u.test(message) ? "data_preparation" : this.locatorNeverResolved(message) ? "locator_resolution" : /UIA_BUSINESS_FAILURE/u.test(message) ? "business_assertion" : "locator_or_timing",
      read_back: this.readBack(caseId),
      saves: this.saveObservations(caseId),
      script: test.location.file, line: test.location.line,
      attachments: result.attachments.filter(a => this.keepAttachment(a)).map(a => ({ name: a.name, path: a.path })) });
    this.flush('running', false);
  }
  private readBack(caseId: string | undefined): unknown {
    if (!caseId || !process.env.UIA_RESULTS_DIR) return null;
    try { return JSON.parse(fs.readFileSync(path.join(process.env.UIA_RESULTS_DIR, `read-back-${caseId}.json`), 'utf8')); }
    catch { return null; }
  }
  private saveObservations(caseId: string | undefined): unknown {
    if (!caseId || !process.env.UIA_RESULTS_DIR) return [];
    try { return JSON.parse(fs.readFileSync(path.join(process.env.UIA_RESULTS_DIR, `save-observations-${caseId}.json`), 'utf8')); }
    catch { return []; }
  }
  private flush(status: string, complete: boolean): void {
    fs.mkdirSync(path.dirname(this.output), { recursive: true });
    const report = { schema_version: 'uia-batch-results.v1', batch_id: process.env.UIA_BATCH_ID ?? null,
      started_at: this.startedAt, finished_at: complete ? new Date().toISOString() : null,
      status, complete, cases: this.cases };
    const temporary = `${this.output}.tmp-${process.pid}`;
    fs.writeFileSync(temporary, JSON.stringify(report, null, 2), { mode: 0o600 });
    fs.renameSync(temporary, this.output);
  }
  onEnd(result: FullResult): void {
    this.flush(result.status, true);
    dropUnsafe(path.dirname(this.output));
  }
}

function dropUnsafe(dir: string): void {
  if (!fs.existsSync(dir)) return;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'playwright-report' || entry.name === 'traces') {
        fs.rmSync(full, { recursive: true, force: true });
        continue;
      }
      dropUnsafe(full);
      continue;
    }
    if (unsafeArtifact(full)) fs.rmSync(full, { force: true });
  }
}
