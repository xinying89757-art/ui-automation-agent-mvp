# Standalone Playwright runner

Each run links to this shared repository directory; delivery packages include a scrubbed copy. It includes
`environments.json`, the complete local `network/gray.pac`, browser configuration,
shared login/site selection, fixture lifecycle, and reporters. No original workspace
or remote PAC download is needed.

1. Run `npm ci`, then `npx playwright install chromium` when ready for real execution.
2. Copy `config.example.json` to `config.local.json`; select `p`, `gray`, or `production`
   and set the target `site` (the public website, not the login backend).
3. Create `.auth/credentials.local.json` using the shape in `credentials.example.json`.
   Keep this local directory private (0700) and credential files 0600.
4. Run commands from this runner directory:

```bash
npm run check:environment -- --config config.local.json
npm run login -- --config config.local.json
UIA_CONFIG=/absolute/path/config.local.json npm test
```

For captcha/manual intervention use `npm run login -- --config config.local.json --manual`.
This opens a browser, waits at most ten minutes, then verifies the target and saves state.

Script/config paths are module-relative, so checks/login also work when invoked by an
absolute script path from another directory. Relative local references are resolved
against the supplied config file. A moved installation supplies its own local credentials.

P starts at `http://jianzhan.leadong.com/website.html` through the fixed P proxy;
gray starts at `http://www.leadong.com/website.html` with the bundled PAC and requires
`X-Via: Ld-Gray`; production starts at `https://www.leadong.com/website.html` with
forced direct access. Explicit environment profiles ignore ambient `UI_PROXY`.
Override individual entry/login/cloud URLs in the local `environment` object.

Use `test` from `support/test.ts`. The default `page`/`context` stay unauthenticated
for profile-based runs. Request `adminPage`, `adminContext`, or call
`caseContext.openAdmin('内容管理')` / `caseContext.openAdmin('编辑网站')` for managed access.
Test execution does not fill passwords; expired authentication returns a blocker so
login can be refreshed outside test traces. Every registered case supplies real
`prepare`, `verifyPrepared`, `cleanup`, `verifyCleanup` hooks. No retries are enabled.

Use the one-shot snapshot instead of a persistent exploration process. From the project root:

```bash
python3 scripts/uia.py snapshot --run REQ-001 --node editor
```
