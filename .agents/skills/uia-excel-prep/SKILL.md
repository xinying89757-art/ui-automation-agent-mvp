---
name: uia-excel-prep
description: 为本项目导入和分组 Excel UI 用例，保留来源、负向数据和预期，调用意图技能生成逐条 Intent，返回集中业务缺口。
---

# Prepare Excel cases

Input: the selected run/case IDs and their `cases/<id>/source.json` files from
`uia-orchestrator`. Read [interfaces](../../../docs/interfaces.md) for column mapping.

1. The project CLI imports XLSX/XLSM with openpyxl. Do not overwrite the workbook or
   execute cell formulas. Do not send the workbook to an external service.
2. Resolve queued header ambiguity once through `answer --file`, then re-import.
   A mapping includes sheet, header row, and field-to-column names. Ignore a sheet
   only when it is a documented supplemental sheet or the user confirms it.
3. Read each selected source case. Preserve deliberately blank/invalid negative data.
   Missing essential expectations, contradictory steps, or unclear business semantics
   become focused `product` questions scoped to the affected cases. Do not invent a result.
4. Group cases by actual shared operation flow, not module/title alone. Use `bind`
   for semantic flow IDs, fixture dependencies and evidence-backed isolation.
5. Use [uia-automation-intent](../uia-automation-intent/SKILL.md) to write each case's
   original `automation-intent.yaml` v1.0. Retain its manifest case ID, original ID,
   source sheet/row/cell references and each expected outcome. Do not match assets here.
6. Call `advance --case <id> --stage matching`. Its deterministic gate checks the Intent
   and UI references. Fix structural defects locally; queue true business ambiguity.

Output: validated case Intents, flow/fixture bindings, and scoped unresolved questions.
Return counts/paths to the orchestrator, which calls `next` automatically. No browser
exploration, final selectors, or Playwright generation belongs to this stage.
