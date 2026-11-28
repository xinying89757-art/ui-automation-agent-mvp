import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { on, once } from 'node:events';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { chromium, expect } from '../assets/playwright-runner/node_modules/@playwright/test/index.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const cli = path.join(root, 'scripts/uia.py');

function startPython(args) {
  const child = spawn('python3', args, {cwd:root, stdio:['pipe', 'pipe', 'inherit']});
  const lines = createInterface({input:child.stdout});
  const events = on(lines, 'line', {close:['close']});
  return {
    child,
    async read() {
      const line = await events.next();
      assert.equal(line.done, false, 'Python process closed before emitting its receipt');
      return line.value[0];
    },
    async stop() {
      if (child.exitCode !== null || child.signalCode !== null) return;
      const done = once(child, 'exit');
      child.kill('SIGINT');
      await done;
    },
  };
}

test('local review saves partial decisions, protects drafts and resumes persisted work', {timeout:30_000}, async () => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'uia-local-review-'));
  const runPath = path.join(runDir, 'run.json');
  const inputPath = path.join(runDir, 'review-input.json');
  const programs = [];
  let browser;
  async function serve() {
    const server = startPython([cli, 'review-page', 'serve', '--run', runPath]);
    programs.push(server);
    const ready = JSON.parse(await server.read());
    assert.equal(ready.event, 'review_ready');
    assert.equal(new URL(ready.url).hostname, '127.0.0.1');
    return {...server, url:ready.url};
  }
  async function readRun() { return JSON.parse(await fs.readFile(runPath, 'utf8')); }

  try {
    const makeCase = (title, source) => ({title, source, stage:'execution', work_status:'runnable', registration:{}, result:null});
    await fs.writeFile(path.join(runDir, 'first.json'), JSON.stringify({expected:['结果应该显示']}));
    await fs.writeFile(path.join(runDir, 'second.json'), JSON.stringify({expected:['提示应该显示']}));
    await fs.writeFile(runPath, JSON.stringify({schema_version:'uia-run.v1', pipeline:'case-spec.v1', run_id:'Local-Review',
      cases:{C1:makeCase('第一条用例', 'first.json'), C2:makeCase('第二条用例', 'second.json')}, questions:{}, sources:[], config:{}, history:[]}));
    const input = {checks:[{id:'A', title:'确认第一条验法', cases:['C1'], expectations:{C1:'结果应该显示'}, checks:['验证结果已经显示']},
      {id:'B', title:'确认第二条验法', cases:['C2'], expectations:{C2:'提示应该显示'}, checks:['验证提示已经显示']}]};
    await fs.writeFile(inputPath, JSON.stringify(input));
    const server = await serve();
    browser = await chromium.launch();
    const page = await browser.newPage();
    assert.equal((await fetch(new URL('/run.json', server.url))).status, 404);
    assert.equal((await fetch(server.url + '/submit', {method:'POST', headers:{origin:'http://example.test'}})).status, 403);
    await page.goto(server.url);
    const choose = name => page.locator('#list').getByRole('button', {name:new RegExp(name)}).click();
    const preview = () => page.getByRole('button', {name:'预览审核结果'}).click();
    const submit = () => page.getByRole('button', {name:'提交审核', exact:true}).click();
    const close = () => page.getByRole('button', {name:'关闭', exact:true}).click();
    await choose('第一条验法');
    await page.getByRole('button', {name:'确认验法'}).click();
    await preview();
    const request = page.waitForRequest(req => req.method() === 'POST' && req.url().endsWith('/submit'));
    await submit();
    const originalPost = (await request).postData();
    await expect(page.getByRole('dialog')).toContainText('1 项已保存，1 项待处理');
    const receipt = JSON.parse(await server.read());
    assert.equal(receipt.event, 'review_saved');
    assert.equal(receipt.next, 'apply_review_decisions');
    assert.equal(receipt.pending, 1);
    const repeated = await fetch(server.url + '/submit', {method:'POST', headers:{'content-type':'application/json',
      origin:new URL(server.url).origin}, body:originalPost});
    assert.equal((await repeated.json()).already_saved, true);
    assert.equal((await readRun()).interaction_events.length, 1);
    const fromOldTab = JSON.parse(originalPost);
    Object.assign(fromOldTab.decisions[0], {status:'edited', value:'旧窗口的另一份意见'});
    const conflict = await fetch(server.url + '/submit', {method:'POST', headers:{'content-type':'application/json',
      origin:new URL(server.url).origin}, body:JSON.stringify(fromOldTab)});
    assert.equal(conflict.status, 409);
    assert.equal((await conflict.json()).code, 'review_conflict');
    const handoff = JSON.parse(await fs.readFile(path.join(runDir, 'review-handoff.json'), 'utf8'));
    assert.deepEqual(handoff.cases.map(row => row.pending.map(item => item.id)), [[], ['B']]);
    const statuses = execFileSync('python3', ['-c', `import json, sys
sys.path.insert(0, 'scripts')
from uia_core.common import load_run
from uia_core.workflow import park_cases_with_pending_review
_, run = load_run(sys.argv[1])
park_cases_with_pending_review(run)
print(json.dumps([case['work_status'] for case in run['cases'].values()]))`, runPath], {cwd:root, encoding:'utf8'});
    assert.deepEqual(JSON.parse(statuses), ['runnable', 'waiting_human']);

    await page.reload();
    await expect(page.getByRole('status', {name:''}).filter({hasText:'已保存 1 项'})).toBeVisible();
    await choose('第二条验法');
    await page.getByRole('button', {name:'修改验法'}).click();
    await page.locator('#draft').fill('第二条尚待核对的意见');
    await page.getByRole('button', {name:'保存修改'}).click();
    await preview();

    const lock = startPython(['-c', `import sys
sys.path.insert(0, 'scripts')
from uia_core.common import locked_run
with locked_run(sys.argv[1]):
    print('locked', flush=True)
    sys.stdin.readline()`, runPath]);
    programs.push(lock);
    assert.equal(await lock.read(), 'locked');
    await submit();
    await expect(page.getByRole('dialog')).toContainText('请稍后重试');
    await expect(page.getByRole('dialog')).toContainText('第二条尚待核对的意见');
    const unlock = once(lock.child, 'exit');
    lock.child.stdin.end();
    await unlock;
    assert.equal((await readRun()).human_review.decisions.length, 1);

    input.checks[1].checks[0] = '验证更新后的提示已经显示';
    await fs.writeFile(inputPath, JSON.stringify(input));
    await submit();
    await expect(page.getByRole('dialog')).toContainText('审核材料已更新');
    assert.equal((await readRun()).human_review.decisions.length, 1);
    await page.getByRole('button', {name:'刷新审核材料'}).click();
    await page.getByText('查看旧版草稿').click();
    await expect(page.locator('#previousDraftItems')).toContainText('第二条尚待核对的意见');
    await choose('第二条验法');
    await expect(page.getByRole('button', {name:'确认验法'})).toBeVisible();
    await page.getByRole('button', {name:'确认验法'}).click();
    await preview();
    await server.stop();
    await submit();
    await expect(page.getByRole('dialog')).toContainText('草稿仍在此页面');
    await expect(page.getByRole('dialog')).toContainText('验证更新后的提示已经显示');
    await close();

    const restarted = await serve();
    assert.notEqual(restarted.url, server.url);
    await page.goto(restarted.url);
    await expect(page.locator('#saveStatus')).toHaveText('已保存 1 项');
    await choose('第一条验法');
    await expect(page.locator('#review')).toContainText('已确认');
  } finally {
    if (browser) await browser.close();
    for (const program of programs.reverse()) await program.stop();
    await fs.rm(runDir, {recursive:true, force:true});
  }
});

