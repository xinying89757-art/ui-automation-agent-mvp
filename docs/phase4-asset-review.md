# Phase 4 资产审核候选

依据 `uia-runtime-feedback-reviewer`：TC-0055 已在真实站点通过，A1/A2/A3、准备及恢复均通过；每日交付同版本 1 次。只提出候选，不长期回写。当前仓库未提供 `automation-assets/` 和 `ui-knowledge/` 注册库，外部资产的重复能力仍需审核；新候选默认 `ADAPT_BEFORE_REUSE / LOW`，不升级为跨版本稳定。

证据：`runs/GO-34d53c906f14/batches/cecde82b6b28405aab21edbd6c138612/case-results.json`、最终 TC-0055 spec，以及 `evidence/phase4-faq-five-restore.json`。

| discovery | classification | target | action | evidence | reason | confidence |
|---|---|---|---|---|---|---|
| 保存处理中按钮不可用并显示保存中，取消/关闭尝试保持弹窗 | UPDATE_UI_KNOWLEDGE | 保存交互规则 | REVIEW | TC-0055 A1/A2 | 真实观察；单次通过不代表定位跨版本稳定 | MEDIUM |
| 按方法/路径延迟、计数和释放请求，真实双击只产生一次请求 | NEW_ASSET_CANDIDATE | network.delay-count | ADD 候选 | TC-0055 A2/A3、network-control.test.mjs | 参数与 Case 数据解耦，可供其他处理中状态测试复用 | MEDIUM |
| 瞬时提示消失后仍能检查可见出现次数 | NEW_ASSET_CANDIDATE | observation.visible-occurrences | ADD 候选 | TC-0055 A3、观察器单测 | 避免将当前 DOM 数量当作全程结果次数 | MEDIUM |
| FAQ 设置 5 条并恢复原始记录、内容、顺序和元数据 | DO_NOT_PERSIST | 独立资产库 | REVIEW | 五条准备/恢复证明、TC-0033 本机证据 | 按用户要求已实现运行目录能力；完整 TC-0033 公开文件尚未通过，不升级为已通过 Case 的长期资产 | HIGH |
| 当前站点、记录 ID、准备标记、保护字段和机器路径 | DO_NOT_PERSIST | — | IGNORE | 本轮运行 | 不进入长期资产；保护字段不保存或输出 | HIGH |

- UI knowledge updates：1 项待审核。
- Existing asset updates：未发现可确认的既有同能力注册项；外部注册库缺失。
- New asset candidates：2 项，均需适配后复用、低稳定性评级。
- Do not persist：站点实例、数据标记、保护信息，以及尚未完整通过用例的升级结论。

## Review required

外部历史资产库的去重检查；TC-0033 远程公开文件验证；其他产品/版本上的适配验证。这里只保存审核清单，运行目录中的 `reports/asset-review.json` 汇总同一轮候选，未自动写入长期资产库。
