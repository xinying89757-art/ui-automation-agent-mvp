---
name: uia-case-spec
description: 从已导入 Excel 原文编写 case-spec.v1，校验后确定性生成单用例 Playwright，仅探索未知页面目标。
---

# Excel → case-spec → Playwright

Read `docs/case-spec.md` from the project root.

Import using scripts/uia.py, bind existing specs, preflight and execute existing
runnable cases before generating. Resume run.json; never create a multi-agent layer.
Read only each selected imported source.json. Write case-spec.yaml with schema_version,
case_id, intent, automatable {status: 'yes'|'needs-env'|'manual', reason}, required_env,
data_prep, mutation_scope, start_page, steps, assertions and questions (normally ~40 lines).

Use environment names from preconditions.yaml and AI data keys from
assets/playwright-runner/knowledge/data-prep.yaml (e.g. faq.count: 5); extend catalogs
rather than hardcoding case branches. Unsupported data handlers remain TODO.
Use named targets from assets/playwright-runner/knowledge/page-map.yaml; unknowns are
?name. No selectors in case-spec. Steps use open/click/fill/hover/select/check/uncheck/
press/upload/wait/close/assert, each with its own target and unique S-number.
Use checks op disabled/enabled for blocked/available controls (native and aria-disabled).
Blocked / cannot save / 无法保存 / 置灰 expectations require a disabled check and an
assert observation step, never click a disabled control. Preserve every Excel error
message and dialog clause; missing errors remain business failures. Do not force-click.
For save-in-progress transitions, the initial click may precede a disabled assertion.

Assertions have A-number, after S-number, exact imported expectation cell/line in excel,
and nonempty checks. Preserve numbering, punctuation, all business clauses and blank
negative inputs. Never replace public-file expectations with editor-value assertions.
Absent/ambiguous expectations become questions in the upfront checklist. Locator
For each mutating save, add an optional top-level read_back entry with an R-number, the
save step, field target and intended value, a named reopen target sequence, and save_target
that references its network rule. The generated test checks the save business response,
reopens the editor and records redacted intended/actual evidence; mismatches are classified
as save_not_persisted. Lint warns when a mutating save has no read-back declaration.
uncertainty goes to exploration, not business questions. Cross-case duplicate checks
are invalid. Close steps require hidden assertions; technical teardown stays in fixtures.

Run spec lint, spec gen and optionally spec render through scripts/uia.py. Unknown
steps emit throwing TODO markers and cannot run. Specs must import test/expect/
businessAssertion from support/fixtures, whose page fixture opens the editor.
Coverage derives from // @step S1 and await businessAssertion('A1', ...); no hand-filled lines.

Explore once per node: knowledge, then bounded snapshot --node editor --frame
'#backstage-innerpage' or --open-target llms --scope '#dialog', then generator only if
needed. External invocation: timeout 2h codex exec ... < /dev/null. No delegation is
required. Strip icon glyphs, scope dialog locators, disambiguate repeated role/name
pairs with a container. Never persist session snapshot refs in knowledge.

Run with run-batch/wait; triage environment → session → data → locator/timing → business.
Only locator/timing changes may be repaired automatically. Never relax assertions.
Xinying authorizes test-site editing, saving and publishing; restore practical baselines
for repeatability. Never print credentials, tokens, cookies, storage or account names.

## Public files, network controls and FAQ

Read docs/remote-checks.md. Use defer_public + remote_file with a catalog public
resource; quote the complete Excel expectation unchanged. @deferred markers record
handoff coverage only, never a local assertion pass. Resolve FAQ conditions from the
prepared list. Preserve immediate-update expectations separately from cache grace.
Use network_delay/network_release and request_count from knowledge/network.yaml.
double_click and attempt_click send real pointer events; observe + occurrence_count
count transient visible results. visible_text observes displayed loading text.
Use faq.count from data-prep.yaml, preserving original IDs/order/content and verifying
restoration; do not delete baseline records to force a smaller count.
