# `automation-intent.yaml` v1.0

This document is the normative contract for the `automation-intent` Skill. The file is
an intermediate representation between business requirements/UI knowledge and a future
Asset Matcher.

```text
Test Case / PRD / Prototype / UI Knowledge
                    ↓
          automation-intent.yaml
                    ↓
              Asset Matcher
```

The Intent records what must be done and verified. It does not choose how an existing
automation asset will implement it. `ui-knowledge/` is a formal semantic evidence input;
`automation-assets/` is deliberately outside this document's input boundary.

## 1. Top-level shape

The required document shape is:

```yaml
schema_version: "1.0"
intent:
  id: "AI-..."
  lifecycle: {}
  case: {}
  eligibility: {}
  goal: {}
  test_data: {}
  preconditions: []
  ui_context: {}
  steps: []
  required_capabilities: []
  assertions: []
  knowledge: {}
  runtime_unknowns: []
  automation_constraints: {}
  validation: {}
```

`intent.runtime_enrichment` is an optional extension described in section 15. A
`PRE_RUNTIME` document may omit it; do not add an empty block only for symmetry.

## 2. Identity and lifecycle

```yaml
intent:
  id: "AI-CUSTOMER-001"
  lifecycle:
    stage: PRE_RUNTIME
    status: DRAFT
```

Allowed `stage` values:

- `PRE_RUNTIME`: generated from static sources; runtime facts are not yet observed;
- `RUNTIME_ENRICHED`: runtime observations have resolved or refined some unknowns;
- `FINALIZED`: the Intent is reviewed and complete for its intended downstream use.

Allowed `status` values:

`DRAFT`, `REVIEWED`, `READY_FOR_MATCHING`, `BLOCKED`, `FINALIZED`.

`BLOCKED` is appropriate for a requirements-level ambiguity or other issue that makes
the business contract unsafe to finalize. A blocking Runtime Unknown may remain in a
`READY_FOR_MATCHING` Intent because it blocks execution at a Step, not Intent creation.

## 3. Case, eligibility, and goal

```yaml
case:
  id: "CUSTOMER-001"
  name: "修改客户负责人"
  module: "客户管理"
  source_refs:
    - type: TEST_CASE
      ref: "CUSTOMER-001"
    - type: PRD
      ref: "客户管理 / 修改负责人"
  priority: P1

eligibility:
  status: ELIGIBLE
  reasons:
    - "核心操作和结果均可通过用户可见 UI 验证"
  excluded_points: []

goal:
  actor:
    semantic_name: "业务用户"
  action:
    semantic_name: "修改"
  object:
    semantic_name: "客户负责人"
  expected_business_result:
    - "目标客户的负责人变更为指定员工"
```

`eligibility.status` is one of `ELIGIBLE`, `PARTIALLY_ELIGIBLE`, or `NOT_ELIGIBLE`.
`goal` must express all four concepts: `actor`, `action`, `object`, and
`expected_business_result`. `expected_business_result` is a list of business outcomes,
not implementation details.

`case.priority` is normally `P0`–`P3` or the source system's explicit priority value;
preserve the source value when it is not one of those labels.

## 4. Test data

```yaml
test_data:
  variables:
    - id: customer_name
      semantic_name: "目标客户"
      type: STRING
      required: true
      value: null
      source:
        type: TEST_CASE
        ref: "CUSTOMER-001"
        description: "测试数据提供目标客户名称"
      sensitivity: NORMAL
```

Each variable supports:

`id`, `semantic_name`, `type`, `required`, `value`, `source`, and `sensitivity`.

Allowed `sensitivity` values are `NORMAL`, `SENSITIVE`, and `SECRET`.

Use references such as `${customer_name}` in Steps and Assertions. A `SECRET` variable
must never contain its literal value in the Intent. Use `value: null` (or an approved
non-secret variable reference) and retain only a source description/reference.

`source.type` must be one of the Source Types in section 12; `TEST_DATA` is not a
permitted Source Type.

## 5. Preconditions

Every item has this shape:

