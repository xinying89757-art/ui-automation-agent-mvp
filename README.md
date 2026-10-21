# Excel UI Automation for Codex

在 Codex 中提供 Excel 测试用例和环境信息，由项目技能组织意图准备、资产匹配、
页面探索、分批执行、有限修复和稳定性验证，交付可以独立运行的 Playwright 工程。

**当前状态：正式版后台已用 llms.txt 用例真实跑通。** 后台和编辑器预检必须通过；
公开前台不可达只阻断会读取公开页的用例。站点域名要带 `http://` 或 `https://`，
裸域名会探测可达协议，探测失败时才沿用环境入口的协议。

公开仓库包含工作流实现、通用模板、三环境默认入口与代理配置、完整灰度 PAC 和检查脚本。本地产品资料 `ui-knowledge/`、
`automation-assets/` 与 `cases/TC_PD_001/` 含环境地址和产品专属信息，仅保留在原机器上，
没有上传。使用时请导入自己的用例并建立对应的 UI Knowledge 和 Automation Assets。

## 在 Codex 中使用

在本目录打开 Codex，用自然语言描述：

> 使用 $uia-orchestrator，把 `/path/to/需求测试用例.xlsx` 转成 UI 自动化。
> 使用灰度环境，目标网站 `en.example.com`，账号配置使用 `my-gray`。必要时集中询问我，其余步骤自动继续。

继续已有任务：

> 使用 $uia-orchestrator，继续运行 REQ-001，先告诉我已完成数量和需要我处理的问题。

`.agents/skills/` 内包含全部项目技能。`skills/` 中的旧入口是迁移说明。
现有四个技能的 schema、模板和必要脚本也已纳入项目，无需本机全局技能。

## 环境准备

Python 3.9+、Node.js 22+。一次装好虚拟环境、PyYAML/openpyxl 和锁定的 Playwright：

```bash
bash scripts/bootstrap.sh
source .venv/bin/activate
python3 scripts/uia.py env list
python3 scripts/uia.py setup --profile my-prod --environment production --site http://en.example.test --account my-account
```

`@playwright/test` 锁定为 1.64.1，与本机已有浏览器一致，避免再下一份 Chromium。
密码通过终端隐藏输入，或使用显式指定的本地私有凭据文件。账号、密码与登录态保存在 `.auth/`，
不提交 GitHub、不写入报告或脚本包。

| 环境 | 初始入口 | 网络 |
|---|---|---|
| P 版（p） | `http://jianzhan.leadong.com/website.html` | 固定 P 版代理 |
| 灰度（gray） | `http://www.leadong.com/website.html` | 项目内完整 PAC，验证灰度响应头 |
| 正式版（production） | `https://www.leadong.com/website.html` | 强制直连 |

后台入口由环境决定，始终是 HTTPS 或环境预设的协议。目标站点是另一回事：
只给裸域名时先探测，HTTP 通而 HTTPS 不通就用 HTTP。已经写了 `http://` 或 `https://` 的地址保持原样。

```bash
python3 scripts/uia.py profile set --profile my-prod --site http://en.example.test --mutation-allowed --scope llms.txt --stability-passes 1
```

`mutation.allowed: false` 且 `scope` 为空表示只读。`scope` 是允许改动的功能名列表，
用例声明的 `mutation_scope` 必须是它的子集。`llms.txt` 表示可以在已配置的这个站点上
创建、修改、删除该功能的数据，并且必须校验清理。`--read-only` 关闭写操作。
`--stability-passes 1` 是每日交付（一次成功即可）；`2` 是夜间回归（同版本连续两批成功）。

详细配置见 [环境与公共登录](docs/environments-and-login.md)。

Codex 首次执行（需要网络安装浏览器缓存，并把提示词从标准输入关掉）：

```bash
codex exec -m gpt-6-luna -c model_reasoning_effort=high -s workspace-write \
  -c sandbox_workspace_write.network_access=true --add-dir ~/.cache --add-dir ~/.npm \
  "使用 uia-orchestrator，把用例跑完。先跑所有能跑的，再问我真正的阻断。" < /dev/null
```

## 流程与人工交互

Excel → 来源保留与业务分组 → 每条 Intent → 资产匹配 → 真实浏览器预检与探索 →
就绪用例分批运行 → 同版本第二次独立运行 → 反馈候选与结果交付。

- 导入时根据用例原文生成一份前置条件清单，只问人一次。缺权限账号、4.0 编辑器、
  全新站点、多语言/简体/小语种、根目录已有 llms.txt、未迁移站点未满足时继续等待，
  不记成 not_suitable。FAQ 条数、分类、导航、首页 Meta、网站简称、快速联系、社媒
  由夹具自己快照、设置并恢复。
