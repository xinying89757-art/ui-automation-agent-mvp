"""One upfront checklist, scoped environment memory and asynchronous review projections.

run.json owns progress. Memory stores explicit non-secret answers, never runtime success.
The CLI emits case-spec tasks for the Codex session; it does not call a model.
"""
from __future__ import annotations

import re
import shutil
import datetime as dt
from pathlib import Path
from .common import (ROOT, UiaError, atomic_write, config, digest, elapsed, event, file_hash,
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
    from .preconditions import derive_items, case_text, labels, local_env
    env, scopes, business = {}, {}, {}
    for cid, c in m['cases'].items():
        path = base / c.get('case_spec', f'cases/{cid}/case-spec.yaml')
        spec = read_yaml(path) if path.is_file() else {}
        items = local_env(spec) if spec else derive_items(case_text(base, c))
        c['precondition_items'] = items
        for key in items:
            if key == 'public_frontend' and any(s.get('verb') == 'defer_public' for s in spec.get('steps', [])):
                continue
            if key == 'delayed_save' and any(s.get('verb') == 'network_delay' for s in spec.get('steps', [])):
                continue
            env.setdefault(key, []).append(cid)
        for key in spec.get('mutation_scope', []):
            scopes.setdefault(key, []).append(cid)
        if not spec and (c.get('registration') or {}).get('fixture'):
            for key in c['registration']['fixture'].get('mutation_scope', []):
                scopes.setdefault(key, []).append(cid)
        for text in spec.get('questions', []):
            business.setdefault(text, []).append(cid)
    from .preconditions import triage
    triaged = triage(base, m)
    result = [{'key': 'env:' + row['key'], 'block': 'A', 'label': row['label'], 'cases': row['cases'],
               'options': ['可用', '缺少，相关用例挂起']} for row in triaged if row['classification'] == 'human_env']
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
    from .entries import page_rows
    from .pathfinder import checklist_rows
    result += page_rows(base, m)
    result += checklist_rows(m, result)
    guided = [row.get('subject', '') for row in result if row.get('kind') == 'guided_exploration']
    result = [row for row in result if row.get('block') != 'D' or not any(
        subject and (subject in row.get('page', '') or row.get('page', '') in subject) for subject in guided)]
    for block in ('A', 'B', 'C', 'D', 'E'):
        for index, row in enumerate((r for r in result if r['block'] == block), 1):
            row['number'] = index
    return result


def sync_checklist(base, m):
    from .preconditions import QUESTION_KEY
    entries = rows(base, m)
    unclassified = [r for r in m.get('precondition_triage', []) if r['classification'] == 'unclassified']
    spec_draft = any(not (base / c.get('case_spec', f'cases/{cid}/case-spec.yaml')).is_file() and not c.get('registration') for cid, c in m['cases'].items())
    m['checklist_draft'] = bool(unclassified or spec_draft)
    # Environment availability and authorization are scoped by the environment
    # fingerprint. Business and route answers remain local to their review/run.
    reusable_keys = {row['key'] for row in entries if row.get('block') in {'A', 'B'}}
    memory_answers = {key: value for key, value in load_memory(m)['answers'].items() if key in reusable_keys}
    answers = memory_answers
    old = m['questions'].get(QUESTION_KEY)
    # Run answers are immutable evidence; environment memory supplies only unseen runs.
    local = (old or {}).get('answer', {}).get('entries', {})
    answers = {**answers, **local}
    issued = m.get('checklist_issued', False)
    previous_keys = {r['key'] for r in (old or {}).get('entries', [])}
    if issued:
        from .entries import resolve
        # Preserve the issued checklist and its answers even after entries become known.
        current_keys = {r['key'] for r in entries}
        for row in (old or {}).get('entries', []):
            hint = resolve(row['page']) if row['block'] == 'D' else None
            if hint and row['key'] not in current_keys:
                entries.append(row)
                answers.setdefault(row['key'], hint['path_text'])
    pending = [r for r in entries if r['key'] not in answers]
    late_entries = [r for r in pending if issued and r['block'] == 'D' and r['key'] not in previous_keys]
    if issued:
        for row in pending:
            if row['block'] == 'D' and row['key'] not in previous_keys:
                add_review(m, 'page_entry', row['cases'], row['page'] + ' 大概在哪里进入？（例：内容管理 → 产品 → 编辑）', page=row['page'])
        # Late entries exist only in the async review, not as new checklist questions.
        entries = [r for r in entries if r['block'] != 'D' or r['key'] in previous_keys]
        pending = [r for r in entries if r['key'] not in answers]
    q = old or {'id': QUESTION_KEY, 'kind': 'preconditions', 'subject': 'run-preconditions',
                'created_at': now(), 'attempted': [], 'resume_states': {}, 'sheet': None}
    q.update(case_ids=sorted({c for row in entries for c in row['cases']}), entries=entries,
             checklist=[r['key'] for r in pending], answer={'entries': {r['key']: answers[r['key']] for r in entries if r['key'] in answers}})
    local_keys = set((old or {}).get('locally_answered_keys', []))
    if old and 'locally_answered_keys' not in old:
        local_keys = set(local) - set(old.get('memory_answer_keys', []))
    memory_keys = {r['key'] for r in entries if r['key'] in memory_answers and r['key'] not in local_keys}
    q['memory_answer_keys'] = sorted(memory_keys)
    q['locally_answered_keys'] = sorted(local_keys)
    q['memory_answer_count'] = len(memory_keys)
    q['entry_count'] = len(entries)
    q['entry_question_count'] = sum(r['block'] == 'D' for r in pending)
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
            if row['block'] != 'D':
                add_review(m, 'new_ambiguity' if row['block'] == 'C' else 'new_permission', row['cases'], row['label'])
    if m.get('initial_review_required'):
        # The HTML review owns per-case waiting for new runs. The generated
        # checklist remains an input to that page, not a second human gate.
        q['status'] = 'answered'
        for case in m['cases'].values():
            if case.pop('checklist_wait', False) and case.get('result') is None:
                case['work_status'] = ('runnable' if case.get('registration') and case.get('stage') == 'execution'
                                       else 'pending')
                if (case.get('classification') or {}).get('reason', '').startswith('前置未满足：'):
                    case.pop('classification', None)
    else:
        apply_checklist(m, q, late_entries)
    q['unclassified'] = unclassified
    q['draft'] = m['checklist_draft']
    text = checklist_text(q)
    (base / 'checklist.md').write_text(scrub_text(text, m['config']), encoding='utf-8')
    if issued and any(x['kind'] == 'page_entry' for x in m.get('review_items', {}).values()):
        review(base, m)
    return {'question_id': QUESTION_KEY, 'question_count': len(pending) if not issued and not m.get('checklist_draft') else 0,
            'entry_question_count': q['entry_question_count'] if not issued and not m.get('checklist_draft') else 0,
            'memory_answer_count': q['memory_answer_count'], 'entry_count': len(entries),
            'draft': bool(m.get('checklist_draft')), 'unclassified': unclassified,
            'ai_tasks': m.get('precondition_tasks', []),
            'pending_review_count': len(pending) + len(late_entries) if issued else 0, 'status': q['status'],
            'checklist': str(base / 'checklist.md')}


def apply_checklist(m, q, extra_entries=()):
    answers = q.get('answer', {}).get('entries', {})
    blocked = {}
    for row in [*q.get('entries', []), *extra_entries]:
        value = answers.get(row['key'])
        okay = bool(value) and value not in {'暂挂待确认', '挂起'} if row['block'] in {'C', 'D', 'E'} else value is True
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
        elif (c.pop('checklist_wait', False) or q.get('status') == 'answered' and cid in q.get('case_ids', [])
              and c.get('work_status') == 'waiting_human') and c.get('result') is None:
            # Cases parked when the checklist was queued resume once it is answered and nothing blocks them.
            others = [x for x in m['questions'].values() if x is not q and x['status'] in {'open', 'deferred'} and cid in x['case_ids']]
            if not others:
                c['work_status'] = 'runnable' if c.get('registration') and c['stage'] == 'execution' else 'pending'
                if (c.get('classification') or {}).get('reason', '').startswith('前置未满足：'):
                    c.pop('classification', None)


def checklist_text(q):
    answers = q.get('answer', {}).get('entries', {})
    lines = ['# 执行前清单', '', '只需一句中文回答；缺少条件的用例挂起，其余照跑。', '']
    if q.get('draft'):
        lines = ['# 执行前清单草稿（尚未向人工提问）', '']
    if q.get('unclassified'):
        lines += ['## 未分类前置条件（AI 必须先分流）', '']
        lines += ['- ' + r['key'] + ' ' + r['label'] + '（' + '、'.join(r['cases']) + '）' for r in q['unclassified']]
    for block, title in [('A', '需要的站点、账号、编辑器和迁移条件'), ('B', '临时修改并还原的数据范围'), ('C', '业务歧义及选项'), ('D', '页面入口（大概在哪）'), ('E', '操作路径存疑（spec-pathfinder，回答一次写入知识库）')]:
        lines += ['## ' + block + ' ' + title, '']
        if block == 'A':
            lines += ['公开文件检查在远程执行，不挂起关联用例；本机先完成编辑器保存和数据准备，交接 remote-checks/request.json。远程回执后恢复并核验数据；到期须续跑或调用恢复命令。请求延迟由浏览器拦截器提供。', '']
        if block == 'B':
            lines += ['配置的测试站可自由编辑、保存和发布；实际可行时恢复快照。清单答案不扩大配置授权。', '']
        subset = [r for r in q['entries'] if r['block'] == block]
        if not subset:
            lines += ['无。', '']
        for row in subset:
            value = answers.get(row['key'], '待回答')
            status = ('已确认可用' if value is True else '已确认缺少／不同意，相关用例挂起' if value is False else value)
            label = row['label'] + (' 大概在哪里进入？（例：内容管理 → 产品 → 编辑）' if block == 'D' else '')
            if block == 'E' and row.get('kind') == 'guided_exploration':
                label += '。请记录一次引导探索看到的入口和现象'
            lines += ['- ' + block + str(row.get('number', 1)) + '. ' + label + '（' + '、'.join(row['cases']) + '）：' + ' / '.join(row['options']) + '。状态：' + str(status)]
        lines += ['']
    lines += ['回答格式：A 除 TC-xxxx 缺少外其余可用，B 同意，C 无歧义，D 页面=大概路径（多项用 D1、D2 或分号分隔），E 按原文可观察或 E1 具体结论 / E 挂起。', '']
    return '\n'.join(lines)


def answer_sentence(base, m, sentence, finalizing=False):
    from .preconditions import QUESTION_KEY
    require(scrub_text(sentence, m['config']) == sentence, '回答含敏感信息，请只回答条件及选项')
    q = m['questions'].get(QUESTION_KEY)
    if m.get('checklist_draft') or (q and q.get('draft')):
        # The human answers once; a draft only means AI work (triage/specs) is unfinished.
        # Keep the sentence and apply it when the checklist is finalized, never ask again for it.
        m['pending_checklist_answer'] = {'sentence': sentence, 'at': now()}
        m.setdefault('interaction_events', []).append({'kind': 'checklist_answer_pending', 'at': now()})
        event(m, 'checklist_answer_deferred')
        return {'answered': 0, 'deferred_until_final': True,
                'instruction': '已保存答复；完成前置分流和全部 case-spec（未知目标可先写 ?名称）后，go 会自动应用这句答复，无需再问。'}
    require(q and not q.get('draft'), '清单仍是草稿；请先分类前置条件并完成规格')
    require(q and (finalizing or q['status'] in {'open', 'deferred'} and not q.get('answered_at')), '没有待回答的开跑前清单；运行中问题请异步审核')
    parts = {a: b.strip(' ，,；;。') for a, b in re.findall(r'(?:^|[，,；;]\s*)([ABC])\s*[:：]?\s*(.*?)(?=(?:[，,；;]\s*[ABCDE](?![A-Za-z])\s*[:：]?)|$)', sentence, re.S)}
    from .entries import parse, store, matches, key as entry_key
    entry_answers = []
    for number, text in re.findall(r'(?:^|[，,；;]\s*)D(\d*)\s*[:：]?\s*(.*?)(?=[，,；;]\s*[ABCDE](?![A-Za-z])|$)', sentence, re.S):
        if number and not re.search(r'[=＝]', text):
            row = next((r for r in q['entries'] if r['block'] == 'D' and r['number'] == int(number)), None)
            require(row, '未知 D 块编号')
            text = row['page'] + '=' + text
        entry_answers += parse(text)
    e_specific, e_blanket = {}, None
    for number, text in re.findall(r'(?:^|[，,；;]\s*)E(\d*)\s*[:：]?\s*(.*?)(?=[，,；;]\s*[ABCD](?![A-Za-z])|$)', sentence, re.S):
        text = text.strip(' ，,；;。')
        if number:
            e_specific[int(number)] = text
        else:
            e_blanket = text
    answers = dict(q.get('answer', {}).get('entries', {}))
    newly_answered = []
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
        elif row['block'] == 'D':
            hint = next((h for h in entry_answers if matches(row['page'], h['label'])), None)
            require(hint, 'D 块请逐项提供 页面=大概路径')
            value = hint['path_text']
        elif row['block'] == 'E':
            value = e_specific.get(row['number'], e_blanket)
            require(value, 'E 块请逐项确认存疑，或回答 E 按原文可观察 / E 挂起')
        else:
            business_count = sum(r['block'] == 'C' for r in q['entries'])
            if business_count > 1:
                segments = dict(re.findall(r'(?:^|[、，,；;])\s*(\d+)\s*[:：=]?\s*(.*?)(?=[、，,；;]\s*\d+|$)', block))
                # A blanket answer ("全部保持原期望" / "无歧义") applies to every C item.
                block = segments.get(str(row['number']), '') or (block if not segments else '')
            chosen = [x for x in row['options'] if x in block]
            if not chosen and re.search(r'无歧义|按原文|保持原期望|都保持', block):
                chosen = [x for x in row['options'] if '原期望' in x or '按原文' in x][:1]
            require(len(chosen) == 1, 'C 块请逐项选择清单中的选项，不接受默认猜测')
            value = chosen[0]
        answers[row['key']] = value
        newly_answered.append(row['key'])
    memory = load_memory(m)
    if entry_answers:
        store(m, entry_answers, 'checklist')
        memory['answers'].update({'entry:' + entry_key(h['label']): h['path_text'] for h in entry_answers})
    from .pathfinder import save_checklist_answers
    save_checklist_answers(m, [r for r in q['entries'] if r['key'] in newly_answered], answers)
    memory['answers'].update(answers)
    memory['updated_at'] = now()
    private = memory_path(m).parent
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    private.chmod(0o700)
    atomic_write(memory_path(m), memory)
    q.update(status='answered', answer={'entries': answers}, answered_at=now())
    q['locally_answered_keys'] = sorted(set(q.get('locally_answered_keys', [])) | set(newly_answered))
    q['memory_answer_keys'] = sorted(set(q.get('memory_answer_keys', [])) - set(newly_answered))
    q['memory_answer_count'] = len(q['memory_answer_keys'])
    m.setdefault('checklist_question_count', len(newly_answered))
    m.setdefault('entry_question_count', sum(r['block'] == 'D' and r['key'] in newly_answered for r in q['entries']))
    m['checklist_issued'] = True
    m.setdefault('interaction_events', []).append({'kind': 'checklist_answer', 'at': now()})
    event(m, 'checklist_answered', entries=len(answers))
    apply_checklist(m, q)
    (base / 'checklist.md').write_text(scrub_text(checklist_text(q), m['config']), encoding='utf-8')
    return {'answered': len(answers), 'waiting': [cid for cid, c in m['cases'].items() if c.get('checklist_wait')], 'memory_saved': True}


def add_review(m, kind, cases, text, **detail):
    key = digest([kind, sorted(cases), text])[:16]
    if kind == 'record_request':
        from .exploration import demo_gate
        demo_gate(m, detail.get('node'), cases, detail.get('interaction'), base=detail.pop('base', None), page=detail.get('page'))
    entry = {'id': key, 'kind': kind, 'case_ids': cases, 'summary': scrub_text(text, m['config']),
             'status': '待审核', 'applied': False, **detail}
    import json
    entry = json.loads(scrub_text(json.dumps(entry, ensure_ascii=False), m['config']))
    m.setdefault('review_items', {})[key] = entry
    return entry


def review(base, m):
    for q in list(m['questions'].values()):
        if q['status'] in {'open', 'deferred'} and q.get('subject') != 'run-preconditions':
            kind = 'record_request' if q['kind'] in {'demo', 'record_request'} else 'new_ambiguity' if q['kind'] == 'product' else 'environment'
            detail = {}
            if kind == 'record_request':
                from .exploration import demo_gate
                try:
                    demo_gate(m, q['subject'], q['case_ids'], q.get('interaction'), page=q.get('page'))
                except UiaError:
                    continue
                detail['node'] = q['subject']
                detail['interaction'] = q.get('interaction')
                detail['page'] = q.get('page')
                detail['command'] = 'node assets/playwright-runner/node_modules/@playwright/test/cli.js codegen --load-storage "$UIA_CODEGEN_STATE" https://www.leadong.com/website.html -o recorded.spec.ts'
                detail['instructions'] = '受保护变量 UIA_CODEGEN_STATE 指向已认证状态；复用登录后录制，只提交脱敏动作脚本，勿录制密码或导出登录态。'
            add_review(m, kind, q['case_ids'], q['prompt'], **detail)
    for cid, c in m['cases'].items():
        if c.get('result') in {'business_failure', 'save_not_persisted'}:
            source = read_json(base / c['source'])
            attempt = c['attempts'][-1]
            read_back = attempt.get('read_back') or {}
            actual = scrub_text('\n'.join(attempt.get('errors', [])), m['config'])
            if read_back:
                actual += ('\n' if actual else '') + '后台读回：' + str(read_back.get('actual', '')) + '；预期：' + str(read_back.get('intended', ''))
            add_review(m, 'suspected_defect', [cid], c['title'], reproduction=source.get('steps'),
                       expected=source.get('expected'), actual=actual or ('远程文件条件不符合；见 remote_checks 回执' if c.get('remote_status') == 'fail' else ''),
                       evidence=attempt['evidence'], screenshot=attempt.get('redacted_screenshot'),
                       screenshot_status='已脱敏' if attempt.get('redacted_screenshot') else '未采集，禁止附原始截图')
        if c.get('stage') == 'discovery' and c.get('work_status') != 'waiting_human':
            add_review(m, 'automation_gap', [cid], '页面目标或数据准备器尚未实现；待限定探索，预算耗尽后再请求录制')
    from .preconditions import QUESTION_KEY
    checklist = m['questions'].get(QUESTION_KEY, {})
    answered_labels = {r['label'] for r in checklist.get('entries', []) if r['key'] in checklist.get('answer', {}).get('entries', {})}
    for entry in m.get('review_items', {}).values():
        if entry['kind'] == 'page_entry':
            from .entries import resolve
            if resolve(entry.get('page', '')):
                entry['status'] = '入口已补充（历史保留）'
        if entry['kind'] in {'new_permission', 'new_ambiguity'} and entry['summary'] in answered_labels:
            entry['status'] = '已答清单'
    for entry in m.get('review_items', {}).values():
        if entry['kind'] == 'record_request' and entry['summary'] == '页面目标或数据准备器尚未实现':
            entry['status'] = '已替换为自动化缺口'
    for entry in m.get('review_items', {}).values():
        owners = [m['cases'][cid] for cid in entry.get('case_ids', []) if cid in m['cases']]
        if entry['kind'] == 'suspected_defect' and owners and all(c.get('result') == 'passed' for c in owners):
            entry['status'] = '已复验通过（历史保留）'
        elif entry['kind'] == 'suspected_defect' and owners and all(c.get('remote_status') in {'pending', 'unreachable', 'still-cached'} and c.get('attempts') and c['attempts'][-1]['result'] == 'passed' for c in owners):
            entry['status'] = '本机原失败已复验，公开文件仍待验证'
        if entry['kind'] == 'automation_gap' and owners and all(c.get('registration') and c.get('stage') != 'discovery' for c in owners):
            entry['status'] = '已补齐（历史保留）'
        if entry['kind'] == 'environment' and not any(q['status'] in {'open', 'deferred'} and q.get('prompt') == entry['summary'] for q in m['questions'].values()):
            entry['status'] = '已恢复（历史保留）'
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
             'record_request': '页面录制请求', 'page_entry': '页面入口待补充', 'new_ambiguity': '新增业务歧义', 'new_permission': '新增权限', 'environment': '环境待处理', 'automation_gap': '自动化缺口（待探索）'}
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


