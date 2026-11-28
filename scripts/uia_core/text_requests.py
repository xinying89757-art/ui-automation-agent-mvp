"""Normalize a small requirement or Bug into the shared case source format."""

import json
import re

from .common import UiaError, digest, require
from .secrets import scrub_text


def parse(path, namespace, config):
    try:
        data = path.read_bytes()
        original_text = data.decode('utf-8')
        request = json.loads(original_text)
    except (OSError, ValueError) as error:
        raise UiaError('文字请求必须是 UTF-8 JSON') from error
    require(isinstance(request, dict) and request.get('schema_version') == 'uia-text-request.v1',
            '文字请求版本应为 uia-text-request.v1')
    require(set(request) <= {'schema_version', 'kind', 'title', 'original', 'references', 'historical_actual', 'cases'},
            '文字请求包含未知字段')
    decoded_text = json.dumps(request, ensure_ascii=False)
    require(scrub_text(original_text, config) == original_text and scrub_text(decoded_text, config) == decoded_text,
            '请用脱敏的需求描述和测试资料')

    def field(row, key, optional=False):
        value = row.get(key, '' if optional else None)
        require(isinstance(value, str) and (optional or value.strip()), f'文字请求字段无效 {key}')
        return value

    kind = request.get('kind')
    require(kind in ('requirement', 'bug'), 'kind 应为 requirement 或 bug')
    title = field(request, 'title')
    field(request, 'original')
    historical_actual = field(request, 'historical_actual', optional=True)
    cases = request.get('cases')
    require(isinstance(cases, list) and cases, '文字请求需要至少一项验证')
    seen = set()
    rows = []
    for case in cases:
        require(isinstance(case, dict), '验证项必须是对象')
        require(set(case) <= {'id', 'title', 'module', 'priority', 'preconditions', 'steps', 'expectations',
                              'expectation_question'}, '验证项包含未知字段')
        cid = field(case, 'id')
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,39}', cid) and cid not in seen,
                '验证项编号格式无效或重复')
        seen.add(cid)
        steps = case.get('steps')
        require(isinstance(steps, list) and steps and all(isinstance(s, str) and s.strip() for s in steps),
                f'验证项需要操作步骤 {cid}')
        expected = case.get('expectations', [])
        require(isinstance(expected, list), f'预期必须是列表 {cid}')
        expectations = []
        for item in expected:
            require(isinstance(item, dict) and set(item) == {'quote', 'source', 'method'},
                    f'预期必须包含原文、出处和验法 {cid}')
            expectations.append({key: field(item, key) for key in ('quote', 'source', 'method')})
        require(len({item['quote'] for item in expectations}) == len(expectations), f'预期原文重复 {cid}')
        question = field(case, 'expectation_question', optional=True)
        require(expectations or question.strip(), f'预期缺失时需要提出业务问题 {cid}')
        row = {'original_id': cid, 'suggested_id': f'{namespace}-{cid}', 'identity_key': f'{namespace}:{cid}',
               'source_kind': kind, 'title': field(case, 'title'), 'module': field(case, 'module', optional=True),
               'priority': field(case, 'priority', optional=True) or 'P2', 'sheet': '文字需求' if kind == 'requirement' else 'Bug 描述',
               'rows': [], 'records': [], 'preconditions': field(case, 'preconditions', optional=True),
               'steps': steps, 'expected': [item['quote'] for item in expectations],
               'expectations': expectations, 'expectation_question': question}
        row['content_hash'] = digest(row)
        rows.append(row)
    refs = request.get('references', [])
    require(isinstance(refs, list) and all(isinstance(ref, str) and ref.strip() for ref in refs), '资料引用必须是文本列表')
    return {'cases': rows, 'sheets': [], 'gaps': [], 'sha256': digest(data), 'original': request,
            'metadata': {'kind': kind, 'title': title, 'references': refs, 'historical_actual': historical_actual}}


def expectation_review_id(case_id):
    return 'request-expected:' + case_id
