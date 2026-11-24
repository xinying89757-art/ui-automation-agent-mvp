# CLI 与阶段接口

从项目根目录调用 `python3 scripts/uia.py`。正常结果为 JSON；`ok: false` 表示操作未完成。
退出码 0 为命令完成，1 为静态校验报告存在错误，2 为输入/阶段条件错误，130 为中断。
路径参数 `--run` 接受 run ID、运行目录或 manifest 文件。证据路径和注册路径相对运行目录；
coverage、hooks、dependencies 的代码路径相对该运行下的 runner。

命令实际执行需由 Codex 按技能推进。`next` 只返回下一动作，**不调用模型、不启动浏览器**。

`review-page ingest` 接收与当前运行和审核版本一致的导出文件，生成 `review-decisions.json` 和按用例
汇总答复及待答问题的 `review-handoff.json`。后者的 `processing: not_applied` 表示仅已接收，Agent
仍须逐项落实到执行规格、断言或本轮范围，再做校验；不会自动修改规格、写入知识库或运行测试。
没有版本信息的历史原型导出不能直接作为当前审核版本导入，需保留原件并人工对照审核项和来源。

已核对的入口答复可通过 `review-page apply-entry --run R --case C --review-id ID --review-source prototype`
接入匹配的运行内清单；旧原型仍记录无审核版本。规格完成后 `review-page bind-case --run R --case C
--review-source prototype --review-ids ID1 ID2` 记录审核项和规格指纹，要求原始用例未变化且通过规格校验；
Agent 仍须对照确认断言语义，工具不凭自然语言自动推断预期。新页面可用 `--review-source current`。

`login --run R --headed` 和 `run-batch --run R --cases C --headed` 使用有界面浏览器；已通过用例的同版本复跑
可加 `--rerun`，保留历史执行及门禁。`report --run R` 默认不写长期知识库；旧参数 `--no-knowledge-writeback` 仍可使用。经用户审核批准后，才手动执行 `kb writeback --run R`。
运行内新控件可写在 `state/page-map-overlay.yaml`（`pages` / `targets`），不能覆盖共享名称；批次快照包含该文件，
导出脚本包附带 overlay 和配置说明，不自动提升为共享知识。

原型迁移可用 `review-page ingest-prototype --run R --file OLD.json --mapping MAP.json`：MAP 是旧 ID
到当前 ID 的一对一对象；命令核对运行、用例归属及已确认内容，另存来源摘要和 `reviewed_revision: null`，
不会声称审核过当前版本。自由文本答复需由 Agent 逐用例拆解为计划，写入 JSON：

```json
{"run_id":"R", "review_source":"review-decisions.json", "review_source_sha256":"答复文件的 SHA-256",
 "items":[{"review_id":"Q1", "case_id":"C1", "disposition":"implement", "scope":"产品描述",
           "instruction":"进入产品描述并打开 FAQ 面板"}]}
```

`review-page validate-plan --run R --file PLAN.json` 核验来源摘要及每个答复与关联用例的组合均有处理项；
`disposition` 支持 implement、partial_exclusion、exclude、blocked。通过仅表示覆盖完整、结构有效；
它不证明语义正确、规格已生成、控件已验证或测试可运行。规格和执行结果必须另行落实。

知识查询通过 `uia go` 自动按每例的页面/入口运行，结果写入 `runs/<id>/knowledge-match.json`，在 generator/spec-gen 之前完成。手动查询与维护命令：

```bash
python3 scripts/uia.py kb query --case TC-0004 [--run GO-id] [--max-tokens N]
python3 scripts/uia.py knowledge merge --from /path/to/assets/playwright-runner/knowledge --run-id GO-id
python3 scripts/uia.py kb validate
python3 scripts/uia.py kb prune [--stale-after-days 90] [--candidate-after-days 180]
python3 scripts/uia.py kb writeback --run GO-id
```

自动匹配按 case 的页面、frame 执行硬过滤，再仅保留 case 查询 BM25 分数大于 0 的条目，以及 case-spec 直接引用的入口、路线和目标；不会设置默认 token 上限。手动 `kb query` 只有显式传 `--max-tokens` 才应用上限。`knowledge-match.json` 继续记录每例实际用量，报告保留 p50/p95。索引过滤与排序见 [知识库设计](knowledge-base.md)。

