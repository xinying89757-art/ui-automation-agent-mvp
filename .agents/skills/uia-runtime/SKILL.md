---
name: uia-runtime
description: 在本项目按 case-spec 预检、探索并生成运行 Playwright，管理数据清理、有限修复，以及每日一次交付或夜间两次回归。
---

# Runtime executor

Read [workflow](../../../docs/workflow.md) and [interfaces](../../../docs/interfaces.md).
Input: selected cases/flow, validated case-specs (legacy Intents/plans remain readable), environment configuration, and
saved runtime facts. Use available browser/Playwright tools to gather real UI evidence;
the Python CLI manages state and subprocesses, not autonomous UI reasoning.
Use `uia.py snapshot --run RUN --node editor` for bounded redacted visible-only
DOM evidence. Scope with `--frame '#backstage-innerpage'` or `--scope '#dialog'`;
`--open-target llms` opens that known node first. Do not use explore.mjs in the default flow.

## Preflight and discovery

- Read [environment/login](../../../docs/environments-and-login.md) for profile-based runs.
  Run `login --run` before exploration/execution; `--check-only` cannot satisfy preflight.
  Admin and editor reachability are required. A public front-end failure is recorded on
  `targets.public` and blocks only cases whose case-spec requires public_frontend or whose script reads a public page. Do not mark
  the rest of the workbook blocked, and do not replace the redacted browser error with
  a generic failure.
  Use the bundled environment, network and auth modules. Gray requires the local PAC
  and observed `X-Via: Ld-Gray`; never replace failed gray routing with direct production.
  Do not copy proxy addresses, historical credentials or site IDs into business specs.
- Verify reachability, actual login and target visibility through the real UI before
  business writes. Save secret-free browser evidence and call `preflight`.
- Explore only required gaps; reuse live-verified flows across selected cases.
  Record each strategy and duration through `explore`. Default budget: ten minutes per
  flow and two distinct strategies per gap. Do not repeat a strategy without new evidence.
- Demo requires a known, reached entry plus generator-cli --entry failure on a named --interaction; keep other flows running and independently replay/clean imported scripts.
- Preserve selectors and observed structures in run-local evidence/implementations;
  static UI knowledge remains semantic. Never invent selectors, routes or hidden behavior.

## Generate and register

- Use `scaffold` once; generate final tests under the standalone runner. Use its
  `support/fixtures` editor/seed fixture for case-spec scripts (legacy scripts retain support/test), title each test `[case_id] title`, and wrap every core expectation
  in `businessAssertion(assertionId, callback)`.
- Implement real flow-specific fixture hooks: prepare, verify prepared, cleanup and
  verify cleanup, including partial-setup cleanup. Read-only fixtures verify prerequisites
  and baseline. Intentionally invalid data in negative cases must remain invalid.
- Prefer semantic locators and observable waits. Use fresh unauthenticated contexts
  for visitor/password cases; never inherit an already-unlocked visitor session.
- Parameterize public/admin URLs, proxy, credentials references and test data. Copy
  reusable code into local exported modules so the runner has no absolute external imports.
- New specs consume the editor page fixture automatically; keep separate visitor
  contexts clean and refresh expired sessions outside test traces with login --run.
- Use spec lint/gen. AI-written final scripts use register with only case_id/script;
  coverage derives from // @step S1 and businessAssertion('A1'), never hand-filled lines.
- Strip icon glyphs; scope dialog-internal locators and repeated accessible names.
  Close steps require assertions. Snapshot refs must never enter knowledge/write-back.
- Triage environment → session → data → locator/timing → business assertion. Only
  locator/timing fixes may be automatic; assertion changes require explicit review.
- Xinying authorizes test-site/account changes, saving and publishing; restore practical
  baselines for repeatability. External Codex uses timeout 2h codex exec ... < /dev/null.

## Run, repair, resume

