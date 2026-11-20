# 内容编辑器骨架

`assets/playwright-runner/support/editor-skeleton.mjs` 是产品/文章富文本编辑器的共享页面对象。生成脚本只调用这里的原语和知识库已验证的 `openTarget`。默认路径是确定性 Playwright。没有模型密钥时 Midscene 整段跳过，不参与执行。

凭据只来自环境变量 `UIA_ACCOUNT` / `UIA_PASSWORD`，或 gitignore 的 `.auth/credentials`。模块和报告都不写账号、密码、会话内容。

## 公开 API

| 方法 | 行为 | 失败码 |
|---|---|---|
| `login` / `openSession` | 提交已知登录表单，或复用 `.auth/sessions` | `LOGIN_FAILED` |
| `enterSite` | 在当前账号的站点卡片中进入已配置站点 | `NAV_FAILED` |
| `openContentEditor({kind})` | 内容管理 → 产品或文章详情 | `NAV_FAILED` |
| `waitForEditorReady` | 嵌套 iframe 解析、可编辑根可见、关闭挡住编辑器的遮罩 | `EDITOR_NOT_READY` / `OVERLAY_BLOCKING` |
| `insertComponent(name)` | 输入 `/`，点击组件卡片；点击失败后才用键盘 | `CONTROL_MISSING` |
| `typeText` | 聚焦后输入，重绘后重新定位 | `EDITOR_NOT_READY` |
| `selectMenuItem` | 点击菜单项，点击失败才用方向键 | `CONTROL_MISSING` |
| `save` / `readBack` | 保存并读回 | `SAVE_FAILED` / `READBACK_MISMATCH` |
| `actVerified` / `expectVerified` | 只使用 page-map 里的命名目标 | `CONTROL_MISSING` |
| `visualAssert` | 可选 Midscene `aiAssert`；无密钥则 `{skipped:true}` | 未通过时 `CONTROL_MISSING` |

`createContentEditor(() => page, { caseContext })` 返回同一组方法。斜杠菜单先点击卡片。稳定定位失败且配置了模型密钥时，才用 Midscene 补一次，并在结果里记 `rescued_by_midscene`。

## 实时冒烟

先确认入口可达，再跑骨架。截图写在 `.auth/live-smoke/`（不进 Git），只截编辑器帧。

```bash
python3 scripts/uia.py login --profile prod-test --check-only
python3 scripts/uia.py editor-smoke --profile prod-test
```

`--out` 可改截图目录。JSON 只含步骤名、耗时、是否插入组件、`rescued_by_midscene` 和截图路径。

## 一次性控件探索

探索把编辑器里可见的按钮、菜单项和组件卡片收成唯一稳定定位（id、`data-component` 或唯一 role），证据是 `match_count: 1` 和 iframe 链。结果写成 `needs_review` 候选，不自动并入可检索知识库。

```bash
python3 scripts/uia.py editor-explore \
  --fixture assets/playwright-runner/fixtures/editor-nested/index.html \
  --out /tmp/editor-candidates
python3 scripts/uia.py editor-explore --profile prod-test --run GO-id
```

有 `MIDSCENE_MODEL_API_KEY`、`OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY` 时，探索会多问一次 Midscene。`UIA_MIDSCENE=0` 强制关闭。未安装 `@midscene/web` 或没有密钥时，探索仍用 DOM 扫描，`midscene` 为 `skipped`。

人工确认后再把候选合并进 `knowledge/`。`needs_review` 默认不会被 `kb query` 注入。

## 生成与待补控件

`spec gen` 输出带 `// @uia-assembled` 的脚本。动作是 `editor.actVerified`、`insertComponent`、`typeText`、`selectMenuItem`、`save`、`readBack` 或 `openTarget`。断言走 `editor.expectVerified`。

知识库没有的控件不会生成 `locator()` / `getByText()`。脚本里写入 `// 待补控件:`，运行目录写出 `missing-controls.md`，清单和报告的「需要你处理」也会列出同一条。带该标记的脚本如果出现原始 locator 点击，`spec lint` 会拒绝。

嵌套 iframe 夹具在 `assets/playwright-runner/fixtures/editor-nested/`。`tests/editor-skeleton.test.mjs` 用它覆盖登录、进站、打开编辑器、点击卡片、保存读回、遮罩和 Midscene 兜底。
