# Phase 3 验证记录

已实现 TC-0048 流程修正及 Phase 3 交互，真实验证 8 条样本：4 条通过并恢复数据、3 条等待前置、1 条待探索。未提交、未推送，未修改原始 Excel，也未将它打包。

唯一安装限制：`.agents/` 为只读挂载，写入技能被沙箱拒绝；技能更新已保存为 [phase3-skills.patch](/workspace/uia-dev/docs/phase3-skills.patch)，在干净克隆中 dry-run 通过，尚未写入实际 SKILL.md。可写环境执行 `patch -p1 < docs/phase3-skills.patch` 后由你提交。

## 逐项改动及验证

| 项目 | 改了什么、解决什么 | 如何验证 |
|---|---|---|
| A：TC-0048 | 根因是 case-spec 将禁用态写成点击，且 lint 缺少语义门禁；既有 disabled/enabled 检查和模板已经支持。改为 assert + disabled/enabled，保留所有原始错误文案、弹窗及负向空值 | 真实站点 A1/A2/A3 全通过；空字符串、纯空格被拦截，有效内容恢复可用；清理通过 |
| A：过程门禁 | blocked / cannot save / 无法保存 / 置灰等期望必须有 disabled 检查；禁止点击预期禁用的目标，允许初次提交后观察保存中状态；无关坏契约不再阻断独立用例生成 | 禁用态、错误点击、独立生成回归测试；TC-0055 示例同步使用 disabled |
| B1：go | 串联导入、既有脚本索引、真实自检、契约任务、清单及可执行批次；相同输入恢复原 run。样本仅在完整业务指纹相同时复用；陌生用例返回 Codex 任务，清单先保持草稿 | 真实 8 条范围导入；单测验证既有脚本优先、幂等恢复及新用例任务；一行提测模板已加入仓库 |
| B2：一次中文清单 | A 环境、B 契约聚合的修改范围、C 歧义及选项；一句中文解析，原子保存环境记忆，否定答案也复用；按环境/站点/身份/网络隔离 | 5 项清单、1 次成功答复；答复后 go 提问数 0；TC-0002 只挂起自身；中文 TC-ID 解析及多歧义编号选项有单测 |
| B3：运行中不提问 | 新权限或环境缺口进入延期审核，挂起关联用例；B 同意不能扩大已锁定配置权限 | 中途提问 0、越权 0；延期问题、独立用例继续和权限不扩张单测通过 |
| B4：异步审核 | 缺陷附复现/原始期望/实际/证据/受限脱敏截图；断言提案默认不应用；预算耗尽的 demo 请求附 codegen 命令。未探索的工程缺口不会直接要求人工录制 | 缺陷投影、拒绝断言修改和脱敏截图测试；真实审核单 2 项：公开前台环境、TC-0055 自动化缺口；4 条通过用例生成资产审核候选，未长期回写 |
| B5：中文报告 | Markdown、HTML、Excel 以结论/需要你处理/流程指标开头；可见状态中文；JSON 保留兼容代码并补中文标签 | 实际生成报告及下方原文 |
| B6：介入指标 | 中文答复自动记事件；session-turn 按用户消息 ID 去重；四类计划内交互与计划外分开，AI CLI 调用不算人工介入。修正 JSON 元组/列表转换造成的断言变更误报 | 会话轮次 1、清单回答 1、计划外介入 0；计数及签名序列化回归测试 |

会话轮次需要 Codex/调用端每条用户消息记录一次 `session-turn`；终端无法自行获知未记录的聊天消息。本次只记录本条提测指令，清单由代理依用户指定默认答案代答。

验证：`.venv/bin/python -m unittest discover -s tests` **44/44**，`node --test tests/*.test.mjs` **19/19**；TypeScript、run validate、`git diff --check` 通过。变更文本/运行记录/脚本包扫描：凭据命中 0、令牌条目 0、私有认证文件 0；原始 workbook 哈希未变。

## 实际命令和清单