### `explore` action

`next` 返回 `explore` 时先自主探索；若已经没有可行线索，也可提前评估并提问。它先选择占位目标最少、优先级最高的 case，每次最多 8 个目标；同入口/frame 的其他 case 仅在共享同一目标时加入 `case_ids` 和 `targets_by_case`。推荐执行 action 返回的 `generator_command`：它包含 `--cases` 和 `--targets`，generator 会把 step ID/占位目标清单写入 prompt，并输出逐目标的 `step_targets` 映射。快照可用 `snapshot --run R --node editor --entry PAGE --purpose TARGET --evidence evidence/CASE-TARGET-1.json` 保存脱敏后的入口、frame、失败步骤等结果元数据，不保存 DOM。

```bash
python3 scripts/uia.py exploration-log --run R --case CASE --target TARGET --method snapshot --purpose TARGET --result failed --evidence evidence/CASE-TARGET-1.json --duration-ms 1234 --note '到达入口后控件仍不可见'
```

成功的 snapshot 同样用 `--result ok` 记录。Generator session 自动记录各 case/target 的结果与耗时；运行 `hints promote --run R --report exploration/generator-SLUG.json` 后，promote 仅接受 `verified: true` 且 `match_count: 1` 的 step locator，通过唯一 catalog 写入路径保存控件、绑定 run 内占位符并重写 case-spec；通常不需要手动 `--for`。手动 `hints target`/`hints promote --for '?placeholder'` 仍可用于精确绑定。没有绑定目标不视为目标已解决。两次尝试、无进展或累计 5 分钟后，`next` 返回 `assess_exploration` 提醒 Agent 判断，不自动给出用例结论；Agent 也可以提前评估。`gap-assess --decision continue` 记录新线索并继续，`gap-assess --decision ask` 创建仅阻断相关用例的答疑；关键问题加 `--urgency critical`，其他问题在独立工作完成后集中提问。答复用 `answer --question ID --file answer.json`（JSON 字符串），并保存为未验证的 run 内知识候选；`candidate-verify --question ID --evidence PATH` 记录人工核对过的实测证据，不自动写入长期知识库。报告中的 exploration_duration_ms 记录次数、总时长和 p50/p95。

```bash
python3 scripts/uia.py exploration-log --run R --case C1 --target '?faq' --method snapshot --purpose faq --result failed --evidence evidence/faq.json --duration-ms 30000 --progress stalled --note '已查看产品描述，没有发现组件入口'
python3 scripts/uia.py gap-assess --run R --cases C1 C2 --target '?faq' --decision ask --page 产品描述 --reason '无进一步线索' --prompt '如何打开 FAQ 组件面板？'
python3 scripts/uia.py gap-assess --run R --cases C1 --target '?faq' --decision continue --reason '发现产品菜单，继续查看'
```

提问时 `--page` 表示业务适用范围，用于避免跨页面复用同名目标的答复；同一页面和目标的问题会合并。若本运行审核答复已覆盖该用例，先用 `gap-assess ... --review-id REVIEW_ID` 取回答复，再按适用范围验证。待处理的审核页问题只暂停其关联用例。

每完成探索、绑定、lint/gen、批次或恢复动作后都重新调用 `next`，继续处理 runnable 用例和其他 AI action，直至所有用例均已结论并生成最终报告；不能以中间摘要结束。

## 初始化、导入、状态与分组

配置三环境及公共登录见 [环境与登录说明](environments-and-login.md)。新增接口：

```bash
python3 scripts/uia.py env list
python3 scripts/uia.py setup --profile my-gray --environment gray --site en.example.com --account my-account
python3 scripts/uia.py init --run-id REQ-001 --profile my-gray
python3 scripts/uia.py login --profile my-gray --check-only
python3 scripts/uia.py login --run REQ-001
```