def checklist_notice(checklist):
    """Tell testers why nothing was asked; never claim memory answered an empty checklist."""
    entries = checklist.get('entry_count', 0)
    if checklist.get('question_count'):
        return None
    if not entries:
        return '本次无清单项，0 问'
    return '清单全部来自环境记忆（' + str(entries) + ' 项），本次 0 问' if entries == checklist.get('memory_answer_count', 0) else None


def go(excel, profile=None, cases=None, arm_watch=None, lead_minutes=20, watch_minutes=10, hints=None,
       smoke_size=3, smoke_pass_rate=1.0, first_result_budget_minutes=26, code_root=None, review_only=False):
    from . import workflow, specs, profiles, runtime, reports
    started_at = now()
    require(type(smoke_size) is int and smoke_size >= 1, "smoke size must be a positive integer")
    require(isinstance(smoke_pass_rate, (int, float)) and not isinstance(smoke_pass_rate, bool) and 0 <= float(smoke_pass_rate) <= 1,
            "smoke pass rate must be between 0 and 1")
    require(isinstance(first_result_budget_minutes, (int, float)) and not isinstance(first_result_budget_minutes, bool)
            and first_result_budget_minutes > 0, "first-result budget must be positive")
    source = Path(excel).resolve()
    require(source.is_file(), '工作簿不存在')
    selected = sorted(set(cid.strip() for cid in cases.split(','))) if cases is not None else None
    require(selected is None or selected and all(selected), '用例范围不能为空')
    if not profile:
        candidates = list((ROOT / '.auth/profiles').glob('*.local.json'))
        require(len(candidates) == 1, '请用 --profile 指定已配置环境')
        profile = candidates[0].name.removesuffix('.local.json')
    path = profiles.profile_path(profile)
    key = digest([str(source), str(path)])[:12]
    matches = []
    new_run = False
    for manifest in (ROOT / 'runs').glob('*/run.json'):
        candidate = read_json(manifest)
        source_rows = candidate.get('sources') or []
        same_source = bool(source_rows and Path(source_rows[0].get('path', '')).resolve() == source and source_rows[0].get('sha256') == file_hash(source))
        same_profile = candidate.get('config_path') and Path(candidate['config_path']).resolve() == path.resolve()
        if candidate.get('go_key') == key or (same_source and same_profile and candidate.get('interaction_mode') == 'once'):
            matches.append(manifest)
    if matches:
        manifest = sorted(matches)[0]
    else:
        run_id = 'GO-' + key
        manifest = ROOT / 'runs' / run_id / 'run.json'
        if not manifest.is_file():
            workflow.init(run_id, path)
            new_run = True
    with locked_run(manifest) as (manifest, m):
        base = manifest.parent
        require(not workflow.historical_intent_run(base, m),
                '历史 Intent 运行仅供查看；需要复跑时检出原始项目版本。')
        if new_run:
            m['initial_review_required'] = True
        if m.get('initial_review_required') and not m.get('human_review'):
            review_only = True
        if hints:
            from .entries import handoff
            handoff(m, hints)
        if m.get('active_batch'):
            if hints:
                save(manifest, m)
            from .metrics import exploration_counts
            repeat_count = exploration_counts(m)['re_explored_known_pages']
            return {'run_id': m['run_id'], 'run_reused': bool(matches),
                    'run_selection': '复用同一工作簿与环境的 run；继续已有活动批次' if matches else '使用当前匹配 run；继续已有活动批次',
                    'question_count': 0, 'entry_question_count': 0, 'next': {**workflow.next_task(base, m),
                        **({'process_issue': {'code': 're_explored_known_pages', 'count': repeat_count}} if repeat_count else {})}}
        urgent = [q for q in m['questions'].values() if q.get('status') == 'open' and
                  q.get('kind') == 'exploration' and q.get('urgency') == 'critical']
        if urgent and not review_only:
            if hints:
                save(manifest, m)
            return {'run_id': m['run_id'], 'run_reused': bool(matches),
                    'next': {'action': 'ask_human', 'questions': urgent}}
        previous_selection = m.get('selected_cases')
        m.update(go_key=key, go_source=str(source), go_profile=str(path.resolve()), interaction_mode='once', selected_cases=selected)
        save(manifest, m)
        workflow.scaffold(base)
        if not m['sources'] or m['sources'][0]['sha256'] != file_hash(source) or previous_selection != selected:
            workflow.import_excel(base, m, source)
        from .remote_checks import expire
        if not review_only:
            expire(base, m)
        workflow.refresh(base, m)
        # Reuse only source-fingerprint-matched example contracts, never by case ID alone.
        index = ROOT / 'examples/phase2/index.json'
        matched = []
        for cid, item in (read_json(index).items() if index.is_file() else []):
            c = m['cases'].get(cid)
            if c and c['source_hash'] == item['source_hash']:
                dest = specs.spec_path(base, c)
                if not dest.is_file():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / item['spec'], dest)
                    c['case_spec'] = str(dest.relative_to(base))
                    matched.append(cid)
                elif c.get('spec_generation_blocked') or not (c.get('registration') or {}).get('case_spec'):
                    matched.append(cid)
        # Retrieval is a fixed pre-generation step, including source-only matches.
        from .knowledge import match_run
        match_run(base, m)
        # Lint and compile matched contracts before legacy scripts claim imported cases.
        if matched and not review_only:
            lint = specs.lint(base, m, matched)
            for cid in matched:
                if not m['cases'][cid].get('spec_lint', {}).get('errors'):
                    try:
                        specs.generate(base, m, cid)
                        m['cases'][cid].pop('spec_generation_blocked', None)
                    except UiaError as error:
                        # Binding below records a visible legacy fallback and duplicate.
                        m['cases'][cid]['spec_generation_blocked'] = scrub_text(str(error), m['config'])
        workflow.bind_specs(base, m)
        from .pathfinder import compile_run, project_specs
        if code_root:
            require(Path(code_root).expanduser().is_dir(), '项目代码路径不是目录')
        try:
            compile_run(base, m, code_root=str(Path(code_root).expanduser()) if code_root else None)
        except UiaError as error:
            if not review_only or str(error) != '人审版或存疑说明混入了代码串':
                raise
            from .review_page import render
            checklist = sync_checklist(base, m)
            page = render(base, m)
            save(manifest, m)
            return {'run_id': m['run_id'], **checklist, **page, 'review_only': True, 'draft': True,
                    'preparation_error': str(error), 'next': {'action': 'prepare_review'}}
        project_specs(base, m)
        # A legacy script that substitutes editor values for a public-file assertion is
        # incompatible with the source-matched deferred contract. Preserve its history,
        # then compile the contract instead of silently running the partial legacy test.
        for cid, c in m['cases'].items():
            contract = specs.spec_path(base, c)
            if c.get('daily_spec') and contract.is_file():
                spec = read_yaml(contract)
                if any(s.get('verb') == 'defer_public' for s in spec.get('steps', [])):
                    from .common import reset_case
                    c.update(registration=None, daily_spec=False, case_spec=str(contract.relative_to(base)))
                    reset_case(c, 'legacy_script_missing_public_assertions', 'spec')
        m['checklist_draft'] = any(not specs.spec_path(base, c).is_file() and not c.get('registration') for c in m['cases'].values())
        checklist = sync_checklist(base, m)
        if not checklist['draft']:
            m['checklist_issued'] = True
            m.setdefault('checklist_question_count', checklist['question_count'])
            m.setdefault('entry_question_count', checklist['entry_question_count'])
            pending = m.get('pending_checklist_answer')
            from .preconditions import QUESTION_KEY as _QK
            q = m['questions'].get(_QK)
            if pending and q:
                try:
                    applied = answer_sentence(base, m, pending['sentence'], finalizing=True)
                    m.pop('pending_checklist_answer', None)
                    event(m, 'checklist_pending_answer_applied', answered=applied.get('answered'))
                except UiaError as exc:
                    pending['error'] = str(exc)
                compile_run(base, m, code_root=str(Path(code_root).expanduser()) if code_root else None)
                project_specs(base, m)
                checklist = sync_checklist(base, m)
        from .review_page import render as render_review_page
        review_page = render_review_page(base, m) if review_only or not checklist['draft'] else {}
        if review_only:
            save(manifest, m)
            return {'run_id': m['run_id'], **checklist, **review_page, 'review_only': True,
                    'next': {'action': 'prepare_review' if checklist['draft'] else 'review'}}
        urgent = [q for q in m['questions'].values() if q.get('status') == 'open' and
                  q.get('kind') == 'exploration' and q.get('urgency') == 'critical']
        if urgent:
            save(manifest, m)
            return {'run_id': m['run_id'], 'run_reused': bool(matches), **review_page,
                    'next': {'action': 'ask_human', 'questions': urgent}}
        # Environment preflight is the first execution gate: login, site, and the content editor.
        m['gates'] = {'smoke_size': smoke_size, 'smoke_pass_rate': float(smoke_pass_rate),
                      'first_result_budget_minutes': float(first_result_budget_minutes)}
        m['go_started_at'] = started_at
        from .environment_gate import preflight_run
        gate = preflight_run(base, m)
        save(manifest, m)
        if gate.get('status') == 'blocked':
            output = reports.make_report(base, m)
            save(manifest, m)
            return {'run_id': m['run_id'], 'run_reused': bool(matches), 'environment_blocked': True,
                    'failure_class': 'environment', 'reason': gate.get('reason'), 'preflight': m.get('preflight'),
                    'report': output, 'spec_tasks': [], **review_page,
                    'next': {'action': 'environment_blocked', 'instruction': '环境预检未通过，未执行用例。'}}
        workflow.refresh(base, m)
        ready = [cid for cid, c in m['cases'].items() if c['work_status'] == 'runnable'
                 and not c.get('case_spec') and not workflow.unbound_review_ids(m, c, base)]
        armed = _arm_requested_watches(base, m, arm_watch, lead_minutes, watch_minutes)
        save(manifest, m)
    # Existing runnable scripts get the first batch, before new generation.
    if ready:
        _execute_ready(manifest, ready, full_batch=selected is None, smoke_size=smoke_size,
                       smoke_pass_rate=float(smoke_pass_rate), budget_minutes=float(first_result_budget_minutes),
                       started_at=started_at)
    with locked_run(manifest) as (manifest, m):
        base = manifest.parent
        if m.get('initial_review_required') or not checklist['question_count']:
            for cid, c in m['cases'].items():
                if c.get('work_status') == 'waiting_human' or workflow.unbound_review_ids(m, c, base) or not specs.spec_path(base, c).is_file() or (c.get('registration') or {}).get('case_spec') or c.get('result'):
                    continue
                # Keep compatible daily scripts; only missing scripts need template compilation.
                if c.get('registration') and not c.get('case_spec'):
                    continue
                if (read_yaml(specs.spec_path(base, c)) or {}).get('questions'):
                    specs.lint(base, m, [cid])
                    continue
                try:
                    specs.generate(base, m, cid)
                except UiaError as error:
                    missing = workflow.unresolved_targets(base, m, c) + workflow.missing_catalog_targets(base, c)
                    if missing:
                        # Missing controls are an exploration task, not a generation verdict.
                        c['spec_generation_blocked'] = scrub_text(str(error), m['config'])
                        c['work_status'] = 'pending'
                        c.pop('classification', None)
                    else:
                        c.update(work_status='waiting_human', classification={'reason': scrub_text(str(error), m['config'])})
                        add_review(m, 'new_ambiguity', [cid], 'case-spec/生成门禁：' + str(error), details=error.details)
            sync_checklist(base, m)
        tasks = [{'case_id': cid, 'source': c['source'], 'action': '编写 case-spec'} for cid, c in m['cases'].items() if not specs.spec_path(base, c).is_file() and not c.get('registration')]
        m['spec_tasks'] = tasks
        save(manifest, m)
        workflow.refresh(base, m)
        ready = [cid for cid, c in m['cases'].items() if c['work_status'] == 'runnable'
                 and not workflow.unbound_review_ids(m, c, base)]
    if ready:
        _execute_ready(manifest, ready, full_batch=selected is None, smoke_size=smoke_size,
                       smoke_pass_rate=float(smoke_pass_rate), budget_minutes=float(first_result_budget_minutes),
                       started_at=started_at)
    with locked_run(manifest) as (manifest, m):
        output = reports.make_report(manifest.parent, m)
        save(manifest, m)
        memory_note = checklist_notice(checklist)
        from .metrics import exploration_counts
        exploration_metric = exploration_counts(m)
        open_questions = [q for q in m['questions'].values() if q.get('status') == 'open' and q.get('kind') == 'exploration']
        actionable = any(c.get('work_status') not in {'waiting_human', 'finished'} and not c.get('result')
                         for c in m['cases'].values())
        ask_now = bool(open_questions and not actionable)
        if m.get('initial_review_required'):
            next_action = workflow.next_task(manifest.parent, m)
            save(manifest, m)
            return {'run_id': m['run_id'], 'run_reused': bool(matches), 'spec_tasks': tasks,
                    'report': output, 'armed_watches': armed, **review_page, 'next': next_action}
        return {'run_id': m['run_id'], 'run_reused': bool(matches),
                'run_selection': '复用同一工作簿与环境的 run；用例子集已更新' if matches else '新建 run；当前环境和工作簿没有匹配的既有 run',
                'checklist_message': memory_note, **checklist, **review_page, 'spec_tasks': tasks, 'report': output, 'armed_watches': armed,
                'pathfinder': {'stage': (m.get('pathfinder') or {}).get('stage'),
                               'requirements': [row.get('name') for row in (m.get('pathfinder') or {}).get('requirements') or []],
                               'guided': (m.get('pathfinder') or {}).get('guided') or [],
                               'output_dir': (m.get('pathfinder') or {}).get('output_dir')},
                'smoke': m.get('smoke'), 'abort': m.get('abort'),
                'next': {'action': 'ask_human' if ask_now else 'classify_preconditions' if checklist['unclassified'] else 'complete_spec_tasks' if checklist['draft'] else 'answer_checklist' if checklist['question_count'] else 'continue_spec_tasks_or_review', 'unclassified': checklist['unclassified'], 'ai_tasks': checklist['ai_tasks'], 'mid_run_questions': sum(e.get('kind') == 'mid_run_question' for e in m.get('interaction_events', [])),
                         **({'questions': open_questions} if ask_now else {}),
                         **({'process_issue': {'code': 're_explored_known_pages', 'count': exploration_metric['re_explored_known_pages']}} if exploration_metric['re_explored_known_pages'] else {}),
                         'exploration_for_missing_controls': exploration_metric['exploration_for_missing_controls'],
                         **({'present_checklist': False, 'instruction': '清单仍是草稿：不要向人展示或提问；先分类全部前置条件并写完全部 case-spec（未知目标写 ?名称），再次运行 go 得到最终清单后一次性展示。'} if checklist['draft'] else {'present_checklist': bool(checklist['question_count'])})}}


