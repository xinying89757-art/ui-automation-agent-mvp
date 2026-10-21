---
name: uia-ui-profile-builder
description: 从前端产品项目源码建立可追溯、可检索的 ui-knowledge/ UI Knowledge Profile V1.1，供 Automation Intent 和 UI Explorer 消费；不分析自动化测试资产、不生成 Playwright 测试、不修改产品源码。
---

# UI Profile Builder V1.1

## Purpose

从前端产品源码建立可追溯、可搜索、明确区分已知与未知的 `ui-knowledge/`。V1.1 在保留 V1 源码结构分析能力的基础上，增加页面和组件的业务检索语义、组件角色、规则激活边界、Runtime 回填链路和轻量 `ui-match-index.yaml`，使后续 Automation Intent 与 UI Explorer 可以直接消费。

## Scope and non-goals

输入只能以产品前端源码及其配置为主：`package.json`、router/routes、pages/views、components/common/shared/ui、layout/layouts，以及 P1 的 hooks/composables、stores/redux/pinia、auth/permissions、services/api、constants 和 P2 的 theme/styles/types/utils。优先扫描公共基础设施和被多个页面引用的组件，再补充业务页面。

不得：

- 以 Playwright、Cypress 或其他自动化测试代码作为主要知识来源；不要用测试脚本反推 UI Profile。
- 生成测试用例、Playwright 脚本或最终 locator。
- 修改产品源码、依赖、路由、权限实现，或用户已有的 `ui-knowledge/` 文件以外的产品文件。
- 写入 secret、token、password、cookie、连接串、真实个人数据或完整 API payload。
- 根据目录名、CSS 类名、文件名或方法名脑补业务能力。

## Stable V1 capabilities to preserve

不要删除或重命名以下既有能力：`CODE_CONFIRMED`、`CODE_INFERRED`、`RUNTIME_REQUIRED`、`HUMAN_CONFIRMED`；`evidence/source_file/symbol/lines`；`pages.yaml`、`components.yaml`、`interaction-rules.yaml`、`permissions.yaml`、`runtime-required.yaml`、`evidence-index.yaml`；P0/P1/P2 扫描优先级；Runtime 的 `verification_method`、`acceptance_signal`、`priority`；以及显式 `conflicts` 机制。

## Input discovery and scan phases

### Phase 0 — Scope and safety

确认前端项目根目录；记录 `scope`、实际扫描目录、排除目录、优先级和输入版本线索。默认排除 `node_modules`、构建产物、缓存、生成文件和 `.git`。读取已有 `ui-knowledge/` 并先校验 YAML；解析失败时不要覆盖对应文件。搜索敏感字段时只记录变量名、键名、相对路径和用途。

### Phase 1 — Foundation inventory (P0/P1)

识别框架、UI library、router、state management、form library、layout、provider、theme、i18n、toast/notification、loading、权限守卫、route metadata 和 test-id 属性约定。只有源码明确出现时才登记。

### Phase 2 — Page Map and business semantics

建立页面、route、page component、layout、主要区域、子页面、list/create/detail/edit 关系。除保留原有字段外，页面可以增加：

```yaml
business_terms:
  zh: []
  en: []
entry_points:
  status: KNOWN # KNOWN | UNKNOWN
  items: []
actions:
  status: KNOWN # KNOWN | UNKNOWN
  items: []
automation_relevance: HIGH # HIGH | MEDIUM | LOW | NONE
```

`business_terms`、`entry_points.items` 和 `actions.items` 只能从 JSP 可见文案、菜单名、按钮文本、label、title、action 名、表单字段、已有代码注释和页面名称抽取，并且必须保留对应 evidence。不能只因 `article_testSimilarity` 这类方法名就确认“相似度检测”是用户动作。源码无法确认时使用 `status: UNKNOWN` 与 `items: []`，不要用空数组伪装成“已确认没有”。

### Phase 3 — Component inventory and role

识别 Table、Modal、Select、Dropdown、Tree、Upload、Pagination、DatePicker、EmployeeSelector、CustomerSelector、Cascader、RichTextEditor 等组件及其 props/events、数据加载、表单绑定、portal/iframe 线索和引用页面。每个组件增加 `role`：

- `UI_SURFACE`：用户可直接看到、操作或定位的表面，如 Table、Popup、Editor、Upload、Message Center、Form。
- `UI_BEHAVIOR`：定义稳定交互但不一定是独立视觉组件，如 AJAX list refresh、pagination behavior、popup controller。
- `LAYOUT`：页面公共结构，如 Header、Module Navigation。
- `INFRASTRUCTURE`：源码基础设施，如 Shared JSP imports、taglib baseline、公共资源 import、内部 bootstrap wiring。

`INFRASTRUCTURE` 不得成为 Automation Intent 或 UI Explorer 的默认 UI Target。所有 `UI_SURFACE`、`UI_BEHAVIOR`、`LAYOUT` 组件增加 `business_terms.zh/en`；`INFRASTRUCTURE` 可省略。Page 和 UI Component 增加 `automation_relevance`，只用于筛选，不能替代 evidence 或 knowledge level。

