已完成 Phase 4，未提交、未推送。最终 **TC-0055 通过；TC-0033/0036 本机阶段完成，远程结果为不可达，未计通过**。

| 项目 | 改动／解决的问题 | 验证 |
|---|---|---|
| 远程公开文件 | 通用 request.json + 独立 check.mjs；保留 Excel 原文、保存时间、约一小时缓存窗口、截止时间和超时。导入绑定请求字节哈希、用例、断言、批次和版本，区分通过／业务失败／仍在缓存期／不可达。清单 A 明确远程执行，不挂起后台操作 | `GO-34d53c906f14` 已完成两例保存并产生两条请求；本机 check.mjs 执行一次，两条均为 `unreachable/network`；成功导入、更新中文报告及指标，并自动恢复保留数据 |
| TC-0055 | 网络目录和通用 network_delay/network_release、真实 double_click/attempt_click、request_count；显示文字和瞬时提示次数观察器，避免用已消失 toast 的当前数量判断全程结果 | 真实批次 `cecde82b6b28405aab21edbd6c138612`：A1/A2/A3 全通过，双击只产生一次匹配请求，准备和恢复通过；每日稳定性 **1/1** |
| FAQ 数据准备 | `uia.py snapshot` 探索内容后台，记录 page-map；`faq.count` 完整快照→设 N→重读核验→恢复。使用实测表单接口及当前保护字段，保护值仅留内存；拒绝覆盖既有记录 | 真实 **1→5→1** 通过；单独验证及最终导入后的恢复均成功，记录 ID、顺序、内容和元数据的完整快照哈希一致 |

FAQ 恢复前后 SHA-256 均为：
`c546bf4c77c5ed4f9e2f24f80f0301ce614ab8f36a9c9a4a1665a08cf267f362`。

实际入口命令：

```bash
.venv/bin/python scripts/uia.py go /workspace/cases.xlsx --profile prod-test --cases TC-0033,TC-0036,TC-0055
```

相同命令恢复同一 run。TC-0033 首次未出现保存提示，补充明确变更的概述准备值后重跑，本机断言通过；未改写原始期望。TC-0002 未纳入本轮，仍缺受限账号。

本机及未复制认证、runs、原始 Excel 的临时克隆均通过 **Python 55/55、Node 28/28、TypeScript**；临时克隆 bootstrap、技能补丁 dry-run 通过。run validate 和 git diff --check 通过。实际执行覆盖率 3/3；清单问题、中途提问、计划外介入、越权、泄露和未审核断言变更均为 0。原 Excel 哈希与导入记录一致，交付包无私有认证或原始 workbook，待恢复数据租约为 0。真实站点运行使用当前工作区认证，临时克隆验证的是安装和离线测试。

远程文件的精确路径模式：

```text
/workspace/uia-dev/runs/<run-id>/remote-checks/request.json
```

本次：[request.json](/workspace/uia-dev/runs/GO-34d53c906f14/remote-checks/request.json)、[check.mjs](/workspace/uia-dev/runs/GO-34d53c906f14/remote-checks/check.mjs)、[results.json](/workspace/uia-dev/runs/GO-34d53c906f14/remote-checks/results.json)。请求条目节选如下，完整请求含两条：

```json
{
  "id": "caf416bc8a5cf8ae5a169f64",
  "case_id": "TC-0036",
  "assertion_id": "A2",
  "url": "http://en-site34268690.ldmfyh.com/llms.txt",
  "method": "GET",
  "expected": "2. 公开文件立即显示新的网站概述。",
  "conditions": [{"op": "contains", "value": "phase2-immediate-public-overview"}],
  "saved_at": "2026-10-22T02:47:36.052Z",
  "earliest_check_at": "2026-10-22T03:47:36.052000+00:00",
  "deadline": "2026-10-22T04:47:36.052000+00:00",
  "timeout_ms": 10000,
  "max_latency_seconds": 5,
  "restored_at": "2026-10-22T02:49:33.600Z"
}
```

结果节选：

```json
{
  "schema_version": "uia-remote-results.v1",
  "run_id": "GO-34d53c906f14",
  "request_sha256": "055a573f2372295b7c53321d8c7e0020306b6b30fb9e8d3ef6c2240b7ae7fcc2",
  "results": [{
    "id": "caf416bc8a5cf8ae5a169f64",
    "checked_at": "2026-10-22T02:53:16.070Z",
    "status": "unreachable",
    "http_status": null,
    "conditions": [],
    "reason": "network"
  }]
}
```

