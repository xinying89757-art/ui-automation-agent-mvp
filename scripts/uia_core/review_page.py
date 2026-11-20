"""Render the shared human review page and receive its structured decisions."""

import json
from pathlib import Path
from urllib.parse import urlsplit

from .common import atomic_write, digest, event, file_hash, inside, read_json, require
from .preconditions import QUESTION_KEY
from .secrets import scrub_text

TEMPLATE = Path(__file__).resolve().parents[2] / 'skills/spec-pathfinder/review/workbench.html'
INPUT = 'review-input.json'
RESULT = 'review-decisions.json'
HANDOFF = 'review-handoff.json'


def _text(value):
    if isinstance(value, list):
        value = '\n'.join(str(part) for part in value)
    return str(value or '').replace('\\n', '\n')


def _review_items(rows, case_ids, kind):
    require(isinstance(rows, list), f'{kind} must be a list')
    items = {}
    for row in rows:
        require(isinstance(row, dict), f'Invalid {kind} entry')
        key = row.get('id')
        owners = row.get('cases')
        title = row.get('title')
        require(isinstance(key, str) and key.strip() and key not in items and key not in case_ids,
                f'Invalid or repeated review ID: {key}')
        require(isinstance(title, str) and title.strip(), f'Missing review title: {key}')
        require(isinstance(owners, list) and owners and all(isinstance(cid, str) and cid in case_ids for cid in owners),
                f'Review item must reference cases in this run: {key}')
        item = {'id': key, 'title': title, 'cases': list(dict.fromkeys(owners)),
                'description': _text(row.get('description')), 'source': _text(row.get('source'))}
        if row.get('link'):
            link = _text(row['link'])
            url = urlsplit(link)
            require(url.scheme == 'https' and url.hostname and not url.username and not url.password,
                    f'Review source links must use HTTPS: {key}')
            item['link'] = link
        if kind == 'checks':
            checks = row.get('checks')
            require(isinstance(checks, list) and checks and all(isinstance(check, str) and check.strip() for check in checks),
                    f'Missing expected checks: {key}')
            item['checks'] = checks
        else:
            item['answer'] = _text(row.get('answer'))
            item['status'] = 'confirmed' if item['answer'] else 'pending'
        items[key] = item
    return items


def _payload(base, run):
    input_path = base / INPUT
    supplied = read_json(input_path) if input_path.is_file() else {}
    require(isinstance(supplied, dict), 'Review input must be a JSON object')
    cases = []
    versions = {}
    deferred = {}
    for cid, case in run['cases'].items():
        source = read_json(inside(base, case['source'])) if case.get('source') else {}
        rows = '、'.join(map(str, case.get('rows', [])))
        location = f"{case.get('sheet', '')} · 第 {rows} 行" if rows else case.get('sheet', '')
        display_id = case.get('original_id') or f'用例 {len(cases) + 1:02d}'
        cases.append({'id': cid, 'displayId': display_id, 'title': case.get('title') or cid, 'source': location,
                      'pre': _text(source.get('preconditions')), 'steps': _text(source.get('steps')),
                      'expected': _text(source.get('expected'))})
        versions[cid] = [case.get('source_hash'), file_hash(inside(base, case['case_spec'])) if case.get('case_spec') else None]
        if case.get('result') == 'suspended':
            deferred[cid] = case.get('classification', {}).get('reason') or '用例已暂缓'
    case_ids = set(versions)
    checklist = run['questions'].get(QUESTION_KEY, {})
    answers = checklist.get('answer', {}).get('entries', {})
    auto = []
    for row in checklist.get('entries', []):
        owners = [cid for cid in row['cases'] if cid in case_ids and cid not in deferred]
        if not owners:
            continue
        page = row.get('page')
        title = f'从哪里进入「{page}」？' if page else row['label']
        options = ' / '.join(map(str, row.get('options', [])))
        value = answers.get(row['key'])
        if isinstance(value, bool):
            answer = ('同意' if value else '不同意') if row['block'] == 'B' else ('可用' if value else '暂缺')
        else:
            answer = value
        auto.append({'id': row['key'], 'title': title, 'cases': owners, 'answer': answer,
                     'description': f'可参考的答复　{options}' if options else ''})
    automatic = _review_items(auto, case_ids, 'questions')
    questions = _review_items(supplied.get('questions', []), case_ids, 'questions')
    checks = _review_items(supplied.get('checks', []), case_ids, 'checks')
    questions = {**automatic, **questions}
    require(not set(questions) & set(checks), 'Questions and checks share a review ID')
    for item in (*questions.values(), *checks.values()):
        if all(cid in deferred for cid in item['cases']):
            item['status'] = 'deferred'
            item['answer'] = '关联用例已暂缓'
    payload = {'runId': run['run_id'], 'title': _text(supplied.get('title')) or run['run_id'],
               'cases': cases, 'questions': list(questions.values()), 'checks': list(checks.values()),
               'deferred': deferred}
    cfg = run.get('config')
    for item in (*cases, *questions.values(), *checks.values()):
        for field in ('displayId', 'title', 'source', 'pre', 'steps', 'expected', 'description', 'link', 'answer'):
            if field in item:
                item[field] = scrub_text(item[field], cfg)
        if 'checks' in item:
            item['checks'] = [scrub_text(check, cfg) for check in item['checks']]
    payload['title'] = scrub_text(payload['title'], cfg)
    payload['deferred'] = {cid: scrub_text(reason, cfg) for cid, reason in deferred.items()}
    payload['revision'] = digest([payload, versions])
    return payload


