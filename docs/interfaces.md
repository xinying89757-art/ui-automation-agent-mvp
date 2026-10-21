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

## Intent 与复用计划

每条用例在 `runs/<run-id>/cases/<case-id>/` 保存原有 v1.0 格式：
`automation-intent.yaml` 和 `reuse-plan.slim.yaml`。

```bash
python3 scripts/uia.py advance --run REQ-001 --case TC-01 --stage matching
python3 scripts/uia.py match --run REQ-001 --case TC-01
# Codex 查看候选、真实来源与依赖，编辑精简计划并确认每项 decision。
python3 scripts/uia.py advance --run REQ-001 --case TC-01 --stage discovery
```

候选检索只产生草案，`selection_confirmed` 默认为 false。每项计划保留 `ref`、
`capability`、`decision`、`runtime_unknowns`、`next_action`，可增加 `candidates`。
选择复用资产时增加 `asset`。Codex 语义审查后设置 `selection_confirmed: true`。

DIRECT_REUSE 还需 `verification`，包含 `exported: true`、实际 `signature`、当前
`source_sha256`、`target_fingerprint` 与当前 `evidence` 文件引用。target fingerprint
是配置 `targets` 字典按键排序的 JSON 的 SHA256（项目 `digest` 函数）。来源、依赖、
前提或风险不完整时保留适配/发现决策；不能将历史 snippets 当作当前可导入函数。

## 预检、生成、注册

```bash
python3 scripts/uia.py scaffold --run REQ-001
python3 scripts/uia.py preflight --run REQ-001 --evidence evidence/preflight.json
python3 scripts/uia.py register --run REQ-001 --case TC-01 --file /path/to/registration.json
```

preflight 证据由真实浏览器观察产生，以下仅为字段示例，不是测试事实：

```json
{
  "targets": {
    "public": {"url": "https://actual-test-host", "reachable": true, "target_visible": true},
    "admin": {"url": "https://actual-admin-host", "reachable": true, "target_visible": true, "authenticated": true}
  },
  "observation": "说明真实访问和目标站点可见性的证据来源"
}
```

registration 字段示例；ID 必须换成真实 Intent ID，行号必须指向实际实现：

```json
{
  "case_id": "TC-01",
  "script": "runner/tests/TC-01.spec.ts",
  "fixture": {
    "hooks": "fixtures/products.ts",
    "mutates": true,
    "mutation_scope": ["products.create", "products.delete"]
  },
  "dependencies": ["flows/products.ts"],
  "reused_assets": ["existing-asset-id"],
  "evidence": ["evidence/product-flow.json"],
  "runtime_resolutions": {
    "RU-01": {"status": "resolved", "evidence": ["evidence/product-flow.json"]}
  },
  "coverage": {
    "steps": {"S1": {"file": "tests/TC-01.spec.ts", "line": 10}},
    "capabilities": {"CAP-01": {"file": "flows/products.ts", "line": 12}},
    "assertions": {"A-01": {"file": "tests/TC-01.spec.ts", "line": 24}}
  }
}
```

准备阶段的每个步骤、能力和断言必须有注册覆盖。所有 blocking runtime unknown
必须有 resolution 证据。静态检查验证引用和存在性，Codex 仍负责语义核对。
显式列出不能由静态相对 import 发现的动态依赖；禁止依赖本机目录中的业务实现。

生成 spec 使用 `support/test` 导出的 test/expect；每个源用例恰好一个测试，标题以
`[case_id] ` 开始。所有核心断言使用 `businessAssertion` 包装。fixture 模块默认导出
`FixtureHooks`，四个方法均提供真实逻辑。配置数据规则保留环境变量引用，具体值在执行时读取。

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
它不代替真实执行或证明页面定位稳定。本次改造按用户要求未运行这些命令。
