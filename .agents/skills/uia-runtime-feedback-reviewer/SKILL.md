---
name: uia-runtime-feedback-reviewer
description: Review a PASSED Playwright case's runtime discoveries and classify what may be proposed for ui-knowledge, existing automation-assets, new asset candidates, or non-persistence. Outputs a review list only; does not write back.
---

# runtime-feedback-reviewer

## Purpose

在一个 Playwright 自动化 Case 已真实 `PASSED` 后，对 Runtime Discovery 和最终实现进行 Post-run Feedback Review，输出可回写候选清单。该 Skill 只做语义判断和 QA SOP，不执行实际回写。

## When to use

仅在以下条件同时满足时使用：

- 最终 Playwright Case 已 `PASSED`；
- 有真实 runtime observation、final spec 或 run result；
- 用户或工作流需要判断哪些内容应进入 `ui-knowledge` / `automation-assets`。

不要在以下情况使用：

- 测试尚未 PASS；
- 只有推测，没有真实 runtime evidence；
- 仅做普通代码 review。

## Inputs

最小输入：

- `automation-intent.yaml`
- `reuse-plan.slim.yaml`（如存在）
- final Playwright spec
- runtime run result / execution evidence
- current `ui-knowledge`
- current `automation-assets`

输入缺失时：不猜；只判断有证据支持的项，并明确标记 `REVIEW` / `INSUFFICIENT_EVIDENCE`。

## Core classification rules

### A. UPDATE_UI_KNOWLEDGE

只有“当前产品 UI 的可复用事实”才归类为此项，例如：

- 页面、region、component；
- 稳定可见语义；
- 导航关系；
- interaction rule；
- permission / UI state；
- runtime 已验证行为；
- iframe、popup、drawer 等结构事实。

结构事实只保留语义，不把本次动态 selector 当作核心知识。

合格示例：

- `当前页面设置 -> 访问权限 -> 密码访问`；
- `前台未解锁时展示密码门禁且产品内容不可见`。

不得进入：Case test data、动态 DOM id、单次 URL 值、账号密码、临时 workaround。

### B. UPDATE_EXISTING_ASSET

当现有 `automation-assets` 已表达相同能力时，优先 `UPDATE`，不新增重复资产。只补充：

- runtime verification evidence；
- 适用条件；
- 已验证行为；
- 必要风险。

若本轮发现旧资产需要适配，仍保留 `ADAPT_BEFORE_REUSE`。单次 PASS 不得自动升级 `DIRECT_REUSE` / `HIGH` stability。

示例：`action-unlock-protected-page`、`assertion-protected-access`。

### C. NEW_ASSET_CANDIDATE

只有同时满足以下条件才提出新资产候选：

- 本轮真实执行通过；
- 能参数化；
- 与当前 Case 数据解耦；
- 明显可能被其他 Case 复用；
- 不是现有 asset 的重复能力；
- 不是临时 workaround。

新资产默认建议：`reuse_readiness: ADAPT_BEFORE_REUSE`，`stability: LOW` 或 `MEDIUM`，并至少记录本轮 runtime evidence。不得直接建议 `DIRECT_REUSE + HIGH`。

### D. DO_NOT_PERSIST

必须归入此项的内容包括：

- 当前 Case test data、当前产品名称、当前测试 URL 值；
- account/password/secret/plaintext credential；
- site instance id、`comId`、`siteSettingId`、record id；
- 动态 DOM id、只在本次页面出现的随机标识；
- `force: true`、`evaluate(click)` 等 workaround 本身；
- 固定 sleep / 固定 timeout 作为解决方案；
- 单次环境路径、调试输出、当前机器绝对路径；
- 未验证推测。

## Stability / evidence rules

始终遵守：

1. Runtime PASS != locator stable。
2. 一次 `PASSED` 只能证明本轮环境下可行，不能证明跨版本稳定。
3. 动态 ID 即使本轮可用，也不得升级成长期 locator。
4. 已有 asset 优先 UPDATE，不新建重复 asset。
5. 有真实 UI 观察证据时，UI Knowledge 可标记 `RUNTIME_VERIFIED`。
6. 新 Asset 第一次通过后通常仍是 `ADAPT_BEFORE_REUSE`。
7. evidence 与现有 knowledge / asset 冲突时，输出 `REVIEW`，不自动覆盖。

