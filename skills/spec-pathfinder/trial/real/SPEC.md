# TC-0008～TC-0011 操作路径补全（真实静态取证 trial）

本次完成 Excel 抽取、真实代码取证、历史脚本对照及规格编译，未启动被测站点、未运行 UI 用例。以下「预期」是待执行的断言，不是本次测试结果。当前状态为**条件可执行**：环境参数须在执行前由测试环境提供者绑定；存疑项明确限定无法由现有代码证明的部分。

## 输入与证据坐标

- Excel：`/home/hatch/workspace/user/files/llms.txt_--____--.xlsx`；主表「测试用例」的 A9:J12，对应 TC-0008～TC-0011。原值与 SHA-256 在 [cases-source.md](cases-source.md)。
- 工作簿还有「测试用例-研发自测」，目标行 A9:I12 与主表一致；它的 K 列为历史验证结果，主表 J 列为历史自动化状态。两者都不是本次运行证据。主表 H 列提及设计稿/需求文档，本次只将这些内容作为用例原文读取，未访问外部设计稿。
- 代码根：`/home/hatch/workspace/goals/web-ui-automation-testing/files/phoenix-llms-evidence/`；只有 TtnSmartBw 的四个证据文件，并非完整 Phoenix 工程。
- 历史根：`/home/hatch/workspace/goals/web-ui-automation-testing/files/historically-passed-scripts/suites/llms-txt/`。

下文 `文件名:行号` 均采用以下真实映射，行号按磁盘文件从 1 起算；源码哈希与行数见 [sources-manifest.json](sources-manifest.json)。

| 文件名 | 相对根目录的文件路径 |
| --- | --- |
| PhoenixCustomizeFileController.java | 代码根下 `TtnSmartBw/src/main/java/com/focustech/subsys/smart/web/controller/phoenix/PhoenixCustomizeFileController.java` |
| llms_tab.jsp | 代码根下 `TtnSmartBw/src/main/webapp/WEB-INF/jsp/phoenix_jsp/customizeFile/llms_tab.jsp` |
| llms_config.jsp | 代码根下 `TtnSmartBw/src/main/webapp/WEB-INF/jsp/phoenix_jsp/customizeFile/llms_config.jsp` |
| phoenix_function_llms_txt.js | 代码根下 `TtnSmartBw/src/main/webapp/assets/script/phoenix/pagefunc/phoenix_function_llms_txt.js` |
| txt-manager-page.mjs | 历史根下 `src/txt-manager-page.mjs` |
| live-fixtures.mjs | 历史根下 `src/live-fixtures.mjs` |
| live-p0.test.mjs | 历史根下 `test/live-p0.test.mjs` |
| live-extended.test.mjs | 历史根下 `test/live-extended.test.mjs` |

## 1. 意图解析

| 用例 / 原文坐标 | 待消解动作 | 在哪？ | 怎么操作？ | 什么算对？ |
| --- | --- | --- | --- | --- |
| TC-0008 / E9:G9、I9 | 新站首次打开、读横幅与配置区 | 3.0 编辑器管理 txt 弹窗 | 设置入口 → 管理txt文件；不主动切 Tab | 默认 llms.txt 页签、开启文案、蓝色闭锁、配置显示 |
| TC-0009 / E10:G10、I10 | 关闭草稿但不保存、访问公开页 | 当前配置表单 + 公开 `/llms.txt` | 切换开关；另页读取 | 关闭文案、灰色闭锁、配置隐藏；公开内容不变 |
| TC-0010 / E11:G11 | 关闭并保存、查公开页、再打开配置 | 保存接口 + 公开页 + 配置片段 | 开关 → 保存 → 重开 → 暂开 | 无二次确认、关闭成功提示、弹窗关闭、404、配置保留 |
| TC-0011 / E12:G12 | 从已关闭配置重新启用并保存 | 同一弹窗、同一站点公开页 | 开关 → 保存 → 公开页 | 原配置回显、保存成功提示、文件按原配置恢复 |

