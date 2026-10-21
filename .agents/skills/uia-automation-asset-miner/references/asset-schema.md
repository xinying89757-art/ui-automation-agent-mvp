# Automation Asset Catalog V2.1 schema

本文件定义 `automation-assets/` 的持久化格式。所有路径均相对自动化项目根目录，统一使用 `/`；禁止绝对机器路径、凭证值和真实个人数据。分类文件、索引和迁移文件使用 `schema_version: 2.1`。V2 的 `reuse_readiness` 仍是唯一主复用字段；V1 `reusable`/`reuse_status` 只能放在 `compatibility.legacy`。

## 文件分工

| 文件 | 内容 |
| --- | --- |
| `asset-catalog.yaml` | 分类文件派生索引、扫描范围、统计和 Bootstrap Summary V2.1 |
| `pages.yaml` | `page_object` |
| `components.yaml` | `ui_component`、`locator_strategy` |
| `actions.yaml` | `auth`、`business_action` |
| `flows.yaml` | `business_flow` |
| `fixtures.yaml` | `fixture`、`test_data`、`environment_helper` |
| `assertions.yaml` | `assertion`、`wait_strategy` |
| `runtime-helpers.yaml` | 可选；`runtime_helper` |
| `state-managers.yaml` | 可选；`state_manager` |
| `risks.yaml` | 风险、duplicate、source missing、identity review、extraction gap 和冲突 |
| `match-index.yaml` | 轻量 matcher 索引，不复制完整 evidence |
| `dependency-index.yaml` | 可选；asset_id 到 dependencies/requires 的轻量映射 |
| `migration-map.yaml` | V1/V2 ID 迁移和 aliases |

## 资产字段

分类文件格式为 `schema_version: 2.1` 和 `assets: []`。每项资产必须有以下字段：

| 字段 | 类型及含义 |
| --- | --- |
| `id` | 稳定且全库唯一的 capability-based slug；不要以 BUG/需求编号为主体 |
| `aliases` | 历史 ID 或稳定别名数组，无则 `[]` |
| `type` | `auth`、`page_object`、`ui_component`、`business_action`、`business_flow`、`runtime_helper`、`state_manager`、`fixture`、`test_data`、`assertion`、`locator_strategy`、`wait_strategy`、`environment_helper` |
| `legacy_type` | V1 无法精确映射时记录，如 `component`；能精确分类时为 `null` |
| `name` | 面向人的稳定能力名称，不以历史编号为主 |
| `capability` | 可检索的稳定能力短语；无法确认时为 `unknown` |
| `description` | 由代码和证据直接支持的简短事实描述 |
| `business_terms` | `{zh: [...], en: [...]}`；从名称、代码和 verified usage 归纳，不脑补 |
| `semantic_tags` | 中英文页面、业务、组件、技术语义词数组；没有事实时使用 `status: NONE` 的集合 |
| `match_keys` | Asset Matcher 使用的业务动作、页面语义、组件语义和可证明同义词数组 |
| `capability_group` | 归一化能力组，如 `authentication`、`order_management`；无法确认时为 `unknown` |
| `scope` | `page`、`module`、`system`、`unknown` |
| `reuse_scope` | `GLOBAL`、`MODULE`、`FEATURE`、`CASE` |
| `reuse_readiness` | `DIRECT_REUSE`、`ADAPT_BEFORE_REUSE`、`REFERENCE_ONLY`、`DO_NOT_REUSE` |
| `stability` | `HIGH`、`MEDIUM`、`LOW` |
| `selection_priority` | `HIGH`、`MEDIUM`、`LOW`；由复用和风险规则计算 |
| `source_file` | 相对路径；原始定义位置，不是输出文件 |
| `symbol` | 导出符号、方法名或 `test title@line` 等可定位的内联标识 |
| `source_state` | `present`、`missing` 或 `unscanned` |
| `verification_status` | `VERIFIED`、`PARTIALLY_VERIFIED`、`UNKNOWN`、`FAILED` |
| `verification_confidence` | `high`、`medium`、`low` |
| `quality_flags` | 如 `FRAGILE`、`SECRET_BEARING`、`STALE_PATH`；无则 `[]` |
| `inputs`…`not_applicable_when` | 统一的 `status + items` 集合，见下文 |
| `dependencies` | `{status, completeness, items}`；每 item 为结构化资产依赖 |
| `requires` | `{status, completeness, items}`；每 item 为结构化非资产前置条件 |
| `provenance` | `task_id`、`origin_paths`、`discovered_from` |
| `verified_usage` | 使用和执行证明对象 |
| `evidence` | 非空数组，记录代码或执行证据 |
| `blocking_risks` | 阻断 `DIRECT_REUSE` 的风险 ID 数组 |
| `non_blocking_risks` | 不阻断直接复用的风险 ID 数组 |
| `required_remediation_before_direct_reuse` | 直接复用前必须完成的行动数组 |
| `duplicate_candidates` | 关联的 duplicate 风险 ID 数组 |
| `conflicts` | 冲突对象数组；无则 `[]` |
| `compatibility.legacy` | 可选；旧 `reusable`/`reuse_status` 兼容值，仅供旧消费者读取 |