def _arm_requested_watches(base, m, arm_watch, lead_minutes, watch_minutes):
    """Arm remote watches before any batch, and announce the hand-off directory immediately."""
    if not arm_watch:
        return []
    import json, sys
    from .remote_checks import arm_watch as arm
    armed = []
    for cid in [x.strip() for x in arm_watch.split(',') if x.strip()]:
        require(cid in m['cases'], 'arm-watch case is not in this run: ' + cid)
        require(m['cases'][cid].get('work_status') == 'runnable', 'arm-watch case must be runnable (reset it with spec gen first): ' + cid)
        result = arm(base, m, cid, lead_minutes, watch_minutes)
        row = m['remote_watches'][result['watch_id']]
        armed.append({'case_id': cid, 'watch_dir': str((base / result['request']).parent),
                      'save_not_before': row['save_not_before'], 'watch_until': row['watch_until']})
    atomic_write(base / 'remote-checks/watch/ARMED.json', armed)
    # go blocks until the save window; the hand-off must be visible before that.
    print(json.dumps({'armed_watches': armed}, ensure_ascii=False), file=sys.stderr, flush=True)
    return armed


def representative_cases(cases, size):
    """Spread a smoke sample across modules, preferring higher priority."""
    priority = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    ordered = sorted(cases, key=lambda case: (priority.get(str(case.get("priority") or "P9").upper(), 9), str(case.get("case_id"))))
    picked, seen = [], set()
    for case in ordered:
        group = case.get("module") or case.get("sheet") or case.get("case_id")
        if group in seen:
            continue
        seen.add(group)
        picked.append(case["case_id"])
        if len(picked) == size:
            return picked
    for case in ordered:
        if case["case_id"] not in picked:
            picked.append(case["case_id"])
        if len(picked) == size:
            break
    return picked