```yaml
preconditions:
  - id: PRE-01
    statement: "当前账号拥有客户编辑权限"
    knowledge_level: CONFIRMED
    source_refs:
      - type: TEST_CASE
        ref: "CUSTOMER-001"
```

Allowed `knowledge_level` values are exactly:

`CONFIRMED`, `INFERRED`, `RUNTIME_UNKNOWN`, `HUMAN_CONFIRMED`, `RUNTIME_VERIFIED`.

Use `RUNTIME_UNKNOWN` when the precondition is necessary but not established. Do not
silently turn a code fact into a business precondition. If the Test Case explicitly says
to prepare a target product, account, password, or other fixture, the existence of that
precondition is `CONFIRMED` from `TEST_CASE`; an unresolved concrete identifier is a
test-data warning, not a reason to downgrade the whole precondition.

## 6. UI Context

```yaml
ui_context:
  entry:
    semantic_path:
      - "客户管理"
      - "客户详情"
    knowledge_refs:
      - "page-customer-management"
      - "page-customer-detail"
  target_page:
    semantic_name: "客户详情"
    knowledge_ref: "page-customer-detail"
    resolution_status: RESOLVED
  target_region:
    semantic_name: "基本信息"
    knowledge_ref: null
    resolution_status: PARTIALLY_RESOLVED
  related_components:
    - semantic_name: "员工选择器"
      knowledge_ref: "component-employee-selector"
      role: UI_SURFACE
```

`entry.semantic_path` and `entry.knowledge_refs` identify the semantic route into the
flow. `target_page` and `target_region` use `semantic_name`, `knowledge_ref`, and
`resolution_status`. `related_components` may include only evidence-backed semantic
components; an `INFRASTRUCTURE` role is not a default UI Target.

Resolve UI references by searching `ui-match-index.yaml` first and then confirming the
match in the relevant detailed profile file. When a real match exists, preserve its exact
Knowledge ID in every applicable `knowledge_ref`, `ui_knowledge_refs`, and
`knowledge.ui_profile_refs` field. A non-null reference must resolve to an ID in the
supplied `ui-knowledge/`; IDs derived from an Intent, Step, Capability, or Runtime
Unknown are invalid. A variant whose `activation` is `RUNTIME_REQUIRED` remains runtime
dependent and cannot be used as an unconditional system fact.

When `ui-knowledge/` is unavailable, generation may continue, but all UI
`knowledge_ref`/`ui_runtime_ref` fields must be `null` and `validation.warnings` must
include `UI_KNOWLEDGE_NOT_AVAILABLE`. The absence itself is a warning, not a reason to
invent a pseudo-reference.

## 6.1 UI Knowledge reference precision

Every UI Knowledge match is classified as either `EXACT` or `RELATED`:

- `EXACT` directly represents the current page, region, component, rule, or Runtime
  Unknown. It may be written to `context.page.knowledge_ref`,
  `context.region.knowledge_ref`, `target.knowledge_ref`,
  `ui_context.target_page.knowledge_ref`, `ui_context.target_region.knowledge_ref`,
  `ui_context.entry.knowledge_refs`, or `ui_runtime_ref`.
- `RELATED` is relevant context but does not directly represent the current target. It
  may be written only to `required_capabilities[].ui_knowledge_refs` and
  `knowledge.ui_profile_refs`.

Being on the same page, in the same component family, or related to the same business
flow is not enough for `EXACT`. Prefer exact match, otherwise downgrade to `RELATED`,
otherwise use `null`. `null` is a valid result and is safer than an over-broad reference.

A Page Knowledge ID must not expand across page scope. A backend product-management page
does not become a frontend product-detail page merely because both mention “product”. A
generic Popup/Overlay Component may support a capability but must not become the exact
target of a page-settings entry unless the UI Profile directly proves that identity. A
Region ID must directly represent the named Region; page membership alone is not enough.

Allowed `resolution_status` values are `RESOLVED`, `PARTIALLY_RESOLVED`, and
`UNRESOLVED`.

## 7. Semantic Steps

Every Step should contain these fields whenever applicable:

