# spec-pathfinder 真实磁盘验收

验收日期：2026-10-29。结论：**技能内容、两套索引、真实静态取证 trial 及脚本行为验收通过；指定目录安装未完成（会话文件系统限制）**。未运行被测站点，未声称 TC-0008～TC-0011 本次 UI 测试通过。

## 交付位置与限制

用户指定：`/home/hatch/workspace/custom-skills/spec-pathfinder/`。

本次落盘：`/home/hatch/workspace/goals/web-ui-automation-testing/custom-skills/spec-pathfinder/`。此目录包含 SKILL.md、脚本、两个 Controller 与一个 FTL fixture、真实 trial、原文快照、两套已落盘索引、验收记录与源码指纹。

会话的开发者文件系统规则只允许写入项目目录和 `/tmp`，审批策略为 never；指定的 workspace/custom-skills 位于可写范围之外。这不是 skill-creator 要求确认，不是自动审批拒绝，也没有尝试绕过限制。压缩包位于项目的 `custom-skills/spec-pathfinder.tar.gz`；安装状态不能记为通过。

由具备目标目录写权限的终端执行以下命令可复制已验收内容（本次未执行）：

```bash
mkdir -p "$HOME/workspace/custom-skills"
cp -R /home/hatch/workspace/goals/web-ui-automation-testing/custom-skills/spec-pathfinder "$HOME/workspace/custom-skills/"
```

## 可重跑命令与实际结果

在已交付 skill 目录运行，代码路径始终是参数：

```bash
node scripts/build-index.mjs trial/fixtures --out trial/fixtures/index --force
node scripts/build-index.mjs /home/hatch/workspace/goals/web-ui-automation-testing/files/phoenix-llms-evidence --out trial/real/index --force
python3 scripts/read-cases.py /home/hatch/workspace/user/files/llms.txt_--____--.xlsx --sheet 测试用例 --ids TC-0008 TC-0009 TC-0010 TC-0011 --out trial/real/cases-source.md
python3 trial/verify.py --code-root /home/hatch/workspace/goals/web-ui-automation-testing/files/phoenix-llms-evidence --history-root /home/hatch/workspace/goals/web-ui-automation-testing/files/historically-passed-scripts/suites/llms-txt --xlsx /home/hatch/workspace/user/files/llms.txt_--____--.xlsx
```

以上命令已在项目内交付目录对应路径实际执行。机器为 Node v24.22.1、Python 3.12.3；脚本只用标准库，建索引不需要 Maven、浏览器、网络或额外 npm 安装。验收程序的命令、退出码及 stdout/stderr 完整落盘于 [acceptance-results.json](acceptance-results.json)；其中临时目录路径为隔离变更测试，结束后已删除。

| 数据集 | 扫描文件 | 路由条数 | 元素候选数 | 动作候选数 | 冷建解析 | 暖缓存解析 / 复用 |
| --- | --- | --- | --- | --- | --- | --- |
| fixtures（恰为 2 Controller + 1 FTL） | 3 | 6 | 6 | 4 | 3 | 0 / 3 |
| 真实 Phoenix 证据（1 Controller + 2 JSP + 1 JS） | 4 | 8 | 74 | 8 | 4 | 0 / 4 |

每套的 `routes.json`、`template-elements.json`、`actions.json` 与 `.cache.json` 均为磁盘实文件。验收程序逐个读取 JSON 并核验关键内容，不能用 stdout 计数代替落盘验收。真实动作 8 条含后端候选 5 条与 JS 请求 3 条；只读 createPop 也会被方法名启发式收入候选，不据此编译写动作。

已实际通过的行为：

- 类/方法路径组合、路径数组、HTTP 方法、视图字符串与类内常量、注释内假路由排除；字符串中的花括号不破坏方法边界。
- fixture 元素的 id、data-testid、字段与真实来源行号；真实正常模板 `.llms-switch` 与错误模板 `#llmsEnabled` 分开入索引。
- 真实保存端点为 POST `/phoenix/customizeFile/llms/save`，Controller 返回类型 void；实际成功字段经 successBody 可追到 `status=success`，JS 请求块关联到 status 检查与两段 toast 回退文字。
- 缓存暖跑全部复用；只改 mtime 仅重新解析该文件；改内容后的路由变化、新增文件、删除文件、输出缺表重建、代码根切换、坏缓存回退均正确。删除的文件不保留旧索引记录。
- 动态拼接路径、混合常量数组、Java 非字面量 value 和 JS 动态 URL 记为 null 并给出 warnings，未伪造 `/prefix` 等静态 endpoint；坏参数/不存在代码目录返回非零退出码。
- 真实 Excel 四条用例全部来自 inlineStr；明确选择「测试用例」。两张工作表的目标行 A:I 逐格一致，历史结果列分开保留，不升级为本次实测。额外自造 OOXML 小样覆盖 sharedStrings、富文本 inlineStr、普通字符串、公式缓存。
- 真实规格中的 53 个完整文件名行号引用均在实际文件行数范围内；简写的同文件 `:行号` 与语义另经人工读源码复核，范围校验本身不能证明语义。

