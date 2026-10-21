---
name: uia-asset-matcher
description: 将本项目的自动化 Intent 与 UI 知识及历史资产匹配，核实来源和依赖，输出兼容的精简复用计划。
---

# Match capabilities to assets

Input: validated Intent and the project's two YAML knowledge bases. Read
[interfaces](../../../docs/interfaces.md) for plan and proof fields.

1. Run `match --case <id>` to seed candidates from the lightweight match index.
   Scores are retrieval hints, not semantic matches or proof of executability.
2. Inspect each required capability, source steps and assertions. Read candidate details,
   dependency-index, actual source files, symbol/export/signature and prerequisites.
   Configured `source_roots` may resolve historical sources; a catalog's old `present`
   or PASS flag never proves availability in this project.
3. Edit the original `reuse-plan.slim.yaml` v1.0. Confirm one decision for every capability:
   `DIRECT_REUSE`, `ADAPT_BEFORE_REUSE`, `DISCOVERY_REQUIRED`, or `MISSING`.
   Set `selection_confirmed: true` only after actual semantic review.
4. Direct reuse needs current export/signature evidence, a source fingerprint, compatible
   target replay, complete prerequisites/dependencies and no unresolved blocking risks.
   Record the verification fields described in the interfaces. Missing sources/unknown
   bounds remain candidates for adaptation or exploration, never fictional imports.
5. Existing non-exported historical helpers can inform a new local parameterized
   implementation after runtime verification. Record the relationship and required adaptation.
   Never change a business assertion to fit an asset.
6. Set the plan status to `READY_WITH_DISCOVERY` or `READY`, then call
   `advance --case <id> --stage discovery` and return gaps/paths to the orchestrator.

Output: capability-level plan, relevant composite flow references, evidence-backed
reuse decisions, and required runtime discovery. Do not declare the final case PASS.