### Phase 4 — Interaction, permission, and variant rules

提取 Navigation、row actions、form validation、Modal save/close、Select searchable/async/multi、Toast/Notification、Loading、Permission hidden/disabled/click_rejected、iframe、portal 等规则。规则增加可选 `business_terms` 和 `interaction.trigger/result`，只有代码能确认时才生成。

规则 `scope` 允许 `system`、`cross-cutting`、`variant`、`page`、`component`。若存在 legacy/new、多 plan/site/context 或未确认的 runtime activation condition，不得把实现特定行为无条件提升为 `system`。variant-specific 规则必须记录 `variant.id/source` 与：

```yaml
activation:
  status: RUNTIME_REQUIRED # CONFIRMED | RUNTIME_REQUIRED | UNKNOWN
  runtime_ref: []
```

只有确实跨版本成立的规则才可使用 `scope: system` 和 `activation.status: CONFIRMED`。未解决的 variant conflict 必须保留 `conflicts`，不可静默覆盖。
只有确实跨版本成立的规则才可使用 `scope: system` 和 `activation.status: CONFIRMED`。未解决的 variant conflict 必须保留 `conflicts`，不可静默覆盖。

### Phase 5 — Runtime gap analysis and resolution links

无法仅凭源码确认的实际可见位置、hover 可操作性、portal 挂载、元素遮挡、真实 loading 时长、动态数据差异、响应式布局、iframe 可访问性、异步选项结果、权限账号表现等写入 `runtime-required.yaml`。Runtime 项保留 `reason`、`verification_method`、`acceptance_signal`、`priority`、`status`，并尽量增加：

```yaml
resolves:
  - knowledge_id: component-popup-layer
    knowledge_type: component
    fields: [runtime_mount, overlay_behavior, pointer_interaction]
```

`resolves` 必须指向真实存在的 Page、Component、Rule 或 Permission ID。V1.1 Builder 不要求生成 `runtime_observation`，但 schema 必须允许未来写入 `observed_at`、`environment`、`result`、`observations`、`evidence`、`verified_fields`；未来回填不得覆盖原 CODE evidence。Runtime `status` 允许 `open`、`verified`、`partially_verified`、`blocked`、`obsolete`。

### Phase 6 — Build match index, merge, validate, summarize

生成轻量 `ui-match-index.yaml`，只复制检索字段和引用 ID，不复制完整 evidence。校验所有知识引用，再按稳定排序合并并输出 `UI Profile Bootstrap Summary V1.1`。

## Knowledge classification and evidence

知识等级保持 V1：

- `CODE_CONFIRMED`：源码直接表达且 evidence 足够。
- `CODE_INFERRED`：由多个代码线索推导；必须有 `reason` 与 `confidence: high | medium | low`。
- `RUNTIME_REQUIRED`：静态源码无法可靠确认，必须进入 `runtime-required.yaml`。
- `HUMAN_CONFIRMED`：用户或产品人员确认的事实；记录 `confirmed_by`、`confirmed_at`（若有）。

每条 Page、Component、Rule、Permission、Runtime item 必须有非空 evidence，可定位到相对 `source_file`、`symbol` 或等价位置及可选 `lines`。业务词、业务动作和 `automation_relevance` 不能没有 evidence。冲突保留双方 evidence，不得把推断伪装为确认事实。

## Output contract

在产品前端项目根目录创建或增量更新 `ui-knowledge/`，保持以下结构，不增加不必要的分类文件：

```text
ui-knowledge/
├── system-profile.yaml
├── pages.yaml
├── components.yaml
├── interaction-rules.yaml
├── permissions.yaml
├── runtime-required.yaml
├── evidence-index.yaml
└── ui-match-index.yaml
```

保留 `schema_version: 1` 以兼容 V1；新输出可增加 `profile_version: "1.1"`。分类文件是事实来源，`evidence-index.yaml` 和 `ui-match-index.yaml` 是派生索引。

## Idempotent merge strategy

1. Page、Component、Rule、Permission、Runtime 使用稳定 `page-*`、`component-*`、`rule-*`、`permission-*`、`runtime-*` ID；先按 ID，再按 `kind + source_file + symbol` 匹配。
2. 已有 evidence 按 `key` 去重；保留人工确认、历史 evidence 和未来 Runtime Observation。
3. 本轮未扫描到不等于删除，标记 `source_state: unscanned`；只有相同范围确认源位置消失才标记 `missing`。
4. 源码与 Runtime Observation 冲突时写 `conflict.state: needs_review`，不得用源码结果静默覆盖真实观察。
5. 规则 variant conflict 不得被提升为无条件 system rule；权限菜单隐藏不得推断 direct URL 一定拒绝。
6. `ui-match-index.yaml` 按 stable ID 更新，不能复制完整 evidence；无新事实时保持稳定 diff。

## Reference integrity validation

运行结束前必须验证以下引用能解析到真实 Knowledge ID：