## 2. 索引结果与路由消解

真实运行索引器得到：8 条路由、74 个模板元素候选、8 条动作候选；其中 5 条为后端候选（包含方法名启发式命中的只读编辑入口），3 条为 JS 请求。磁盘三表位于 [index/routes.json](index/routes.json)、[index/template-elements.json](index/template-elements.json)、[index/actions.json](index/actions.json)。候选数不等于可执行步骤数。

- `GET /phoenix/customizeFile` → managePop → `phoenix_jsp/customizeFile/manage_pop`。证据：`PhoenixCustomizeFileController.java:44`、`:76`、`:81`。管理弹窗模板本体不在这批证据中。
- `GET /phoenix/customizeFile/llms/config` → loadLlmsConfig。正常分支返回常量 LLMS_CONFIG_VIEW，对应 `phoenix_jsp/customizeFile/llms_tab`；错误捕获分支返回 LLMS_CONFIG_ERROR_VIEW，对应 `llms_config`。证据：`PhoenixCustomizeFileController.java:47`、`:48`、`:334`、`:345`、`:350`、`:352`。
- `POST /phoenix/customizeFile/llms/save` → saveLlmsConfig，返回类型 void，实际用 renderJson 输出；不能凭 void 判断没有响应。关闭分支调用 saveDisabledConfig，开启分支调用 saveLlmsConfig，完成后返回 successBody。证据：`PhoenixCustomizeFileController.java:385`、`:397`、`:398`、`:408`、`:411`、`:475`、`:477`。
- JS 的 API.config/API.save 及请求方法与上面对应。证据：`phoenix_function_llms_txt.js:8`、`:66`、`:67`、`:68`、`:208`、`:209`、`:210`。

## 3. 按需取证结论

正常表单在 `.llms-form` 上输出 data-enabled/data-source（`llms_tab.jsp:4`、`:5`），开关为 `.llms-switch`（`:13`），配置容器为 `.llms-fields`（`:17`），内容来源为 `name=llmsSource` 的 system/custom 单选（`:21`、`:22`）。网站概述 `.llms-overview` 在 `:30`，扩展字段 `.llms-extra-name`/`.llms-extra-value` 在 `:42`、`:43`，自定义正文 `.llms-custom-content` 在 `:63`。这些元素直接存在是高置信事实；当前显隐、点击后文案和样式由未提供的 view 模块/CSS 决定，不能一并标高。

虽 `llms_config.jsp:14` 有 `#llmsEnabled`，正常链路不能用它替换 `.llms-switch`。错误捕获分支还设置 llmsErrorCode，因此该模板的普通 checkbox 分支不能证明当前成功加载链路会走到它。证据：`PhoenixCustomizeFileController.java:349`、`:350`；`llms_config.jsp:5`、`:6`、`:11`、`:14`。

切换回调只调用 setEnabled 和 refresh（`phoenix_function_llms_txt.js:148`、`:149`、`:150`、`:151`），保存 AJAX 在另一个 save 方法（`:201`、`:208`）。这直接证明本回调内没有 save AJAX；view/rules 模块内部实现未提供，故「整个点击过程绝无持久化」仍是有用例和历史脚本支持的中置信验收目标。

保存成功分支检查 `response.status == 'success'`，按 config.enabled 选择两段回退提示，700ms 后调用 close；close 中调用 dialog.close。证据：`phoenix_function_llms_txt.js:216`、`:218`、`:219`、`:220`、`:222`、`:224`、`:225`、`:142`、`:143`。高置信仅覆盖这些代码路径。国际化可以覆盖回退提示（`:15`、`:16`），showToast 的 DOM 节点和服务层移除/恢复文件效果不是这些代码能证明的事实。

## 4. 受控自然语言规格

### 公共前置条件、定位约定和恢复方式