## 技能校验与五步自查

执行了系统 skill-creator 提供的校验器：

```bash
python3 /home/hatch/.codex/skills/.system/skill-creator/scripts/quick_validate.py /home/hatch/workspace/goals/web-ui-automation-testing/custom-skills/spec-pathfinder
```

实际结果：`Skill is valid!`，退出码 0。SKILL.md 的 YAML frontmatter 包含 `name: spec-pathfinder` 与中文 description；本校验器是此次验收工具，不是技能运行依赖。另检查本地 Markdown 链接可达、脚本可运行、无未完成脚手架占位。

| 简报要求 | 已交付证据 |
| --- | --- |
| 受控自然语言，固定字段、可读可改 | SKILL.md 定义格式并有完整 fixture 示例；real/SPEC.md 的每一步含操作、定位依据、预期、证据出处、置信度，另有前置条件与清理 |
| 五步无断点 | real/SPEC.md 依次给出意图表、索引、源码消解、11 步规格、6 项具体存疑；Excel 原文另落盘 |
| 代码 > 用例 > 设计推断 > AI 推测 | SKILL.md 固定分层；历史脚本仅旁证；Excel 引用外部设计未伪称本次已读 |
| 不编造 | 未猜正常模板 id、入口 URL、toast 选择器、真实域名、service 行号；动态表达式不静态补 URL |
| 探索前移，执行时无探索 | 编译时固定作用域/唯一性/失败处置；执行匹配漂移则报告回编译；环境参数先绑定 |
| 任何智能体可跑 | Markdown + 普通文件读写，Node 无依赖索引器和 Python 标准库可选抽取器；不用专属 agent API |
| MVP 不扩张 | 输入仅 Excel 与代码，历史脚本旁证；保留需求/原型接口但未调用设计工具或解析新需求文档 |
| 真实证据替代 Mac 离线假设 | 使用已就位的四文件，确认正常/错误视图分支、DOM 与保存成功链路；仅缺失模块标待代码取证 |
| 编辑器边界 | SKILL.md 明确不反解 tiptap 构建 chunks，缺口为「需历史脚本/人工补充」 |

## 高置信度逐项审计

真实规格共 11 步，其中 9 步包含**限定范围的代码实证高置信事实**，其它行为分别标中；没有把任何整条端到端链路标高，没有低置信硬断言。9 处高置信事实均可对应下表实际代码；存疑清单共 Q-1～Q-6，不为空。下表文件位置按 real/SPEC.md 的证据坐标映射。

| 步骤 | 高置信范围 | 实际代码核验 |
| --- | --- | --- |
| TC-0008 / 1 | 配置 API 和正常表单挂载分支 | phoenix_function_llms_txt.js:67、:73、:74、:75；PhoenixCustomizeFileController.java:352 |
| TC-0008 / 2 | data-enabled 和开关/配置控件声明 | llms_tab.jsp:4、:13、:17、:21、:22 |
| TC-0009 / 1 | 开关声明与 setEnabled/refresh 回调 | llms_tab.jsp:13；phoenix_function_llms_txt.js:148、:150、:151 |
| TC-0009 / 2 | 当前回调没有 save AJAX，save AJAX 在单独 save 方法中 | phoenix_function_llms_txt.js:148～:152、:201、:208（仅此局部事实，不推广到缺失 view 模块） |
| TC-0010 / 1 | POST、enabled 参数、关闭分派、success 字段 | PhoenixCustomizeFileController.java:385、:387、:397、:398、:411、:477 |
| TC-0010 / 2 | 成功回调的关闭回退文案与 close 调用 | phoenix_function_llms_txt.js:216、:220、:224、:225、:143 |
| TC-0010 / 4 | 配置读取及字段到视图的映射 | PhoenixCustomizeFileController.java:339、:342、:456、:459、:460、:468 |
| TC-0011 / 1 | 模板控件与 toggle 回调 | llms_tab.jsp:13、:17；phoenix_function_llms_txt.js:148、:150、:151 |
| TC-0011 / 2 | 开启保存分支和 success 回调 | PhoenixCustomizeFileController.java:403～:411、:477；phoenix_function_llms_txt.js:216、:220、:224 |

默认开启、默认 Tab、切换后的显隐与文案、无二次确认、颜色图标、404、原配置保留、公开文件恢复没有被这些局部代码事实连带升级为高。缺服务层、view/rules、样式和国际化等材料已经各自说明补证方式与执行降级，不虚标「整条链路待代码取证」。

## 验收范围