def split_smoke(ready, cases, smoke_size, full_batch, smoke_state):
    """Return ``(first_batch, remainder)``. Remainder runs only after the smoke bar is met."""
    ready = list(ready)
    if not ready:
        return [], []
    state = smoke_state or {}
    if not full_batch or len(cases) <= smoke_size or state.get("status") == "accepted":
        return ready, []
    if state.get("status") in {"rejected", "aborted"}:
        return [], []
    chosen = [cid for cid in representative_cases(cases, smoke_size) if cid in set(ready)]
    for cid in ready:
        if len(chosen) >= min(smoke_size, len(ready)):
            break
        if cid not in chosen:
            chosen.append(cid)
    chosen = chosen[:smoke_size]
    return chosen, [cid for cid in ready if cid not in chosen]


def _smoke_rate(m, ids):
    rows = [m["cases"][cid] for cid in ids if cid in m["cases"] and m["cases"][cid].get("result")]
    if not rows:
        return None
    return sum(case.get("result") == "passed" for case in rows) / len(rows)


def first_result_exceeded(m, budget_minutes, started_at):
    finished = m.get("first_result_at")
    if not finished or not budget_minutes:
        return False
    sources = m.get("sources") or []
    start = next((row.get("imported_at") for row in sources if row.get("imported_at")), None) or started_at or m.get("created_at")
    if not start:
        return False
    return elapsed(start, finished) > float(budget_minutes) * 60


