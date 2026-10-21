---
name: uia-automation-intent
description: Create traceable automation-intent.yaml from test cases, PRDs, prototypes, and ui-knowledge without asset matching, locator generation, or Playwright generation.
metadata:
  short-description: Build traceable UI automation intent YAML
---

# Automation Intent

Use this Skill when the user wants a business test case translated into the formal
`automation-intent.yaml v1.0` intermediate representation.

The Skill consumes Test Case, PRD, Prototype, and, when available, existing
`ui-knowledge/` assets and produces `automation-intent.yaml`. Its output describes
business intent, semantic UI context, semantic steps, required capabilities, assertions,
evidence, and runtime unknowns. It is an input to a future Asset Matcher.

## Hard boundary

Do not perform any of the following:

- choose or match an automation asset;
- emit `reuse-plan`, `matched_asset`, `selected_asset`, `reuse_readiness`,
  `effective_reuse_readiness`, or `dependency_closure`;
- read or use `automation-assets/`, its `match-index.yaml`, `dependency-index.yaml`,
  historical Playwright registries, or historical run reports reachable only through
  that asset library;
- use historical automation code or asset evidence to claim that the current business
  behavior has been verified;
- generate CSS, XPath, `nth`, `locator(...)`, or any final Locator;
- generate Playwright code;
- explore the browser or turn runtime observations into invented static facts;
- change a business assertion to fit an existing helper or asset.

Read [references/automation-intent-schema.md](references/automation-intent-schema.md)
as the normative field and enum contract before generating or updating an Intent.
Use [templates/automation-intent.example.yaml](templates/automation-intent.example.yaml)
when a complete example is needed, and
[templates/automation-intent.minimal.yaml](templates/automation-intent.minimal.yaml)
for a draft scaffold.

## Inputs and output

Inputs may be supplied inline, as files, or as links already available in the task:

- Test Case: expected business flow and business assertions;
- PRD: business rules and expected outcomes;
- Prototype: intended page/region terminology and visual flow;
- `ui-knowledge/ui-match-index.yaml`: first lookup for page/component/rule semantics;
- `ui-knowledge/runtime-required.yaml`: runtime unknowns and resolution references;
- `ui-knowledge/pages`, `components`, `interaction-rules`, `permissions`: detailed evidence;
- `ui-knowledge` runtime references and human-confirmed facts when explicitly supplied.

By default write `automation-intent.yaml` in the current task workspace, unless the
user specifies another path. If the file already exists, update the matching stable
`intent.id` or `intent.case.id` in place and preserve runtime/human enrichment.

## Required workflow

1. Read the normative reference and inspect the supplied source material. Resolve
   `ui-knowledge/` before generating UI references: search `ui-match-index.yaml` first,
   then open only the relevant `runtime-required.yaml`, `pages.yaml`, `components.yaml`,
   `interaction-rules.yaml`, and `permissions.yaml` records. Never search
   `automation-assets/` during this stage.
2. Establish the business contract from PRD and Test Case. For business expectations,
   PRD has priority over Test Case. A conflict is recorded as a blocking issue; never
   choose the “most reasonable” interpretation.
3. Resolve semantic page, region, and component references from `ui-match-index.yaml`
   plus detailed UI Profile evidence. Preserve every real Knowledge ID in
   `ui_context.*.knowledge_ref`, `ui_context.related_components[].knowledge_ref`,
   `required_capabilities[].ui_knowledge_refs`, and `knowledge.ui_profile_refs`.
   A UI Profile fact marked `CODE_CONFIRMED` or `CODE_INFERRED` is not automatically
   business `CONFIRMED`. Do not use an `INFRASTRUCTURE` component as a UI Target by
   default, and do not treat a `variant` with `activation: RUNTIME_REQUIRED` as an
   unconditional fact.
4. Create the exact top-level shape under `intent`: `id`, `lifecycle`, `case`,
   `eligibility`, `goal`, `test_data`, `preconditions`, `ui_context`, `steps`,
   `required_capabilities`, `assertions`, `knowledge`, `runtime_unknowns`,
   `automation_constraints`, and `validation`.
5. Express each action as a semantic Step. Use business names, anchors, expected types,
   variable references, transitions, capability references, runtime-unknown references,
   and source references. Never put a final Locator in a Step.
6. Add one Required Capability for each reusable ability the future Asset Matcher will
   need. Capabilities describe what is needed in stable semantic `snake_case`; they do
   not name helpers, bug IDs, historical files, or concrete asset IDs. Every required
   Step must reference at least one capability, and every capability must reference a
   Step.
7. Add core Assertions only for business expectations supported by a source reference or
   the business goal. Do not add `SUCCESS_FEEDBACK` merely because source code contains a
   toast. Use `runtime_unknowns` for unresolved close, search, loading, permission, or
   post-action behavior.