def render(base, run):
    payload = _payload(base, run)
    review = run.get('human_review') or {}
    if review.get('revision') == payload['revision']:
        payload['savedDecisions'] = {item['id']: {'status': item['status'], 'text': item['value']}
                                     for item in review['decisions']}
    html = TEMPLATE.read_text(encoding='utf-8')
    # Treat all workbook and reviewer content as inert data, including script end tags.
    data = json.dumps(payload, ensure_ascii=False).replace('<', r'\u003c')
    path = base / 'review.html'
    path.write_text(html.replace('__REVIEW_DATA__', data, 1), encoding='utf-8')
    return {'review_page': str(path), 'review_revision': payload['revision'],
            'review_questions': len(payload['questions']), 'review_checks': len(payload['checks'])}


def _handoff(payload, decisions, pending, source):
    by_case = {case['id']: {'case_id': case['id'], 'display_id': case['displayId'],
                            'decisions': [], 'pending': [], 'processing': 'not_applied'}
               for case in payload['cases']}
    for item in decisions:
        for cid in item['cases']:
            by_case[cid]['decisions'].append(item)
    for item in pending:
        for cid in item['cases']:
            by_case[cid]['pending'].append({'id': item['id'], 'title': item['title']})
    return {'run_id': payload['runId'], 'revision': payload['revision'],
            'source': source, 'cases': list(by_case.values())}


