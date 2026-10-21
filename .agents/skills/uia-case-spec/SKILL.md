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
Assertions have A-number, after S-number, exact imported expectation cell/line in excel,
and nonempty checks. Preserve numbering, punctuation, all business clauses and blank
negative inputs. Never replace public-file expectations with editor-value assertions.
Absent/ambiguous expectations become questions in the upfront checklist. Locator
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