`setup` 的密码隐藏输入，或显式使用 `--credentials-file` / `--password-env`；不接受密码参数。
裸域名会探测 HTTP/HTTPS；写明协议则保持该协议。`profile set` 修改已有配置的站点、变更范围和稳定性次数，不手改 JSON：

```bash
python3 scripts/uia.py profile set --profile my-prod --site http://en.example.test \
  --mutation-allowed --scope llms.txt --stability-passes 1 --run REQ-001
```

`mutation.allowed: false` 且 `scope: []` 为只读。`scope` 中的名字是允许变更的功能；
用例的 `mutation_scope` 必须是其中的子集。`llms.txt` 允许在该站点上增删改这一功能，并要求清理被验证。
`stability_passes` 为 1 时，一次清理成功即交付；为 2 时需要夜间的第二批独立成功。
站点和范围只在 `init` 前的清单阶段修改；运行中 CLI 会拒绝并记录范围变更。专用测试站点如允许
编辑器内任意数据，需显式记录批准人与恢复要求：

```bash
python3 scripts/uia.py profile set --profile my-prod --mutation-allowed --scope '*' --editor-data-restorable
```

`login` 的 `--profile`、`--config`、`--run` 三选一，可加 `--force`；`--run` 成功后保存环境/站点证据并接入 preflight。
后台目标必须可达且已登录。公开站点失败只写入 `capabilities.public_frontend` 和脱敏后的原因，
不阻断后台用例；只有脚本调用 `waitForPublic` 的用例会等待公开站点。
命名环境的证据必须含当前环境 ID、实际初始地址、网络指纹及灰度标记，不可只沿用下方旧配置的 targets 示例。
旧 `init --config` 接口继续兼容。配置格式仍为 `uia-config.v1`，新增 `environment`、`network`、`site` 及 `auth.provider/credentials_file/identity`。

```bash
python3 scripts/uia.py go /path/to/cases.xlsx --profile my-prod
python3 scripts/uia.py go /path/to/cases.xlsx --profile my-prod --code /path/to/project
python3 scripts/uia.py init --run-id REQ-001 --config config/uia.local.yaml
python3 scripts/uia.py import --run REQ-001 --excel /path/to/cases.xlsx
python3 scripts/uia.py bind-specs --run REQ-001
python3 scripts/uia.py status --run REQ-001
python3 scripts/uia.py next --run REQ-001
python3 scripts/uia.py bind --run REQ-001 --cases TC-01 TC-02 --flows product-create --fixtures products
```

`go` 在导入和 bind-specs 之后运行 spec-pathfinder。默认只做无代码 v1，写出 `runs/<id>/spec-pathfinder/<需求>/SPEC-human-v1.md` 与 `DOUBTS-v1.md`。`--code` 额外运行索引器并写出执行版、证据附录和 v1→v2 升级记录；索引 JSON 只留在该 run 目录。存疑并入同一次 `checklist.md`（D 为未知入口，E 为路径/预期/前端控件）。本运行保留答复；未验证的业务结论只作为候选，不跨运行自动当作确认结果。随后的 `spec gen` 消费确认稿中的入口、步骤和预期。

导入响应会提示先运行 `bind-specs`，索引 `tests/*.spec.ts` 并优先回放已有脚本。页面探索使用
`python3 scripts/uia.py snapshot --run REQ-001 --node page|content-admin|editor`：登录、打开目标页面、
输出脱敏 DOM 结构（含同源 `#backstage-innerpage`）后退出。禁止原始 page/body、cookie 或 storage dump。

`--isolated` 只用于已证明数据隔离的用例；多 worker 另需 registration 的
`isolation_evidence`。默认单 worker。

表头映射 JSON 示例（列号可为 Excel 字母或从 1 开始的整数）：

```json
{
  "产品管理": {
    "header_row": 2,
    "columns": {
      "id": "A", "module": "B", "title": "C", "priority": "D",
      "preconditions": "E", "steps": "F", "expected": "G", "data": "H"
    }
  },
  "说明页": {"ignore": true}
}
```

通过 `import --mapping /path/to/mapping.json` 提供，或回答 column_mapping 问题。
问题的答案文件只放单张工作表的 `{header_row, columns}` 对象，回答后重新导入。
空白负向输入按原样保存；读取公式文本，不求值。

