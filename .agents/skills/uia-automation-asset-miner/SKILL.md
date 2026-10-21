---
name: uia-automation-asset-miner
description: 从已有 UI 自动化测试脚本中提取可追溯、可检索、可增量合并的 Automation Asset Registry V2.1。适用于 Playwright 等现有 UI 测试资产盘点；不分析产品源码建立 UI Profile，也不修改测试代码。
---

# Automation Asset Miner V2.1

## Purpose

把已有 UI 自动化脚本中真实存在的能力整理为可追溯、可检索、可增量合并的 Automation Asset Registry，供后续 Automation Intent、Asset Matcher 和 Skeleton 生成直接检索。V2.1 保留 V2 的 `evidence`、`verified_usage`、`reuse_scope`、`reuse_readiness`、`stability`、`provenance`、`migration-map` 和 `match-index` 体系，并补足中文业务语义、依赖图、UNKNOWN/NONE 语义和 duplicate 分类。

## Scope

输入包括：测试代码、被测试引用的 page object、fixture、helper、测试数据定义、测试报告、CI 结果及已有 `automation-assets/`。默认只读输入，不运行可能改变测试环境的用例。

输出包括 `automation-assets/` 下的资产分类文件、风险文件、轻量 matcher 索引、可选依赖索引和必要的 ID 迁移映射。扫描应覆盖真实源文件与可核验的运行证据，不以猜测补齐业务语义或依赖关系。

## Non-goals

- 不扫描产品页面、组件、路由或权限源码来建立 UI Profile。
- 不修改测试、fixture、配置、页面对象或业务代码。
- 不因为资产存在、被调用过或有一次 passed 记录，就把它标为 `DIRECT_REUSE`。
- 不自动删除、合并或改写 duplicate candidate。
- 不把 secret、token、密码、session 值、连接串或真实个人数据写入输出。

## Strict rules

- MUST 先读取并校验已有 `automation-assets/`，再按稳定 `asset_id` 增量合并；不得覆盖用户现有输出文件以外的工作。
- MUST 只使用代码、调用/导入/初始化/运行路径和运行记录能支持的事实；无法确认的事实必须是 `status: UNKNOWN`，不得脑补。
- MUST 对 `inputs`、`outputs`、`preconditions`、`side_effects`、`dependencies`、`requires`、`applicable_when`、`not_applicable_when` 使用统一的 `status + items` 结构。
- MUST NOT 用空数组代替 unknown。`NONE` 仅在代码证据明确证明没有该项时使用；默认不确定使用 `UNKNOWN`。
- MUST 将 `verification_status`、`verification_confidence`、`reuse_scope`、`reuse_readiness`、`stability` 分开记录。
- MUST 保留 V2 的 `evidence`、`verified_usage` 和历史 run report；同一个 evidence key 不得重复追加。
- MUST 为每个 `FRAGILE` 资产关联风险，并写清 `blocking_risks`、`non_blocking_risks` 及必要的 remediation。
- MUST 为 duplicate candidate 明确区分 `ASSET_DUPLICATE` 与 `SOURCE_DUPLICATE`。只有 `ASSET_DUPLICATE` 才能有 `canonical_candidate`。
- MUST 将 BUG/需求编号放在 `provenance`，不得把它作为长期 capability identity，除非业务能力本身确实只属于该功能。
- MUST 让 `match-index.yaml` 只保留 matcher 所需的轻量字段，不复制完整 evidence；matcher 默认只读取 `reuse_readiness`。
- MUST 为中文业务词提供可追溯的 `business_terms.zh`；只能从 `name`、`capability`、source symbol、verified usage 和已有语义标签归纳，不得脑补不存在的产品能力。
- MUST 为明确存在的资产依赖记录 `dependencies`，为非资产前置条件记录 `requires`；依赖必须有 import、call、initialization 或运行路径证据。
- MUST NOT 仅根据语义猜 dependency；无法确认时保留已证实的边，并把集合状态标为 `UNKNOWN`/`PARTIAL`。
- MUST NOT 因为“有 passed 记录”默认 `DIRECT_REUSE`。
- MUST NOT 因为资产存在就标 `REUSABLE`。
- MUST NOT 把低质量 locator、固定 sleep、过度依赖 `nth`/XPath 的资产直接标 `DIRECT_REUSE`。
- MUST NOT 让旧 `reusable`/`reuse_status` 参与 matcher 或新的复用判断；如需兼容，只能置于 `compatibility.legacy`。
- MUST NOT 将 `SOURCE_DUPLICATE` 当成 `ASSET_DUPLICATE`，也不得让 page object 与 business flow 互相成为 canonical asset。
- MUST NOT 给没有可靠依赖/前置条件边界的资产 `DIRECT_REUSE`。

