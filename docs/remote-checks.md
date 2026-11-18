# 公开文件远程检查

这是文件交接协议，不依赖云服务或仓库运行时。编辑器、认证、数据准备和恢复留在本机；外部执行端只收到 `request.json` 和 `check.mjs`，不接收 `.auth/`、run.json、state 或账号信息。

## 产生与执行

case-spec 使用 page-map 中声明 `resource: {path: /任意公开文件}` 的目标，`defer_public` 步骤，以及 `remote_file` 检查。每个断言的 `excel` 必须逐字引用导入的 Excel 单元格或完整行。`contains`、`not_contains`、`equals`、`max_length`、`truncated_at`、`ordered_pairs` 与 `faq_page` 是可执行条件，不能代替原文。`truncated_at` 使用 `{op: truncated_at, value: N, text: 完整预期文本}`，要求远程正文恰为完整文本的前 N 个 Unicode 字符，因而明确不含第 N+1 个字符。`faq_page` 使用 `{op: faq_page, value: {count: N, objects: [{pairs: [[问题, 答案], ...]}, ...]}}`；每个 JSON-LD FAQPage 对象分别核对，严格检查对象数、对象内问答集合且不接受跨对象混合。`ordered_pairs` 用 `section` 指定二级标题，要求该节恰好是 N 组问题/答案两行，拒绝缺项、多项、乱序或合并一行。

```yaml
steps:
- {id: S2, verb: defer_public, target: public.llms}
assertions:
- id: A2
  after: S2
  excel: 2. 公开文件立即显示新的网站概述。
  checks:
  - target: public.llms
    op: remote_file
    value: {op: contains, value: example-overview}
```

本机成功完成该断言之前的操作后，`uia.py` 自动生成：

- `runs/<run-id>/remote-checks/request.json`
- `runs/<run-id>/remote-checks/check.mjs`

远程检查器会随每个条件返回限长、脱敏证据。检查器解析错误属于自动化问题，不是产品缺陷；导入失败回执时会用本机同版解析器复核证据。也可将 `{ "id": "检查 ID", "section": "## FAQ\\n..." }` 保存为 JSON 并运行 `.venv/bin/python scripts/uia.py remote-checks reevaluate --run RUN evidence.json`，无需再次访问远端。该命令仅在本机生命周期和清理都已核验后结案，并保存证据及 SHA-256。

`// @deferred A2` 只表示交接覆盖，不执行空断言、不计本机通过。用例结果为“待远程检查”；不因本机 HTTP 前台不可达而挂起后台准备。

将上述两个文件复制到可访问目标前台的机器，Node 18+ 执行：

```bash
node /path/to/remote-checks/check.mjs
```

脚本总是读取自身目录的 `request.json`，原子写入同目录 `results.json`。每条仅 fetch 一次，有超时和 1 MiB 响应上限；不自动等待、不轮询。普通检查根据 `earliest_check_at` 调度。带 `max_latency_seconds` 的立即检查会设置 `immediate: true`、`cache_bust: true`，并把 `earliest_check_at` 设为 `saved_at`；脚本追加每检查唯一的 `uia_cb` 查询参数，结果 `variant` 标为 `cache_busted`。其他检查的 variant 是 `default`，导入会核对实际 variant 与请求一致。

调度会先运行不需要 hold 的用例，再准备 deferred 用例，所有准备完成后才生成最终 `request.json`。数据 hold 写入私有 `.auth/remote-holds/`，供同环境的其他 run/clone 阻止数据修改；只读用例仍可运行。导入或 restore 完成恢复后清除 hold。

## 立即生效：预布监听

当 box 无法访问公开前台、而断言有 `max_latency_seconds` 时，先启动远程监听器，再保存：

