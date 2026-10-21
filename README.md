# Excel UI Automation for Codex

在 Codex 中提供 Excel 测试用例和环境信息，由项目技能组织意图准备、资产匹配、
页面探索、分批执行、有限修复和稳定性验证，交付可以独立运行的 Playwright 工程。

**本次改造状态：实现已交付，未验收。** 未安装依赖或浏览器，未运行静态校验命令、
测试套件、本地模拟流程或真实用例。

公开仓库只包含工作流实现和通用模板。本地产品资料 `ui-knowledge/`、
`automation-assets/` 与 `cases/TC_PD_001/` 含环境地址和产品专属信息，仅保留在原机器上，
没有上传。使用时请导入自己的用例并建立对应的 UI Knowledge 和 Automation Assets。

## 在 Codex 中使用

在本目录打开 Codex，用自然语言描述：

> 使用 $uia-orchestrator，把 `/path/to/需求测试用例.xlsx` 转成 UI 自动化。
> 环境配置使用 `config/uia.local.yaml`。必要时集中询问我，其余步骤自动继续。

继续已有任务：

> 使用 $uia-orchestrator，继续运行 REQ-001，先告诉我已完成数量和需要我处理的问题。

`.agents/skills/` 内包含全部项目技能。`skills/` 中的旧入口是迁移说明。
现有四个技能的 schema、模板和必要脚本也已纳入项目，无需本机全局技能。

## 环境准备

Python 3.9+、Node.js 22+。以下命令供后续使用，本次改造未执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp config/uia.example.yaml config/uia.local.yaml
```

编辑配置中的 public/admin 等目标地址、认证状态引用、所需 secret 环境变量名和数据规则。
修改业务数据的用例需配置 `mutation.allowed` 与具体操作范围；默认关闭。
示例地址使用 `.invalid`，必须替换。凭证值通过当前进程的环境变量提供。

技能初始化运行并生成 runner 后，在对应工程中安装锁定依赖和浏览器：

```bash
cd runs/REQ-001/runner
npm ci
npx playwright install chromium
```

Windows 使用对应的虚拟环境激活命令及 Python 启动命令。Playwright 可能需要操作系统浏览器依赖。

## 流程与人工交互

Excel → 来源保留与业务分组 → 每条 Intent → 资产匹配 → 真实浏览器预检与探索 →
就绪用例分批运行 → 同版本第二次独立运行 → 反馈候选与结果交付。

- 默认每批最多 10 条，不限制总条数；先运行就绪用例，再探索能解锁更多用例的流程。
- 默认单 worker；公共流程探索 10 分钟、每个缺口两种策略、自动化失败最多两轮修复。
- 登录、环境/数据缺失、业务歧义和探索耗尽进入集中问题队列；独立用例继续推进。
- 首次成功标记 `candidate`；相同版本两次独立成功并验证清理后标记 `stable`。
- 报告分别展示执行覆盖率、已执行用例通过率、全部用例稳定率，以及人工等待和探索耗时。

大批量用例通过按流程分组、分批处理和运行清单恢复实现。所有用例都保留状态，
环境阻断或不适合 UI 自动化的用例不会被删出报告分母。

## 命令入口与产物

总控负责解释用例、探索 UI、生成代码；Python CLI 提供确定性的状态操作，**不会单独调用模型**。

```bash
python3 scripts/uia.py init --run-id REQ-001 --config config/uia.local.yaml
python3 scripts/uia.py import --run REQ-001 --excel /path/to/cases.xlsx
python3 scripts/uia.py next --run REQ-001
python3 scripts/uia.py status --run REQ-001
```

后续阶段的完整接口见 [接口说明](docs/interfaces.md)，阶段执行约定见 [工作流](docs/workflow.md)。

运行状态位于 `runs/<run-id>/run.json`；源用例归一记录、Intent、复用计划、脚本和运行证据
位于该运行目录。运行数据、认证状态、环境配置和依赖目录默认不进入 Git。

最终报告包括 `results.json`、`results.xlsx`、`index.html`、`scripts.zip` 和
`asset-review.json`。脚本包包含可独立运行的 Node 工程、公共流程和 fixtures，
不包含认证状态、依赖安装目录或原始运行日志。后续运行仍需提供自己的配置与认证来源。

## 后续验证

本轮没有执行下列检查。后续可先静态校验项目技能，再用真实 Excel 和授权环境验证：

```bash
python3 scripts/uia.py validate
python3 scripts/uia.py validate --run REQ-001
```

重点覆盖不同 Excel 布局、跨工作表重名 ID、负向空值、公共流程复用、问题答复与恢复、
中断恢复、数据清理失败隔离，以及代码修改后成功计数重置。
