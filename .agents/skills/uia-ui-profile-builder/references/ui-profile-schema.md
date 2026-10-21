# UI Knowledge Profile V1.1 Schema

本 Schema 定义 `ui-knowledge/` 的稳定、可追溯、可检索输出。保留 `schema_version: 1` 以兼容 V1；V1.1 输出可增加 `profile_version: "1.1"`。路径均相对前端项目根目录，统一使用 `/`。示例只说明字段，不代表目标项目事实。

## Common fields and knowledge levels

Page、Component、Rule、Permission、Runtime record 通常包含：

| 字段 | 说明 |
| --- | --- |
| `id` | 稳定 slug；推荐 `page-*`、`component-*`、`rule-*`、`permission-*`、`runtime-*` |
| `name` | 人可读名称 |
| `knowledge_level` | `CODE_CONFIRMED`、`CODE_INFERRED`、`RUNTIME_REQUIRED`、`HUMAN_CONFIRMED` |
| `confidence` | `high`、`medium`、`low`；`CODE_INFERRED` 必填 |
| `scope` | `system`、`cross-cutting`、`variant`、`page`、`component`，按文件语义取值 |
| `source_state` | `present`、`missing`、`unscanned` |
| `evidence` | 非空证据数组 |
| `conflicts` | 冲突项数组；未解决冲突使用 `state: needs_review` |

`CODE_INFERRED` 必须有 `reason` 和 `confidence`。`HUMAN_CONFIRMED` 必须有 `confirmed_by`，有日期时记录 `confirmed_at`。`RUNTIME_REQUIRED` 必须有 `reason`、`verification_method`、`acceptance_signal`、`priority` 和 `status`。

## Evidence

```yaml
evidence:
  - key: "code:src/router/routes.ts:orders-route"
    kind: code # code | package | import | reference | human_confirmation | runtime_observation
    source_file: src/router/routes.ts
    symbol: orders-route
    lines: "18-31"
    detail: "路由注册并指向 OrderListPage"
```

`key` 是幂等去重键；`source_file`、`symbol`、`lines` 应能定位事实。业务词、动作和 automation relevance 同样需要 evidence。不得写入大段源码、完整响应、secret 或真实敏感数据。

## system-profile.yaml

```yaml
schema_version: 1
profile_version: "1.1"
profile_id: ui-profile-v1
source_root: .
scope:
  included: [package.json, src/router, src/pages, src/components]
  excluded: [node_modules, dist, build, coverage]
  priority_applied: [P0, P1]
stack:
  framework:
    name: React
    version_range: "^18"
    knowledge_level: CODE_CONFIRMED
    confidence: high
    evidence: []
  ui_library: []
  router: []
  state_management: []
  form_library: []
conventions:
  test_id_attributes: []
  route_naming: []
  permission_naming: []
infrastructure:
  layouts: []
  providers: []
  notification: []
  loading: []
  portal: []
  iframe: []
conflicts: []
```

## pages.yaml

原有 `route`、`page_component`、`layout`、`regions`、`relationships`、`knowledge_level`、`evidence` 字段保留；V1.1 增加业务语义：

```yaml
schema_version: 1
profile_version: "1.1"
pages:
  - id: page-article
    name: Article management
    route: /article
    route_name: article
    page_component: src/pages/article/ArticlePage.tsx
    layout: src/layouts/AppLayout.tsx
    business_terms:
      zh: [文章, 文章管理, 文章列表, 新增文章, 编辑文章]
      en: [article, article management, article list]
    entry_points:
      status: KNOWN # KNOWN | UNKNOWN
      items: [文章]
    actions:
      status: KNOWN # KNOWN | UNKNOWN
      items: [新增, 编辑, 保存, 预览, 保存并新增]
    automation_relevance: HIGH # HIGH | MEDIUM | LOW | NONE
    regions:
      - id: article-management
        name: Article list, category, editor
        business_terms:
          zh: [文章列表, 文章分类, 文章编辑器]
          en: [article list, category, editor]
        component_ids: [component-tiptap-editor, component-upload-file]
    relationships:
      create: page-article-create
      detail: page-article-detail
      edit: page-article-edit
    knowledge_level: CODE_CONFIRMED
    scope: page
    source_state: present
    evidence: []
```