```yaml
steps:
  - id: S1
    intent: "打开目标客户详情"
    context:
      page:
        semantic_name: "客户管理"
        knowledge_ref: "page-customer-management"
      region:
        semantic_name: "客户列表"
        knowledge_ref: null
    anchor:
      primary:
        semantic_name: "目标客户"
        value_ref: "${customer_name}"
      secondary: []
    target:
      semantic_name: "客户详情入口"
      expected_type: LINK_OR_ROW_ACTION
      knowledge_ref: null
    action:
      type: OPEN
      value_ref: null
    expected_transition:
      - type: PAGE_OR_REGION_VISIBLE
        semantic_target: "客户详情"
    required_capability_refs:
      - CAP-01
    runtime_unknown_refs: []
    source_refs:
      - type: TEST_CASE
        ref: "CUSTOMER-001"
```

Required/expected Step fields are:

- `id`: stable semantic ID;
- `intent`: human-readable business intent;
- `context.page` / `context.region`: semantic execution context;
- `anchor.primary` / optional `anchor.secondary`: semantic anchor and optional variable
  reference;
- `target.semantic_name`, `target.expected_type`, `target.knowledge_ref`;
- `action.type` and optional `action.value_ref`;
- `expected_transition`: semantic state/page/region change;
- `required_capability_refs`;
- `runtime_unknown_refs` when behavior is not established;
- `source_refs`.

Use semantic action types such as `OPEN`, `CLICK`, `FILL`, `SELECT`, `SAVE`, `WAIT`, and
`ASSERT`; preserve a more specific source term when needed. The action is an intent,
not an implementation instruction.

Never put CSS, XPath, `nth`, `locator(...)`, DOM depth, dynamic class names, or a final
Locator into any Step field.

## 8. Required Capabilities

Required Capabilities are the formal entry point for the future Asset Matcher:

```yaml
required_capabilities:
  - id: CAP-01
    capability: navigate_to_customer_detail
    semantic_name: "打开客户详情"
    category: NAVIGATION
    required: true
    step_refs: [S1]
    preferred_asset_types:
      - business_action
      - page_object
    ui_knowledge_refs:
      - "page-customer-management"
      - "page-customer-detail"
```

Each item has at least `id`, `capability`, `semantic_name`, `category`, `required`,
`step_refs`, `preferred_asset_types`, and `ui_knowledge_refs`.

Capabilities are reusable semantic units, not a one-to-one copy of UI micro-steps.
Consecutive, tightly coupled actions may share one capability, for example selecting a
custom URL, filling its path, and saving it as `configure_product_custom_url`, or
selecting password access, filling the secret, and saving it as
`configure_password_access`. Do not collapse an entire Case into one capability.

`preferred_asset_types` must use only the canonical Automation Asset Registry values:

`auth`, `business_action`, `assertion`, `wait_strategy`, `ui_component`,
`locator_strategy`, `fixture`, `test_data`, `environment_helper`, `business_flow`,
`page_object`, `runtime_helper`, `state_manager`.

Normalize `environment_setup` to `environment_helper` and `assertion_helper` to
`assertion`; do not introduce synonyms. These are static shared type labels, not
selected assets and not permission to read `automation-assets/`.

Allowed `category` values:

`AUTH`, `NAVIGATION`, `STATE_SETUP`, `TEST_DATA`, `UI_TARGET`, `UI_INTERACTION`,
`BUSINESS_ACTION`, `BUSINESS_FLOW`, `WAIT`, `ASSERTION`, `UPLOAD`, `DOWNLOAD`,
`ENVIRONMENT`.

`capability` must be stable semantic `snake_case` and express what is needed, for
example `navigate_to_customer_detail`. It must not be a historical helper name, bug ID,
concrete asset ID, or an instruction to reuse a particular asset.

Every required Step must reference at least one Capability. Every Capability's
`step_refs` must point to an existing Step. `ui_knowledge_refs` are evidence references,
not selected assets.

## 9. Assertions