8. Separate knowledge into `confirmed`, `inferred`, and `ui_profile_refs`. Inferred
   facts must include `confidence`, `basis`, and
   `must_not_be_treated_as_confirmed: true`. Use only the allowed Source Types from the
   reference; model guesses belong in `knowledge.inferred`, not in `source`.
9. Record unresolved facts as Runtime Unknowns with a question, category, blocking
   decision, priority, affected Steps/Capabilities, UI runtime reference, and a
   preferred resolution. `blocking: true` means the affected Step must not execute
   before resolution; it does not prevent generating the Intent or matching assets.
   Runtime Unknowns must ask how the UI is presented, identified, operated, or observed;
   they must not ask whether a Test Case/PRD assertion occurs. For TC_PD_001, ask what
   control presents the page settings entry and how the selected “基础设置” state is
   identified, not whether that tab is selected; ask how the password control is rendered
   and identified, not whether it appears.
10. If `ui-knowledge/` is absent, explicitly degrade: use `null` for every
    `knowledge_ref` and `ui_runtime_ref`, add the `UI_KNOWLEDGE_NOT_AVAILABLE` warning,
    and do not invent a profile or runtime ID. A non-null UI reference is valid only if
    it resolves to an ID in the supplied `ui-knowledge/`.
11. Treat business assertions and Runtime Unknowns as separate classes. A result already
    stated by the Test Case or PRD is a business Assertion, not an unknown. Runtime
    Unknowns may ask only about implementation, presentation, entry/control semantics,
    navigation/refresh/async behavior, DOM/overlay/iframe behavior, or similar runtime
    mechanics. For example, “show the password page” and “show product content after
    correct verification” are assertions; “is the gate rendered as a page replacement,
    overlay, or another surface?” is a Runtime Unknown.
12. Set `validation.ready_for_asset_matching: true` only when the business goal, at least
   one valid Step, Step-to-Capability coverage, capability references, and at least one
   core business Assertion are complete and there is no requirements-level blocking
   ambiguity. Runtime Unknowns alone do not make it false.
13. Run the lightweight validator when available:
    `python3 scripts/validate_automation_intent.py automation-intent.yaml`.
    Fix structural violations, forbidden Locator syntax, source-type violations, missing
    references, unresolved UI IDs, forbidden asset references, lifecycle inconsistencies,
    and Secret values before reporting completion.
14. Return the Intent Summary described below.

## Source and conflict rules

Allowed source types are exactly:

`TEST_CASE`, `PRD`, `PROTOTYPE`, `UI_PROFILE`, `UI_PROFILE_RUNTIME_REQUIRED`, `HUMAN`,
`RUNTIME_OBSERVATION`.

Use this precedence for conflicting evidence:

1. Business expectation/rule: PRD, then Test Case; conflict is blocking.
2. Page/region semantics: Prototype plus UI Profile evidence.
3. Implementation-visible facts: UI Profile.
4. Real-page facts: Runtime Observation.
5. Human Confirmed may supplement a business fact but cannot silently override a PRD conflict.

Do not use `MODEL_GUESS` as a source. Record model reasoning as an inferred fact with a
transparent basis. Do not use an `INFRASTRUCTURE` component as a UI Target by default.
Do not treat a variant rule whose activation is `RUNTIME_REQUIRED` as unconditional.

## UI Knowledge, runtime input, and degradation

`ui-knowledge/` is a formal input, not optional decoration. The preferred lookup order
is `ui-match-index.yaml` → the matching page/component/rule/permission records → the
matching `runtime-required.yaml` record. When a match exists, retain the real ID in all
applicable UI context, capability, and knowledge reference fields, but first classify the
match as `EXACT` or `RELATED`:

- `EXACT` directly represents the current page, region, component, rule, or Runtime
  Unknown. Use it in target/context `knowledge_ref` fields and `ui_runtime_ref`.
- `RELATED` only supports the capability or profile context. Use it only in
  `required_capabilities[].ui_knowledge_refs` and `knowledge.ui_profile_refs`.

Same-page or same-component relevance is not enough for `EXACT`. Prefer EXACT, otherwise
downgrade to RELATED, otherwise use `null`. Never manufacture an ID from a Step,
Capability, Intent, or Runtime Unknown ID (for example `RU-01`).

Do not expand a Page ID across backend/frontend scope, use a generic Popup/Overlay
Component as an exact business target, or use a page-level ID as an exact Region ID.

If no `ui-knowledge/` is available, the Intent may still be generated from the Test
Case/PRD/Prototype, but every UI `knowledge_ref` and `ui_runtime_ref` must be `null` and
`validation.warnings` must contain `UI_KNOWLEDGE_NOT_AVAILABLE`. This is a transparent
degradation, not permission to create placeholder UI Profile references.