业务词、entry point 和 action 只能有 JSP 可见文案、菜单名、按钮文本、label、title、action 名、字段、注释或页面名称证据。仅凭文件名/方法名不可标为 `CODE_CONFIRMED`；无法确认时保留 `status: UNKNOWN` 与空 items。

## components.yaml

`role` 是 V1.1 必填字段：

- `UI_SURFACE`：用户可直接看到、操作或定位的 UI，如 Table、Popup、Editor、Upload、Message Center、Form。
- `UI_BEHAVIOR`：稳定交互行为，如 AJAX list refresh、pagination behavior、popup controller。
- `LAYOUT`：页面公共结构，如 Header、Module Navigation。
- `INFRASTRUCTURE`：内部源码基础设施，如 Shared JSP imports、taglib baseline、bootstrap wiring。

`UI_SURFACE`、`UI_BEHAVIOR`、`LAYOUT` 应有 `business_terms.zh/en` 和 `automation_relevance`；`INFRASTRUCTURE` 可省略业务词，且不得进入默认 UI Target。

```yaml
schema_version: 1
profile_version: "1.1"
components:
  - id: component-message-center
    name: Header message center
    component_file: src/layout/HeaderMessageCenter.jsp
    kind: MessageCenter
    role: UI_SURFACE
    public: true
    automation_relevance: HIGH
    business_terms:
      zh: [消息中心, 通知, 未读消息, 系统消息]
      en: [message center, notification, unread message]
    reused_by_pages: [page-article, page-dashboard]
    props: []
    events: [onOpen]
    interaction_clues:
      pagination: false
      row_actions: false
      searchable: false
      async_options: true
      multi_select: false
      portal: unknown
    knowledge_level: CODE_CONFIRMED
    confidence: high
    scope: component
    source_state: present
    evidence: []
  - id: component-shared-jsp-import
    name: Shared JSP tag/import baseline
    component_file: src/common/base.jsp
    kind: Other
    role: INFRASTRUCTURE
    automation_relevance: NONE
    knowledge_level: CODE_CONFIRMED
    scope: component
    source_state: present
    evidence: []
```

## interaction-rules.yaml

允许的 `scope` 是 `system`、`cross-cutting`、`variant`、`page`、`component`。V1.1 增加 `business_terms`、`interaction`、`activation`：

```yaml
schema_version: 1
profile_version: "1.1"
rules:
  - id: rule-popup-overlay-and-close
    name: Popup overlay close behavior
    scope: variant
    variant:
      id: new-navigation
      source: src/header/header_navigate_new.jsp
    activation:
      status: RUNTIME_REQUIRED # CONFIRMED | RUNTIME_REQUIRED | UNKNOWN
      runtime_ref: [runtime-legacy-new-header-selection]
    category: modal
    applies_to: [component-popup-layer]
    business_terms:
      zh: [弹窗, 关闭弹窗, 确认, 取消]
      en: [popup, close, confirm, cancel]
    interaction:
      trigger: 点击关闭/确认/取消
      result: 弹窗关闭或执行回调
    behavior: overlay remains until close callback completes
    knowledge_level: CODE_CONFIRMED
    confidence: high
    evidence: []
    conflicts: []
```

未解决的 legacy/new 或 plan/site/context variant conflict 不得生成无条件 `scope: system`。真正跨版本成立的规则可使用 `scope: system` 与 `activation.status: CONFIRMED`。

## permissions.yaml

保留 `effects.hidden`、`effects.disabled`、`effects.click_rejected`；新增 `runtime_refs`，可增加 `direct_access.status`：

```yaml
schema_version: 1
profile_version: "1.1"
permissions:
  - id: permission-func-prod
    name: Product function permission
    scope: page
    applies_to: [page-prod, component-module-navigation]
    permission_key: func.prod
    effects:
      hidden: true
      disabled: unknown
      click_rejected: unknown
    direct_access:
      status: UNKNOWN # KNOWN | UNKNOWN
    runtime_refs: [runtime-permission-role-matrix]
    enforcement_points:
      - source_file: src/navigation/ModuleNavigation.tsx
        symbol: ProductMenuItem
    knowledge_level: CODE_CONFIRMED
    evidence: []
    conflicts: []
```