## Decision procedure

对每一个本轮新增事实依次判断：

1. 这是产品 UI 本身的稳定事实吗？是则归类 `UPDATE_UI_KNOWLEDGE`。
2. 这是可参数化的自动化执行能力吗？是则检查现有 asset：
   - 已有同能力：`UPDATE_EXISTING_ASSET`；
   - 没有同能力且可复用：`NEW_ASSET_CANDIDATE`。
3. 它是否属于 Case 数据、dynamic id、secret、workaround 或单次环境事实？是则归类 `DO_NOT_PERSIST`。
4. 仍不确定：标记 `REVIEW` / `INSUFFICIENT_EVIDENCE`。

## Output format

第一版只输出 Markdown Review 清单，不定义新的 YAML 输出协议。每行包含：

| discovery | classification | target | action（ADD / UPDATE / IGNORE / REVIEW） | evidence | reason | confidence（HIGH / MEDIUM / LOW） |
|---|---|---|---|---|---|---|

最后输出四个小结：

- UI knowledge updates
- Existing asset updates
- New asset candidates
- Do not persist

再输出 `Review required` 区块，只列冲突或证据不足项。

## Guardrails

- 不直接修改任何文件；
- 不修改 `automation-intent` / `reuse-plan`；
- 不把 runtime observation 反向改写成需求；
- 不根据最终代码推测 UI 事实，必须结合真实 runtime evidence；
- 不因 final spec 中出现某 selector 就默认 selector 稳定；
- 不泄露 secret；
- 不创建重复 asset；
- 不把 workaround 伪装成稳定能力。

## Recommended workflow

```text
Playwright PASSED
   ↓
runtime-feedback-reviewer
   ↓
Review list
   ↓
Human / controlled updater approval
   ↓
ui-knowledge / automation-assets update
```

## Example

以下是基于 TC_PD_001 已知 Runtime Discovery 的最小示例：

| discovery | classification | target | action | evidence | reason | confidence |
|---|---|---|---|---|---|---|
| 页面设置 -> 访问权限 -> 密码访问 | UPDATE_UI_KNOWLEDGE | interaction-rules | UPDATE | runtime observed | 可复用的产品导航与设置事实 | HIGH |
| 输入密码并提交解锁 | UPDATE_EXISTING_ASSET | `action-unlock-protected-page` | UPDATE | PASSED | 已有同能力，补充本轮验证，不重复创建 | HIGH |
| 密码门禁存在 | UPDATE_EXISTING_ASSET | `assertion-protected-access` | UPDATE | PASSED + UI observed | 已有同能力，增强验证证据 | HIGH |
| 动态 id `#rc-tabs-0-tab-...` | DO_NOT_PERSIST | — | IGNORE | 本轮 DOM observed | 动态 locator 不是长期知识 | HIGH |
| 当前产品名 | DO_NOT_PERSIST | — | IGNORE | Case data | 属于本 Case 数据 | HIGH |
| `force: true` workaround | DO_NOT_PERSIST | — | IGNORE | final spec | 临时绕过，不应伪装成稳定能力 | HIGH |
| 解锁后产品详情标题可见 | NEW_ASSET_CANDIDATE | content-visibility assertion | ADD | runtime observed | 可能参数化复用，但需后续适配验证 | MEDIUM |

## Review required

只列出与现有 knowledge / asset 冲突、输入缺失或证据不足的项，并说明需要补充的 evidence；不要自动覆盖或回写。

## Project integration

This is the self-contained project skill `uia-runtime-feedback-reviewer`. Resolve supporting files relative to this folder. The project root is three parents above this folder. Coordinate through the project `uia-orchestrator` and `scripts/uia.py`; do not read or change globally installed skills. Existing YAML filenames and schemas retain their original names. Stage failure returns a concrete gap and affected case IDs to the orchestrator.
