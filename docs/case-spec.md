# case-spec.v1

可机读结构见 [JSON Schema](../schemas/case-spec.schema.json)；CLI 另检查 Excel 原文、跨用例重复及动态词表。

每条已导入用例的 `runs/<id>/cases/<case>/case-spec.yaml` 是业务到代码的精简契约。
`run.json` 仍是唯一进度源；case-spec、Markdown、coverage、清单都是输入或投影。

```yaml
schema_version: case-spec.v1
case_id: TC-0004
intent: 从设置面板打开管理txt文件并显示默认页签
automatable: {status: 'yes', reason: 已知编辑器目标}
required_env: []
data_prep: {}
mutation_scope: []
start_page: editor
steps:
  - {id: S1, verb: open, target: settings}
  - {id: S2, verb: click, target: txt.entry}
assertions:
  - id: A1
    after: S2
    excel: '2. 页面打开标题为“管理txt文件”的弹窗。'
    checks:
      - {target: txt.title, op: text, value: 管理txt文件}
questions: []
```

字段均必填，不接受额外字段；`yes` 必须加引号避免 YAML 1.1 布尔转换。
`automatable.status` 为 yes/needs-env/manual 并附 reason。required_env 只引用根目录
preconditions.yaml。data_prep 引用 runner/knowledge/data-prep.yaml，例如 `faq.count: 5`；
没有 handler 的条目保持 TODO，不能伪造准备成功。mutation_scope 为已授权的功能名列表。
start_page 来自 page-map 的 pages；所有 target 必须是命名目标或 `?未知名字`，不接受选择器。

步骤固定 12 个动词：open/click/fill/hover/select/check/uncheck/press/upload/wait/close/assert。
输入动词必须显式 value（允许空字符串）。S 编号唯一。每条断言含唯一 A 编号、after、
excel 和非空 checks。检查使用 visible/hidden/text/contains/value/attribute/count/enabled/disabled/left_of；
attribute 另需 attribute 名；left_of 的 value 是另一个命名目标，比较实际横坐标。text 允许字符串或按顺序的字符串列表，值类型必须正确。close 后必须有 hidden 断言。
excel 必须是导入期望的整个单元格或完整非空行，包含编号、空格和标点，不做 trim/正则改写。
一个期望有多个业务子句时，用多个 checks 完整验证；生成器不会判断自然语言语义，Codex 必须审查。

`spec lint` 检查结构、跨用例相同 checks、词表及数据类型、未知目标、业务问题、fixture
导入、图标字符、弹窗 scope、重复角色名及 snapshot refs。首次 lint 结果记在 manifest，
之后修复不改首轮分母。没有 spec 的其他导入用例保持待处理，不从工作簿分母删除。
`spec gen` 输出每例一个文件；未知项抛出显式 TODO，数据准备无 handler 时不能注册为 runnable。
模板生成不运行模型。AI 修改后 lint 与执行门禁仍检查 `support/fixtures`、覆盖标记及 TODO。

coverage 从 `// @step S1` 和 `await businessAssertion('A1', ...)` 的实际行自动提取；
移动代码会重新推导，不能通过旧的手填行号满足覆盖。标记只证明结构覆盖，真实执行由 reporter
记录断言步骤。生成后用 `run-batch` 回放；缺环境保持等待，不能用降低期望取得 PASS。

`spec render` 生成 Markdown，可供人审阅或作为限定范围的 generator 输入。调用外部 Codex
一律 `timeout 2h codex exec ... < /dev/null`。快照 ref 只在会话内使用，知识回写和 lint 拒绝它。

AI 完成未知步骤后，用 `register --run ID --case CASE --file registration.json`，文件仅需 case_id/script；其 fixture、变更声明和 coverage 从 case-spec 与代码标记推导。交付包携带不含认证信息的 cases.json 投影，重新配置环境/登录即可消费同一 fixture。


禁用态是已有的 `checks.op: disabled/enabled`，模板生成 `toBeDisabled/toBeEnabled`，同时支持原生和 aria-disabled。
blocked / cannot save / 无法保存 / 置灰 / 不可用 等期望必须包含 disabled 检查。
静态禁用态用 `verb: assert` 观察，不点击、不强制派发；保存中的初始提交可以先 click 再观察禁用。
TC-0048 保留空字符串及纯空格，不把禁用态代替 Excel 要求的错误文案和弹窗状态。

## Phase 4：远程文件、请求时序与 FAQ

完整文件协议见 [remote-checks.md](remote-checks.md)。`defer_public` 关联带 `resource` 的 page-map 目标，断言用 `remote_file`，条件支持 contains、equals、按指定二级标题截取的 ordered_pairs。`excel` 原文不能改写。本机脚本用 `// @deferred A2` 标识交接覆盖；该断言不记为本机 PASS。远程等待期间数据保留，最终回执后恢复核验；清理 pending 不能计通过。

网络规则在 `assets/playwright-runner/knowledge/network.yaml`，page-map 的 `network_rule` 引用该规则，不在用例中放 URL/定位器。`network_delay` 的字符串 value 为 1..30000 毫秒；使用 Playwright route 按 method/path 匹配、计数和延迟。`network_release` 释放同一规则。脚本 finally 释放并移除规则，避免污染清理。`request_count` 核验精确请求数。`double_click` 为物理双击，第二击仍落在同一位置；`attempt_click` 为真实指针尝试，用于核验处理中取消、关闭被阻止。不会 force-click 或绕过 DOM 禁用状态派发事件。

`visible_text` 核验控件实际显示的文字，适合内部同时存在隐藏“保存”和显示“保存中…”节点的按钮。`observe` 在操作前安装观察器，`occurrence_count` 检查提示全程可见出现次数，提示消失后仍可验证；不会用已消失 toast 的当前 DOM 数量冒充全程计数。

`faq.count` 使用可恢复 FAQ 准备器：完整快照原始条目 ID、列表顺序、分类/时间元数据、答案文字与 HTML；增加当前 owner 的条目达到 N，重读验证；恢复时只删除 owner 新增项，再比较原始快照哈希。分页不完整或 N 小于既有条数时在变更前明确拒绝，不能删除原始记录冒充精确恢复。当前真实样本从 1 条增至 5 条再恢复。富文本有两层子 iframe，page-map 保留实际结构，不保留会话 ref。

FAQ 创建使用实测成功的 `faq.create` 表单接口（网络目录记录方法、路径和字段名），每次读取当前添加表单并保留其站点及保护字段，仅在内存内覆盖本次问题/答案后提交；不记录或传出保护字段值。拒绝带既有记录 ID 的创建表单，避免覆盖原记录。创建后仍由真实 FAQ 管理页重新读取数量、内容及顺序。该接口仅用于可恢复的数据准备，业务断言仍使用编辑器实际保存和远程公开文件。