def ingest(base, run, path):
    payload = _payload(base, run)
    report = read_json(path)
    require(isinstance(report, dict) and report.get('review_version') == 1 and
            report.get('run_id') == run['run_id'] and report.get('revision') == payload['revision'],
            '审核结果与当前运行或审核版本不一致，请使用当前页面导出')
    questions = payload['questions']
    checks = payload['checks']
    cases = [{'id': case['id'], 'title': case['title'], 'cases': [case['id']]} for case in payload['cases']]
    items = {item['id']: (kind, item) for kind, group in (('question', questions), ('check', checks), ('case', cases))
             for item in group}
    decisions = report.get('decisions')
    require(isinstance(decisions, list), '审核结果缺少 decisions')
    received = {}
    for row in decisions:
        require(isinstance(row, dict) and isinstance(row.get('review_id'), str), '无效审核决定')
        key = row['review_id']
        require(key in items and key not in received, f'审核项不存在或重复：{key}')
        kind, item = items[key]
        require(row.get('case_ids') == item['cases'], f'关联用例不匹配：{key}')
        value = row.get('value')
        statuses = ('edited',) if kind == 'case' else ('confirmed', 'edited', 'deferred')
        require(row.get('status') in statuses and isinstance(value, str) and value.strip(),
                f'审核决定缺少状态或内容：{key}')
        require(scrub_text(value, run.get('config')) == value, '审核决定中包含敏感内容')
        received[key] = {'id': key, 'kind': kind, 'title': item['title'], 'cases': item['cases'],
                         'status': row['status'], 'value': value}
    pending = [item for item in [*questions, *checks] if item['id'] not in received]
    result = {'run_id': run['run_id'], 'revision': payload['revision'],
              'source_files': {cid: file_hash(inside(base, case['source'])) for cid, case in run['cases'].items() if case.get('source')},
              'decisions': list(received.values()), 'pending': pending}
    handoff = _handoff(payload, received.values(), pending, RESULT)
    if run.get('human_review') != result:
        run['human_review'] = result
        event(run, 'human_review_received', decisions=len(received), pending=len(pending))
    atomic_write(base / RESULT, result)
    atomic_write(base / HANDOFF, handoff)
    return {'review_decisions': str(base / RESULT), 'decisions': list(received.values()), 'pending': pending,
            'review_handoff': str(base / HANDOFF),
            'next': 'apply_review_decisions'}


def ingest_prototype(base, run, path, mapping_path):
    """Reconcile an unversioned prototype export without claiming current-page approval."""
    payload = _payload(base, run)
    report, mapping = read_json(path), read_json(mapping_path)
    require(isinstance(report, dict) and report.get('review_version') == 1 and
            report.get('run_id') == run['run_id'] and 'revision' not in report,
            '仅支持本运行缺少版本号的原型导出')
    require(isinstance(mapping, dict) and mapping and all(isinstance(k, str) and isinstance(v, str)
            for k, v in mapping.items()) and len(set(mapping.values())) == len(mapping), '映射必须是一对一 ID 对象')
    items = {item['id']: (kind, item) for kind, group in
             (('question', payload['questions']), ('check', payload['checks'])) for item in group}
    rows = report.get('decisions')
    require(isinstance(rows, list) and rows, '原型导出缺少审核决定')
    require(set(mapping) == {row.get('review_id') for row in rows if isinstance(row, dict)},
            '映射必须覆盖且仅覆盖全部原型审核项')
    received = {}
    for row in rows:
        require(isinstance(row, dict), '无效审核决定')
        old = row.get('review_id')
        key = mapping.get(old)
        require(key in items and key not in received, f'审核项不存在或重复：{old}')
        kind, item = items[key]
        require(row.get('case_ids') == item['cases'], f'关联用例不匹配：{old}')
        status, value = row.get('status'), row.get('value')
        require(status in ('confirmed', 'edited', 'deferred') and isinstance(value, str) and value.strip(),
                f'审核决定缺少状态或内容：{old}')
        require(scrub_text(value, run.get('config')) == value, '审核决定中包含敏感内容')
        # A confirmation applies only when its original displayed content still matches.
        if status == 'confirmed':
            expected = '\n'.join(item['checks']) if kind == 'check' else item.get('answer', '')
            require(value == expected, f'已确认内容与当前审核项不一致：{old}')
        received[key] = {'id': key, 'prototype_id': old, 'kind': kind, 'title': item['title'],
                         'cases': item['cases'], 'status': status, 'value': value}
    pending = [item for item in [*payload['questions'], *payload['checks']] if item['id'] not in received]
    deferred = report.get('deferred_cases', [])
    require(isinstance(deferred, list) and all(isinstance(row, dict) and row.get('id') in run['cases']
            and isinstance(row.get('reason'), str) and row['reason'].strip() for row in deferred), '无效的原型暂缓用例')
    require(all(scrub_text(row['reason'], run.get('config')) == row['reason'] for row in deferred), '暂缓原因中包含敏感内容')
    result = {'run_id': run['run_id'], 'source_kind': 'unversioned_prototype',
              'source_sha256': file_hash(path), 'mapping_sha256': file_hash(mapping_path),
              'current_snapshot_revision': payload['revision'], 'reviewed_revision': None,
              'source_files': {cid: file_hash(inside(base, case['source'])) for cid, case in run['cases'].items() if case.get('source')},
              'decisions': list(received.values()), 'pending': pending, 'deferred_cases': deferred}
    handoff = _handoff(payload, received.values(), pending, 'review-prototype-decisions.json')
    handoff['reviewed_revision'] = None
    handoff['source_kind'] = 'unversioned_prototype'
    atomic_write(base / 'review-prototype-decisions.json', result)
    atomic_write(base / 'review-prototype-handoff.json', handoff)
    if run.get('prototype_review') != result:
        run['prototype_review'] = result
        event(run, 'prototype_review_reconciled', decisions=len(received), pending=len(pending))
    return {'review_decisions': str(base / 'review-prototype-decisions.json'),
            'review_handoff': str(base / 'review-prototype-handoff.json'),
            'decisions_received': len(received), 'pending': len(pending),
            'reviewed_revision': None, 'next': 'apply_review_decisions'}