Runtime Observation is a separate, explicit input. Only a user-provided
`runtime-observation.yaml` or equivalent named Runtime Observation may populate
`knowledge.confirmed`/`RUNTIME_VERIFIED` or `runtime_enrichment`. Finding an old report
or any file under `automation-assets/` never qualifies. A PRE_RUNTIME Intent has no
`runtime_enrichment`; when explicit runtime input produces enrichment,
`lifecycle.stage` is `RUNTIME_ENRICHED`.

## Preconditions and capability granularity

If the Test Case explicitly says to prepare a product, account, password, or other
fixture, the existence of that precondition is `CONFIRMED` from `TEST_CASE`. Missing
concrete identifiers may be recorded as unresolved test data or a warning, but must not
downgrade the whole precondition to `RUNTIME_UNKNOWN`.

Capabilities are reusable semantic units for the future Asset Matcher, not a mechanical
copy of UI micro-operations. Several consecutive, tightly coupled Steps may share one
Capability, such as `configure_product_custom_url` for selecting a custom URL, entering
the path, and saving it, or `configure_password_access` for selecting password access,
entering the secret, and saving. Keep independent business abilities separate and do not
collapse an entire Case into one `business_flow` capability.

`eligibility.excluded_points` contains only source-test points intentionally excluded from
automation. Skill boundaries such as “does not generate Locators or match assets” belong
in this Skill, not in `excluded_points`; use `[]` when no test point is excluded.

`preferred_asset_types` uses only this canonical Automation Asset Registry vocabulary:

`auth`, `business_action`, `assertion`, `wait_strategy`, `ui_component`,
`locator_strategy`, `fixture`, `test_data`, `environment_helper`, `business_flow`,
`page_object`, `runtime_helper`, `state_manager`.

Do not invent synonyms. Normalize `environment_setup` to `environment_helper` and
`assertion_helper` to `assertion`. This is a static type protocol only; it does not
authorize Asset Matching or reading `automation-assets/`.

For TC_PD_001, prefer stable reusable capabilities such as
`navigate_to_product_management`, `open_target_product_editor`,
`configure_product_custom_url`, `open_product_page_settings`,
`configure_password_access`, `open_product_custom_url_in_clean_browser`,
`assert_password_gate_state`, `complete_frontend_password_verification`, and
`assert_product_detail_content_visible`. The exact count may vary with the source Steps,
but it should represent reusable abilities rather than one capability per micro-action.

## Data and security rules

Test-data variables use references such as `${customer_name}` and `${target_employee}`.
For `SECRET` variables, write no literal value into the Intent: use `value: null` or an
approved variable reference and keep only a non-secret source description/reference.

## Idempotent updates

When updating an existing Intent:

- match by stable `intent.id` or `case.id`;
- preserve `HUMAN_CONFIRMED`, `RUNTIME_VERIFIED`, and `runtime_enrichment` facts;
- do not silently downgrade verified facts with a new static scan;
- record source conflicts in `validation.conflicts` and/or
  `validation.blocking_issues`;
- do not append duplicate `source_refs` or duplicate Knowledge facts;
- keep the existing stable IDs for Steps, Capabilities, Assertions, and Runtime Unknowns
  when their meaning is unchanged.

## Intent Summary

After generating or updating the file, report:

- `case.id` / `case.name`;
- `eligibility`;
- `step_count`;
- `required_capability_count`;
- `assertion_count`;
- counts of confirmed, inferred, and runtime-unknown facts;
- resolved / partially-resolved / unresolved UI context counts;
- blocking Runtime Unknown count;
- `ready_for_asset_matching`;
- blocking issues and warnings.
- `ui_knowledge_available`;
- `ui_knowledge_refs_resolved`;
- `ui_knowledge_refs_unresolved`;
- `pseudo_reference_count` (must be `0`);
- `runtime_unknown_business_assertion_conflicts` (must be `0`);
- `automation_asset_reads` (must be `0`);
- `lifecycle_stage`.
- `reference_quality.exact_refs`;
- `reference_quality.related_refs`;
- `reference_quality.unresolved_refs`;
- `reference_quality.suspected_overmatches` (must be `0`).

Do not silently report PASS when `pseudo_reference_count` or
`runtime_unknown_business_assertion_conflicts` is non-zero, when any asset read is
detected, or when available UI Knowledge clearly matches the business semantics but all
related `knowledge_ref` fields remain null.

The summary is a report only. It must not contain an asset selection or Locator.

## Project integration

This is the self-contained project skill `uia-automation-intent`. Resolve supporting files relative to this folder. The project root is three parents above this folder. Coordinate through the project `uia-orchestrator` and `scripts/uia.py`; do not read or change globally installed skills. Existing YAML filenames and schemas retain their original names. Stage failure returns a concrete gap and affected case IDs to the orchestrator.
