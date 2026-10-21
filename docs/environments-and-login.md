# 环境选择与公共登录

项目提供 P 版、灰度、正式版三套独立初始入口：

| ID | 环境 | 初始入口 | 网络 |
|---|---|---|---|
| p | P 版 | `http://jianzhan.leadong.com/website.html` | `http://101.43.28.166:7128` |
| gray | 灰度 | `http://www.leadong.com/website.html` | 随项目提供的 `network/gray.pac` |
| production | 正式版 | `https://www.leadong.com/website.html` | 直连，校验证书 |

灰度从 HTTP 开始，允许服务器在同一主机跳转 HTTPS；必须观察到 `X-Via: Ld-Gray` 才确认环境。
完整 PAC 位于 `assets/playwright-runner/network/gray.pac`，包含域名分流、HTTP/HTTPS 代理、
monitor 例外和直连规则。该文件是原规则的项目内副本，不从旧工作区或远程 PAC 地址加载。
灰度继承原脚本的证书容错设置；正式版始终直连并校验证书。

## 首次配置

安装 Python 依赖和项目自带 Node 组件后，执行：

```bash
python3 scripts/uia.py env list
python3 scripts/uia.py setup --profile my-p --environment p --site en.example.com --account my-account
```

密码通过终端隐藏输入；JSON 结果不包含账号密码。配置分别保存在 `.auth/profiles/`、
`.auth/credentials/` 和 `.auth/sessions/`。这些目录默认不提交 Git，也不进入交付脚本包。
目录权限为 0700，凭据和登录态文件权限为 0600。

也可以显式使用已有私有 JSON，格式为 `{"account":"...","password":"..."}`：

```bash
python3 scripts/uia.py setup --profile my-gray --environment gray --site en.example.com --credentials-file /private/operator.json
```

无人值守配置支持 `--account NAME --password-env UIA_SETUP_PASSWORD`，只传环境变量名称，
不支持密码命令行参数。旧工作区的历史密码不会自动迁移。

未写协议的目标域名按所选环境初始入口的协议补全；显式写入 `http://` 或 `https://` 时保留。
目标网站域名与登录后台地址是两项配置，不会将目标网站域名替换成后台入口。
可编辑对应 `.auth/profiles/NAME.local.json` 的 `environment` 对象，分别覆盖 `entry_url`、
`login_url`、`cloud_url`；`network` 支持 direct、proxy、pac，本地 PAC 路径相对于配置文件。
正式版拒绝代理或关闭证书验证的覆盖。

## 登录和运行

```bash
python3 scripts/uia.py login --profile my-gray --check-only
python3 scripts/uia.py login --profile my-gray
python3 scripts/uia.py init --run-id REQ-001 --profile my-gray
python3 scripts/uia.py scaffold --run REQ-001
```

为生成的 runner 安装依赖后：

```bash
python3 scripts/uia.py login --run REQ-001
```

该命令将真实浏览器证据写入 run，并接入已有 preflight 门控；`--check-only` 仅检查环境，
不能将运行标为预检通过。`--force` 强制新上下文重新认证。遇到验证码可显式执行 `login --run REQ-001 --manual`：
浏览器将打开并最多等待 10 分钟，由用户以当前配置账号完成登录，再验证环境和目标站点、保存会话。仅刷新同账号的登录态保留历史结果；
切换环境、账号、域名或代理规则后，相关结果失效并重新累计两次独立成功。

登录先访问环境初始入口，再检测登录表单。需要时填写 `#loginName`、`#password` 并提交
`#loginSubmit`，进入领动云平台并确认目标网站。账号配置及会话绑定使用环境、账号身份、
目标域名和网络规则；存在缓存也会检查当前页面与站点权限。

密码错误只提交一次。验证码、无权限、站点不存在或匹配多条记录时返回明确错误及操作选项；
`login --run` 会保存问题，补充配置后再次执行可恢复相关用例。

## 业务脚本复用

生成脚本从 `support/test.ts` 导入 `test` 和 `expect`：

```ts
// 默认 page/context 是前台未登录访客，后台通过显式 fixture 获取。
test('[CASE_001] example', async ({ adminPage, page, caseContext }) => {
  const contentPage = await caseContext.openAdmin('内容管理');
  // 在 contentPage 中操作已确认的目标站点；page 保持独立访客身份。
});
```

也可以使用 `adminContext`。`openAdmin('编辑网站')` 支持进入编辑器。
站点卡片、语言选项和站点 ID 从当前 UI 读取，不内置历史账号的标识。
测试执行阶段只消费已准备的认证状态，若过期则返回 `UIA_ENVIRONMENT_BLOCKED`；
总控在测试外重新登录，再预检和继续。填密码时不开启截图或 trace。

浏览器探索工具使用同一环境、代理和认证模块；追加 `--public` 可显式创建未登录上下文。
老的 `uia-config.v1` 配置、`proxy_env` 和 storage_state 引用继续可用，未选择命名环境时仍按旧配置解释。

## 移动项目和独立交付

项目自带 `environments.json`、完整 `network/gray.pac`、环境检查及公共登录脚本。
脚本目录相对于模块定位，不依赖进程启动目录。`scripts.zip` 同样包含这些资源。
在其他机器安装 Node 依赖及浏览器，重新提供本地凭据，即可使用。
原机器的密码、登录态和私有配置不会打包；需要复用时由用户自行安全转移或重新配置。
