import type { FullResult, Reporter, TestCase, TestResult } from '@playwright/test/reporter';
import fs from 'node:fs';
import path from 'node:path';

export default class UiaReporter implements Reporter {
  private cases: Record<string, unknown>[] = [];
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
  }
  private clean(value: string): string {
    for (const secret of this.secrets) value = value.split(secret).join('[REDACTED]');
    return value;
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
    const passed = result.status === 'passed' && lifecycle.setup_verified === true && lifecycle.cleanup_verified === true;
    const status = passed ? 'passed' : /UIA_ENVIRONMENT_BLOCKED/u.test(message) ? 'environment_blocked'
      : /UIA_PRODUCT_CONFIRMATION/u.test(message) ? 'product_confirmation'
      : /UIA_SETUP_FAILED/u.test(message) ? 'automation_failure'
      : /UIA_BUSINESS_FAILURE/u.test(message) ? 'business_failure'
      : /UIA_CLEANUP_FAILED/u.test(message) ? 'automation_failure'
      : result.status === 'interrupted' || result.status === 'skipped' ? 'interrupted' : 'automation_failure';
    this.cases.push({ case_id: caseId, result: status, playwright_status: result.status,
      setup_started: result.attachments.some(a => a.name === 'uia-setup-started'),
      duration_ms: result.duration, retry: result.retry, errors, lifecycle,
      script: test.location.file, line: test.location.line,
      attachments: result.attachments.filter(a => a.path).map(a => ({ name: a.name, path: a.path })) });
    this.flush('running', false);
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
  onEnd(result: FullResult): void { this.flush(result.status, true); }
}
