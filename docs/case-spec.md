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
