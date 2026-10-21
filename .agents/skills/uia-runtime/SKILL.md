---
name: uia-runtime
description: 在本项目按复用计划预检、探索并生成运行 Playwright，管理数据清理、有限修复，以及每日一次交付或夜间两次回归。
---

# Runtime executor

Read [workflow](../../../docs/workflow.md) and [interfaces](../../../docs/interfaces.md).
Input: selected cases/flow, validated Intents/plans, environment configuration, and
saved runtime facts. Use available browser/Playwright tools to gather real UI evidence;
the Python CLI manages state and subprocesses, not autonomous UI reasoning.
If no browser connector exists, use the scaffold's self-contained JSON-line
`support/explore.mjs` session described in its README. It uses the runner's locked
Playwright dependency. Keep the process session alive across tool interactions.

## Preflight and discovery

- Read [environment/login](../../../docs/environments-and-login.md) for profile-based runs.
  Run `login --run` before exploration/execution; `--check-only` cannot satisfy preflight.
  Admin and editor reachability are required. A public front-end failure is recorded on
  `targets.public` and blocks only cases whose spec calls `waitForPublic`. Do not mark
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
- When a gap remains at the limit, queue a concrete locator/flow demonstration. Other
  flows continue. Imported Playwright scripts stay pending until independent replay
  and cleanup are evidenced via `replay-demo`. A Trace alone cannot replace the script.
- Preserve selectors and observed structures in run-local evidence/implementations;
  static UI knowledge remains semantic. Never invent selectors, routes or hidden behavior.

## Generate and register

- Use `scaffold` once; generate final tests under the standalone runner. Use its
  `support/test` fixture, title each test `[case_id] title`, and wrap every core expectation
  in `businessAssertion(assertionId, callback)`.
- Implement real flow-specific fixture hooks: prepare, verify prepared, cleanup and
  verify cleanup, including partial-setup cleanup. Read-only fixtures verify prerequisites
  and baseline. Intentionally invalid data in negative cases must remain invalid.
- Prefer semantic locators and observable waits. Use fresh unauthenticated contexts
  for visitor/password cases; never inherit an already-unlocked visitor session.
- Parameterize public/admin URLs, proxy, credentials references and test data. Copy
  reusable code into local exported modules so the runner has no absolute external imports.
- Keep default `page`/`context` unauthenticated. Use `adminPage`, `adminContext` or
  `caseContext.openAdmin('内容管理'|'编辑网站')` for managed access. These consume verified
  login state; refresh an expired session outside test traces via `login --run`.
  The runner and exported package carry `environments.json`, `network/gray.pac` and
  environment-check/login scripts. Do not introduce paths to the source workspace.
- Save registration JSON with source-step/capability/assertion file+line coverage,
  evidence, required gap resolutions, hooks, reuse IDs and dynamic dependencies.
  Call `register`; failed gates return concrete problems to repair without weakening assertions.

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
- A business expectation mismatch is a `business_failure`; preserve it. Locator/timing/
  generation failures may use `repair` after a saved diagnosis and successful cleanup,
  at most two repair rounds. Re-register changed scripts and restart the success count.
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
