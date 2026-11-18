# Phase 2 与 spike follow-ups 验证记录

分支 `cursor/llms-txt-mvp-b575`。未执行 commit 或 push；未修改/复制/跟踪原始 cases.xlsx。
验证于 2026-10-22（北京时间），续用已存在的 `PHASE1-CHECK-20261021`，重新导入
`/workspace/cases.xlsx` 得到 63 条来源不变的用例，随后 bind-specs 与真实预检。
这是 8 条样本的实现验证，没有把完整 63 条工作簿声明为完成。

## 逐项结果

| 项目 | 改动及解决的问题 | 验证 |
|---|---|---|
| case-spec | 独立 v1 契约、12 动词、命名目标、动态环境词表、数据目录、变更范围、逐条原文期望 | 8 条真实 Excel 样本；紧凑副本每例 19–41 行 |
| lint | 结构/数据类型、逐字期望、跨用例相同 checks、独立目标、未知目标/业务歧义聚合 | 首轮 8/8=100%；19 条断言全部逐字引用；跨例重复 0 |
| gen/render | 确定性单例 TS、显式抛错 TODO、Markdown；从 @step/businessAssertion 自动推导覆盖 | 4 条全已知目标生成成功；3 条真实回放；单测验证 TODO 不可运行和移动行号后重推导 |
| seed fixture | 登录态外部准备；生成/AI spec 导入 support/fixtures，page 自动进入编辑器；交付包包含绑定投影 | TC-0004/0016 最终批次通过，fixture 准备/清理验证通过；包内含 cases.json |
| snapshot | iframe/任意容器、已知入口、hover/click；仅可见节点、去图标、脱敏及重复名计数 | 真实弹窗与规则浮层；本地浏览器测试 iframe、容器、display/opacity/aria 隐藏及重复链接 |
| locator/write-back lint | 弹窗内部 scope、图标字符、已知重复角色名、关闭断言；禁止知识及回写 snapshot refs | Python 门禁测试通过；真实通过用例生成集中审核 diff，未应用长期写回 |
| 默认流程与权限 | 新运行默认 case-spec，历史 intent/reuse-plan 可读；测试站可修改/保存/发布，恢复用于复跑 | 新/旧运行门禁与迁移测试；技能补丁 dry-run 通过（目录只读，尚未安装） |
| 安全与非交互 | 所有仓库 Codex 示例有 timeout 和 stdin 关闭；假 JWT 运行时拼接；忽略 cases.xlsx | 变更文件、运行产物及脚本包扫描未发现凭据/JWT；测试文件无字面 token 形状 |

## 真实生成脚本

| 用例 | 结果 | 业务断言 | 最后回放耗时 | 说明 |
|---|---|---|---|---|
| TC-0004 | PASS / stable（每日 1 次） | A1/A2/A3 全通过 | 11.781 秒 | 入口、标题、默认页签、取消/保存和左右布局 |
| TC-0016 | PASS / stable（每日 1 次） | A1/A2 全通过 | 2.154 秒 | 浮层、标题、首行及九项模块说明的数量/顺序 |
| TC-0048 | automation_failure | 尚未进入 | 23.274 秒 | 空内容时保存按钮 aria-disabled=true，正常点击等待超时；未强制派发事件或放松期望 |
| TC-0019 | 已生成，未执行 | 未执行 | — | 本次真实回放范围为三条脚本 |
| TC-0033 / TC-0036 | 等待公开前台/探索 | 未执行 | — | 保留公开文件断言，未替换成编辑器值；FAQ 准备器尚待实现 |
| TC-0002 / TC-0055 | 等待特殊环境/探索 | 未执行 | — | 缺权限账号 / 延迟保存环境已进入集中清单 |

最终通过批次：`0d738b99f5fe43e39143703dcacdd5f0`（TC-0004、TC-0016）。
TC-0048 失败批次：`ee2e7cf7c7d4440b91d555d9ddafff5a`，清理验证通过。
共享编辑器复用仅是批次内性能优化，没有算成第二次稳定性通过。

早期一次预检回放因编辑器等待超时及执行期间共享代码发生修改保留为中断记录。
首次三条生成脚本回放中，TC-0016/0048 的来源选项不可见，记录为数据准备失败；
补充等待异步表单配置就绪后复跑，未修改业务断言。所有尝试和中断留存在 run.json 与批次报告。
真实后台 HTTPS 可达；HTTP 公开前台不可达，与预期一致。没有追求所有用例通过。