`source.json` 保存原始 ID、sheet、rows、每个字段的原始单元格位置和原始内容，
业务内容指纹与位置分离。manifest 的规范 case ID 用于目录和 test 标题，原始 ID
始终保留。跨工作表重复 ID 加来源后缀，缺失 ID 按来源内容生成并保存映射。

## case-spec 与生成

格式见 [case-spec 契约](case-spec.md)。旧 advance/match/register 只保留历史兼容，
新代码不手填覆盖行号。

```bash
python3 scripts/uia.py spec lint --run REQ-001 --cases TC-0004
python3 scripts/uia.py spec gen --run REQ-001 --cases TC-0004
python3 scripts/uia.py spec render --run REQ-001 --cases TC-0004
python3 scripts/uia.py snapshot --run REQ-001 --node editor --frame '#backstage-innerpage'
python3 scripts/uia.py snapshot --run REQ-001 --node editor --open-target llms --scope '#backstage-dialog-customizeFile'
```

快照过滤隐藏节点、图标字符和敏感信息，并报告重复 role/name。lint 聚合未知目标及业务问题，
每条断言须引用 Excel 原始期望行/单元格。生成器输出统一 fixture、独立 spec 和覆盖标记；
TODO 不能进入执行。preflight 仍由真实浏览器证据接入。

## 探索、问题和演示

```bash
python3 scripts/uia.py explore --run REQ-001 --flow product-create --gap save-entry \
  --strategy accessible-name --seconds 80 --outcome unresolved --evidence evidence/save-entry.json
python3 scripts/uia.py question --run REQ-001 --kind product --subject target-product \
  --prompt "请确认目标产品的唯一标识" --cases TC-01 TC-02
python3 scripts/uia.py answer --run REQ-001 --question QUESTION_ID --file /path/to/answer.json
python3 scripts/uia.py replay-demo --run REQ-001 --question QUESTION_ID --evidence evidence/demo-replay.json
```

问题类型：login、environment、product、demo、column_mapping、preconditions。
`preconditions` 在导入时合并成一个问题。回答 `{"available":["item"],"unavailable":["item"]}`。
unavailable 的用例保持等待，结果留空，不记为 not_suitable。
`--key` 可显式提供缺口身份，默认按类型/subject/sheet 合并。人工回答用 JSON 值或对象，
不要包含凭证值。demo 回答为 `{"script":"/path/to/recorded.spec.ts"}`，导入后仍需独立回放。
回放证据含实际 `script_sha256`、`result: passed` 和 `cleanup_verified: true`。

## 执行、修复和恢复

```bash
python3 scripts/uia.py run-batch --run REQ-001 --cases TC-01 TC-02
python3 scripts/uia.py wait --run REQ-001
python3 scripts/uia.py preconditions --run REQ-001
python3 scripts/uia.py next --run REQ-001
python3 scripts/uia.py repair --run REQ-001 --case TC-01 --evidence evidence/diagnosis.json
python3 scripts/uia.py recover --run REQ-001
python3 scripts/uia.py recover --run REQ-001 --abandon --evidence evidence/interruption.json
python3 scripts/uia.py resolve-fixture --run REQ-001 --fixture products --evidence evidence/cleanup.json
```

`run-batch` 是实际启动浏览器的入口。保存 active batch 后运行独立 Playwright 进程，
并用 `runs/<id>/heartbeat.json` 每几秒写一次进度。`wait` 只读这个文件，不看 PID。
运行结束自动读取专用 reporter 结果；有通过用例时自动吸收定位。`record-run` 可显式导入同一 active batch 的结果，
不能导入未知批次或重复导入历史报告。脚本或依赖在执行期间变化不会计入成功。
同一批复用一个编辑器会话。每日 `stability_passes: 1` 时，这一次成功就是交付；
夜间任务设为 2，才需要另一批独立成功。公开文件缓存不作为当次断言。