前置条件：执行前绑定 `EDITOR_URL`（已登录且有网站设置权限的 3.0 编辑器）、`SITE_REF`（唯一站点标识）、`PUBLIC_BASE_URL`（该站点公开域名），固定语言为中文。不得从历史配置的示例域名推测真实环境。出处：各用例前置条件及 `txt-manager-page.mjs:10`、`:14`；`live-fixtures.mjs:75`、`:77`。置信度：中（环境尚未验证，疑问 Q-1）。

前置条件：TC-0008 使用独立的新站 N；TC-0009～0011 使用测试站 S，已保存有效配置且无根目录同名冲突。执行编译好的恢复链路前，读出 S 的基线 B：enabled、source、overview、customContent、按顺序的扩展字段 name/value；公开页记录状态及原始正文 P。保持站点内容无并发变化，系统生成模式恢复时按 B 对应内容校验，避免以其它内容变更误判。出处：Excel「测试用例」!E9:E12；`txt-manager-page.mjs:93`、`:94`、`:95`、`:96`、`:97`、`:98`、`:99`、`:100`、`:101`。置信度：中（前置数据尚未提供，Q-1、Q-6）。

定位依据：打开 EDITOR_URL 后，点击唯一可见 `.backstage-siteTool-setting > .backstage-siteTool-inner`；再点击唯一可见、规范化文本为「管理txt文件」的链接；等待唯一可见 `.customize-file-content`。证据出处：`txt-manager-page.mjs:7`、`:10`、`:11`、`:14`、`:15`、`:18`、`:23`、`:35`、`:36`、`:40`。置信度：中（历史入口旁证，入口模板待代码取证，Q-2）。多匹配或零匹配停止该用例并回报，不复制历史脚本的 first/force/重试点击。

定位依据：后续所有 `.llms-*` 表单定位均限定在上述可见容器中；固定控件预期唯一一个，扩展字段按 B 的行数与顺序比对，排除 `.llms-extra-template` 隐藏模板。保存按钮在唯一可见 `.customize-file-footer .customize_file_llms_save`；关闭不保存使用唯一可见 `.backstage-dialog-close.customize_file_manage_close`。证据出处：`llms_tab.jsp:39`、`:40`、`:41`、`:42`、`:43`、`:51`；`txt-manager-page.mjs:72`、`:73`、`:76`、`:77`、`:80`、`:81`。置信度：高（表单元素声明）；中（容器、保存/关闭按钮及运行时唯一性，Q-2）。

等待约定：一般 UI/保存响应等待上限 20 秒；公开页最多 6 次、间隔 1 秒，复用同一已绑定站点域名，使用标准浏览器或 HTTP 客户端禁用缓存，不自行推断新域名。来源：`txt-manager-page.mjs:130`、`live-fixtures.mjs:87`、`:88`、`:89`；禁用缓存为本次编译采用的执行策略，并非产品 SLA。若超时，记录实际结果与诊断信息后停止，不扩大探索。公开页定位固定为 `PUBLIC_BASE_URL` 的根路径 `/llms.txt`；来源：`live-fixtures.mjs:75`、`:77`。置信度：中（历史策略及当前编译约定）。

保存观察约定：点击前开始记录 POST `/phoenix/customizeFile/llms/save` 响应及页面提示；要求响应业务字段 `status=success`，HTTP 200 单独不作成功依据。可通过无障碍树/可见文本观察提示，不为 toast 编造专属 DOM 选择器。中文原文作为用例验收目标；若国际化覆盖与原文不同，记录差异交回裁决。证据出处：`PhoenixCustomizeFileController.java:411`、`:477`；`phoenix_function_llms_txt.js:216`、`:218`、`:220`。置信度：高（代码分支/回退文字）；中（实际渲染文字，Q-5）。