```bash
.venv/bin/python scripts/uia.py go /workspace/cases.xlsx --profile prod-test --cases TC-0004,TC-0016,TC-0048,TC-0019,TC-0033,TC-0002,TC-0036,TC-0055
```

首次生成清单正文（省略重复的“待回答”状态）：

只需一句中文回答；缺少条件的用例挂起，其余照跑。

### A 需要的站点、账号、编辑器和迁移条件

- 无网站设置权限的账号（TC-0002）：可用 / 缺少，相关用例挂起。
- 可读取公开站点文件（TC-0033、TC-0036）：可用 / 缺少，相关用例挂起。
- 保存操作可保持处理中数秒的环境（TC-0055）：可用 / 缺少，相关用例挂起。

### B 临时修改并还原的数据范围

配置的测试站可自由编辑、保存和发布；实际可行时恢复快照。清单答案不扩大配置授权。

- llms.txt（TC-0016、TC-0019、TC-0033、TC-0036、TC-0048、TC-0055）：同意临时修改并还原 / 不同意，相关用例挂起。
- faq（TC-0033）：同意临时修改并还原 / 不同意，相关用例挂起。

### C 业务歧义及选项

无。

成功答复的一句话：

> A 除 TC-0002、TC-0033、TC-0036 缺少外其余可用，B 同意，C 无歧义

```bash
.venv/bin/python scripts/uia.py answer --run GO-2c3a86a95842 'A 除 TC-0002、TC-0033、TC-0036 缺少外其余可用，B 同意，C 无歧义'
```

答复后再次运行同一 go：**question_count=0，pending_review_count=0**；环境记忆生效，成功答复总数仍为 1。开发过程中的解析错误及跨例 lint 阻断均已修正，没有把失败答复计作已确认答案；历史实际批次仍保留。

最终真实批次 `832f2379120641ba81213f902aa79237`：TC-0004、TC-0016、TC-0019、TC-0048 全部通过，准备和清理均经验证，每日稳定性为同版本 1 次。TC-0002 缺权限账号，TC-0033/0036 缺公开前台，TC-0055 尚未完成时序模拟及目标探索。没有通过改写期望追求全绿。

## 报告开头三块（原文）

### 结论

本次共 8 条：3 条等待前置，4 条通过，1 条未执行。

### 需要你处理

TC-0002：前置未满足：无网站设置权限的账号
TC-0033：前置未满足：可读取公开站点文件
TC-0036：前置未满足：可读取公开站点文件
异步审核单 2 项；断言建议默认不应用。

### 流程指标

清单问题 5，清单回答 1，中途提问 0，计划外人工介入 0，会话轮次 1；脚本实际执行覆盖率 80.0%；越权 0，泄露 0，未审核断言变更 0。

## metrics.json（原文）

```json
{
  "spec_lint_first_pass": {
    "passed": 8,
    "automatable": 8,
    "rate": 1.0
  },
  "unplanned_interventions": 0,
  "session_turns": 1,
  "checklist_answers": 1,
  "checklist_questions": 5,
  "mid_run_questions": 0,
  "import_to_first_result_seconds": 159.008708,
  "import_to_final_report_seconds": 1092.562316,
  "script_coverage": {
    "scripted": 4,
    "executed": 4,
    "eligible": 5,
    "ratio": 0.8
  },
  "new_scripts_generated": 0,
  "new_script_paths": [],
  "re_explored_known_pages": 0,
  "scope_violations": 0,
  "leak_hits": 0,
  "unreviewed_assertion_changes": 0,
  "measured_at": "2026-10-21T16:46:46.017701+00:00"
}
```

80% 的分母为当前具备前置条件的 5 条用例；全部 8 条的实际执行覆盖率为 **50%**。这不是“验证一整体达标”的结论。

## 干净克隆检查及剩余条件

已实际本地 clone 到临时目录，覆盖本次拟提交工作区文件，不复制 `.auth/`、runs 或原始 Excel。bootstrap、44 条 Python 单测、19 条 Node 单测、TypeScript 和技能补丁 dry-run 均通过；测试中的认证配置均为临时假数据。修复了浏览器安装命令依赖 npm exec 工作目录、初始化断言基线读错路径、空脚本目录报错、生成脚本误绑旧 fixture、未保存初始化无法恢复等低成本问题。