- Install declared dependencies and the required browser only when executing an authorized
  workflow. Call `run-batch` for every runnable case before escalating. Default worker
  count is one. One editor session is reused inside the batch; cases only reset the dialog.
  Playwright retries are disabled. The command saves receipts, a `heartbeat.json`, code
  snapshots and results, then absorbs passing locator hits.
- Wait with `python3 scripts/uia.py wait --run RUN`. It blocks on the heartbeat file.
  Do not decide that a batch died because a PID is invisible. Do not poll `status` in a
  loop for minutes, and do not classify the whole workbook as blocked in the first few
  minutes.
- `execution.stability_passes` 1 means the first clean pass is the daily deliverable
  (`stable`). Nightly regression sets it to 2 and needs a second independent batch.
  Do not relabel a single pass as stable when the run is configured for 2.
- A business expectation mismatch is a `business_failure`; preserve it. Before classifying
  a failure inside `businessAssertion` as a product defect, check whether the locator ever
  resolved. Strict-mode violations, zero matches, and timeouts waiting for locator resolution
  are automation failures even inside the wrapper. Route these through the locator/wait-only
  repair path; the healer gate must confirm the assertion signature is unchanged, then rerun
  once. Only a failure at the assertion value after that repaired run is a suspected defect.
  Do not reinterpret an assertion value mismatch as a locator miss. Other locator/timing/
  generation failures may use `repair` after saved diagnosis and successful cleanup, at most
  two repair rounds. Re-register changed scripts and restart the success count.
- Never edit framework code (scripts/uia_core, support/*.mjs|ts, schemas, skills) during a
  tester's run, even when a gate looks wrong. Keep the case at its current classification,
  add a `review` item named 流程缺陷 with the evidence, and finish the other cases.
- Run one `uia.py` command per run at a time. If a command returns "busy", use `wait`/`status`;
  do not start another `go` for the same workbook until the first returns.
- Cleanup failure blocks only affected fixtures. Restore them through observed UI,
  save cleanup verification and call `resolve-fixture`, then answer the scoped question.
- If interrupted, inspect `next`/`status`. `recover` consumes a completed batch report;
  `recover --abandon --evidence` preserves interruption evidence. Never abandon a still
  running process; verify it stopped first. Mutating interrupted cases require cleanup.
- While `next` returns `monitor`, run `wait` and send concise updates. Reporter output
  is partial until its complete flag is true; do not import it early.
- Run every case `next` marks runnable before asking a human. A public-file cache,
  a slow editor, or cases waiting on a precondition are not a reason to stop the run.
  Data preconditions (FAQ count, categories, navigation, homepage meta, site short name,
  quick contact, social widgets) are prepared and restored by the fixture. Human-only
  preconditions stay `waiting_human` until the one checklist is answered; do not classify
  them `not_suitable`.

Output: real case results/evidence, registered scripts, reusable local flows and remaining
gaps. Return to the orchestrator after each batch. Do not silently mark unexecuted cases
passed, relabel one PASS as stable, or mutate the long-term knowledge bases here.

## Deferred checks and cleanup leases

Case-spec defer_public resources do not require local public_frontend reachability.
Run every case that does not need the deferred data hold first. Reserve an environment
hold before starting remote-deferred preparation; persist it in private `.auth/` memory so
other runs/clones cannot mutate that site's data, while read-only cases remain runnable.
Prepare remote-deferred cases after independent work and emit request.json only after all
such preparations are complete. Immediate resources need `cache_bust: true` and
`earliest_check_at == saved_at`; preserve the executed result variant in the receipt.
A cleanup_pending lease is explicitly unverified, never a clean pass. Snapshot before
mutation under protected run-local state. remote-checks ingest restores overlapping
snapshots in reverse order after final results. On deadline/cancellation invoke
remote-checks restore; verify its evidence. A different run may execute read-only cases
while a hold exists, but cannot mutate site data. still-cached/unreachable stay pending
remote rather than waiting for a human or becoming PASS. Keep all attempts.