清理约定：TC-0008 无写入，直接关闭；TC-0009 关闭未保存弹窗；TC-0010/0011 结束后按 B 恢复。恢复动作：重开弹窗，必要时临时开启以便填值；按 B.source 选择 `.llms-source-system` 或 `.llms-source-custom`，回填 B 的当前模式内容及扩展字段，再按 B.enabled 调回状态并点击保存，检查 success，重开比较配置及公开页。添加/移除扩展字段使用 `.llms-add-field`/可见字段行内 `.llms-remove-field`，值用 `.llms-extra-name`/`.llms-extra-value`；不得点击隐藏模板。证据出处：`llms_tab.jsp:21`、`:22`、`:30`、`:36`、`:42`、`:43`、`:44`、`:63`；`live-fixtures.mjs:44`、`:55`、`:56`、`:57`、`:58`、`:60`、`:61`、`:62`、`:63`、`:66`、`:67`。置信度：高（表单控件声明）；中（恢复流程及数据保留，Q-6）。恢复失败单独记录，不能伪报已恢复。

### TC-0008：新站点首次打开 llms.txt 页签显示默认开启状态

状态：条件可执行（Q-1、Q-2）；视觉细项隔离（Q-3）。

前置条件：新站 N 从未修改 llms.txt 配置，满足公共登录/站点条件。证据出处：Excel「测试用例」!E9；置信度：中（仅原文约束，默认值服务未提供）。

步骤 1：

- 操作：按公共入口打开「管理txt文件」，不主动选择页签；等待 GET `/phoenix/customizeFile/llms/config` 完成并出现 `.llms-form`。
- 定位依据：公共入口、可见 `.customize-file-content` 内唯一 `.llms-form`；配置响应应来自正常 llms_tab 视图。
- 预期：弹窗默认停留 llms.txt 页签；有正常表单、未显示加载错误。不通过主动点击页签来掩盖默认页签错误。
- 证据出处：Excel「测试用例」!F9、G9；`phoenix_function_llms_txt.js:64`、`:67`、`:73`、`:74`、`:75`；`PhoenixCustomizeFileController.java:352`；`txt-manager-page.mjs:18`。
- 置信度：高（配置接口与挂载分支）；中（默认页签及打开流程，Q-2）。

步骤 2：

- 操作：只读横幅与下方配置，勿切开关。
- 定位依据：`.llms-form` 的 data-enabled；其中 `.llms-switch`、`.llms-fields`、`input[name="llmsSource"]` 及当前模式配置区。
- 预期：data-enabled 为 true，开关内显示「开启」，内容来源与配置区可见。蓝色闭锁图标要求引用 Q-3，当前不生成精确 CSS/像素断言；不添加独立状态徽章断言（Excel I9 裁决）。
- 证据出处：`llms_tab.jsp:4`、`:8`、`:10`、`:13`、`:17`、`:21`、`:22`；Excel「测试用例」!G9、I9；`live-p0.test.mjs:32`、`:39`、`:40`。
- 置信度：高（上述 DOM 属性和控件声明）；中（默认 true、可见性与中文文案）；颜色/具体图标渲染待代码取证，见 Q-3。

清理：关闭且不保存，保持新站首次配置状态；依据公共清理约定（中）。

### TC-0009：关闭开关即时隐藏配置但未保存前不改变公开文件

状态：条件可执行（Q-1、Q-2）；视觉细项隔离（Q-3）。

前置条件：站 S enabled=true 且已保存，公开地址能读到 P，按公共约定记录 B。证据出处：Excel「测试用例」!E10；`live-extended.test.mjs:158`、`:159`、`:160`。置信度：中。

步骤 1：

- 操作：打开弹窗；确认当前为开启后点击 `.llms-switch` 一次，不点保存。
- 定位依据：公共容器内唯一 `.llms-switch`，直接来自正常模板；配置显隐观察 `.llms-fields`，不能只测系统模式专属区。
- 预期：开关显示「关闭」，配置区隐藏，data-enabled 反映关闭草稿；回调执行 setEnabled(false) 与 refresh。灰色闭锁图标引用 Q-3，隔离视觉断言。
- 证据出处：`llms_tab.jsp:4`、`:13`、`:17`；`phoenix_function_llms_txt.js:148`、`:149`、`:150`、`:151`；Excel「测试用例」!F10、G10、I10；`live-extended.test.mjs:162`、`:163`。
- 置信度：高（开关存在、本回调调用关系）；中（文字、data-enabled 更新和显隐效果，view 模块待代码取证）。