索引器采用正则/轻量词法解析，提供候选证据导航，不能替代 Java AST、模板渲染和运行验证；跨文件常量、继承/组合注解、复杂 JSP 标签与动态 JS 仍需按需取证。缓存依赖 mtime 与大小；刻意保持二者不变的文件替换需 `--force`。

本轮通过的是离线编译与磁盘行为验收。UI 执行所需环境参数、9 处局部高置信范围以外的运行效果，以及指定安装目录的写入，仍分别受 real/SPEC.md 的条件和本页文件系统限制约束。

## 两阶段编译与双层输出增量验收（2026-10-29）

本次以已通过 v1 验收的目录为基线增量修改。开始前逐文件比较指定目录与项目内可写副本，20 个文件内容全部一致。原有五步流程、agent 执行版固定字段模板、索引器、Excel 抽取器和真实技术规格均保留；未重新初始化或重写技能。

修改 `SKILL.md`，新增 `real/SPEC-human.md` 与 `real/SPEC-evidence.md`，并在本文件末尾追加本次验收。除技能说明和本验收记录外，原有 18 个文件逐字节不变；本文件原有内容完整保留。

### 两阶段规则完整性

| 验收项 | 实际核对结果 |
| --- | --- |
| 提测前输入与目标 | Excel 加可用需求文档、原型或设计稿，三种材料不要求齐备；探出页面入口、点击对象、顺序与断言，不追求精确定位 |
| 无代码置信度上限 | 所有步骤和原子主张最高为中，不得标高；低置信推测移入存疑清单 |
| 提测前交付 | 人审版 v1、存疑清单 v1；已读材料出处保存在清单的独立证据附录区，供人审引用与后续对账 |
| 提测后输入与取证 | v1 产物加项目代码，运行 build-index.mjs 后读取实际代码；默认 Mac 同步代码版本等于提测版本，记录版本标识或源码指纹 |
| 逐条处置 | v1 每条中置信断言均升级为高或打回；拆分复合主张，打回项说明证据不足或冲突原因并进入存疑清单，不连带升级整步 |
| 提测后交付 | 人审版 v2、agent 执行版 v2、按步骤编号的证据附录、每条一句话的 v1→v2 升级/打回记录，并同步存疑清单 |

以上为逐项阅读技能规则的结果。本次没有新建无代码需求 trial，也没有真实提测前 v1 可供补证，因此不声称已完成一轮真实 v1→v2 编译，不倒造升级记录。

### 双层输出与样例检查

- 人审版覆盖 TC-0008～TC-0011 全部 4 条用例、11 个步骤，以及公共约定、前置条件、清理和 6 项存疑说明。
- 全文人工通读并扫描：接口名/路径、源码文件及行号、定位器、CSS 类名、方法名、变量及响应字段等代码串为 0；没有反引号代码或代码块。仅保留用例/存疑/附录编号，以及界面名称与提示中的“管理txt文件”和“llms.txt”，这些属于用户可见原文。
- 人审版 32 处证据引用全部能对应附录中的 32 个独立条目：7 项公共证据、11 个步骤、4 组前置及清理、6 项存疑。没有悬空引用或未引用条目。附录各步骤的技术定位、预期、证据及置信度逐行对应原技术规格。
- 人审版与执行版逐步核对顺序、操作对象、预期、清理和降级要求。9 个步骤保留限定范围的高置信代码事实，另外 2 个步骤仅中置信；所有实际页面效果的中置信限制继续保留。未将颜色图标、文件移除、配置保留、公开文件恢复等连带升级为高。
- 原执行版固定字段模板逐字保持一致。原技术规格、脚本、索引、原文快照保持不变；来源清单中的 9 个文件指纹与现有文件一致。技能与附录的本地链接均可解析。

本轮实际执行：

```bash
python3 /home/hatch/.codex/skills/.system/skill-creator/scripts/quick_validate.py /home/hatch/workspace/goals/web-ui-automation-testing/custom-skills/spec-pathfinder
python3 /tmp/check-spec-pathfinder-update.py
```

两条命令均退出 0；技能校验结果为 `Skill is valid!`。第二条是本轮临时核验脚本，实际核验全文代码串、用例/步骤与高/中范围对应、32 处证据引用、附录证据保真、原文件不变性、来源指纹及本地链接；规则含义与自然语言改写准确性另经人工阅读核对。本次只改说明和样例，未改脚本，因此未重复运行 v1 索引器全量回归，也未运行被测网站或声称 UI 验收通过。

本轮交付仍位于项目内可写副本。指定的 `~/workspace/custom-skills/spec-pathfinder/` 在当前会话允许写入范围之外，未直接修改；本轮更新包为项目内 `custom-skills/spec-pathfinder.tar.gz`，另提供 `custom-skills/spec-pathfinder-v2-update.patch` 供查看四个文件的增量。指定目录同步状态仍为未完成，原因与前述会话文件系统限制相同。