一条命令（推荐）：`.venv/bin/python scripts/uia.py go cases.xlsx --profile PROFILE --cases TC-0036 --arm-watch TC-0036 --lead-minutes 20 --watch-minutes 10`。go 在任何批次前布监听，立刻在 stderr 和 `runs/RUN/remote-checks/watch/ARMED.json` 给出监听目录与 `save_not_before`，然后先跑 hold-free 用例，到点才保存。把目录交给远程执行器后，取回 `watch-results.json` 运行 `ingest-watch`（第 4 步）。分步做法如下：

0. 如果该用例已经在本 run 执行过，先运行 `.venv/bin/python scripts/uia.py spec gen --run RUN --cases TC-0036` 重置用例，再布监听。建议使用 `--watch-minutes 10`：更新若几分钟内仍不可见，已经不符合“立即”要求。
1. 运行 `.venv/bin/python scripts/uia.py remote-checks arm-watch --run RUN --case TC-0036 [--lead-minutes 20] [--watch-minutes 10] [--interval-ms 1000]`。该命令从 case-spec 与 page-map 读取静态条件、公开路径和时效阈值；fixture 动态条件会被拒绝。默认在 20 分钟后开放保存窗口，并监听 40 分钟。
2. 将返回的 `runs/RUN/remote-checks/watch/WATCH_ID/` 目录交给可访问公开前台的远程执行器。必须在 `save_not_before` 前启动 `node check.mjs` 并保持进程运行；脚本每秒带唯一 cache-bust 参数采样，并原子写 `watch-results.json`。只交付该目录，不交付 run.json、state 或认证文件。
3. `arm-watch` 后立即在 box 运行 `.venv/bin/python scripts/uia.py go cases.xlsx --profile PROFILE --cases TC-0036`；该命令到该用例时会自行等待至 `save_not_before`（等待超过 60 分钟会拒绝），再执行保存流程。
4. 将生成的 `watch-results.json` 带回 box，并运行 `.venv/bin/python scripts/uia.py remote-checks ingest-watch --run RUN /path/to/watch-results.json`。

旧版 `watch_gap` 可用 `.venv/bin/python scripts/uia.py remote-checks reevaluate-watch --run RUN [--watch WATCH_ID]` 对已归档并校验 SHA-256 的监听结果重新判定。此操作只更新本地判定历史，不访问前台或恢复站点数据；相同判定重复执行不会重复追加历史。

监听结果按 `schemas/remote-watch-results.schema.json` 校验；请求格式见 `schemas/remote-watch-request.schema.json`。仅保存每次采样的时刻、HTTP 成功标志和条件匹配标志、状态变化时间线及首次出现时限长脱敏证据，不保存响应头或完整正文。`ingest-watch` 将 verdict 写入同一 regular remote check 并经现有 case folding / cleanup 流程结案；重复导入幂等。

回到本机导入：

```bash
.venv/bin/python scripts/uia.py remote-checks ingest --run RUN /path/to/results.json
```

## request.json v1

顶层：`schema_version: uia-remote-request.v1`、`run_id`、`checks` 数组。每条：

| 字段 | 含义 |
|---|---|
| id | run/批次/用例/断言绑定的唯一 ID；重跑后旧 ID 失效 |
| case_id / assertion_id | 规范用例及原始断言 ID |
| expected | Excel 完整行原文；不会为了缓存改写“立即”等要求 |
| url / method | page-map 相对文件路径结合配置的公开站点；当前方法 GET |
| conditions | `{op, value}`，有序问答另有 `section`；无定位器、认证信息 |
| saved_at | 本机观察保存成功后生成交接的时间 |
| earliest_check_at | 普通检查为 saved_at + 1 小时；立即检查为 saved_at |
| deadline | saved_at + 2 小时；超过后为无法验证，不计通过 |
| timeout_ms | 单次 fetch/读流超时，默认 10000 |
| cache_bust / immediate | 可选布尔值；立即检查使用 `cache_bust: true`，并把 `immediate` 设为 true |
| max_latency_seconds | 可选；TC-0036 为 5 秒观察窗口，延迟执行不能证明“立即更新” |
| restored_at | 可选；本机已恢复数据的时间；此后的观察不能作为该准备版本的业务通过/失败 |