test('review progress, filters and inline answers preserve partial decisions', {timeout:30_000}, async () => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'uia-review-workbench-'));
  const runPath = path.join(runDir, 'run.json');
  let browser;
  let server;
  try {
    const makeCase = title => ({title, stage:'execution', work_status:'runnable', registration:{}, result:null});
    await fs.writeFile(runPath, JSON.stringify({schema_version:'uia-run.v1', pipeline:'case-spec.v1', run_id:'Workbench',
      cases:{C1:makeCase('首条用例'), C2:makeCase('独立用例'), C3:makeCase('无需审核的用例')}, questions:{}, sources:[], config:{}, history:[]}));
    await fs.writeFile(path.join(runDir, 'review-input.json'), JSON.stringify({
      questions:[{id:'Q1', title:'确认入口', cases:['C1']}],
      checks:[{id:'A1', title:'确认关键结果', cases:['C2'], checks:['结果可见']}],
    }));
    server = startPython([cli, 'review-page', 'serve', '--run', runPath]);
    const ready = JSON.parse(await server.read());
    browser = await chromium.launch();
    const page = await browser.newPage();
    await page.goto(ready.url);
    await expect(page.locator('#progressText')).toHaveText('0 / 2 已处理');
    await page.getByLabel('你的答复').fill('从产品描述进入');
    await expect(page.locator('#saveStatus')).toContainText('有未提交修改');
    await expect(page.locator('#progressText')).toHaveText('1 / 2 已处理');
    await page.reload();
    await page.getByRole('button', {name:'待回答', exact:true}).click();
    await expect(page.locator('#review')).toContainText('从产品描述进入');
    await expect(page.locator('#saveStatus')).toContainText('有未提交修改');
    await page.getByRole('button', {name:'已修改', exact:true}).click();
    await expect(page.locator('#list')).toContainText('确认入口');
    await page.getByRole('button', {name:'暂缓', exact:true}).click();
    await expect(page.locator('#review')).toContainText('当前筛选下没有审核项');
    await page.getByRole('button', {name:'预览审核结果'}).click();
    await page.getByRole('button', {name:'提交审核', exact:true}).click();
    await expect(page.getByRole('dialog')).toContainText('1 项已保存，1 项待处理');
    assert.equal(JSON.parse(await server.read()).event, 'review_saved');
    await expect(page.locator('#saveStatus')).toHaveText('已保存 1 项');
    await page.reload();
    await expect(page.locator('#progressText')).toHaveText('1 / 2 已处理');
    await expect(page.locator('#saveStatus')).toHaveText('已保存 1 项');
  } finally {
    if (browser) await browser.close();
    if (server) await server.stop();
    await fs.rm(runDir, {recursive:true, force:true});
  }
});