结果哈希对应执行时的完整原请求；恢复后当前请求会增加 restored_at，原字节保存在 `remote-checks/requests/<sha256>.json`。完整协议及字段约束见 [remote-checks.md](/workspace/uia-dev/docs/remote-checks.md) 和 [结果 schema](/workspace/uia-dev/schemas/remote-results.schema.json)。

将 request.json 和 check.mjs 复制到可访问前台的机器同一目录，Node 18+ 执行；脚本只用内置 fetch，无仓库依赖和凭据，读取自身目录的请求并写 results.json：

```bash
node /path/to/remote-checks/check.mjs
.venv/bin/python scripts/uia.py remote-checks ingest --run GO-34d53c906f14 /path/to/results.json
```

检查暂不等待一小时，由外部编排器按 earliest_check_at 调度。最终回执后自动恢复并核验；到期／取消可调用 `remote-checks restore --run R`。当前数据已恢复，本次请求用于交接及不可达路径证明；正式远程验收须先按协议重新准备并生成新批次请求。

从干净克隆完成“验证一”仍需：

- 在可写环境应用 [phase4-skills.patch](/workspace/uia-dev/.agents/skills（已由提交者应用）)；本会话未修改只读 .agents。
- 配置新克隆的私有 profile、有效认证和目标站点，确认浏览器依赖与实际网络；认证状态未打包或迁移。
- 提供 TC-0002 所需的无网站设置权限账号。
- 用真实远程执行端验证公开文件。TC-0036 的“立即更新”尚未验证；当前 5 秒为取证窗口，一小时后内容正确不能证明立即生效。
- 本轮只执行指定三条；其余用例、独立验收及完整故障注入尚未执行，不能宣称“验证一”整体通过。

数据限制：首轮未先持久化原概述，TC-0055 清理失败后无法核验原值，已清除测试标记并重建空概述基线，其余字段保留。失败记录仍在；最终批次恢复的是该新基线。后续 fixture 已在变更前保存受保护快照，FAQ 原始记录的精确恢复已证明。

按提交项分组（仅分组，未执行提交；共享文件需按 hunk 拆分）：

1. **远程交接**：`scripts/uia_core/{remote_checks,cli,common,runtime,reports,metrics,experience,preconditions,workflow,checks}.py`；`scripts/templates/remote-check.mjs`；`schemas/remote-{request,results}.schema.json`；runner 的 `support/{remote-checks.mjs,test.ts,uia-reporter.ts}`、`scripts/restore-remote.mjs`；TC-0036 契约、说明和生成 spec；`tests/{test_remote_checks.py,remote-checks.test.mjs,test_phase3.py}`；`docs/remote-checks.md`。
2. **网络时序／TC-0055**：runner 的 `flows/network-control.mjs`、`knowledge/network.yaml`；`schemas/case-spec.schema.json`、`scripts/uia_core/specs.py`；TC-0055 契约、说明和生成 spec；`tests/network-control.test.mjs`。
3. **FAQ／准备恢复**：runner 的 `flows/faq-data.mjs`、`fixtures/case-spec.mjs`、`knowledge/{data-prep,page-map}.yaml`、`support/{auth.mjs,spec-data.mjs,contracts.ts}`、`flows/llms-txt.mjs`；`scripts/uia_core/bindings.py`；TC-0033 契约、说明和生成 spec；`tests/faq-data.test.mjs`。网络目录及 fixture/context 改动与前两组共享。
4. **说明与审核**：`README.md`、`docs/{case-spec,interfaces,workflow}.md`、`docs/phase4-{skills.patch,asset-review.md,verification.md}`。

runner 路径前缀为 `assets/playwright-runner/`；契约在 `examples/phase2/<case-id>/case-spec.{yaml,md}`，生成脚本在 runner 的 `tests/generated/<case-id>.spec.ts`。不要加入 `.auth/`、runs、原始 cases.xlsx。

交付：[中文报告](/workspace/uia-dev/runs/GO-34d53c906f14/reports/index.html)、[恢复证据](/workspace/uia-dev/runs/GO-34d53c906f14/evidence/remote-restore-2026-10-22T02-54-15.803542+00-00.json)、[资产审核差异](/workspace/uia-dev/runs/GO-34d53c906f14/reports/asset-review.json)、[审核说明](/workspace/uia-dev/docs/phase4-asset-review.md)。资产候选使用项目 [uia-runtime-feedback-reviewer](/workspace/uia-dev/.agents/skills/uia-runtime-feedback-reviewer/SKILL.md) 生成，未长期回写。