- `page.component_ids`
- `rule.applies_to`
- `permission.applies_to`
- `permission.runtime_refs`
- `runtime.applies_to`
- `runtime.resolves.knowledge_id`
- `ui-match-index` 的所有 `knowledge_id`、`component_ids`、`permission_refs`、`interaction_rule_refs`、`runtime_refs`

无法解析时必须写出 `validation_issue: { type: BROKEN_REFERENCE, ... }`，不得静默忽略。

## Bootstrap Summary V1.1

最终摘要除原统计外，至少包含：

```yaml
counts:
  pages: 0
  components: 0
  components_by_role: {UI_SURFACE: 0, UI_BEHAVIOR: 0, LAYOUT: 0, INFRASTRUCTURE: 0}
  interaction_rules: 0
  permissions: 0
  runtime_required: 0
  runtime_by_priority: {P0: 0, P1: 0, P2: 0}
  knowledge_levels: {CODE_CONFIRMED: 0, CODE_INFERRED: 0, RUNTIME_REQUIRED: 0, HUMAN_CONFIRMED: 0}
  pages_with_business_terms: 0
  pages_missing_business_terms: 0
  ui_components_with_business_terms: 0
  ui_components_missing_business_terms: 0
  runtime_with_resolves: 0
  runtime_missing_resolves: 0
  unresolved_conflicts: 0
  broken_references: 0
  ui_match_index_ready: false
```

摘要还要说明扫描范围、主要风险、未确认假设、Top runtime verification 项和是否修改了已有知识（本 Skill 不修改用户生成的 `ui-knowledge/` 文件，除非用户明确要求扫描更新）。

## Strict MUST / MUST NOT

MUST：

- MUST 保留 V1 的四级知识、evidence、P0/P1/P2、conflict 和七个原有输出文件。
- MUST 让业务语义来自真实可见文案、菜单、按钮、label、title、action、字段、注释或页面名称，并保留 evidence。
- MUST 给 UI Component 标注 role；`INFRASTRUCTURE` 不进入默认 UI Target 搜索。
- MUST 为 UI Surface/Behavior/Layout 和 Page 提供可检索业务语义或明确标记缺失。
- MUST 为 Runtime 尽量声明 `resolves`，并校验其目标 ID。
- MUST 为 variant-specific rule 标注 activation boundary；未解决 variant 冲突不得成为无条件 system rule。
- MUST 完整校验所有引用并显式输出 `BROKEN_REFERENCE`。
- MUST 输出 V1.1 counts 和 `ui_match_index_ready`。

MUST NOT：

- MUST NOT 根据目录名、文件名、方法名或 CSS 猜业务能力。
- MUST NOT 根据 CSS 推断真实元素可见或可点击。
- MUST NOT 把菜单隐藏推断为 direct URL 一定被拒绝。
- MUST NOT 把 legacy/new 两套实现混成一个确定 system behavior。
- MUST NOT 让 `INFRASTRUCTURE` 组件进入默认 Automation Intent UI Target 搜索。
- MUST NOT 把 `RUNTIME_REQUIRED` 写成 `CODE_CONFIRMED`，或以新源码扫描静默覆盖 Runtime Observation。
- MUST NOT 修改产品源码、自动化脚本或用户已有 `ui-knowledge/` 文件。

## Validation checklist

- 所有八个目标文件存在、YAML 可解析、`schema_version` 一致。
- ID 稳定且唯一；所有 `applies_to`、`component_ids`、`permission_refs`、`runtime_refs`、`resolves` 和索引引用可解析。
- `CODE_INFERRED` 有 `reason/confidence`；`RUNTIME_REQUIRED` 有验证字段；Runtime 状态属于允许集合。
- Page/Component 业务词有 evidence；`UNKNOWN` 不被误写成“确认无”。
- Component role 合法；`INFRASTRUCTURE` 没有被列为默认 UI Target。
- system/cross-cutting/variant 规则有合理 activation；未解决 variant conflict 未被提升。
- `ui-match-index.yaml` 不包含完整 evidence，且统计与事实文件一致。
- 输出不包含 secret/token/password/cookie 等敏感原文。

## Example invocation

```text
使用 ui-profile-builder 扫描当前前端项目，建立或更新 ui-knowledge V1.1。
保留 V1 的证据与知识等级；新增页面/组件业务语义、组件 role、automation_relevance、ui-match-index、Runtime resolves 和 variant activation。
只分析产品源码，不把自动化测试作为主要来源，不生成 Playwright 测试，不修改产品源码，也不要覆盖已有 Runtime Observation。
完成后输出 UI Profile Bootstrap Summary V1.1，并列出 Top 10 runtime verification 与所有 BROKEN_REFERENCE。
```

字段细节与示例见 [ui-profile-schema.md](references/ui-profile-schema.md)；模板见 `templates/` 下的 V1.1 示例文件。

## Project integration

This is the self-contained project skill `uia-ui-profile-builder`. Resolve supporting files relative to this folder. The project root is three parents above this folder. Coordinate through the project `uia-orchestrator` and `scripts/uia.py`; do not read or change globally installed skills. Existing YAML filenames and schemas retain their original names. Stage failure returns a concrete gap and affected case IDs to the orchestrator.