## 自动检查与证据

- `.venv/bin/python -m unittest discover -s tests`：32/32。
- `node --test tests/*.test.mjs`：18/18。
- `npm --prefix assets/playwright-runner run typecheck`：通过。
- `uia.py spec lint`、`uia.py validate --run PHASE1-CHECK-20261021`：通过。
- `git diff --check`：通过。
- 变更文件凭据/令牌扫描、run leak_scan、脚本 ZIP JWT 扫描：0 命中；ZIP 私有认证条目：0。

本地证据（runs 被 Git 忽略，进度仍以 run.json 为唯一来源）：

- [原始首轮 lint](../runs/PHASE1-CHECK-20261021/evidence/phase2-first-lint.json)
- [逐条运行结果](../runs/PHASE1-CHECK-20261021/reports/results.json)
- [结果页面](../runs/PHASE1-CHECK-20261021/reports/index.html)
- [集中审核 diff](../runs/PHASE1-CHECK-20261021/reports/asset-review.json)
- [独立脚本包](../runs/PHASE1-CHECK-20261021/reports/scripts.zip)
- [8 条可审阅样本](../examples/phase2/README.md)

## 可拆分提交的文件组

以下组有代码依赖，建议按顺序提交；无需把本地 runs/ 或原始 Excel 加入版本控制。

1. **case-spec 契约、CLI、状态衔接与报告**
   - `schemas/case-spec.schema.json`、`preconditions.yaml`
   - `scripts/uia_core/specs.py`、`bindings.py`、`checks.py`、`cli.py`
   - `scripts/uia_core/preconditions.py`、`workflow.py`、`runtime.py`、`metrics.py`、`reports.py`
   - `assets/playwright-runner/knowledge/page-map.yaml`、`data-prep.yaml`
   - `tests/test_specs.py`、`tests/test_profiles.py`
2. **编辑器 fixture 与生成脚本运行支持**
   - `assets/playwright-runner/support/fixtures.ts`、`case-spec.ts`、`spec-data.mjs`
   - `assets/playwright-runner/support/test.ts`、`contracts.ts`、`uia-reporter.ts`
   - `assets/playwright-runner/fixtures/case-spec.mjs`
   - `assets/playwright-runner/flows/llms-txt.mjs`（编辑器等待预算）
   - `assets/playwright-runner/tests/generated/TC-{0004,0016,0019,0048}.spec.ts`
3. **限定快照与定位规则验证**
   - `assets/playwright-runner/support/auth.mjs`、`scripts/session.mjs`
   - `scripts/uia_core/profiles.py`（快照参数与权限说明）
   - `tests/snapshot.test.mjs`
   - 相关 CLI 参数和定位 lint 与第 1 组共用文件，可按 hunk 拆分。
4. **安全规则及假 JWT 清理**
   - `AGENTS.md`、`.gitignore`
   - `tests/test_secrets.py`、`tests/redact.test.mjs`、`tests/environment-auth.test.mjs`
5. **技能、默认流程说明与真实样本**
   - `skills/uia-case-spec/SKILL.md`、`docs/phase2-skills.patch`
   - `README.md`、`docs/case-spec.md`、`docs/workflow.md`、`docs/interfaces.md`
   - `docs/environments-and-login.md`、`docs/phase2-verification.md`
   - `examples/phase2/README.md` 和八个用例目录中的 `case-spec.yaml`、`case-spec.md`

## 只读技能目录限制

本会话的文件系统将 `.agents/` 设为只读，新增目录和修改现有技能均返回只读文件系统错误。
因此没有声称 `.agents/skills/uia-case-spec/SKILL.md` 已安装，也没有绕过挂载限制。
正文和更新已准备为 [技能补丁](phase2-skills.patch)，包含新 uia-case-spec、orchestrator 和 runtime 默认流程调整。
已在临时目录对现有文件执行 `patch --dry-run -p1` 验证。后续可在可写环境从仓库根目录执行：

```bash
patch -p1 < docs/phase2-skills.patch
```

该步骤仅安装已审阅文本；不执行 Git 提交或推送。

> 更新：技能补丁已由提交者应用到 `.agents/skills/`，`skills/` 暂存目录和补丁文件已移除。
