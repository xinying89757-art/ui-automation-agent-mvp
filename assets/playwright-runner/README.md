# Standalone Playwright runner

Generated specs execute with Node.js and Playwright; no Codex runtime, global skills,
or external business-source checkout is required.

1. With Node.js 22+, run `npm ci`, then `npx playwright install chromium`.
2. Copy `config.example.json` to a protected local JSON file and configure targets,
   fixture data rules and authentication references. Supply secret values through named
   environment variables. `{ "env": "VARIABLE_NAME" }` data rules resolve at runtime.
3. Set `UIA_CONFIG` to the absolute config path, then run `npm test`. On POSIX shells:
   `UIA_CONFIG=/absolute/path/config.local.json npm test`.
4. View `results/manual/`. Manual execution reports evidence; it does not update the
   parent run manifest or claim the two-run stability gate was completed.

Specs use `support/test.ts`; each case has one `[case_id] title` test. Fixture modules
verify setup, cleanup and baseline; their prepare result is `caseContext.fixtureState`.
Core expectations use `businessAssertion`. Negative inputs remain invalid/blank.
Protected-page visitor cases create fresh unauthenticated contexts explicitly.

For discovery without a browser connector, use the local JSON-line session:

```bash
node support/explore.mjs --config /absolute/path/config.local.json --evidence-dir /absolute/path/evidence
```

Send one JSON object per line: `{"op":"navigate","url":"https://configured-host/path"}`,
`{"op":"snapshot"}`, or `{"op":"click","target":{"role":"button","name":"保存"},"mutates":true,"scope":"products.save"}`.
Use `value_env` for secret field fills. `frame` accepts observed iframe selectors and
`within` an observed container. Declare the real mutation flag/scope for each operation;
the helper cannot infer business side effects from button text.
Commands return saved evidence paths. Close with `{"op":"close"}` or stdin EOF.
Login state can be saved only when `--auth-out` was supplied; keep it outside delivered source.