def validate_plan(base, run, path):
    """Validate case-level interpretation coverage; no plan is an executable spec."""
    plan = read_json(path)
    require(isinstance(plan, dict) and plan.get('run_id') == run['run_id'], '处理计划与运行不匹配')
    source_name = plan.get('review_source')
    require(source_name in (RESULT, 'review-prototype-decisions.json'), '未知审核答复来源')
    source_path = inside(base, source_name)
    source = read_json(source_path)
    require(source.get('run_id') == run['run_id'] and plan.get('review_source_sha256') == file_hash(source_path),
            '处理计划所依据的审核答复已变化')
    required = {(decision['id'], cid) for decision in source['decisions'] for cid in decision['cases']}
    rows = plan.get('items')
    require(isinstance(rows, list), '处理计划缺少 items')
    pairs = set()
    for row in rows:
        require(isinstance(row, dict), '无效处理计划项')
        pair = (row.get('review_id'), row.get('case_id'))
        require(pair in required and pair not in pairs, f'处理计划编号不存在或重复：{pair}')
        pairs.add(pair)
        require(row.get('disposition') in ('implement', 'partial_exclusion', 'exclude', 'blocked'),
                f'无效处理方式：{pair}')
        for field in ('scope', 'instruction'):
            value = row.get(field)
            require(isinstance(value, str) and value.strip() and scrub_text(value, run.get('config')) == value,
                    f'处理计划缺少安全的 {field}：{pair}')
    require(pairs == required, '处理计划未覆盖全部审核决定与关联用例',
            {'missing': sorted(required - pairs)})
    result = {'run_id': run['run_id'], 'review_source': source_name,
              'review_source_sha256': plan['review_source_sha256'], 'plan_sha256': file_hash(path),
              'items': len(rows), 'state': 'planned_not_applied'}
    atomic_write(base / 'review-plan-validation.json', result)
    return {**result, 'next': 'implement_plan_and_lint_specs'}