```yaml
assertions:
  - id: A-01
    type: FIELD_VALUE
    target:
      semantic_name: "负责人"
      knowledge_ref: null
    expected:
      value_ref: "${target_employee}"
    required_capability_ref: CAP-05
    required: true
    source_refs:
      - type: TEST_CASE
        ref: "CUSTOMER-001"
```

Allowed assertion types:

`FIELD_VALUE`, `TEXT`, `VISIBILITY`, `PAGE_STATE`, `DIALOG_STATE`, `ROW_STATE`, `URL`,
`COUNT`, `ENABLED_STATE`, `SELECTED_STATE`, `SUCCESS_FEEDBACK`, `BUSINESS_RESULT`.

Each Assertion should include `id`, `type`, `target`, `expected`, `required`, and
`source_refs` or an explicit reference to the business goal. `required_capability_ref`
may identify its assertion capability. Do not add `SUCCESS_FEEDBACK` only because the
codebase contains a toast; it must be a business expectation or a confirmed runtime
observation.

## 10. Knowledge

```yaml
knowledge:
  confirmed:
    - id: K-01
      fact: "系统支持修改客户负责人"
      source_refs:
        - type: PRD
          ref: "客户管理 / 修改负责人"
  inferred:
    - id: K-02
      fact: "负责人编辑入口可能表现为按钮或图标"
      confidence: medium
      basis:
        - type: PROTOTYPE
          ref: "客户详情原型"
      must_not_be_treated_as_confirmed: true
  ui_profile_refs:
    pages:
      - "page-customer-detail"
    components:
      - "component-employee-selector"
    interaction_rules: []
    permissions: []
    runtime_refs:
      - "runtime-owner-editor-entry"
```

`knowledge` must distinguish:

- `confirmed`: facts directly supported by allowed evidence;
- `inferred`: conclusions with `confidence`, `basis`, and
  `must_not_be_treated_as_confirmed: true`;
- `ui_profile_refs.pages`, `components`, `interaction_rules`, `permissions`, and
  `runtime_refs`: retained Knowledge IDs used as evidence.

Do not promote UI Profile `CODE_CONFIRMED`/`CODE_INFERRED` to business `CONFIRMED`
without an appropriate business source. Do not turn `RUNTIME_REQUIRED` into a confirmed
behavior. Variant rules with `activation: RUNTIME_REQUIRED` remain runtime-dependent.

## 11. Runtime Unknowns

```yaml
runtime_unknowns:
  - id: RU-01
    question: "负责人编辑入口在真实页面中是按钮、图标还是其他可见入口？"
    category: TARGET_RESOLUTION
    blocking: true
    priority: P1
    applies_to:
      steps: [S2]
      capabilities: [CAP-02]
    source:
      type: UI_PROFILE_RUNTIME_REQUIRED
      ref: "runtime-owner-editor-entry"
    ui_runtime_ref: "runtime-owner-editor-entry"
    preferred_resolution: UI_EXPLORATION
    status: OPEN
```

Required fields are `id`, `question`, `category`, `blocking`, `priority`,
`applies_to.steps`, `applies_to.capabilities`, `source`, `ui_runtime_ref`,
`preferred_resolution`, and `status`.

Runtime Unknowns describe implementation or runtime mechanics only. A business result
already stated by the Test Case or PRD—such as showing a password page, hiding product
content before verification, or showing product content after correct verification—must
remain a business Assertion and must not be restated as an unknown. Valid questions ask
about presentation, entry/control semantics, navigation/refresh/async behavior,
DOM/overlay/iframe behavior, or another implementation detail.

If the source already asserts that a page appears, a field is shown, an option is
selected, content is hidden, saving succeeds, or content is displayed after verification,
do not ask Runtime Unknown questions such as “是否出现？/是否选中？/是否保存成功？/
是否隐藏？/是否展示？”. For TC_PD_001, ask “页面设置入口在真实 UI 中以什么控件形式
出现，以及如何识别‘基础设置’当前选中状态？” and “选择‘密码访问’后，密码输入控件以
什么 UI 类型呈现，其可编辑状态和交互方式如何识别？”.