- 默认每批最多 10 条。同一批复用一个编辑器会话，用例之间只收起弹窗。
- 公开 llms.txt 有大约一小时缓存。断言以重新打开编辑器读到的值为准；
  公开文件只做延后记录，并试一次带查询参数的请求，参数若不能绕过缓存就不作为失败。
- 每日 `stability_passes: 1`，一次清理成功就是交付。夜间回归改为 `2`。
- 通过的批次会自动把定位写回知识库。元素名只保留短文本，不用面板整段 innerText。
- 登录、环境/数据缺失和业务歧义进入问题队列。先把能跑的用例跑完，再集中提问。

等待一批执行时用心跳文件，不要靠 PID：

```bash
python3 scripts/uia.py wait --run REQ-001
```

大批量用例通过按流程分组、分批处理和运行清单恢复实现。所有用例都保留状态，
环境阻断或不适合 UI 自动化的用例不会被删出报告分母。

## 命令入口与产物

总控负责解释用例、探索 UI、生成代码；Python CLI 提供确定性的状态操作，**不会单独调用模型**。

```bash
python3 scripts/uia.py init --run-id REQ-001 --profile my-gray
python3 scripts/uia.py scaffold --run REQ-001
# 为 runner 安装依赖和浏览器后执行；登录成功后记录真实环境预检证据。
python3 scripts/uia.py login --run REQ-001
python3 scripts/uia.py import --run REQ-001 --excel /path/to/cases.xlsx
# The import response asks you to bind existing specs before creating new ones.
python3 scripts/uia.py bind-specs --run REQ-001
python3 scripts/uia.py preconditions --run REQ-001
python3 scripts/uia.py next --run REQ-001
python3 scripts/uia.py run-batch --run REQ-001 --cases TC-0001
python3 scripts/uia.py wait --run REQ-001
python3 scripts/uia.py status --run REQ-001
```

Use `python3 scripts/uia.py snapshot --run REQ-001 --node editor` for one-shot,
redacted page exploration. Each run links directly to `assets/playwright-runner`; its
bindings remain in run-local state. The report writes `metrics.json` at the run root and
shows it in the HTML/JSON report. Set broad editor mutation permission before `init` with
`profile set --mutation-allowed --scope '*' --editor-data-restorable`; every changed
record must have a verified restoration hook.

后续阶段的完整接口见 [接口说明](docs/interfaces.md)，阶段执行约定见 [工作流](docs/workflow.md)。

运行状态位于 `runs/<run-id>/run.json`；源用例归一记录、Intent、复用计划、脚本和运行证据
位于该运行目录。运行数据、认证状态、本地账号配置和依赖目录默认不进入 Git；三环境默认配置和灰度 PAC 随项目交付。

最终报告包括 `results.json`、`results.xlsx`、`index.html`、`scripts.zip` 和
`asset-review.json`。脚本包包含可独立运行的 Node 工程、公共登录/流程、fixtures、环境定义及完整灰度 PAC，
不包含认证状态、依赖安装目录或原始运行日志。后续运行仍需提供自己的配置与认证来源。

## 离线检查与后续验收

本轮离线验证可复现为：

```bash
node --test tests/environment-auth.test.mjs
python3 -m unittest discover -s tests -p 'test_*.py' -v
npm --prefix assets/playwright-runner run typecheck
```

静态校验及后续真实运行的校验入口：

```bash
python3 scripts/uia.py validate
python3 scripts/uia.py validate --run REQ-001
```

## 可选生成器

本仓库的日常路径是人读 Excel、直接写确定性 Playwright。下面两种生成器没有接进这次 llms.txt 实跑，
因为现有编辑器控件已经能定位，接进来不会让未覆盖用例在这一轮变成可执行规格。

- Playwright Test Agents（`npx playwright init-agents --loop=codex`，需要 Playwright 1.56+）：
  适合全新模块还没有 spec 时，用 planner/generator 起草用例。healer 只能改定位和等待；
  本仓库的 `support/heal.mjs` 会把改断言的提案标成疑似产品缺陷并且不写回 spec。
  接入方式：在 runner 里单独生成草稿，人工确认预期后放进 `tests/*.spec.ts`，再走 `bind-specs`。
- Midscene：只作为画布或视觉区域的后备。这个编辑器的预览是同源 iframe，不是 canvas，
  不需要视觉模型。遇到真正的 canvas 时，再把 Midscene 的步骤限制在那一块，断言仍用 Playwright。

重点覆盖不同 Excel 布局、跨工作表重名 ID、负向空值、公共流程复用、问题答复与恢复、
中断恢复、数据清理失败隔离，以及代码修改后成功计数重置。