## Discovery strategy

1. 确认自动化项目根目录、测试框架、扫描范围、现有输出和通过证据根目录。优先扫描有可核验报告的测试，再沿真实引用关系扫描其 page object、fixture、helper、数据和断言。
2. 先读取所有分类文件、`risks.yaml`、`match-index.yaml`、`dependency-index.yaml` 和 `migration-map.yaml`（若存在），解析失败时停止覆盖对应文件并报告问题。
3. 识别定义位置、导出符号、测试调用、import/export、fixture 初始化、runtime 注册、断言调用链、运行报告、CI 结果和当前源版本。只有可定位到源文件与符号或内联位置的发现才入库。
4. 对每个候选资产同时提取业务语义和依赖证据：检查 import、显式 call、构造/初始化、fixture 注入、registry lookup、runtime path 和测试实际调用。语义相似本身不是依赖证据。
5. 检查 `nth`/位置索引、XPath、过度依赖层级的 CSS、固定 `sleep`/`waitForTimeout`、stale path、secret-bearing fixture、隐式环境依赖。语法出现本身不足以断言失败，但实际用于定位或等待时必须记录风险。
6. 生成资产语义、验证状态、复用决策、依赖索引和 matcher 索引；按 [asset-schema.md](references/asset-schema.md) 校验，再稳定排序写入。

## Asset identity rules

- 稳定 `id` 优先表达 capability，例如 `runtime-point-resolution`、`auth-admin-storage-state-session`、`page-order-list`。
- ID 组成应来自稳定 type/capability/scope/符号；不得使用 `BUG1004949`、历史需求号或临时目录名作为主体。
- `name` 是面向人的稳定能力名称，也不得以历史编号为主标题。
- 历史任务、Bug、目录和发现来源写入：`provenance.task_id`、`provenance.origin_paths`、`provenance.discovered_from`。
- 重新扫描可以把 V1 的 `auth-bug1004949-admin-session` 迁移为 `auth-admin-storage-state-session`，但必须保留 `aliases`，并在 `migration-map.yaml` 写 `old_id -> new_id`。
- 合并优先级：稳定 `id`，其次 `source_file + symbol`，再其次 `aliases`；仅凭显示名称相似不得自动合并。

## Business-language indexing

每个主要资产都应包含：

```yaml
business_terms:
  zh: ["会员登录", "受保护页面"]
  en: ["member login", "protected page"]
```

- `business_terms.zh` 可来自资产 `name`、`capability` 的可靠翻译、source symbol、测试标题/步骤、verified usage、已有 `semantic_tags` 和页面语义词。
- `business_terms.en` 可包含代码中出现的英文业务词、技术语义和可证明的英文表达。
- 不得把“页面上可能存在的功能”、产品术语或推测同义词写入 business terms。无法确认的词不写入，而不是写 `unknown`。
- `match-index.yaml` 每项必须包含 `name`、`business_terms`、`semantic_tags`、`match_keys` 和 `capability`。
- 推荐 matcher 优先级固定为：`name/business_terms.zh` > `semantic_tags` > `capability/match_keys` > `aliases`。`aliases` 只作兼容和低优先级召回，不得覆盖复用决策。
- 中文 Automation Intent（例如“会员登录后访问受保护页面”“保存富文本”“修改负责人”）应能通过上述字段召回历史资产；能否直接复用仍由 `reuse_readiness`、风险和依赖完整度决定。

## Semantic extraction rules

每个主要资产都应包含：`capability`、`description`、`business_terms`、`semantic_tags`、`inputs`、`outputs`、`preconditions`、`side_effects`、`dependencies`、`requires`、`applicable_when`、`not_applicable_when`、`match_keys`、`capability_group`、`scope`、`stability`、`selection_priority`。

- `capability` 是从符号、调用方式、测试标题和安全注释中抽取的稳定能力短语；没有依据则为 `unknown`。
- `description` 只描述代码或证据直接支持的行为；不要推断产品规则。
- `semantic_tags`、`match_keys` 可包含代码中出现的中英文业务词、页面词、组件词及可证明同义词；没有证据时保持空数组即可，因为它们不是事实集合的 UNKNOWN/NONE 字段。
- `scope` 只能是 `page`、`module`、`system`、`unknown`，表示能力作用范围；它不同于 `reuse_scope`。
- `selection_priority` 只能按明确规则生成：`HIGH` 仅限 `DIRECT_REUSE` 且无 blocking risk；`MEDIUM` 限 `ADAPT_BEFORE_REUSE` 或有非阻断风险；`LOW` 用于 `REFERENCE_ONLY`、`DO_NOT_REUSE` 或证据冲突。