## 集合字段：UNKNOWN 与 NONE

`inputs`、`outputs`、`preconditions`、`side_effects`、`dependencies`、`requires`、`applicable_when`、`not_applicable_when` 都必须使用：

```yaml
inputs:
  status: KNOWN # KNOWN | NONE | UNKNOWN
  items:
    - "富文本内容"
```

`KNOWN` 表示已抽取事实；`NONE` 表示代码证据明确证明没有该项且 `items: []`；`UNKNOWN` 表示证据不足或尚未完成分析，默认使用 UNKNOWN。不得用裸 `[]`、`null` 或字符串 `unknown` 代替状态。

对 `dependencies` 和 `requires` 增加 `completeness: COMPLETE|PARTIAL`：`UNKNOWN + PARTIAL` 可以包含已知部分，但不得作为完整图或 `DIRECT_REUSE` 的依据。

## 依赖字段

```yaml
dependencies:
  status: KNOWN
  completeness: COMPLETE
  items:
    - asset_id: "runtime-point-resolution"
      required: true
      reason: "assertion helper calls resolvePoint()"
      evidence_refs: ["code:tests/assertions/expectPoint.ts:resolvePoint"]
requires:
  status: KNOWN
  completeness: COMPLETE
  items:
    - kind: "registry"
      name: "verified point registry"
      required: true
      reason: "point keys are resolved from the initialized registry"
      evidence_refs: ["code:tests/runtime/pointRegistry.ts:init"]
```

只允许由 import、call、初始化、fixture 注入、registry lookup 或运行路径建立依赖；语义推断不算证据。依赖项引用不存在的 asset_id 是 schema/graph error。

## `verified_usage`

```yaml
verified_usage:
  level: confirmed_pass # confirmed_pass | reported_pass | code_only | unknown
  test_refs: ["tests/order-list.spec.ts::filters orders"]
  run_refs: ["test-results/report.json::filters orders"]
  note: "报告中的通过用例调用了该资产"
```

`confirmed_pass` 才能支持当前 `VERIFIED`；`reported_pass`、`code_only` 和 `unknown` 仍不能证明当前可复用。

## `evidence`

```yaml
evidence:
  - key: "code:tests/runtime/pointRuntime.ts:resolvePoint"
    kind: "code" # code | test_call | run_report | ci_result | user_report
    ref: "tests/runtime/pointRuntime.ts::resolvePoint"
    detail: "从 registry 解析 point key"
    outcome: null # passed | failed | null
    applicability: "current" # current | historical | unknown
```

`key` 是去重键；重跑同一个报告不得追加重复项。历史报告必须保留并标注 `historical`。

## `risks.yaml`