`max_latency_seconds` 是执行证据窗口，不能使缓存后成功变成“立即更新”成功。TC-0036 必须由已准备好的远程执行器在保存后立刻读取；一小时后的内容即使正确也只能记录 `immediate_timing_unverified`。若需不同“立即”时间定义，需业务明确确认后更改资源契约。

## results.json v1

机器 schema：[`schemas/remote-results.schema.json`](../schemas/remote-results.schema.json)。顶层字段严格为：

- `schema_version: uia-remote-results.v1`
- `run_id`：必须匹配。
- `request_sha256`：所执行 request.json **原始文件字节** SHA-256，包含换行；不能重新格式化后配旧结果。
- `results`：非空数组，可分批回传；同一文件内 ID 不可重复。

结果行字段严格为 `id`、`checked_at`（带时区 ISO 时间）、`status`、`http_status`（整数或 null）、`conditions`（与请求条件对应的布尔数组；传输失败可为空）、`reason`（schema 中的有限枚举）和 `variant`（`default` 或 `cache_busted`）。不允许自由错误信息、响应 body、cookie、storage 等额外字段。

| status | 中文报告 | 归并 |
|---|---|---|
| pass | 远程通过 | 所有远程断言通过且本机准备/恢复核验成功，才计用例通过及稳定性 |
| fail | 远程业务失败 | 缓存窗口后内容不符合，或及时性要求在有效窗口内不符合，计业务失败 |
| still-cached | 公开文件仍在缓存期 | 暂不判业务失败；保留待远程状态，可再回传新时间的观察 |
| unreachable | 远程不可达或无法验证 | 网络/HTTP 权限或服务错误、超时、过期、数据已还原、无法证明立即更新；不计通过 |

导入先校验整个文件再改 manifest：run/hash、ID、当前批次和版本、时间窗口、条件长度和布尔类型、通过与 HTTP 状态/条件结果的一致性。旧版本回执、恢复后的通过、缓存期结束后仍宣称 still-cached 等会被拒绝。同一回执重复导入幂等；更新的结果保留全部历史。用例结果、中文 Markdown/HTML/Excel、JSON 和 `metrics.remote_checks` 同步更新。JSON 保留机器状态码。

## 数据有效期与恢复

远程读取临时数据时，不能提前恢复后再把不匹配判成产品错误。因此默认 fixture 在发出远程检查后保留已保存的数据，**清理标为 pending，而不是 verified**；本机受保护 `state/fixture-snapshots/` 先保存原始快照。普通用例仍立即恢复。

所有活跃检查均收到 pass/fail/unreachable 后，ingest 在本机使用共享认证模块恢复数据，按准备的反序恢复重叠快照，并重读核验。still-cached 或尚未回传的检查继续保留准备状态。恢复失败保留证据及 pending，禁止计通过；可重试：

```bash
.venv/bin/python scripts/uia.py remote-checks restore --run RUN
```

外部编排器必须在 deadline 后调用此命令，或调用 go 续跑触发到期恢复；项目没有后台守护进程。要取消检查也用此命令，不能直接覆盖快照或重跑写操作。恢复后请求写入 restored_at，旧请求字节哈希的结果不再适用。重新验证需重新准备并生成新批次请求。不要将受保护快照发送到远程执行端。

已恢复后的再次验证，可明确重新编译/登记相关契约再续跑（原批次和回执仍保留）：

```bash
.venv/bin/python scripts/uia.py spec gen --run RUN --cases TC-0033 TC-0036
.venv/bin/python scripts/uia.py go /path/to/cases.xlsx --profile PROFILE --cases TC-0033,TC-0036,TC-0055
```

恢复或重跑导致 request.json 改变时，旧请求原始字节按 SHA-256 留存在 `remote-checks/requests/`；已导入结果在 `remote-checks/ingested-<receipt-hash>.json`，便于复核历史结果关联的确切请求。