步骤 2：

- 操作：保持弹窗未保存，在另一页读取同一 `/llms.txt`，比较状态码和完整正文与 P。
- 定位依据：公共公开页地址约定；同时记录本次切换期间是否出现保存接口请求。
- 预期：公开文件仍与 P 相同，不发生持久化保存。历史脚本只比了前后状态码，不能把历史通过当作已验证正文相同；本次待执行规格明确补上正文比较。
- 证据出处：Excel「测试用例」!F10、G10；`phoenix_function_llms_txt.js:148`、`:150`、`:151`、`:201`、`:208`；`live-extended.test.mjs:160`、`:164`、`:166`。
- 置信度：高（当前控制器回调未包含保存请求）；中（整个模块无其它持久化副作用、公开正文不变，Q-4、Q-6）。

清理：关闭未保存弹窗，再打开核对仍为 B；不点击保存；依据 `txt-manager-page.mjs:84`、`:87` 及 `live-extended.test.mjs:168`，置信度中。

### TC-0010：关闭并保存后移除文件且保留原配置

状态：条件可执行（Q-1、Q-2、Q-5、Q-6）。

前置条件：站 S 已开启且保存有效网站概述、扩展字段或自定义内容，已记录 B 与 P。B 至少包含一个非空的可核验内容，不用空值声称已验证保留。证据出处：Excel「测试用例」!E11；`live-extended.test.mjs:177`、`:178`；置信度中。

步骤 1：

- 操作：重开弹窗，将开关由开启改为关闭，点击保存一次；同时观察是否出现确认对话。
- 定位依据：公共开关、保存按钮及 POST `/phoenix/customizeFile/llms/save`；Controller 明确读取 boolean enabled。
- 预期：请求 enabled=false，响应 `status=success`；无二次确认，不自动接受任何意外出现的确认框。这里只证明 Controller 分派到 saveDisabledConfig，不声称已有删除文件实现证据。
- 证据出处：`PhoenixCustomizeFileController.java:385`、`:387`、`:397`、`:398`、`:411`、`:477`；`phoenix_function_llms_txt.js:203`、`:208`、`:209`、`:210`、`:213`、`:216`；`txt-manager-page.mjs:76`、`:77`；Excel「测试用例」!F11、G11。
- 置信度：高（端点、参数声明、关闭分支及成功字段）；中（按钮、payload 序列化、无二次确认，rules/view 模块未提供）。

步骤 2：

- 操作：观察保存成功提示并等待弹窗关闭。
- 定位依据：页面可见文字观察及公共弹窗容器消失；先开始记录提示，避免自动关闭后漏读。
- 预期：显示「已关闭 llms.txt 功能，该文件已从网站根目录移除」，随后弹窗关闭；JS 成功路径设置了 700ms 后 close，但不把 700ms 当端到端精确时间断言。
- 证据出处：`phoenix_function_llms_txt.js:216`、`:218`、`:219`、`:220`、`:222`、`:224`、`:225`、`:142`、`:143`；Excel「测试用例」!G11。
- 置信度：高（成功分支的回退文案和关闭调用）；中（实际中文文案、toast 渲染和关闭效果，Q-5）。

步骤 3：

- 操作：按公共轮询策略访问公开 `/llms.txt`。
- 定位依据：绑定的 PUBLIC_BASE_URL，根路径固定，不将保存 API 的响应当公开文件响应。
- 预期：HTTP 404 或明确找不到文件；优先记录真实 HTTP 状态，若 200 但正文是错误页面，仅记录偏差交回裁决，不自动认定等价通过。
- 证据出处：Excel「测试用例」!G11；`live-extended.test.mjs:182`、`:183`；`live-fixtures.mjs:77`。
- 置信度：中（用例 + 历史旁证；服务层/公开服务实现待代码取证，Q-6）。