菜单隐藏不得推断 direct URL 一定被拒绝。

## runtime-required.yaml

`resolves` 声明 Runtime Observation 完成后需要补全的现有知识字段；每个 `knowledge_id` 必须能解析：

```yaml
schema_version: 1
profile_version: "1.1"
runtime_required:
  - id: runtime-popup-mount-and-obscuration
    name: Confirm popup mount and pointer interaction
    scope: component
    applies_to: [component-popup-layer]
    reason: portal 挂载和遮挡取决于真实浏览器环境
    verification_method: browser inspection with representative data and viewports
    acceptance_signal: popup is visible, unobscured, and receives pointer input
    priority: P0
    resolves:
      - knowledge_id: component-popup-layer
        knowledge_type: component
        fields: [runtime_mount, overlay_behavior, pointer_interaction, viewport_behavior]
    knowledge_level: RUNTIME_REQUIRED
    confidence: medium
    source_state: present
    evidence: []
    status: open # open | verified | partially_verified | blocked | obsolete
    runtime_observation:
      observed_at: null
      environment: null
      result: null
      observations: []
      evidence: []
      verified_fields: []
```

Builder 暂时不要求生成 `runtime_observation`，但后续回填不得覆盖原 CODE evidence。

## evidence-index.yaml

```yaml
schema_version: 1
profile_version: "1.1"
scope:
  source_root: .
  included: []
  excluded: []
  scan_priorities: [P0, P1, P2]
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
entries: []
conflicts: []
validation_issues: []
```

`entries` 是轻量索引，至少包含 `id`、`kind`、`file`、`knowledge_level`、`evidence_keys`；不要把完整 evidence 复制进索引。

## ui-match-index.yaml

该文件供 Automation Intent、UI Explorer 和未来 matcher 直接消费，只存检索字段和引用 ID，不复制完整 evidence：

```yaml
schema_version: 1
profile_version: "1.1"
matcher_priority:
  - business_terms.zh
  - name
  - actions
  - regions.business_terms.zh
  - business_terms.en
  - aliases
entries:
  - knowledge_id: page-article
    type: page
    name: 文章管理
    business_terms:
      zh: [文章, 文章管理, 新增文章, 编辑文章]
      en: [article, article management]
    route: /article
    actions: [新增, 编辑, 保存, 预览]
    regions: [文章列表, 文章分类, 文章编辑器]
    component_ids: [component-tiptap-editor, component-upload-file]
    permission_refs: [permission-similarity-test]
    runtime_refs: [runtime-tiptap-iframe-same-origin]
    knowledge_level: CODE_INFERRED
    confidence: high
  - knowledge_id: component-popup-layer
    type: component
    role: UI_SURFACE
    name: Popup/overlay layer
    business_terms:
      zh: [弹窗, 确认弹窗, 提示框]
    interaction_rule_refs: [rule-popup-overlay-and-close]
    runtime_refs: [runtime-popup-mount-and-obscuration]
    knowledge_level: CODE_CONFIRMED
```

## Merge and reference invariants

1. 先按稳定 ID，再按 `kind + source_file + symbol` 匹配；已有 evidence、人工确认和 Runtime Observation 保留。
2. evidence 按 `key` 去重；未扫描不删除，源位置确认消失才标记 `missing`。
3. 源码与 Runtime Observation 冲突写 `state: needs_review`，不得自动覆盖观察。
4. 必须解析 `page.component_ids`、`rule.applies_to`、`permission.applies_to`、`permission.runtime_refs`、`runtime.applies_to`、`runtime.resolves.knowledge_id` 及 match index 的全部引用。
5. 解析失败时写入 `validation_issue.type: BROKEN_REFERENCE`，不得静默忽略。
6. 输出不得包含 secret/token/password/cookie 原文或真实敏感数据。
