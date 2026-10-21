---
name: uia-runtime
description: 在本项目按复用计划预检、探索并生成运行 Playwright，管理数据清理、有限修复和同版本两次独立成功判定。
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
- Save registration JSON with source-step/capability/assertion file+line coverage,
  evidence, required gap resolutions, hooks, reuse IDs and dynamic dependencies.
  Call `register`; failed gates return concrete problems to repair without weakening assertions.

## Run, repair, resume

- Install declared dependencies and the required browser only when executing an authorized
  workflow. Call `run-batch` for selected ready cases; default worker count is one,
  Playwright retries are disabled. The command saves receipts, code snapshots and results.
- After first PASS, the case remains runnable. Call `next` and run it again with fresh
  setup/context. Stable means two consecutive successes of identical relevant versions.
- A business expectation mismatch is a `business_failure`; preserve it. Locator/timing/
  generation failures may use `repair` after a saved diagnosis and successful cleanup,
  at most two repair rounds. Re-register changed scripts and restart the success count.
- Cleanup failure blocks only affected fixtures. Restore them through observed UI,
  save cleanup verification and call `resolve-fixture`, then answer the scoped question.
- If interrupted, inspect `next`/`status`. `recover` consumes a completed batch report;
  `recover --abandon --evidence` preserves interruption evidence. Never abandon a still
  running process; verify it stopped first. Mutating interrupted cases require cleanup.
- While `next` returns `monitor`, inspect `status` batch progress and send concise
  updates. Reporter output is partial until its complete flag is true; do not import it early.

Output: real case results/evidence, registered scripts, reusable local flows and remaining
gaps. Return to the orchestrator after each batch. Do not silently mark unexecuted cases
passed, relabel one PASS as stable, or mutate the long-term knowledge bases here.