步骤 4：

- 操作：重新打开管理弹窗，确认已关闭，临时切为开启但不保存；读取当前模式字段及扩展字段。
- 定位依据：公共表单定位，使用 `.llms-overview`、可见 `.llms-extra-fields` 各行和 `.llms-custom-content`，与 B 中各自适用字段逐项比对。
- 预期：B 的内容来源及之前非空内容被保留；仅临时打开草稿不恢复公开文件。必须覆盖本次 B 中实际非空的内容，不能把「输入框存在」当「数据保留」。
- 证据出处：Excel「测试用例」!F11、G11；`llms_tab.jsp:5`、`:30`、`:40`、`:42`、`:43`、`:63`；`PhoenixCustomizeFileController.java:339`、`:342`、`:456`、`:459`、`:460`、`:468`；`live-extended.test.mjs:205`、`:206`。
- 置信度：高（读取配置、映射到视图字段的代码）；中（跨关闭保存的数据保留效果，Q-6）。

清理：独立执行时丢弃临时草稿再按 B 恢复；若与 TC-0011 组成连续链路，先丢弃临时草稿，保持已保存的关闭状态供下一例使用，最终统一恢复 B。采用哪种方式在执行前固定；来源为本次编译的测试隔离约定，恢复路径见公共清理（中）。

### TC-0011：重新开启并保存后按关闭前配置恢复文件

状态：条件可执行（Q-1、Q-2、Q-5、Q-6）。

前置条件：站 S 已保存关闭状态，B 中配置仍在，根目录不存在其它 llms.txt 冲突；连续运行时接 TC-0010 的已保存关闭状态。证据出处：Excel「测试用例」!E12；`live-extended.test.mjs:201`、`:202`、`:204`、`:205`；置信度中。

步骤 1：

- 操作：重新打开弹窗，核对初始为关闭，点击开关切为开启；不修改其它配置。
- 定位依据：公共 `.llms-switch`、data-enabled、当前来源和对应字段。
- 预期：显示「开启」，配置区可见，之前保存的内容与 B 对应部分相同。若发现 B 丢失，停止，不用重新填 B 掩盖恢复缺陷。
- 证据出处：`llms_tab.jsp:4`、`:5`、`:13`、`:17`、`:30`、`:42`、`:43`、`:63`；`phoenix_function_llms_txt.js:148`、`:150`、`:151`；Excel「测试用例」!F12、G12；`live-extended.test.mjs:206`、`:207`。
- 置信度：高（控件与回调）；中（显示状态、原配置保留，Q-3、Q-6）。

步骤 2：

- 操作：点击保存，等待业务成功与弹窗关闭，不接受额外确认框。
- 定位依据：公共保存按钮、POST `/phoenix/customizeFile/llms/save`、可见成功文字及弹窗容器消失。
- 预期：enabled=true，响应 `status=success`，显示「llms.txt 配置已保存」并关闭。保存成功分支及回退文案有直接代码证据；rules.toPayload 的具体序列化尚未取证。
- 证据出处：`PhoenixCustomizeFileController.java:403`、`:404`、`:405`、`:406`、`:407`、`:408`、`:411`、`:477`；`phoenix_function_llms_txt.js:213`、`:216`、`:220`、`:224`；Excel「测试用例」!F12、G12。
- 置信度：高（开启分支和成功回调）；中（payload、按钮与最终 UI 文案，Q-2、Q-5）。

步骤 3：