If `source.type` is `UI_PROFILE_RUNTIME_REQUIRED`, both `source.ref` and
`ui_runtime_ref` must be the exact ID of a real `ui-knowledge/runtime-required.yaml`
record whose `reason`, `verification_method`, and `resolves` directly help answer the
current Runtime Unknown. Same-page, same-component, or business relevance alone is not
enough. If the question is inferred only from a Test Case or Prototype and no matching
UI Profile runtime record exists, use `source.type: TEST_CASE` or `PROTOTYPE` and set
`ui_runtime_ref: null`. Never use pseudo IDs such as `product-page-settings-entry` or an
Intent-local ID such as `RU-01` as a UI runtime reference.

Allowed `category` values:

`PAGE_RESOLUTION`, `TARGET_RESOLUTION`, `INTERACTION_BEHAVIOR`, `DATA_BEHAVIOR`,
`PERMISSION_BEHAVIOR`, `LOADING_BEHAVIOR`, `POST_ACTION_BEHAVIOR`, `IFRAME_BEHAVIOR`,
`OVERLAY_BEHAVIOR`, `RESPONSIVE_BEHAVIOR`, `UNKNOWN`.

Allowed `preferred_resolution` values:

`UI_EXPLORATION`, `HUMAN_HINT`, `HUMAN_DEMO`, `REQUIREMENT_CONFIRMATION`,
`TEST_DATA_PREPARATION`.

`status` normally starts as `OPEN`; runtime enrichment may change it to `RESOLVED`.
`blocking: true` means resolution is required before executing the affected Step. It
does not by itself make `ready_for_asset_matching` false.

## 12. Source Types and conflicts

The only allowed Source Types are:

`TEST_CASE`, `PRD`, `PROTOTYPE`, `UI_PROFILE`, `UI_PROFILE_RUNTIME_REQUIRED`, `HUMAN`,
`RUNTIME_OBSERVATION`.

`MODEL_GUESS` is forbidden. Model reasoning is an `inferred` fact with a stated basis.

Conflict handling:

- business expectation/rule: `PRD` has priority over `TEST_CASE`, but a conflict is a
  `validation.blocking_issue`, not an automatic choice;
- page/region semantics: use Prototype plus UI Profile evidence;
- implementation-visible fact: use UI Profile;
- real-page fact: use Runtime Observation;
- Human Confirmed can supplement but cannot silently override a PRD conflict.

Use `validation.conflicts` to preserve both sides and their source references. Never
overwrite a source fact with a guess.

## 13. Automation Constraints

```yaml
automation_constraints:
  locator_policy:
    prefer:
      - verified_semantic_asset
      - data_testid
      - role_and_accessible_name
      - label
      - semantic_relative_locator
    avoid:
      - nth
      - complex_xpath
      - dom_depth_css
      - dynamic_class
  timing_policy:
    avoid:
      - fixed_sleep
    prefer:
      - visible_state
      - enabled_state
      - url_state
      - response_state
      - application_state
  behavior_policy:
    - "不得修改业务预期以让自动化通过"
    - "未确认的交互不得作为确定事实执行"
    - "存在歧义时优先 Runtime Exploration"
    - "低置信度目标不得通过猜测点击"
    - "产品行为与预期不一致时不得自动修改 Assertion"
```

These are constraints for downstream automation planning. `verified_semantic_asset` is
a preference label, not a selected asset and not a reference to a concrete asset.

## 14. Validation and readiness

```yaml
validation:
  ready_for_asset_matching: false
  checks:
    - id: V-01
      name: "核心业务目标明确"
      status: PASS
  blocking_issues: []
  conflicts: []
  warnings: []
  reference_quality:
    exact_refs:
      count: 0
    related_refs:
      count: 0
    unresolved_refs:
      count: 0
    suspected_overmatches:
      count: 0
```

Set `ready_for_asset_matching: true` only when all are true:

1. the core business goal is clear;
2. at least one valid Step exists;
3. every required Step references a Required Capability;
4. all Capability references are complete and point to existing Steps;
5. at least one core business Assertion exists and is traceable;
6. there is no requirements-level blocking ambiguity.