def apply_entry(base, run, cid, review_id, source='current'):
    """Apply one reviewed entry to its matching run-local checklist, never to shared KB."""
    require(cid in run['cases'], '审核用例不存在')
    review = run.get('prototype_review' if source == 'prototype' else 'human_review') or {}
    revision = review.get('current_snapshot_revision' if source == 'prototype' else 'revision')
    current_revision = _payload(base, run)['revision']
    existing = run.get('review_applications', {}).get(review_id) or {}
    if existing.get('source') == source and cid in existing.get('case_ids', []) and existing.get('post_revision') == current_revision:
        existing.setdefault('source_files', {owner: file_hash(inside(base, run['cases'][owner]['source'])) for owner in existing['case_ids']})
        return {'review_id': review_id, 'case_ids': existing['case_ids'], 'source': source,
                'reviewed_revision': existing.get('reviewed_revision'), 'next': 'write_case_spec', 'already_applied': True}
    require(revision and revision == current_revision, '审核材料或运行已变化，请重新核对')
    decisions = [row for row in review.get('decisions', []) if row.get('id') == review_id and
                 row.get('kind') == 'question' and row.get('status') in {'confirmed', 'edited'}]
    require(len(decisions) == 1 and cid in decisions[0].get('cases', []), '审核答复不适用于该用例')
    q = run.get('questions', {}).get(QUESTION_KEY) or {}
    rows = [row for row in q.get('entries', []) if row.get('key') == review_id and row.get('block') == 'D']
    require(len(rows) == 1 and cid in rows[0].get('cases', []) and
            set(rows[0]['cases']) <= set(decisions[0]['cases']), '清单入口与审核答复范围不匹配')
    answer = decisions[0]['value']
    require(isinstance(answer, str) and answer.strip(), '审核答复为空')
    answers = q.setdefault('answer', {}).setdefault('entries', {})
    require(review_id not in answers or answers[review_id] == answer, '清单已有不同答复，不能覆盖')
    answers[review_id] = answer
    q.setdefault('locally_answered_keys', [])
    if review_id not in q['locally_answered_keys']:
        q['locally_answered_keys'].append(review_id)
    run.setdefault('review_applications', {})[review_id] = {'case_ids': rows[0]['cases'],
        'source': source, 'reviewed_revision': review.get('reviewed_revision', review.get('revision')),
        'source_sha256': review.get('source_sha256'), 'value': answer,
        'source_files': {owner: file_hash(inside(base, run['cases'][owner]['source'])) for owner in rows[0]['cases']}}
    from .experience import sync_checklist
    sync_checklist(base, run)
    run['review_applications'][review_id]['post_revision'] = _payload(base, run)['revision']
    event(run, 'review_entry_applied', review_id=review_id, case_ids=rows[0]['cases'], source=source)
    return {'review_id': review_id, 'case_ids': rows[0]['cases'], 'source': source,
            'reviewed_revision': review.get('reviewed_revision', review.get('revision')),
            'next': 'write_case_spec'}


def bind_case(base, run, cid, review_ids, source='current'):
    from .specs import lint, spec_path
    require(cid in run['cases'] and len(review_ids) == len(set(review_ids)), '无效用例或重复审核项')
    review = run.get('prototype_review' if source == 'prototype' else 'human_review') or {}
    applications = run.get('review_applications', {})
    anchors = [row for row in applications.values() if row.get('source') == source and cid in row.get('case_ids', [])]
    current_source = file_hash(inside(base, run['cases'][cid]['source']))
    reviewed_source = review.get('source_files', {}).get(cid)
    if reviewed_source:
        require(reviewed_source == current_source, '审核后的用例原文已变化')
    else:
        # Compatibility for previously reconciled prototypes that predate per-case hashes.
        require(anchors and all(row.get('source_files', {}).get(cid) == current_source for row in anchors),
                '缺少来源未变化的审核记录')
    for key in review_ids:
        rows = [row for row in review.get('decisions', []) if row.get('id') == key and
                cid in row.get('cases', []) and row.get('status') in {'confirmed', 'edited'}]
        require(len(rows) == 1, '审核项未确认或不属于该用例：' + key)
    result = lint(base, run, [cid])
    require(not result['errors'] and not result['cases'][cid]['errors'], '用例规格校验失败', result)
    run['cases'][cid]['review_binding'] = {'source': source, 'review_ids': review_ids,
        'reviewed_revision': review.get('reviewed_revision', review.get('revision')),
        'source_sha256': review.get('source_sha256'), 'source_file_sha256': file_hash(inside(base, run['cases'][cid]['source'])),
        'spec_sha256': file_hash(spec_path(base, run['cases'][cid]))}
    event(run, 'review_case_bound', case_id=cid, review_ids=review_ids, source=source)
    return {'case_id': cid, 'review_binding': run['cases'][cid]['review_binding'], 'next': 'generate_or_register_spec'}
