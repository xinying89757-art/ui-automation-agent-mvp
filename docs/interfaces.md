# CLI 与阶段接口

从项目根目录调用 `python3 scripts/uia.py`。正常结果为 JSON；`ok: false` 表示操作未完成。
退出码 0 为命令完成，1 为静态校验报告存在错误，2 为输入/阶段条件错误，130 为中断。
路径参数 `--run` 接受 run ID、运行目录或 manifest 文件。证据路径和注册路径相对运行目录；
coverage、hooks、dependencies 的代码路径相对该运行下的 runner。

命令实际执行需由 Codex 按技能推进。`next` 只返回下一动作，**不调用模型、不启动浏览器**。

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
