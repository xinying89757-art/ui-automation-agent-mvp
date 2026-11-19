import fs from 'node:fs';
import path from 'node:path';
import type { FullResult, Reporter, TestCase, TestResult, TestStep } from '@playwright/test/reporter';
import { credentials } from './auth.mjs';
import { classifyFailure } from './failure-class.mjs';
import { scrubText, unsafeArtifact } from './redact.mjs';

export default class UiaReporter implements Reporter {
  private cases: Record<string, unknown>[] = [];
  private assertions = new Map<string, { id: string; passed: boolean; evidence: { source: string; started_at: string; duration_ms: number } }[]>();
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
      rows.push({ id, passed: !step.error, evidence: { source: 'playwright-reporter',
        started_at: step.startTime.toISOString(), duration_ms: step.duration } });
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
    const spec = this.binding(caseId)?.spec;
    const isDeferred = (assertion: any) => assertion.checks?.length > 0 && assertion.checks.every((check: any) => check.op === 'remote_file');
    const localAssertions = (spec?.assertions ?? []).filter((assertion: any) => !isDeferred(assertion));
    const remoteExpected = (spec?.assertions ?? []).filter(isDeferred);
    const expected = (spec?.assertions ?? []).map((assertion: any) => assertion.id);
    const actual = this.assertions.get(test.id) ?? [];
    const deferred = this.deferredAssertions(caseId, remoteExpected);
    const assertionEvidence = localAssertions.length > 0
      ? localAssertions.every((assertion: any) => actual.some(row => row.id === assertion.id && row.evidence))
      : remoteExpected.length > 0 || (spec?.assertions?.length ?? 0) === 0 && actual.length > 0;
    const completeEvidence = assertionEvidence && remoteExpected.every((assertion: any) =>
      deferred.some(row => row.id === assertion.id && row.recorded && row.evidence));
    const passed = result.status === 'passed' && lifecycle.setup_verified === true && (lifecycle.cleanup_verified === true || lifecycle.cleanup_pending === true) && completeEvidence;
    const judged = result.status === 'passed' && !completeEvidence ? { result: 'unasserted', failure_class: null }
      : passed ? { result: 'passed', failure_class: null }
      : classifyFailure(message, result.status, this.locatorNeverResolved(message));
    const status = judged.result;
    const annotations = result.annotations?.length ? result.annotations : test.annotations;
    const rescued = annotations.filter(item => item.type === 'rescued_by_midscene').length;
    this.cases.push({ case_id: caseId, result: status, failure_class: judged.failure_class, playwright_status: result.status,
      rescued_by_midscene: rescued,
      setup_started: result.attachments.some(a => a.name === 'uia-setup-started'),
      duration_ms: result.duration, retry: result.retry, errors, lifecycle,
      assertions: actual, deferred_assertions: deferred, expected_assertions: expected,
      successful_steps: this.successfulSteps.get(test.id) ?? [],
      failure_stage: passed ? null : judged.failure_class === 'environment' ? 'environment' : /UIA_SAVE_NOT_PERSISTED/u.test(message) ? "save_not_persisted" : /UIA_SETUP_FAILED/u.test(message) ? "data_preparation" : this.locatorNeverResolved(message) ? "locator_resolution" : /UIA_BUSINESS_FAILURE/u.test(message) ? "business_assertion" : "locator_or_timing",
      read_back: this.readBack(caseId),
      saves: this.saveObservations(caseId),
      script: test.location.file, line: test.location.line,
      attachments: result.attachments.filter(a => this.keepAttachment(a)).map(a => ({ name: a.name, path: a.path })) });
    this.flush('running', false);
  }
  private binding(caseId: string | undefined): any {
    if (!caseId) return null;
    try {
      const file = process.env.UIA_CASES_FILE ?? path.join(process.env.UIA_RUN_ROOT ?? '.', 'state/cases.json');
      return JSON.parse(fs.readFileSync(file, 'utf8'))[caseId] ?? null;
    } catch { return null; }
  }
  private deferredAssertions(caseId: string | undefined, expected: any[]): any[] {
    if (!caseId || !expected.length || !process.env.UIA_RESULTS_DIR) return [];
    try {
      const file = path.join(process.env.UIA_RESULTS_DIR, `remote-${caseId}.json`);
      const rows = JSON.parse(fs.readFileSync(file, 'utf8')) as any[];
      return expected.map(assertion => {
        const row = rows.find(item => item.assertion_id === assertion.id && item.expected === assertion.excel &&
          Array.isArray(item.conditions) && item.conditions.length === assertion.checks.length);
        return { id: assertion.id, recorded: Boolean(row), evidence: row ? {
          source: 'remote-check-request', saved_at: row.saved_at } : null };
      });
    } catch { return []; }
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
