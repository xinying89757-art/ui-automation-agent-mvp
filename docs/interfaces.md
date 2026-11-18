# CLI 与阶段接口

从项目根目录调用 `python3 scripts/uia.py`。正常结果为 JSON；`ok: false` 表示操作未完成。
退出码 0 为命令完成，1 为静态校验报告存在错误，2 为输入/阶段条件错误，130 为中断。
路径参数 `--run` 接受 run ID、运行目录或 manifest 文件。证据路径和注册路径相对运行目录；
coverage、hooks、dependencies 的代码路径相对该运行下的 runner。

命令实际执行需由 Codex 按技能推进。`next` 只返回下一动作，**不调用模型、不启动浏览器**。

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

`next` 返回 `explore` 时不提问。它按入口/frame 聚合 `case_ids` 和 `targets_by_case`；在同一入口会话中处理每个 case 的全部目标。使用 `snapshot --run R --node editor --entry PAGE --purpose TARGET --save-as evidence/CASE-TARGET-1.json`，或 `generator --run R --purpose TARGET --entry PAGE --plan PLAN`（编辑器内保存时允许加 `--draft`）。快照证据只保存脱敏后的入口、frame、失败步骤等结果元数据，不保存 DOM。生成器报告文件本身可用作 `--evidence`。每次尝试后必须记录结果及现存证据文件：

```bash
python3 scripts/uia.py exploration-log --run R --case CASE --target TARGET --method snapshot --purpose TARGET --result failed --evidence evidence/CASE-TARGET-1.json --note '到达入口后控件仍不可见'
```

成功同样用 `--result ok` 记录，再通过 `hints target --name catalog.target --locator 'JSON' --evidence evidence/FILE --for '?placeholder'` 或 `hints promote --report exploration/generator-SLUG.json --for '?placeholder'` 写入实际观察到的控件、绑定该运行的规格占位符并重写 case-spec；多占位符用逗号分隔。只写入但未绑定的占位符仍算未解决，并消耗一次失败上限。每个 case/target 最多两次失败；此后 `next` 返回 `classify`，按返回的 `reason` 与 `evidence` 执行 `uia.py classify --run R --case CASE --result suspended --reason REASON --evidence PATH`。报告必须引用本次实际生成的证据路径。不要自行增加重试或向用户提问。

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
python3 scripts/uia.py init --run-id REQ-001 --config config/uia.local.yaml
python3 scripts/uia.py import --run REQ-001 --excel /path/to/cases.xlsx
python3 scripts/uia.py bind-specs --run REQ-001
python3 scripts/uia.py status --run REQ-001
python3 scripts/uia.py next --run REQ-001
python3 scripts/uia.py bind --run REQ-001 --cases TC-01 TC-02 --flows product-create --fixtures products
```

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

`validate` 检查技能引用、Intent/计划/代码覆盖，以及运行状态与证据一致性。
它不代替真实执行或证明页面定位稳定。校验不代替真实站点验证。


## 一步提测与一次清单（Phase 3）

```bash
.venv/bin/python scripts/uia.py go /path/to/cases.xlsx --profile my-prod --cases TC-0004,TC-0016
.venv/bin/python scripts/uia.py answer --run GO-xxx "A 除 TC-0002 缺少外其余可用，B 同意，C 无歧义"
.venv/bin/python scripts/uia.py session-turn --run GO-xxx --id conversation-turn-1 --kind 发起
```

`--cases` 以逗号分隔；不传则保留全部用例。未知 ID 直接报错。省略 profile 时仅在恰有一份
私有配置时自动选择。相同工作簿路径、profile、用例范围恢复同一个 run；工作簿内容变化仍做来源对齐。
导入、索引既有脚本、真实环境自检、可恢复样本契约复用、case-spec 任务、前置聚合和可执行批次由 go 衔接。
只有全量业务指纹匹配才复用样本契约。未知工作簿由当前 Codex 会话编写契约，不会启动模型子进程。
待编写契约时清单为草稿，不提问；已具备权限的独立既有脚本优先执行。

checklist.md 是 run.json 的中文投影，A 为站点/账号/编辑器/迁移等必要环境，B 为契约聚合的临时修改范围，
C 为原始业务歧义及明确选项。中文一句话必须明确各块；不理解的答复原子拒绝，不保存半份答案。
C 有多项时须逐项给选项；不会把“默认”当作业务答案。旧 --question/--file JSON 接口继续可用。
环境记忆位于私有 .auth/environment-memory，绑定环境/站点/身份/网络指纹，权限 0600；不打印身份内容。
否定答案也长期记忆。记忆不代替实时可达性、认证和变更范围检查；同意 B 也不能扩大已锁定权限。
新范围、业务歧义、产品问题及录制请求进 review.md/review.json，不提中途问题，不阻塞其他用例交付。
通过独立审核及原有 replay-demo 入口吸收动作脚本，不自动信任录制或改动断言。

会话适配器/当前 Codex 对每个用户消息调用一次 session-turn，稳定 id 去重。
四类计划内事件为发起、答清单、审核单、看报告；其余交互标记计划外。
中文 answer 自动计入清单回答数；AI 调用 repair/classify/login 不再伪装成人工介入。
没有接入会话轮次记录的调用者，无法从终端自动推断真实聊天轮次；指标只统计已记录事件。

报告的 Markdown/HTML/Excel 首先展示“结论、需要你处理、流程指标”，可见状态使用中文。
JSON 保留兼容的机器状态码，并附同样中文开头。metrics.json 记录清单问题数、回答数、会话轮次、
中途提问和计划外介入。review.json 包含复现、原始期望、实际失败、证据和受限脱敏截图。
只有公共控件文字白名单保留的弹窗截图可保留；任意输入、自由文字及媒体均遮罩，未采集时明确标注，
不替代成原始全页截图。截图不进入 scripts.zip。

## 公开文件远程交接（Phase 4）

```bash
.venv/bin/python scripts/uia.py remote-checks ingest --run RUN /path/to/results.json
.venv/bin/python scripts/uia.py remote-checks restore --run RUN
```

[完整协议及 schema](remote-checks.md)。限定用例的 go 正常完成后台保存、FAQ 准备和时序检查；公开前台不可达不挂起 defer_public 用例。交接文件为 `runs/<id>/remote-checks/{request.json,check.mjs}`，外部只需 Node 18+。回执保留 pass/fail/still-cached/unreachable 四类，严格绑定请求文件字节哈希、批次和版本；远程通过仍需本机恢复成功。等待远程的准备快照不发送到外部；最终回执会自动恢复，到期/取消可显式 restore，或通过 go 续跑处理到期恢复。