- 操作：按公共策略读取公开 `/llms.txt`，比较 B 对应生成内容与关闭前 P；站点内容不变时可作完整正文比较，同时记录模式与字段比较。
- 定位依据：PUBLIC_BASE_URL 的根路径 `/llms.txt`。
- 预期：重新返回可读文件（通常 HTTP 200），内容反映关闭前的配置；若系统生成内容依赖外部数据且发生变化，记录差异，不能仅凭 200 判通过。历史脚本通过唯一概述 marker 覆盖了一种恢复场景，并没有覆盖所有内容来源/扩展字段组合。
- 证据出处：Excel「测试用例」!G12；`live-extended.test.mjs:196`、`:197`、`:199`、`:206`、`:207`、`:208`、`:210`、`:211`。
- 置信度：中（用例与历史旁证；公开生成/恢复链路服务实现待代码取证，Q-6）。

清理：按公共约定恢复 B 并单独记录恢复结果；即使断言失败也按已编译路径尝试清理，若定位漂移则停止写入并报告。恢复流程置信度中。

## 5. 存疑清单

| 编号 | 具体缺口 / 冲突及已有证据 | 影响与处理 | 补证方式 |
| --- | --- | --- | --- |
| Q-1 | 未提供本次可登录的 EDITOR_URL、公开域名、站点标识、权限账号、新站 N 与基线 B；Excel 仅规定条件 | 所有用例条件可执行；环境提供者绑定前不启动 UI，不猜域名和数据 | 测试环境提供者给出参数及新站/基线数据，编译者核验并写入最终规格 |
| Q-2 | manage_pop、父弹窗/工具栏模板和绑定脚本未提供；Controller 只给视图名；入口/按钮仅有 txt-manager-page.mjs 旁证；默认 Tab 无直接代码证据 | 保留历史定位为中，匹配不唯一/入口缺失就阻断；默认 Tab 保留为用例目标，不主动点 Tab 代替验证 | 待代码取证：提供管理弹窗、工具栏、页签初始化、按钮事件绑定相关源码 |
| Q-3 | llmsTxtParts.createView、规则模块及 CSS 不在四文件内。JS 仅委托 setEnabled/render；模板同时包含 icon-lock/icon-unlock 和双文案 span。Excel I9/I10 要闭锁与当前状态文案，而模板还含 llms-status 节点（llms_tab.jsp:10），无法凭节点存在证明可见 | 颜色/图标/独立徽章的可见性不硬断言；文字/配置显隐以中置信用例目标验证，失败记录，执行时不探索 CSS。不能声称已读过 Figma | 待代码取证：补 view/rules/CSS/国际化文件；视觉争议由用例负责人按已有裁决明确验收条件 |
| Q-4 | llms_config.jsp 有 #llmsEnabled，但正常返回 llms_tab.jsp；错误返回设置 llmsErrorCode。不能跨分支采用更高优先级 id | 正文锁定 `.llms-switch`；若实际部署出现旧 checkbox 或错误片段，停止并回编译，不自动切换定位器 | 当前分支已消解；待核部署版本及错误场景，补视图解析/部署信息 |
| Q-5 | JS 记录 success、两段回退提示及 700ms 关闭，text() 使用 p_i18n.ov；showToast/对话关闭实现缺失 | 不编造 toast DOM；用可见文本观察。最终文案为中；若出现确认框或文案差异记录裁决，不自动接受。700ms 不作为性能断言 | 待代码取证：补国际化、view.showToast、父弹窗的保存/关闭事件实现 |
| Q-6 | Controller 调用 PhoenixLlmsConfigService.saveDisabledConfig/saveLlmsConfig 与 legacy.load；内部未提供。404、保留配置与重建文件仅有用例 + 历史脚本旁证 | 这些预期均为中，绝不伪标高，也不虚标所有步骤缺代码。历史 TC-0009 只比状态码，TC-0011 只覆盖系统概述 marker；正文和其它配置仍待实际验证 | 待代码取证：补配置/迁移/生成/公开服务实现及存储接口；环境具备后再运行当前规格验证 |

本 trial 没有使用 AI 推测补定位或行为；低置信可执行断言为零。上述未决点按原文目标、历史旁证和明确缺失文件分别记录，不能据此声称已通过 UI 验收。