清理恢复证据包含 `fixture_id`、`cleanup_verified: true` 及实际观察记录。清理后还需
回答相关问题，以保留人工/环境阻断的完整生命周期。只允许修复 automation_failure；
业务失败不得通过修复期望或填补负向数据转为通过。

需要结束无法继续的用例时：

```bash
python3 scripts/uia.py classify --run REQ-001 --case TC-01 --result environment_blocked \
  --reason "说明不能继续的具体原因" --evidence evidence/blocker.json
```

结果为 passed、business_failure、automation_failure、environment_blocked、
product_confirmation、not_suitable 或 interrupted。passed 只能来自实际批次报告，
不能用 classify 人工设置。

## 反馈、报告与校验

```bash
python3 scripts/uia.py feedback --run REQ-001 --case TC-01 --file /path/to/feedback.json
python3 scripts/uia.py report --run REQ-001
python3 scripts/uia.py validate
python3 scripts/uia.py validate --run REQ-001
```

反馈 JSON 为 `{case_id, items}`，items 可为空。每项包含 classification、summary、
evidence 文件引用列表；分类沿用 UPDATE_UI_KNOWLEDGE、UPDATE_EXISTING_ASSET、
NEW_ASSET_CANDIDATE、DO_NOT_PERSIST。回写候选可附 proposed_change、target_asset_id
和 before/after，项目不会自动应用。

`report` 可生成部分结果，未执行/等待用例清楚保留。JSON 和 Excel 包含逐条状态与指标，
HTML 支持筛选；脚本 ZIP 排除依赖、凭证与运行日志。只有源用例全部有最终结果、
未知工作表已解决、PASS 反馈完成且交付物齐全时，run 才进入 completed。

`validate` 检查技能引用、规格与代码覆盖，以及运行状态与证据一致性。
它不代替真实执行或证明页面定位稳定。校验不代替真实站点验证。


## 新需求提测与 HTML 审核

新需求的人审阶段可以使用固定的单文件 HTML。以下命令分别准备审核材料、重新生成界面和接收答复。

```bash
python3 scripts/uia.py go /path/to/cases.xlsx --profile my-prod
python3 scripts/uia.py review-page render --run GO-xxx
python3 scripts/uia.py review-page ingest --run GO-xxx --file /path/to/GO-xxx-review.json
```

页面生成到 `runs/<id>/review.html`，自动显示运行清单中的问题。可选的 `runs/<id>/review-input.json`
提供 `title`、`questions` 与 `checks`。每项使用稳定的 `id`、`title` 和包含实际用例 ID 的 `cases` 数组，
可附 `description`、`source`、HTTPS `link`。问题可附现有 `answer`，同 ID 可补充系统问题。
关键断言用 `checks` 字符串数组列出应验证的结果。Agent 只添加需人工判断的问题和关键断言，原始用例随时可查。
导出带运行 ID 和审阅版本的 JSON 文件，导入后把结构化决定保存到运行记录及 `review-decisions.json`。
Agent 按返回的决定更新相关规格并核验后继续执行。工具保存审核意见，业务步骤与断言由 Agent 按用例原文和审核结果落实。

```bash
.venv/bin/python scripts/uia.py preflight --profile my-prod
.venv/bin/python scripts/uia.py go /path/to/cases.xlsx --profile my-prod --cases TC-0004,TC-0016 \
  --smoke-size 3 --smoke-pass-rate 1 --first-result-budget-minutes 26
.venv/bin/python scripts/uia.py answer --run GO-xxx --question QUESTION_ID --file /path/to/answer.json
.venv/bin/python scripts/uia.py session-turn --run GO-xxx --id conversation-turn-1 --kind 发起
```

`uia preflight` 不带 `--evidence` 时现场检查登录、目标网站是否可选、内容编辑器是否打开。凭据只来自环境变量或 `.auth/`。失败时把整个 run 标为 `environment_blocked` 并停止，不执行用例。`--run` 加 `--evidence` 仍只校验已有浏览器证据。

`uia go` 在执行用例前固定做同一次预检。全量（未传 `--cases`）且用例数大于 `--smoke-size`（默认 3）时，先跑按优先级和模块分散的代表用例；通过率达到 `--smoke-pass-rate`（默认 1）才继续其余用例。首个结果耗时超过 `--first-result-budget-minutes`（默认 26）时中止后续批次。