## Unknown vs None semantics

所有事实集合统一为：

```yaml
inputs:
  status: KNOWN # KNOWN | NONE | UNKNOWN
  items:
    - "富文本内容"
```

规则：

- `KNOWN`：已抽取到至少一个有证据的 item；对依赖集合还应有 `completeness: COMPLETE` 或 `PARTIAL`。
- `NONE`：代码/调用/初始化/运行路径明确证明没有该项，`items: []`。
- `UNKNOWN`：尚未分析完整或证据不足，`items` 可以保留已证实的部分，但不得宣称完整。
- 默认值是 `UNKNOWN`，不是 `NONE`。
- `dependencies` 的 item 必须是 `{asset_id, required, reason, evidence_refs}`；`requires` 的 item 必须是 `{kind, name, required, reason, evidence_refs}`。它们不能只写字符串。
- `applicable_when` 和 `not_applicable_when` 也采用同一结构；如果只知道部分适用条件，应是 `UNKNOWN`，而不是空数组。

## Dependency extraction

依赖分为两类：

```yaml
dependencies:
  status: KNOWN
  completeness: COMPLETE
  items:
    - asset_id: "runtime-point-resolution"
      required: true
      reason: "assertion helper calls resolvePoint() before querying the registry"
      evidence_refs: ["code:tests/assertions/expectPoint.ts:resolvePoint"]
requires:
  status: KNOWN
  completeness: COMPLETE
  items:
    - kind: "registry"
      name: "verified point registry"
      required: true
      reason: "runtime resolves point keys from the initialized registry"
      evidence_refs: ["code:tests/runtime/pointRegistry.ts:init"]
```

- `dependencies` 只记录另一个已入库资产；`requires` 记录 registry、authenticated context、test environment、specific page state 等非资产前置条件。
- 证据来源必须是 import、call、构造/初始化、fixture 注入、registry lookup 或可追踪运行路径。仅凭名称相似、同一目录或业务语义不得建立边。
- 如果存在部分已知边但无法证明完整，使用 `status: UNKNOWN`、`completeness: PARTIAL` 并保留已知 items；这会阻断 `DIRECT_REUSE` 并计入 unknown 统计。
- 如果代码明确不需要依赖或前置条件，使用 `status: NONE`；不要把“没有找到”当作 NONE。
- 可选输出 `dependency-index.yaml`，只包含 `asset_id -> dependencies/requires`，不得复制 evidence；用于 Asset Matcher 依赖展开。
- assertion 调用 point runtime 时应建立到 `runtime-point-resolution` 的资产边；runtime helper 调用 registry fixture 时应记录资产依赖或 `requires`，取决于 fixture 是否已作为资产入库。

## Verification rules

允许的状态：`VERIFIED`、`PARTIALLY_VERIFIED`、`UNKNOWN`、`FAILED`。

- `VERIFIED`：当前源实现与测试调用都能关联到当前适用的通过 run report/CI 证据。
- `PARTIALLY_VERIFIED`：有部分当前实现的通过证据，但覆盖不足、版本关联不完整或只验证了部分路径。
- `UNKNOWN`：只有代码、reported pass、历史 completed 档案或无法关联当前实现的证据。
- `FAILED`：当前实现有可核验失败证据，或已确认不能按当前契约工作。

`verification_confidence` 为 `high`、`medium`、`low`，只表示验证证据的可信度，不替代状态。历史档案 `completed` 但没有当前独立 run evidence 必须是 `UNKNOWN`/`low`，不能因为历史成功就升级。

## Reuse decision matrix

`reuse_readiness` 是 matcher 的唯一主复用判断字段，允许 `DIRECT_REUSE`、`ADAPT_BEFORE_REUSE`、`REFERENCE_ONLY`、`DO_NOT_REUSE`。旧 `reusable`/`reuse_status` 只能放在 `compatibility.legacy`，新逻辑禁止读取。