def _execute_ready(manifest, ready, *, full_batch, smoke_size, smoke_pass_rate, budget_minutes, started_at):
    with locked_run(manifest) as (_path, m):
        first, rest = split_smoke(ready, list(m["cases"].values()), smoke_size, full_batch, m.get("smoke"))
    if not first:
        return
    _run_ready(manifest, first)
    with locked_run(manifest) as (path, m):
        aborted = bool(m.get("abort"))
        if rest:
            rate = _smoke_rate(m, first)
            if aborted:
                status = "aborted"
            elif rate is None or rate + 1e-9 >= smoke_pass_rate:
                status = "accepted"
            else:
                status = "rejected"
            m["smoke"] = {"case_ids": list(first), "pass_rate": rate, "bar": smoke_pass_rate,
                          "status": status, "at": now()}
            save(path, m)
            if status != "accepted":
                return
        elif aborted:
            return
    if rest:
        _run_ready(manifest, rest)


def _run_ready(manifest, ready):
    from . import runtime
    from .common import read_yaml
    with locked_run(manifest) as (_path, m):
        base = manifest.parent
        independent, deferred = [], []
        for cid in ready:
            c = m['cases'].get(cid, {})
            spec_path = c.get('case_spec')
            spec = read_yaml(base / spec_path) if spec_path and (base / spec_path).is_file() else {}
            (deferred if any(s.get('verb') == 'defer_public' for s in spec.get('steps', [])) else independent).append(cid)
        ready = independent + deferred
        has_deferred = bool(deferred)
        held_ids = set(deferred)
    while ready:
        with locked_run(manifest) as (path, m):
            if not m.get('preflight') or m['preflight']['status'] != 'passed':
                return
            size = m['config']['execution']['batch_size']
            selected = ready[:size]
            ready = ready[len(selected):]
            if any(cid in held_ids for cid in selected) and any(cid not in held_ids for cid in selected):
                deferred_part = [cid for cid in selected if cid in held_ids]
                selected = [cid for cid in selected if cid not in held_ids]
                ready = deferred_part + ready
            selected = [cid for cid in selected if m['cases'][cid]['work_status'] == 'runnable']
            if not selected:
                continue
            if any(cid in held_ids for cid in selected):
                from .remote_checks import hold_path, persist_hold
                if not hold_path(m).is_file():
                    persist_hold(m, sorted(held_ids))
            from .remote_checks import timestamp, wait_for_watch
            armed = [row for row in m.get('remote_watches', {}).values()
                     if row.get('status') == 'armed' and row.get('case_id') in selected]
            for row in armed:
                remaining = (timestamp(row['save_not_before']) - dt.datetime.now(dt.timezone.utc)).total_seconds()
                require(remaining <= 3600, 'Armed watch is more than 60 minutes away; refusing to wait')
            batch = runtime.begin_batch(path.parent, m, selected, headed=bool(m.get('initial_review_required')))
            cfg = m['config']; save(path, m)
        for row in armed:
            def beat(watch, seconds):
                body = {'batch_id': batch['id'], 'case_ids': list(batch['case_ids']), 'completed': [],
                        'running': True, 'waiting_for_watch': watch['watch_id'],
                        'remaining_seconds': round(seconds), 'updated_at': now()}
                atomic_write(path.parent / 'heartbeat.json', body)
                atomic_write(path.parent / batch['directory'] / 'heartbeat.json', body)
            wait_for_watch(path.parent, row, heartbeat=beat)
        code = runtime.execute_process(path.parent, batch, cfg)
        with locked_run(manifest) as (path, m):
            runtime.consume_batch(path.parent, m, code)
            budget_minutes = (m.get("gates") or {}).get("first_result_budget_minutes")
            started_at = m.get("go_started_at")
            if first_result_exceeded(m, budget_minutes, started_at):
                sources = m.get("sources") or []
                start = next((row.get("imported_at") for row in sources if row.get("imported_at")), None) or started_at
                m["abort"] = {"reason": "first_result_budget", "budget_minutes": budget_minutes,
                              "elapsed_seconds": elapsed(start, m["first_result_at"]) if start and m.get("first_result_at") else None,
                              "at": now()}
                save(path, m)
                return
            save(path, m)
    if has_deferred:
        with locked_run(manifest) as (path, m):
            from .remote_checks import finalize
            finalize(path.parent, m)
            save(path, m)
