"""One upfront checklist, scoped environment memory and asynchronous review projections.

run.json owns progress. Memory stores explicit non-secret answers, never runtime success.
The CLI emits case-spec tasks for the Codex session; it does not call a model.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from .common import (ROOT, UiaError, atomic_write, config, digest, event, file_hash,
                     locked_run, now, read_json, read_yaml, require, save)
from .secrets import scrub_text


def memory_path(m):
    # Bind answers to the exact environment/site/identity/network, using hashes only.
    from .profiles import connection_settings
    return ROOT / '.auth/environment-memory' / (digest(connection_settings(m['config'])) + '.json')


def load_memory(m):
    path = memory_path(m)
    return read_json(path) if path.is_file() else {'answers': {}}


def rows(base, m):
    from .preconditions import derive_items, case_text, labels
    env, scopes, business = {}, {}, {}
    for cid, c in m['cases'].items():
        path = base / c.get('case_spec', f'cases/{cid}/case-spec.yaml')
        spec = read_yaml(path) if path.is_file() else {}
        items = spec.get('required_env', derive_items(case_text(base, c)))
        c['precondition_items'] = items
        for key in items:
            env.setdefault(key, []).append(cid)
        for key in spec.get('mutation_scope', []):
            scopes.setdefault(key, []).append(cid)
        if not spec and (c.get('registration') or {}).get('fixture'):
            for key in c['registration']['fixture'].get('mutation_scope', []):
                scopes.setdefault(key, []).append(cid)
        for text in spec.get('questions', []):
            business.setdefault(text, []).append(cid)
    result = []
    for key, owners in env.items():
        result.append({'key': 'env:' + key, 'block': 'A', 'label': labels().get(key, key), 'cases': owners,
                       'options': ['可用', '缺少，相关用例挂起']})
    for key, owners in scopes.items():
        result.append({'key': 'scope:' + key, 'block': 'B', 'label': key, 'cases': sorted(set(owners)),
                       'options': ['同意临时修改并还原', '不同意，相关用例挂起']})
    for text, owners in business.items():
        # Choices must be authored with the question; never invent a business answer.
        result.append({'key': 'business:' + digest(text), 'block': 'C', 'label': text, 'cases': owners,
                       'options': re.split(r'[、/|]', text.split('选项：', 1)[1]) if '选项：' in text else ['保持原期望', '暂挂待确认']})
    for block in ('A', 'B', 'C'):
        for index, row in enumerate((r for r in result if r['block'] == block), 1):
            row['number'] = index
    return result


def sync_checklist(base, m):
    from .preconditions import QUESTION_KEY
    entries = rows(base, m)
    answers = load_memory(m)['answers']
    old = m['questions'].get(QUESTION_KEY)
    # Run answers are immutable evidence; environment memory supplies only unseen runs.
    local = (old or {}).get('answer', {}).get('entries', {})
    answers = {**answers, **local}
    pending = [r for r in entries if r['key'] not in answers]
    issued = m.get('checklist_issued', False)
    previous_keys = {r['key'] for r in (old or {}).get('entries', [])}
    q = old or {'id': QUESTION_KEY, 'kind': 'preconditions', 'subject': 'run-preconditions',
                'created_at': now(), 'attempted': [], 'resume_states': {}, 'sheet': None}
    q.update(case_ids=sorted({c for row in entries for c in row['cases']}), entries=entries,
             checklist=[r['key'] for r in pending], answer={'entries': {r['key']: answers[r['key']] for r in entries if r['key'] in answers}})
    q['status'] = 'deferred' if pending and issued else 'open' if pending else 'answered'
    if pending and not issued:
        q.pop('answered_at', None)
    if not pending:
        q.setdefault('answered_at', now())
    q['prompt'] = '执行前清单（一次回答，缺少条件只挂起相关用例）'
    m['questions'][QUESTION_KEY] = q
    if issued and pending:
        for row in pending:
            if row['key'] in previous_keys:
                continue
            add_review(m, 'new_ambiguity' if row['block'] == 'C' else 'new_permission', row['cases'], row['label'])
    apply_checklist(m, q)
    text = checklist_text(q)
    (base / 'checklist.md').write_text(scrub_text(text, m['config']), encoding='utf-8')
    return {'question_id': QUESTION_KEY, 'question_count': len(pending) if not issued and not m.get('checklist_draft') else 0,
            'draft': bool(m.get('checklist_draft')),
            'pending_review_count': len(pending) if issued else 0, 'status': q['status'],
            'checklist': str(base / 'checklist.md')}


def apply_checklist(m, q):
    answers = q.get('answer', {}).get('entries', {})
    blocked = {}
    for row in q.get('entries', []):
        value = answers.get(row['key'])
        okay = value is True if row['block'] != 'C' else bool(value) and value != '暂挂待确认'
        if row['block'] == 'B':
            mutation = m['config'].get('mutation', {})
            allowed = mutation.get('allowed') and (row['label'] in mutation.get('scope', []) or
                      mutation.get('scope') == ['*'] and mutation.get('authorization_profile', {}).get('approved_by') == 'Xinying')
            if not allowed:
                okay = False
                add_review(m, 'new_permission', row['cases'], '配置尚未授权变更：' + row['label'])
        if not okay:
            for cid in row['cases']:
                blocked.setdefault(cid, []).append(row['label'])
    for cid, c in m['cases'].items():
        if cid in blocked:
            c['checklist_wait'] = True
            c['work_status'] = 'waiting_human'
            c['classification'] = {'reason': '前置未满足：' + '、'.join(blocked[cid]), 'at': now()}
        elif c.pop('checklist_wait', False) and c.get('result') is None:
            others = [x for x in m['questions'].values() if x is not q and x['status'] in {'open', 'deferred'} and cid in x['case_ids']]
            if not others:
                c['work_status'] = 'runnable' if c.get('registration') and c['stage'] == 'execution' else 'pending'


def checklist_text(q):
    answers = q.get('answer', {}).get('entries', {})
    lines = ['# 执行前清单', '', '只需一句中文回答；缺少条件的用例挂起，其余照跑。', '']
    for block, title in [('A', '需要的站点、账号、编辑器和迁移条件'), ('B', '临时修改并还原的数据范围'), ('C', '业务歧义及选项')]:
        lines += ['## ' + block + ' ' + title, '']
        if block == 'B':
            lines += ['配置的测试站可自由编辑、保存和发布；实际可行时恢复快照。清单答案不扩大配置授权。', '']
        subset = [r for r in q['entries'] if r['block'] == block]
        if not subset:
            lines += ['无。', '']
        for row in subset:
            value = answers.get(row['key'], '待回答')
            status = ('已确认可用' if value is True else '已确认缺少／不同意，相关用例挂起' if value is False else value)
            lines += ['- ' + block + str(row.get('number', 1)) + '. ' + row['label'] + '（' + '、'.join(row['cases']) + '）：' + ' / '.join(row['options']) + '。状态：' + str(status)]
        lines += ['']
    lines += ['回答格式：A 除 TC-xxxx 缺少外其余可用，B 同意，C 无歧义（有歧义时逐项选择）。', '']
    return '\n'.join(lines)


def answer_sentence(base, m, sentence):
    from .preconditions import QUESTION_KEY
    require(scrub_text(sentence, m['config']) == sentence, '回答含敏感信息，请只回答条件及选项')
    q = m['questions'].get(QUESTION_KEY)
    require(q and q['status'] in {'open', 'deferred'} and not q.get('answered_at'), '没有待回答的开跑前清单；运行中问题请异步审核')
    parts = {a: b.strip(' ，,；;。') for a, b in re.findall(r'(?:^|[，,；;]\s*)([ABC])\s*[:：]?\s*(.*?)(?=(?:[，,；;]\s*[ABC](?![A-Za-z0-9])\s*[:：]?)|$)', sentence, re.S)}
    answers = dict(q.get('answer', {}).get('entries', {}))
    for row in q['entries']:
        if row['key'] in answers:
            continue
        block = parts.get(row['block'], '')
        if row['block'] == 'A':
            mentioned = row['label'] in block or any(cid in block for cid in row['cases'])
            negative = bool(re.search(r'缺少|没有|不可用|都无|均无', block))
            positive = bool(re.search(r'可用|都有|均有|具备', block))
            if '除' in block and '其余' in block and positive:
                value = not mentioned
            elif mentioned and negative or re.search(r'都没有|均缺少|都无', block):
                value = False
            elif positive and not negative:
                value = True
            else:
                raise UiaError('A 块答案不明确，请说明缺少的用例或条件及其余是否可用')
        elif row['block'] == 'B':
            require(bool(re.search(r'同意|允许|不同意|拒绝', block)), 'B 块请回答同意或不同意')
            value = not bool(re.search(r'不同意|拒绝', block))
        else:
            business_count = sum(r['block'] == 'C' for r in q['entries'])
            if business_count > 1:
                segments = dict(re.findall(r'(?:^|[、，,；;])\s*(\d+)\s*[:：=]?\s*(.*?)(?=[、，,；;]\s*\d+|$)', block))
                block = segments.get(str(row['number']), '')
            chosen = [x for x in row['options'] if x in block]
            require(len(chosen) == 1, 'C 块请逐项选择清单中的选项，不接受默认猜测')
            value = chosen[0]
        answers[row['key']] = value
    memory = load_memory(m)
    memory['answers'].update(answers)
    memory['updated_at'] = now()
    private = memory_path(m).parent
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    private.chmod(0o700)
    atomic_write(memory_path(m), memory)
    q.update(status='answered', answer={'entries': answers}, answered_at=now())
    m['checklist_issued'] = True
    m.setdefault('interaction_events', []).append({'kind': 'checklist_answer', 'at': now()})
    event(m, 'checklist_answered', entries=len(answers))
    apply_checklist(m, q)
    (base / 'checklist.md').write_text(scrub_text(checklist_text(q), m['config']), encoding='utf-8')
    return {'answered': len(answers), 'waiting': [cid for cid, c in m['cases'].items() if c.get('checklist_wait')], 'memory_saved': True}


def add_review(m, kind, cases, text, **detail):
    key = digest([kind, sorted(cases), text])[:16]
    entry = {'id': key, 'kind': kind, 'case_ids': cases, 'summary': scrub_text(text, m['config']),
             'status': '待审核', 'applied': False, **detail}
    import json
    entry = json.loads(scrub_text(json.dumps(entry, ensure_ascii=False), m['config']))
    m.setdefault('review_items', {})[key] = entry
    return entry


def review(base, m):
    for q in m['questions'].values():
        if q['status'] in {'open', 'deferred'} and q.get('subject') != 'run-preconditions':
            kind = 'record_request' if q['kind'] == 'demo' else 'new_ambiguity' if q['kind'] == 'product' else 'environment'
            detail = {}
            if kind == 'record_request':
                detail['command'] = 'node assets/playwright-runner/node_modules/@playwright/test/cli.js codegen --load-storage "$UIA_CODEGEN_STATE" https://www.leadong.com/website.html -o recorded.spec.ts'
                detail['instructions'] = '受保护变量 UIA_CODEGEN_STATE 指向已认证状态；复用登录后录制，只提交脱敏动作脚本，勿录制密码或导出登录态。'
            add_review(m, kind, q['case_ids'], q['prompt'], **detail)
    for cid, c in m['cases'].items():
        if c.get('result') == 'business_failure':
            source = read_json(base / c['source'])
            attempt = c['attempts'][-1]
            add_review(m, 'suspected_defect', [cid], c['title'], reproduction=source.get('steps'),
                       expected=source.get('expected'), actual=scrub_text('\n'.join(attempt.get('errors', [])), m['config']),
                       evidence=attempt['evidence'], screenshot=attempt.get('redacted_screenshot'),
                       screenshot_status='已脱敏' if attempt.get('redacted_screenshot') else '未采集，禁止附原始截图')
        if c.get('stage') == 'discovery' and c.get('work_status') != 'waiting_human':
            add_review(m, 'automation_gap', [cid], '页面目标或数据准备器尚未实现；待限定探索，预算耗尽后再请求录制')
    from .preconditions import QUESTION_KEY
    checklist = m['questions'].get(QUESTION_KEY, {})
    answered_labels = {r['label'] for r in checklist.get('entries', []) if r['key'] in checklist.get('answer', {}).get('entries', {})}
    for entry in m.get('review_items', {}).values():
        if entry['kind'] in {'new_permission', 'new_ambiguity'} and entry['summary'] in answered_labels:
            entry['status'] = '已答清单'
    for entry in m.get('review_items', {}).values():
        if entry['kind'] == 'record_request' and entry['summary'] == '页面目标或数据准备器尚未实现':
            entry['status'] = '已替换为自动化缺口'
    items = [x for x in m.get('review_items', {}).values() if x['status'] == '待审核']
    merged = {}
    for item in items:
        key = (item['kind'], item['summary']) if item['kind'] == 'environment' else (item['id'],)
        if key in merged:
            merged[key] = dict(item, case_ids=sorted(set(item['case_ids']) | set(merged[key]['case_ids'])))
        else:
            merged[key] = item
    items = list(merged.values())
    payload = {'blocking_delivery': False, 'assertion_changes_default': '不应用', 'items': items}
    atomic_write(base / 'review.json', payload)
    names = {'suspected_defect': '疑似产品缺陷', 'assertion_change': '断言变更建议（默认不应用）',
             'record_request': '页面录制请求', 'new_ambiguity': '新增业务歧义', 'new_permission': '新增权限', 'environment': '环境待处理', 'automation_gap': '自动化缺口（待探索）'}
    lines = ['# 异步审核单', '', '不阻塞其他用例交付；断言变更默认不应用。', '']
    for row in items:
        lines += ['## ' + names.get(row['kind'], row['kind']) + '：' + '、'.join(row['case_ids']), '', row['summary'], '',
                  '```json', scrub_text(__import__('json').dumps(row, ensure_ascii=False, indent=2), m['config']), '```', '']
    (base / 'review.md').write_text('\n'.join(lines), encoding='utf-8')
    return payload


def session_turn(m, turn_id, kind):
    require(kind in {'发起', '答清单', '审核单', '看报告', '计划外'}, '未知会话类型')
    events = m.setdefault('interaction_events', [])
    if not any(x.get('turn_id') == turn_id for x in events):
        events.append({'kind': 'session_turn', 'turn_id': turn_id, 'category': kind, 'at': now()})
    return {'session_turns': sum(x['kind'] == 'session_turn' for x in events)}


def go(excel, profile=None, cases=None):
    from . import workflow, specs, profiles, runtime, reports
    source = Path(excel).resolve()
    require(source.is_file(), '工作簿不存在')
    selected = sorted(set(cid.strip() for cid in cases.split(','))) if cases is not None else None
    require(selected is None or selected and all(selected), '用例范围不能为空')
    if not profile:
        candidates = list((ROOT / '.auth/profiles').glob('*.local.json'))
        require(len(candidates) == 1, '请用 --profile 指定已配置环境')
        profile = candidates[0].name.removesuffix('.local.json')
    path = profiles.profile_path(profile)
    key = digest([str(source), str(path), selected])[:12]
    matches = []
    for manifest in (ROOT / 'runs').glob('*/run.json'):
        candidate = read_json(manifest)
        if candidate.get('go_key') == key:
            matches.append(manifest)
    if matches:
        manifest = sorted(matches)[0]
    else:
        run_id = 'GO-' + key
        manifest = ROOT / 'runs' / run_id / 'run.json'
        if not manifest.is_file():
            workflow.init(run_id, path)
    with locked_run(manifest) as (manifest, m):
        base = manifest.parent
        if m.get('active_batch'):
            return {'run_id': m['run_id'], 'question_count': 0, 'next': workflow.next_task(base, m)}
        m.update(go_key=key, interaction_mode='once', selected_cases=selected)
        save(manifest, m)
        workflow.scaffold(base)
        if not m['sources'] or m['sources'][0]['sha256'] != file_hash(source):
            workflow.import_excel(base, m, source)
        workflow.refresh(base, m)
        workflow.bind_specs(base, m)
        # Reuse only source-fingerprint-matched example contracts, never by case ID alone.
        index = ROOT / 'examples/phase2/index.json'
        for cid, item in (read_json(index).items() if index.is_file() else []):
            c = m['cases'].get(cid)
            if c and c['source_hash'] == item['source_hash'] and not specs.spec_path(base, c).is_file():
                dest = specs.spec_path(base, c); dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / item['spec'], dest)
                if not c.get('registration'):
                    c['case_spec'] = str(dest.relative_to(base))
        m['checklist_draft'] = any(not specs.spec_path(base, c).is_file() and not c.get('registration') for c in m['cases'].values())
        checklist = sync_checklist(base, m)
        if not checklist['draft']:
            m['checklist_issued'] = True
            m.setdefault('checklist_question_count', checklist['question_count'])
        # Runtime environment evidence is refreshed each invocation; memory is not a preflight.
        evidence = 'evidence/go-environment-' + now().replace(':', '-') + '.json'
        try:
            profiles.invoke_login(m['config'], base / 'runner', evidence=base / evidence)
            runtime.preflight(base, m, evidence)
        except UiaError as error:
            workflow.question(m, 'environment', 'preflight', scrub_text(str(error), m['config']), list(m['cases']), reopen=True)
        save(manifest, m)
        ready = [cid for cid, c in m['cases'].items() if c['work_status'] == 'runnable' and not c.get('case_spec')]
    # Existing runnable scripts get the first batch, before new generation.
    if ready:
        _run_ready(manifest, ready)
    with locked_run(manifest) as (manifest, m):
        base = manifest.parent
        if not checklist['question_count']:
            for cid, c in m['cases'].items():
                if c.get('work_status') == 'waiting_human' or not specs.spec_path(base, c).is_file() or (c.get('registration') or {}).get('case_spec') or c.get('result'):
                    continue
                # Keep compatible daily scripts; only missing scripts need template compilation.
                if c.get('registration') and not c.get('case_spec'):
                    continue
                try:
                    specs.generate(base, m, cid)
                except UiaError as error:
                    c.update(work_status='waiting_human', classification={'reason': scrub_text(str(error), m['config'])})
                    add_review(m, 'new_ambiguity', [cid], 'case-spec/生成门禁：' + str(error), details=error.details)
            sync_checklist(base, m)
        tasks = [{'case_id': cid, 'source': c['source'], 'action': '编写 case-spec'} for cid, c in m['cases'].items() if not specs.spec_path(base, c).is_file() and not c.get('registration')]
        m['spec_tasks'] = tasks
        save(manifest, m)
        ready = [cid for cid, c in m['cases'].items() if c['work_status'] == 'runnable'] if not checklist['question_count'] else []
    if ready:
        _run_ready(manifest, ready)
    with locked_run(manifest) as (manifest, m):
        output = reports.make_report(manifest.parent, m)
        save(manifest, m)
        return {'run_id': m['run_id'], **checklist, 'spec_tasks': tasks, 'report': output,
                'next': {'action': 'complete_spec_tasks' if checklist['draft'] else 'answer_checklist' if checklist['question_count'] else 'continue_spec_tasks_or_review', 'mid_run_questions': 0}}


def _run_ready(manifest, ready):
    from . import runtime
    while ready:
        with locked_run(manifest) as (path, m):
            if not m.get('preflight') or m['preflight']['status'] != 'passed':
                return
            selected = ready[:m['config']['execution']['batch_size']]
            ready = ready[len(selected):]
            selected = [cid for cid in selected if m['cases'][cid]['work_status'] == 'runnable']
            if not selected:
                continue
            batch = runtime.begin_batch(path.parent, m, selected)
            cfg = m['config']; save(path, m)
        code = runtime.execute_process(path.parent, batch, cfg)
        with locked_run(manifest) as (path, m):
            runtime.consume_batch(path.parent, m, code); save(path, m)