Runtime Unknowns may remain. A blocking Runtime Unknown means “resolve before this
Step executes,” not “do not generate Intent” and not necessarily “do not match assets.”

The validator must also check that every non-null `knowledge_ref` and `ui_runtime_ref`
resolves to a real ID in `ui-knowledge/`. An unresolved or pseudo-reference is a
validation failure. If `ui-knowledge/` is absent, emit `UI_KNOWLEDGE_NOT_AVAILABLE`; do
not fail a fully degraded Intent solely for that absence, provided it contains no
non-null UI references.

Do not silently pass when `pseudo_reference_count > 0`,
`runtime_unknown_business_assertion_conflicts > 0`, `automation_asset_reads > 0`, or
when available `ui-knowledge` clearly matches the business semantics but all related
UI references remain null.

`validation.reference_quality` reports semantic reference quality. Its
`suspected_overmatches.count` must be `0`; an over-broad Page, Region, Component, or
Runtime Required binding is a validation failure even when the referenced ID exists.

`validation.blocking_issues` and `validation.conflicts` are the designated place to
record unresolved requirement/source disagreements. `validation.warnings` records
non-blocking data quality issues such as an English-only `business_terms.zh` region.

`eligibility.excluded_points` contains only test points explicitly excluded from
automation. Do not put Skill responsibilities such as “no Locator generation” or “no
asset matching” there; use `[]` when no source test point is excluded.

## 15. Runtime enrichment extension

After runtime work, the optional `intent.runtime_enrichment` list may contain:

```yaml
runtime_enrichment:
  - runtime_unknown_ref: RU-01
    status: RESOLVED
    observed_semantic_type: BUTTON
    observed_behavior: "点击后打开负责人编辑界面"
    evidence_ref: "runtime-observation-owner-editor-2026-09-18"
```

The extension may record `runtime_unknown_ref`, `status: RESOLVED`, observed semantic
type/behavior, and `evidence_ref`. It must not write CSS/XPath/`nth`/`locator(...)` back
into the Intent.

This extension is allowed only when an independent Runtime Observation was explicitly
provided as input. A PRE_RUNTIME Intent must omit `runtime_enrichment`; when enrichment
is produced, `intent.lifecycle.stage` must be `RUNTIME_ENRICHED` and the evidence must
trace to `RUNTIME_OBSERVATION`. Historical reports or anything reachable through
`automation-assets/` do not qualify.

## 16. Idempotency and preservation

When an existing Intent is updated, match by stable `intent.id` or `case.id`. Preserve
`HUMAN_CONFIRMED`, `RUNTIME_VERIFIED`, and `runtime_enrichment` facts. A new static scan
must not silently overwrite them. Deduplicate identical `source_refs` and Knowledge
facts, preserve stable IDs when semantics are unchanged, and record conflicts instead
of overwriting one source with another.

## 17. Explicit exclusions

The following fields belong to the future Asset Matcher and must not occur in an Intent:

`matched_asset`, `selected_asset`, `reuse_readiness`, `effective_reuse_readiness`,
`dependency_closure`, `reuse-plan`.

The Intent must not read or cite `automation-assets/`, `match-index.yaml`,
`dependency-index.yaml`, historical Playwright registries, or historical run reports
reachable only through those assets. In particular, it must not contain an
`automation-assets/...` evidence reference.

An Intent also must not contain final Locator syntax, Playwright code, or a concrete
automation asset selection.

## 18. Intent Summary

The post-generation report includes the normal case/step/capability/assertion and
readiness counts plus these boundary checks:

```text
ui_knowledge_available: true|false
ui_knowledge_refs_resolved: <count>
ui_knowledge_refs_unresolved: <count>
pseudo_reference_count: 0
runtime_unknown_business_assertion_conflicts: 0
automation_asset_reads: 0
lifecycle_stage: PRE_RUNTIME|RUNTIME_ENRICHED|FINALIZED
reference_quality:
  exact_refs: <count>
  related_refs: <count>
  unresolved_refs: <count>
  suspected_overmatches: 0
```