| 条件 | 默认决策 |
| --- | --- |
| `FAILED` | `DO_NOT_REUSE` |
| `UNKNOWN`，包括仅有历史 completed | `REFERENCE_ONLY` |
| `PARTIALLY_VERIFIED` | 最多 `ADAPT_BEFORE_REUSE` |
| `VERIFIED` 但有 `FRAGILE`、fixed sleep、brittle nth/XPath、stale path 或 secret-bearing fixture | `ADAPT_BEFORE_REUSE` |
| `dependencies` 或 required `requires` 为 `UNKNOWN`/`PARTIAL` | 不得 `DIRECT_REUSE`；通常为 `ADAPT_BEFORE_REUSE` 或 `REFERENCE_ONLY` |
| required `preconditions` 为 `UNKNOWN` | 不得 `DIRECT_REUSE`；必须产生 blocking issue 或降级 |
| 仅出现在一个 case/bug，且绑定测试数据或页面结构 | `FEATURE`/`CASE` + `ADAPT_BEFORE_REUSE` 或 `REFERENCE_ONLY` |
| `VERIFIED`、当前 run evidence、语义字段充分、`stability: HIGH`、无 blocking risk、依赖和 required 前置条件边界已知、具备可替换输入 | 可为 `DIRECT_REUSE` |

`FRAGILE` 只有在有明确、可核验的 override 证据（如当前代码中的稳定替代定位、独立修复提交和之后的通过 run）时才可解除直接复用限制；override 必须记录 `reuse_override` 的证据引用和理由，不得静默覆盖规则。

`reuse_scope` 允许 `GLOBAL`、`MODULE`、`FEATURE`、`CASE`。`GLOBAL` 要求跨模块或跨场景有证据；单一 case/bug 默认不能是 `GLOBAL`。

## Duplicate classification

风险和资产引用中必须使用以下分类：

- `ASSET_DUPLICATE`：相同 `type` 且 capability/业务语义等价，可能是真资产重复。可以提出 `canonical_candidate`，但不能自动合并。
- `SOURCE_DUPLICATE`：不同目录、历史 copy、runner 副本或生成副本导致来源重复，能力身份未必重复。只能记录 `canonical_source_path`、来源范围和 migration recommendation。
- `SOURCE_DUPLICATE` 不得把 page object、business_flow、fixture 等不同资产类型互相设为 canonical asset；不同 type 的关系应记录 `related_asset_ids` 或 migration recommendation。
- duplicate 风险必须包含 `equivalence_scope`、`canonical_candidate`（仅 ASSET_DUPLICATE）、`canonical_source_path`（SOURCE_DUPLICATE）、`why_not_auto_merge` 和 `migration_recommendation`。

## Type classification

至少支持以下类型，并按最具体的能力分类：

`auth`、`page_object`、`ui_component`、`business_action`、`business_flow`、`runtime_helper`、`state_manager`、`fixture`、`test_data`、`assertion`、`locator_strategy`、`wait_strategy`、`environment_helper`。

映射原则：BackendStateManager → `state_manager`；point-runtime 或通用运行时封装 → `runtime_helper`；页面类 → `page_object`；业务语义操作 → `business_action`；可编排跨步骤流程 → `business_flow`；定位/等待策略独立记录。无法从 V1 精确映射时保留 `legacy_type`，不要把所有旧 `component` 继续归入同一类。

## Output contract

在项目根目录保持 `automation-assets/`，至少生成并持续维护：

- `asset-catalog.yaml`：分类文件的轻量总索引、统计、扫描范围和 Bootstrap Summary V2.1。
- `pages.yaml`、`components.yaml`、`actions.yaml`、`flows.yaml`、`fixtures.yaml`、`assertions.yaml`：分类资产事实来源；无发现时保留 `assets: []`。
- `risks.yaml`：风险、`ASSET_DUPLICATE`/`SOURCE_DUPLICATE`、source missing、identity review 和冲突。
- `match-index.yaml`：供 Asset Matcher 直接消费的轻量索引，每项至少 `asset_id`、`type`、`name`、`capability`、`business_terms`、`semantic_tags`、`match_keys`、`capability_group`、`scope`、`reuse_scope`、`reuse_readiness`、`stability`、`selection_priority`、`source_file`，并提供 `has_dependencies` 或 `dependency_count`。
- `dependency-index.yaml`：可选；每项只包含 `asset_id`、`dependencies`、`requires`，不复制 evidence。
- `migration-map.yaml`：旧 ID 到新 ID 的迁移、aliases、冲突和迁移状态；没有迁移时仍可写空数组。

发现 `runtime_helper` 或 `state_manager` 时可分别生成 `runtime-helpers.yaml`、`state-managers.yaml`，避免把它们塞进宽泛的 `components.yaml`；没有发现时无需新增分类文件。

`risks.yaml` 除风险基础字段外，资产决策必须能落到 `blocking_risks`、`non_blocking_risks`、`required_remediation_before_direct_reuse`。duplicate risk 必须有 `duplicate_class`，并按分类规则填写字段；禁止只输出 primary。

## Match readiness validation