真正从干净克隆启动计划“验证一”仍需：

- **技能安装**：本会话无法修改只读 `.agents/`，须在可写环境应用补丁后提交。
- **有效本地认证**：通过 setup/login 配置新克隆的 `.auth/`；复制旧目录时绝对路径可能失效，应重新配置引用，不能自动迁移历史账号。验证码、权限及会话有效性仍须真实验证。
- **TC-0002**：当前没有无网站设置权限的账号，继续挂起。
- **TC-0033/0036**：HTTP 前台不可达；HTTPS 后台可达不代表公开文件可读，不能替换原始公开文件断言。
- **TC-0033**：FAQ 可恢复准备器仍未实现，内容后台目标及五条输出校验还需探索；恢复快照和验证恢复不能省略。
- **TC-0055**：需实现浏览器内延迟保存、请求计数和处理中控件检查。属于自动化工程缺口，不要求新增特殊账号。
- **新机器依赖**：Python/venv、Node 22+、包下载网络、Chromium 系统库须具备；当前机器 bootstrap 已通过，不代表任意操作系统均已验证。

本次未启动计划指定的独立 gpt-6-luna/high 验证会话，也未在真实站点完成“改坏定位/改错期望”的完整故障注入轮次；已有门禁单测，不能替代该轮验收。

## 按提交项分组的文件

1. **A：禁用态过程修复**：`scripts/uia_core/specs.py`、`tests/test_specs.py`、`assets/playwright-runner/tests/generated/TC-0048.spec.ts`、`examples/phase2/TC-0048/case-spec.{yaml,md}`、`examples/phase2/TC-0055/case-spec.yaml`、`docs/case-spec.md`。技能补丁的 case-spec hunk 属于此组。
2. **B1–B3：入口/清单/记忆/调度**：`scripts/uia_core/experience.py`、`cli.py`、`preconditions.py`、`workflow.py`（后 3 个同目录）、`examples/phase2/index.json`、`tests/test_phase3.py`、`README.md`、`docs/interfaces.md`、`docs/test-request-template.md`。技能补丁的 orchestrator hunk 属于此组。
3. **B4–B5：审核/截图/报告**：`scripts/uia_core/{reports,runtime,secrets}.py`；`assets/playwright-runner/support/{fixtures.ts,test.ts,review-screenshot.mjs,redact.mjs,uia-reporter.ts}`；`tests/review-screenshot.test.mjs`。`cli.py` 的 heal-review hunk 与第 2 组共享。
4. **B6：指标**：`scripts/uia_core/metrics.py`，以及 `cli.py`/`experience.py`/`tests/test_phase3.py` 中的会话与签名测试 hunk，与第 2 组共享。
5. **克隆与验证记录**：`scripts/bootstrap.sh`、`docs/phase3-skills.patch`、`docs/phase3-verification.md`。

未解决的临时生成占位脚本已移除；契约及运行历史保留。不要加入 `.auth/`、runs、原始 cases.xlsx。以上组存在代码依赖，适合按顺序或按 hunk 拆分。

本地证据：[清单](/workspace/uia-dev/runs/GO-2c3a86a95842/checklist.md)、[零提问回执](/workspace/uia-dev/runs/GO-2c3a86a95842/evidence/phase3-go-memory.json)、[HTML 报告](/workspace/uia-dev/runs/GO-2c3a86a95842/reports/index.html)、[审核单](/workspace/uia-dev/runs/GO-2c3a86a95842/review.md)、[资产审核差异](/workspace/uia-dev/runs/GO-2c3a86a95842/reports/asset-review.json)、[独立脚本包](/workspace/uia-dev/runs/GO-2c3a86a95842/reports/scripts.zip)。

> 更新：技能补丁已由提交者应用到 `.agents/skills/`，补丁文件已移除。