```yaml
schema_version: 2.1
risks:
  - id: "risk-page-copy-source-duplicate"
    kind: "duplicate_candidate"
    duplicate_class: "SOURCE_DUPLICATE" # ASSET_DUPLICATE | SOURCE_DUPLICATE
    asset_ids: ["page-member-detail", "page-member-detail-copy"]
    evidence: ["code:tests/runner-a/pages/MemberDetail.ts:MemberDetail"]
    impact: "不同 runner 目录存在同一页面对象的来源副本"
    recommendation: "保留 canonical_source_path，评估迁移来源，不自动合并资产"
    state: "open" # open | resolved | needs_review
    blocking: false
    equivalence_scope: "same source implementation copied across runner directories"
    canonical_candidate: null # 只允许 ASSET_DUPLICATE 使用
    canonical_source_path: "tests/pages/MemberDetail.ts"
    related_asset_ids: []
    why_not_auto_merge: "来源重复不等于能力身份重复，且需要人工确认 runner 差异"
    migration_recommendation: "迁移副本引用 canonical_source_path，并保留 provenance"
```

`ASSET_DUPLICATE` 才能设置 `canonical_candidate`；`SOURCE_DUPLICATE` 必须使用 `canonical_source_path`，且不能把不同 type 互相设为 canonical asset。依赖不完整导致的风险使用 `kind: extraction_gap`。

## `match-index.yaml`

```yaml
schema_version: 2.1
entries:
  - asset_id: "runtime-point-resolution"
    type: "runtime_helper"
    aliases: []
    name: "解析测试点位并返回可断言值"
    capability: "resolve registered point values for assertions"
    business_terms:
      zh: ["解析点位", "查询测试点", "断言点位"]
      en: ["point resolution", "registered point"]
    semantic_tags: ["点位", "断言", "registry", "runtime"]
    match_keys: ["解析点位", "point value", "resolvePoint"]
    capability_group: "assertion_runtime"
    scope: "system"
    reuse_scope: "GLOBAL"
    reuse_readiness: "DIRECT_REUSE"
    stability: "HIGH"
    selection_priority: "HIGH"
    source_file: "tests/runtime/pointRuntime.ts"
    has_dependencies: true
    dependency_count: 1
```

推荐 matcher 优先级为 `name/business_terms.zh` > `semantic_tags` > `capability/match_keys` > `aliases`。索引不得复制 `evidence`，且必须与分类资产保持 ID 和复用字段一致。

## `dependency-index.yaml`

```yaml
schema_version: 2.1
entries:
  - asset_id: "assertion-point-value"
    dependencies:
      status: KNOWN
      completeness: COMPLETE
      items:
        - asset_id: "runtime-point-resolution"
          required: true
          reason: "assertion calls point runtime"
    requires:
      status: NONE
      completeness: COMPLETE
      items: []
```

只复制 `asset_id`、`dependencies` 和 `requires`，不得复制 evidence；未知状态必须保留，不得折叠为空数组。

## `migration-map.yaml`

```yaml
schema_version: 2.1
migrations:
  - old_id: "auth-bug1004949-admin-session"
    new_id: "auth-admin-storage-state-session"
    status: "mapped" # mapped | needs_review | blocked
    reason: "能力身份稳定，历史编号移入 provenance"
    aliases_preserved: true
    evidence_refs: ["code:tests/support/adminSession.ts:adminSession"]
```

没有 ID 迁移时写 `migrations: []`；冲突写 `status: needs_review`，不得静默覆盖。

## Compatibility and validation

- V1 `reusable`/`reuse_status` 如需保留，只能位于 `compatibility.legacy`；matcher 和新的复用逻辑不得读取它们。
- `VERIFIED` 必须有当前适用的通过运行证据；`UNKNOWN` 不得 `DIRECT_REUSE`。
- `FRAGILE`、fixed sleep、brittle nth/XPath、stale path 和 secret-bearing fixture 默认不得 `DIRECT_REUSE`。
- `DIRECT_REUSE` 的 `dependencies`、required `requires` 和 required `preconditions` 必须是已知且完整；否则降级并记录 blocking issue。
- 每个 `FRAGILE` 必须有风险 ID；每个风险引用的资产必须存在。
- `match-index` 每项必须包含 V2.1 要求字段；中文 `name` 缺少中文 business terms 时索引不 ready。
- `dependency-index` 的 asset_id 和 dependency asset_id 必须存在；UNKNOWN/PARTIAL 不计入 graph ready。
- YAML 解析、字段枚举、风险引用、索引引用、证据 key 去重、UNKNOWN/NONE 语义和 summary 统计都必须在写入后校验。