每个 `match-index` entry 必须指向真实资产，并包含完整 V2.1 字段。资产 `name` 为中文时，`name` 或 `business_terms.zh` 缺失视为索引不完整。中文业务词缺失、`capability` 为 `unknown`、或必要 matcher 字段缺失，计入 `match_index_ready` 之外。

## Dependency graph readiness validation

`dependency_graph_ready` 只统计依赖边和 required `requires` 已知且完整、引用资产存在、没有 unresolved asset id 的资产。`UNKNOWN`/`PARTIAL` 依赖不能算 ready，也不能支持 `DIRECT_REUSE`。依赖索引必须与分类资产同步且稳定排序。

## Idempotent merge and conflict handling

1. 按 `id`、`source_file + symbol`、`aliases` 合并；保留已有 ID、人工备注、历史 evidence、历史 verified_usage 和 migration 信息。
2. V2.1 新字段按稳定 `asset_id` 合并。evidence 按稳定 `key` 去重；同一 run report 不重复追加。当前源变化但没有新的通过证据时，将当前状态降为 `UNKNOWN`，旧证据标记 `historical`，不得删除。
3. 未覆盖不等于删除。确认源位置消失时写 `source_state: missing` 和风险；保留记录及旧 evidence。
4. 新旧规则冲突不得静默覆盖：在资产的 `conflicts` 或风险的 `identity_review` 中写明字段、旧值、新值、证据引用和待处理动作。
5. 若 V1/V2 ID 重命名，写 `migration-map.yaml`，保留 `aliases`，并在 summary 统计 `migration_count`。相同输入且无新事实时输出应保持稳定。
6. 写入后必须检查 YAML 可解析、schema_version、ID 唯一、`match-index` 指向真实资产、dependency-index 引用有效、风险引用有效、每个 `FRAGILE` 有风险、`DIRECT_REUSE` 满足决策矩阵、UNKNOWN/NONE 没有混淆、必要字段完整。

## Match and dependency extraction gaps

如果 `assertion`、`runtime_helper` 或 `page_object` 的代码存在明确 import/call/initialization/runtime path，但输出的 `dependencies` 仍为 `UNKNOWN`，必须新增 `extraction_gap` 风险或 summary issue，引用相关代码证据；不能静默认为无依赖。required `preconditions` 同理。

## Bootstrap Summary V2.1

最终摘要必须包含扫描范围、证据来源、资产目录位置，并至少统计：

- `total_assets`
- `DIRECT_REUSE`、`ADAPT_BEFORE_REUSE`、`REFERENCE_ONLY`、`DO_NOT_REUSE`
- `reuse_scope` 的 `GLOBAL`/`MODULE`/`FEATURE`/`CASE` 分布
- `VERIFIED`/`PARTIALLY_VERIFIED`/`UNKNOWN`/`FAILED` 分布及 `verification_confidence`
- `HIGH`/`MEDIUM`/`LOW` stability 分布
- `fragile_count`、duplicate candidates、migration count
- `assets_with_known_dependencies`
- `assets_with_unknown_dependencies`
- `assets_with_business_terms_zh`
- `assets_missing_business_terms_zh`
- `assets_with_unknown_inputs`
- `assets_with_unknown_outputs`
- `assets_with_unknown_preconditions`
- `ASSET_DUPLICATE` count
- `SOURCE_DUPLICATE` count
- `match_index_ready` count
- `dependency_graph_ready` count
- `top_reusable_capabilities`：只列 `DIRECT_REUSE`，附 capability、asset_id、证据和 selection priority
- `top_remediation_priorities`：按阻断直接复用的风险、影响资产数和明确 remediation 排序
- 新增、更新、未改动、source missing、冲突、extraction gap 数量

明确区分“资产已被整理/验证”和“资产已在当前环境重新跑通”。

示例和字段定义见 [asset-schema.md](references/asset-schema.md)、[asset-catalog.example.yaml](templates/asset-catalog.example.yaml)、[pages.example.yaml](templates/pages.example.yaml)、[asset-examples-v2.yaml](templates/asset-examples-v2.yaml)、[match-index.example.yaml](templates/match-index.example.yaml)、[dependency-index.example.yaml](templates/dependency-index.example.yaml) 和 [risks.example.yaml](templates/risks.example.yaml)。

## Project integration

This is the self-contained project skill `uia-automation-asset-miner`. Resolve supporting files relative to this folder. The project root is three parents above this folder. Coordinate through the project `uia-orchestrator` and `scripts/uia.py`; do not read or change globally installed skills. Existing YAML filenames and schemas retain their original names. Stage failure returns a concrete gap and affected case IDs to the orchestrator.