`--cases` 以逗号分隔；不传则保留全部用例。未知 ID 直接报错。省略 profile 时仅在恰有一份
私有配置时自动选择。相同工作簿路径、profile、用例范围恢复同一个 run；工作簿内容变化仍做来源对齐。
导入、索引既有脚本、真实环境自检、可恢复样本契约复用、case-spec 任务、前置聚合和可执行批次由 go 衔接。
只有全量业务指纹匹配才复用样本契约。未知工作簿由当前 Codex 会话编写契约，不会启动模型子进程。
已有脚本和新规格都须在相关审核答复落实后执行。等待答复的用例不会阻断独立用例。

HTML 审核页是新需求的人工审核入口。执行中新增问题使用 `answer --question --file` 保存答复；
旧 Intent 运行的原文件和报告可只读查看，需要复跑时检出历史 Git 版本。
环境记忆位于私有 .auth/environment-memory，绑定环境/站点/身份/网络指纹，权限 0600；不打印身份内容。跨运行只自动采用环境和授权条件，业务预期与入口答复在本运行内保留，未验证前不作为跨运行确认结果。
否定答案也长期记忆。记忆不代替实时可达性、认证和变更范围检查；同意 B 也不能扩大已锁定权限。
新发现的业务歧义和操作缺口可以在运行中提问；只等待受影响的用例，其他用例继续。明确预期后的实际不符先留证并按业务问题处理。
通过独立审核及原有 replay-demo 入口吸收动作脚本，不自动信任录制或改动断言。

会话适配器/当前 Codex 对每个用户消息调用一次 session-turn，稳定 id 去重。
四类计划内事件为发起、答清单、审核单、看报告；其余交互标记计划外。
HTML 审核提交和运行中答复分别计数；AI 调用 repair/classify/login 不计入人工介入。
没有接入会话轮次记录的调用者，无法从终端自动推断真实聊天轮次；指标只统计已记录事件。

报告的 Markdown/HTML/Excel 首先展示“结论、需要你处理、流程指标”，可见状态使用中文。
JSON 保留兼容的机器状态码，并附同样中文开头。`results.json` 的 `metrics` 与 `flow_metrics`，以及
`metrics.json`，都包含：`time_to_first_result_seconds`、`pass_rate`、`failure_class_counts`、
`failure_class_shares`（environment / automation / product / suspended，在已分类失败中的占比）、
`human_interventions_per_case`、`kb_hit_rate`（检索到且被规格或脚本实际引用的条目占比）、
`re_explored_known_pages`、`knowledge_injected_tokens` 的 p50/p95，以及 `rescued_by_midscene`
（计数字段，由并行改动写入 run；缺省为 0）。逐条结果带 `failure_class`。
`SITE_NOT_ACCESSIBLE`、未找到目标网站、登录失败和站点加载超时归入 `environment`，不再记为自动化失败。
review.json 包含复现、原始期望、实际失败、证据和受限脱敏截图。
只有公共控件文字白名单保留的弹窗截图可保留；任意输入、自由文字及媒体均遮罩，未采集时明确标注，
不替代成原始全页截图。截图不进入 scripts.zip。

## 公开文件远程交接（Phase 4）

```bash
.venv/bin/python scripts/uia.py remote-checks ingest --run RUN /path/to/results.json
.venv/bin/python scripts/uia.py remote-checks restore --run RUN
```

[完整协议及 schema](remote-checks.md)。限定用例的 go 正常完成后台保存、FAQ 准备和时序检查；公开前台不可达不挂起 defer_public 用例。交接文件为 `runs/<id>/remote-checks/{request.json,check.mjs}`，外部只需 Node 18+。回执保留 pass/fail/still-cached/unreachable 四类，严格绑定请求文件字节哈希、批次和版本；远程通过仍需本机恢复成功。等待远程的准备快照不发送到外部；最终回执会自动恢复，到期/取消可显式 restore，或通过 go 续跑处理到期恢复。
