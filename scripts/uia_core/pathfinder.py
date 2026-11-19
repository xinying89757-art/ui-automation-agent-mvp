"""Deterministic spec-pathfinder stage: Excel steps become a confirmed operation spec.

v1 (no code) and optional v2 (project source index) both write Chinese Markdown under
the gitignored run directory. Nothing in this module writes case text or code indexes
into the tracked skill tree or knowledge catalog except short, non-secret answers.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
from pathlib import Path

from . import common
from .common import UiaError, atomic_write, digest, file_hash, now, read_json, read_yaml, require
from .secrets import scrub_text

RESOLUTIONS = 'pathfinder-resolutions.v1'
COMPILED = 'pathfinder-compile.v1'
VAGUE = {'正常', '成功', '正确', '符合预期', '无异常', '通过', 'ok', 'OK', '显示', '生效', '没问题', '可以'}
FRONTEND = ('富文本', 'tiptap', 'TipTap', 'contenteditable', '正文编辑器', '所见即所得')
PAGE_SUFFIX = re.compile(r'(?:页面|编辑器|弹窗|面板|列表|后台|详情页|详情|管理|维护|设置|查询)$')
CODEISH = re.compile(
    r'(?:'
    r'[\w./\\-]+\.(?:java|ftl|ftlh|jsp|html|js|mjs|vue|tsx|css)\b'
    r'|#[A-Za-z_][\w-]*'
    r'|\b(?:data-testid|getByRole|getByText|locator\(|Controller|RequestMapping)\b'
    r')'
)
REPO = Path(__file__).resolve().parents[2]
STEP_NO = re.compile(r'^\s*(\d+)\s*[\.、．\)]\s*(.*)$')
QUOTE = re.compile(r'[「“"\']([^「」“”"\']{1,40})[」”"\']')


def output_dir(base):
    path = (Path(base) / 'spec-pathfinder').resolve()
    _owned(Path(base), path)
    return path


def _owned(base, path):
    """Run-local outputs only. Never the tracked skill tree or trial fixtures."""
    base_resolved = Path(base).resolve()
    resolved = Path(path).resolve()
    require(resolved == base_resolved or base_resolved in resolved.parents,
            'spec-pathfinder 只能写在本次 run 目录内')
    skill = (REPO / 'skills' / 'spec-pathfinder').resolve()
    require(resolved != skill and skill not in resolved.parents,
            'spec-pathfinder 拒绝把用例或代码索引写进已跟踪的 skill 目录')
    return resolved


def resolutions_path():
    return common.ROOT / 'knowledge' / 'pathfinder-resolutions.yaml'


def load_resolutions():
    path = resolutions_path()
    if not path.is_file():
        return {'schema_version': RESOLUTIONS, 'resolutions': {}}
    data = read_yaml(path)
    if not isinstance(data, dict):
        data = {}
    data.setdefault('schema_version', RESOLUTIONS)
    data.setdefault('resolutions', {})
    return data


def resolution_key(kind, subject):
    from .preconditions import normalize
    return 'pathfinder:' + digest([kind, normalize(subject)])[:16]


def remembered(kind, subject):
    return load_resolutions()['resolutions'].get(resolution_key(kind, subject))


def remember(m, kind, subject, answer, claim_ids):
    """Persist one non-secret answer. The same subject is never asked again."""
    from .preconditions import normalize
    text = scrub_text(str(answer).strip(), m.get('config'))
    require(text and text == str(answer).strip(), '存疑答复含敏感信息，请只写操作结论')
    require(len(text) <= 500, '存疑答复过长')
    record = {'kind': kind, 'subject': normalize(subject)[:80], 'answer': text,
              'claim_ids': list(claim_ids)[:20], 'source': 'checklist', 'at': now()}
    require(scrub_text(json.dumps(record, ensure_ascii=False), m.get('config')) == json.dumps(record, ensure_ascii=False),
            '存疑答复含敏感信息')
    data = load_resolutions()
    data['resolutions'][resolution_key(kind, subject)] = record
    path = resolutions_path()
    _not_skill(path)
    atomic_write(path, data, as_yaml=True)
    return record


def _not_skill(path):
    skill = (REPO / 'skills' / 'spec-pathfinder').resolve()
    resolved = Path(path).resolve()
    require(resolved != skill and skill not in resolved.parents, '拒绝把知识写进 spec-pathfinder skill 目录')


def _pages_catalog():
    for relative in ('knowledge/page-map.yaml', 'assets/playwright-runner/knowledge/page-map.yaml'):
        path = common.ROOT / relative
        if path.is_file():
            data = read_yaml(path) or {}
            data.setdefault('pages', {})
            data.setdefault('targets', {})
            return data
    return {'pages': {}, 'targets': {}}


def _human_path(text):
    """Keep a route a person can read. Drop control ids, frames and selectors."""
    text = str(text or '')
    text = re.sub(r'#[\w.-]+', '', text)
    text = re.sub(r'iframe(?:\[[^\]]*\])?(?:\.[\w-]+)*', '', text, flags=re.I)
    text = re.sub(r'>>', ' ', text)
    text = re.sub(r'\binternal:control=\S+', '', text)
    text = re.sub(r'\b(?:click|hover|fill|goto):[^\s，,。；;]+', '', text)
    text = re.sub(r'\b[\w-]+(?:\.[\w-]+){2,}\b', '', text)
    text = re.sub(r'\s+', ' ', text).strip(' ，,。；;')
    if not re.search(r'[\u4e00-\u9fff]', text) or CODEISH.search(text):
        return ''
    return text


def _name_fits(label, names):
    """Do not treat a 3-character fragment such as 编辑器 as the same page."""
    from .entries import key
    query = key(label)
    if len(query) < 4:
        return False
    for name in names:
        other = key(str(name or ''))
        if not other:
            continue
        if query == other:
            return True
        if len(other) >= 4 and (other in query or query in other):
            return True
    return False


def _known_page(label, pages):
    """A known entry is a human route in entries.yaml or a named page, never a control id."""
    if not label:
        return None
    from .entries import key, load, matches, literal_route, navigation_hint
    choices = []
    for name, hint in (load().get('entries') or {}).items():
        names = [name, hint.get('label'), *hint.get('aliases', [])]
        if not _name_fits(label, names) or not any(matches(label, item) for item in names if item):
            continue
        path = _human_path(hint.get('path_text'))
        if not path:
            continue
        exact = any(key(label) == key(item) for item in names if item)
        chosen = dict(hint, path_text=path, key=name)
        choices.append((exact, len(key(name)), chosen))
    if choices:
        hint = literal_route(max(choices)[2])
        hinted = navigation_hint(dict(hint))
        if hinted.get('node') in (pages.get('pages') or {}):
            hint['node'] = hinted['node']
        return hint
    for name, row in (pages.get('pages') or {}).items():
        names = [name, row.get('label'), row.get('entry'), *row.get('aliases', [])]
        if not _name_fits(label, names) or not any(matches(label, item) for item in names if item):
            continue
        path = _human_path(row.get('path') or row.get('entry') or row.get('label') or '')
        if not path:
            continue
        return {'key': name, 'label': label, 'path_text': path, 'open_target': name,
                'source': 'page-map', 'confirmed': True}
    return None


SKIP_PLACES = {'实现页面', '当前页面', '该页面', '此页面', '目标页面', '测试页面', '编辑页面', '新页面'}
_LEADING_VERB = re.compile(r'^(?:已经|已)?(?:打开|进入|访问|使用|位于|通过|在|到|从)+')
_INNER_VERB = re.compile(r'(?:已经|已)?(?:打开|进入|访问|使用|位于|通过)')


def _clean_place(name):
    name = _LEADING_VERB.sub('', str(name or '').strip())
    name = _INNER_VERB.split(name)[-1]
    name = name.split('的')[-1].strip(' ，,。；;：:')
    if len(name) < 4 or name in SKIP_PLACES:
        return ''
    return name


def _page_phrases(text):
    from .entries import phrases, GENERIC_PAGES
    found = []
    for name in list(phrases(text or '')):
        cleaned = _clean_place(name)
        if cleaned and cleaned not in GENERIC_PAGES:
            found.append(cleaned)
    for match in PAGE_SUFFIX.finditer(text or ''):
        start = match.end()
        while start > 0 and re.match(r'[\u4e00-\u9fffA-Za-z0-9]', (text or '')[start - 1]):
            start -= 1
        cleaned = _clean_place((text or '')[start:match.end()])
        if cleaned and cleaned not in GENERIC_PAGES and cleaned not in found:
            found.append(cleaned)
    return list(dict.fromkeys(found))


def _entry_places(*texts):
    found = []
    for text in texts:
        found.extend(_page_phrases(text))
    return list(dict.fromkeys(found))


def _page_in_catalog(name, pages):
    """Resolve an entry name only against pages, never the control/target catalog."""
    if not name:
        return None
    from .preconditions import normalize
    want = normalize(name)
    hits = []
    for ident, row in pages.get('pages', {}).items():
        labels = [ident, row.get('label', ''), row.get('name', ''), row.get('entry', ''), *row.get('aliases', [])]
        if any(normalize(str(label)) == want for label in labels if label):
            hits.append(ident)
    return hits[0] if len(hits) == 1 else None


def _is_payload(line):
    """A markdown sample line is part of the previous action, not its own step."""
    return bool(re.match(r'^(?:#{1,6}\s?|[|>]|[-*+]\s|\|)', line))


def _split_steps(cells):
    """Stable S-numbers from explicit step numbers, otherwise source order."""
    raw_cells = cells if isinstance(cells, list) else [cells or '']
    pieces = []
    for cell in raw_cells:
        text = str(cell or '')
        logical = text.replace('\\n', '\n')
        lines = [line.strip() for line in logical.splitlines() if line.strip()] or ([text.strip()] if text.strip() else [])
        numbered, intact = [], True
        for line in lines:
            match = STEP_NO.match(line)
            if match and match.group(2).strip():
                numbered.append([int(match.group(1)), match.group(2).strip()])
            elif numbered:
                # Sample text between numbered actions stays in the previous step.
                numbered[-1][1] += '\n' + line
            else:
                intact = False
                break
        if numbered and intact:
            pieces.extend((number, body) for number, body in numbered)
            continue
        buffer = None
        for line in lines:
            if buffer is not None and _is_payload(line):
                buffer += '\n' + line
            else:
                if buffer is not None:
                    pieces.append((None, buffer))
                buffer = line
        if buffer is not None:
            pieces.append((None, buffer))
    steps, seen = [], set()
    auto = 1
    for number, text in pieces:
        sid = number or auto
        while sid in seen:
            sid += 1
        seen.add(sid)
        auto = sid + 1
        steps.append({'id': 'S' + str(sid), 'text': text})
    return steps


def _verb(text):
    if re.search(r'无法保存|不能保存|不可用|置灰|禁用', text):
        return 'assert', None
    if re.search(r'取消勾选|去掉勾选', text):
        return 'uncheck', None
    if re.search(r'勾选|选中', text):
        return 'check', None
    if re.search(r'悬停|鼠标移到', text):
        return 'hover', None
    if re.search(r'上传', text):
        return 'upload', _quoted(text)
    if re.search(r'关闭', text):
        return 'close', None
    if re.search(r'按下|按键', text):
        value = _quoted(text) or 'Enter'
        return 'press', value
    if re.search(r'输入|填写|修改为|改为', text):
        return 'fill', _quoted(text) or ''
    if re.search(r'等待', text):
        return 'wait', None
    if re.search(r'打开|进入|访问', text) and _page_phrases(text):
        return 'open', None
    if re.search(r'打开|进入|访问', text):
        return 'open', None
    return 'click', None


def _quoted(text):
    match = QUOTE.search(text or '')
    return match.group(1) if match else ''


def _control(text):
    quoted = _quoted(text)
    if quoted:
        return quoted
    match = re.search(r'(?:点击|选择|打开|进入|勾选|关闭)(.{1,20})$', text or '')
    if not match:
        return ''
    name = re.sub(r'[，,。；;：:\s].*$', '', match.group(1)).strip('「」“”"\' ')
    return name[:20]


def _slug_target(name, fallback):
    token = re.sub(r'[^\w.\-\u4e00-\u9fff]+', '', name or '')[:24]
    return '?' + (token or fallback)


def _target_in_catalog(name, pages):
    if not name:
        return None
    from .preconditions import normalize
    want = normalize(name)
    hits = []
    for ident, row in pages.get('targets', {}).items():
        labels = [ident, row.get('label', ''), row.get('name', ''), *row.get('aliases', [])]
        if any(normalize(str(label)) == want for label in labels if label):
            hits.append(ident)
    return hits[0] if len(hits) == 1 else None


def _vague(text):
    token = re.sub(r'\s+', '', text or '')
    return token in VAGUE or len(token) < 2


def _observable_value(text):
    match = QUOTE.search(text or '')
    return match.group(1) if match else ''


def _claim(cid, step_id, index, kind, text, confidence, doubt=None):
    return {'id': f'{cid}/{step_id}/C{index}', 'kind': kind, 'text': text,
            'confidence': confidence, 'v1_confidence': confidence, 'doubt': doubt}


def _new_doubt(kind, subject, cases, claim_ids, summary, block):
    return {'id': 'Q-' + kind + '-' + digest([kind, subject])[:8], 'kind': kind, 'subject': subject,
            'cases': cases, 'claim_ids': claim_ids, 'summary': summary, 'block': block}


def _load_sources(base, m):
    loaded = []
    for cid, case in m.get('cases', {}).items():
        path = Path(base) / case.get('source', '')
        if not path.is_file():
            continue
        try:
            source = read_json(path)
        except (OSError, ValueError):
            continue
        steps = source.get('steps') or []
        expected = source.get('expected') or []
        if not any(str(x).strip() for x in (steps if isinstance(steps, list) else [steps])):
            continue
        loaded.append((cid, case, source, steps, expected))
    return loaded


def _legacy_locked(case):
    """Cases that already have a hand-written spec or a bound script keep their contract."""
    if case.get('spec_origin') == 'pathfinder':
        return False
    if case.get('registration'):
        return True
    return bool(case.get('case_spec'))


def build_case(cid, case, source, pages):
    steps = _split_steps(source.get('steps') or [])
    expected_cells = source.get('expected') if isinstance(source.get('expected'), list) else [source.get('expected') or '']
    expected_lines = []
    for cell in expected_cells:
        lines = [line for line in str(cell or '').splitlines() if line.strip()] or ([str(cell)] if str(cell or '').strip() else [])
        expected_lines.extend(lines)
    claims, doubts = [], []
    rendered = []
    # Preconditions say where the case already is. Steps are next.
    # A module name is used only when it itself looks like a place (for example 产品管理).
    places = (_entry_places(source.get('preconditions') or '')
              or _entry_places(*(step['text'] for step in steps))
              or _entry_places(source.get('module') or ''))
    entry_page = places[0] if places else ''
    known = _known_page(entry_page, pages) if entry_page else None
    remembered_entry = remembered('entry', entry_page) if entry_page else None
    if remembered_entry:
        entry_text = '从「' + entry_page + '」开始。已确认路径：' + remembered_entry['answer'] + '。'
    elif known and known.get('path_text'):
        entry_text = '从「' + entry_page + '」开始。到达方式：' + known['path_text'] + '。'
    elif entry_page:
        entry_text = '从「' + entry_page + '」开始。知识库没有这条入口的自然语言路径。'
    else:
        noted = remembered('entry_missing', '入口未写明')
        entry_text = '人工确认：' + noted['answer'] if noted else '用例没有写明入口页面'
    if entry_page and not known and not remembered_entry:
        doubt = _new_doubt('entry', entry_page, [cid], [], '知识库没有「' + entry_page + '」的入口', 'D')
        doubts.append(doubt)
    elif not entry_page and not remembered('entry_missing', '入口未写明'):
        doubt = _new_doubt('entry_missing', '入口未写明', [cid], [], '用例没有写明从哪个页面开始', 'E')
        doubts.append(doubt)
    paired = len(expected_lines) == len(steps) and len(steps) > 1
    for index, step in enumerate(steps):
        verb, value = _verb(step['text'])
        control = _control(step['text'])
        if verb == 'open':
            # Opening a page must never bind to a similarly named KB control ID.
            opened_page = _page_in_catalog(control or entry_page, pages)
            target = opened_page or _slug_target(control or entry_page, 'start')
        else:
            catalog = _target_in_catalog(control, pages)
            target = catalog or _slug_target(control, '操作' + step['id'])
        step_claims = []
        operation = _claim(cid, step['id'], 1, 'operation', step['text'], '中')
        step_claims.append(operation)
        if entry_page and index == 0:
            confidence = '中'
            entry_claim = _claim(cid, step['id'], 2, 'entry', '入口页面是' + entry_page, confidence,
                                 doubts[0]['id'] if doubts and doubts[0]['kind'] == 'entry' else None)
            step_claims.append(entry_claim)
            if doubts and doubts[0]['kind'] == 'entry':
                doubts[0]['claim_ids'] = [entry_claim['id']]
        attached = [expected_lines[index]] if paired else (expected_lines if index == len(steps) - 1 else [])
        expectations = []
        next_index = len(step_claims) + 1
        for line in attached:
            observable = _observable_value(line)
            if _vague(line) and not observable and not remembered('expected', cid + ':' + line):
                doubt = _new_doubt('expected', cid + ':' + line, [cid], [],
                                   '预期「' + line + '」看不出什么算对', 'E')
                claim = _claim(cid, step['id'], next_index, 'expected', line, '低', doubt['id'])
                doubt['claim_ids'] = [claim['id']]
                doubts.append(doubt)
            else:
                claim = _claim(cid, step['id'], next_index, 'expected', line, '中')
            step_claims.append(claim)
            expectations.append({'excel': line, 'value': observable, 'vague': claim['confidence'] == '低',
                                 'target': _slug_target(observable or '结果' + cid + step['id'], '结果')})
            next_index += 1
        claims.extend(step_claims)
        rendered.append({'id': step['id'], 'text': step['text'], 'verb': verb, 'value': value,
                         'target': target, 'control': control, 'claims': step_claims, 'expectations': expectations})
    if not steps:
        doubts.append(_new_doubt('steps', cid, [cid], [], '用例没有可执行步骤', 'E'))
    return {'case_id': cid, 'title': source.get('title') or case.get('title') or cid,
            'module': source.get('module') or case.get('module') or '',
            'sheet': source.get('sheet') or case.get('sheet') or '',
            'rows': source.get('rows') or case.get('rows') or [],
            'preconditions': source.get('preconditions') or '',
            'entry': entry_text, 'entry_page': entry_page, 'known_entry': bool(known),
            'steps': rendered, 'expected_lines': [row['excel'] for step in rendered for row in step['expectations']],
            'claims': claims, 'doubts': doubts, 'locked': _legacy_locked(case)}


def _requirement_name(case_model):
    return case_model.get('module') or case_model.get('sheet') or '未命名需求'


def _requirement_slug(name):
    ascii_part = re.sub(r'[^A-Za-z0-9]+', '-', name).strip('-').lower()[:32]
    return (ascii_part + '-' if ascii_part else 'req-') + digest(name)[:8]


def render_human(requirement, models, stage):
    cap = '本阶段无代码，置信度最高为「中」。' if stage == 'v1' else '代码只说明控件和信号在哪里；对错仍以用例预期为准。'
    lines = [f'# 人审版 {stage} · {requirement}', '', cap,
             '本文件只写人能看懂的操作。证据编号见存疑清单或证据附录，正文不写文件、行号、接口和定位器。', '',
             '## 公共约定', '',
             '- 低置信主张不能当成已经通过的检查。',
             '- 知识库里没有的页面，入口以清单里的一次答复为准，答复后不再追问。', '']
    for model in models:
        open_doubts = [d['id'] for d in model['doubts']]
        status = '阻断（' + '、'.join(open_doubts) + '）' if not model['steps'] else (
            '条件可执行（' + '、'.join(open_doubts) + '）' if open_doubts else '可执行')
        lines += [f"## 用例 {model['case_id']} {model['title']}", '', f'状态：{status}', '']
        pre = model['preconditions'].strip() or '用例未单列前置条件。'
        lines += [f'前置条件：{pre}', '']
        lines += [f"入口：{model['entry']}", '']
        for step in model['steps']:
            lines += [f"### 步骤 {step['id']}", '', f"操作：{step['text']}", '']
            where = '知识库已有同名控件。' if not str(step['target']).startswith('?') else '界面位置还不能从知识库确定，不猜测选择器。'
            if step['control']:
                where = '操作对象是页面上的「' + step['control'] + '」。' + where
            lines += [f'定位：{where}', '']
            if step['expectations']:
                for item in step['expectations']:
                    lines += [f"预期：{item['excel']}", '']
            else:
                lines += ['预期：这一步没有单独的预期原文。', '']
            for claim in step['claims']:
                extra = ' 见存疑 ' + claim['doubt'] + '。' if claim.get('doubt') else ''
                shown = '中' if stage == 'v1' and claim['confidence'] == '高' else claim['confidence']
                lines += [f"主张 {claim['id']}：{claim['text']}。置信度：{shown}。{extra}".rstrip()]
            lines.append('')
        cleanup = '用例未要求清理。' if not any('清理' in (model['preconditions'] or '') for _ in [0]) else model['preconditions']
        lines += [f'清理：{cleanup}', '']
    return '\n'.join(lines).rstrip() + '\n'


def render_doubts(requirement, models, stage):
    lines = [f'# 存疑清单 {stage} · {requirement}', '',
             '这里只列还不能确定的入口、预期和代码里找不到的前端控件。已写入知识库的答复不会再次出现。', '']
    doubts = [d for model in models for d in model['doubts']]
    if not doubts:
        lines += ['无未决存疑。', '']
    for doubt in doubts:
        lines += [f"## {doubt['id']}", '', doubt['summary'], '',
                  '影响主张：' + ('、'.join(doubt['claim_ids']) or '整条用例') + '。',
                  '影响用例：' + '、'.join(doubt['cases']) + '。', '']
        if doubt['kind'] == 'entry':
            lines += ['补证：在执行前清单 D 块回答「' + doubt['subject'] + '=大概路径」。写入知识库后不再询问。',
                      '执行：未回答前不猜测入口。', '']
        elif doubt['kind'] == 'guided_exploration':
            lines += ['补证：该控件只出现在前端（例如富文本），后端代码索引里没有。做一次有人复核的引导探索，把看到的入口和现象写入清单。',
                      '执行：探索结论写入知识库后不再询问，也不要把猜测写成硬断言。', '']
        elif doubt['kind'] == 'code_gap':
            lines += ['补证：代码索引不能直接证明这条主张。它仍按用例原文作为中置信验收，不升为高。', '']
        else:
            lines += ['补证：在执行前清单 E 块确认怎样算对，或回答挂起。写入知识库后不再询问。', '']
    lines += ['## 来源记录', '']
    for model in models:
        rows = '、'.join(str(r) for r in model['rows']) or '未知'
        lines += [f"### SRC-{model['case_id']}", '',
                  f"工作表：{model['sheet'] or '未知'}；行：{rows}；用例 {model['case_id']}。", '',
                  '步骤原文：', '']
        for step in model['steps']:
            lines += [f"- {step['id']} {step['text']}"]
        lines += ['', '预期原文：', '']
        for line in model['expected_lines']:
            lines += ['- ' + line]
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def _element_hits(elements, needle):
    """Exact visible text wins. A longer blob that merely contains the word is not enough."""
    needle = (needle or '').strip()
    if len(needle) < 2:
        return []
    exact, partial = [], []
    for row in elements:
        texts = [str(row.get('text') or ''), str(row.get('id') or ''), str(row.get('name') or ''),
                 *[str(item) for item in (row.get('i18nFallbacks') or [])]]
        if any(text == needle for text in texts):
            exact.append(row)
        elif any(needle in text for text in texts if text):
            partial.append(row)
    return exact or partial


def _frontend_text(*parts):
    blob = '\n'.join(str(p or '') for p in parts)
    return next((token for token in FRONTEND if token.lower() in blob.lower()), '')


def upgrade_models(models, index):
    """Raise a claim to 高 only when one indexed element contains its visible text."""
    elements = index.get('elements') or []
    for model in models:
        for step in model['steps']:
            marker = _frontend_text(step['text'], model['entry_page'], *(c['text'] for c in step['claims']))
            if marker and not _element_hits(elements, marker):
                claim = next((c for c in step['claims'] if c['kind'] in {'operation', 'entry'}), step['claims'][0])
                claim['confidence'] = '低'
                model['doubts'] = [d for d in model['doubts'] if not (d['kind'] == 'entry' and marker in d['subject'])]
                if not remembered('guided_exploration', marker) and not any(d['kind'] == 'guided_exploration' and d['subject'] == marker for d in model['doubts']):
                    doubt = _new_doubt('guided_exploration', marker, [model['case_id']], [claim['id']],
                                       '「' + marker + '」不在后端代码索引中，需要一次人工复核的引导探索', 'E')
                    claim['doubt'] = doubt['id']
                    model['doubts'].append(doubt)
                continue
            for claim in step['claims']:
                if claim['v1_confidence'] == '低':
                    continue
                needle = step['control'] if claim['kind'] == 'operation' else (_observable_value(claim['text']) or '')
                hits = _element_hits(elements, needle) if needle else []
                unique = {(h.get('file'), h.get('line')) for h in hits}
                if len(unique) == 1:
                    hit = hits[0]
                    claim['confidence'] = '高'
                    claim['evidence'] = {'file': hit.get('file'), 'line': hit.get('line'),
                                         'strategy': (hit.get('locatorCandidate') or {}).get('strategy'),
                                         'value': (hit.get('locatorCandidate') or {}).get('value')}
                    claim['doubt'] = None
                elif claim['v1_confidence'] == '中' and needle and not claim.get('doubt'):
                    doubt = _new_doubt('code_gap', claim['id'], [model['case_id']], [claim['id']],
                                       '代码索引不能唯一证明「' + needle + '」，保持用例原文为中置信', 'E')
                    claim['doubt'] = doubt['id']
                    model['doubts'].append(doubt)
        known = {d['id'] for d in model['doubts']}
        model['claims'] = []
        for step in model['steps']:
            for claim in step['claims']:
                if claim.get('doubt') and claim['doubt'] not in known:
                    claim['doubt'] = None
                model['claims'].append(claim)
    return models


def render_agent(requirement, models, fingerprint):
    lines = [f'# agent 执行版 v2 · {requirement}', '',
             f'代码索引指纹：{fingerprint}。路径相对于本次代码根，正文不写绝对路径。',
             '低置信主张只记录，不生成硬断言。', '']
    for model in models:
        open_doubts = [d['id'] for d in model['doubts']]
        status = '阻断（' + '、'.join(open_doubts) + '）' if not model['steps'] else (
            '条件可执行（' + '、'.join(open_doubts) + '）' if open_doubts else '可执行')
        lines += [f"用例：{model['case_id']} {model['title']}", '', f'状态：{status}', '',
                  f"前置条件：{model['preconditions'].strip() or '未单列'}。入口：{model['entry']}。", '']
        for step in model['steps']:
            lines += [f"步骤 {step['id']}：", '', f"操作：{step['text']}"]
            evidence = next((c.get('evidence') for c in step['claims'] if c.get('evidence')), None)
            if evidence:
                lines += [f"定位依据：可见文本或稳定属性「{evidence.get('value') or step['control']}」，策略 {evidence.get('strategy') or 'text'}；运行时唯一数仍须执行时确认。"]
                lines += [f"证据出处：{evidence['file']}:{evidence['line']}"]
            else:
                lines += ['定位依据：知识库或用例原文中的名称；没有代码行号时不编造定位器。']
            for item in step['expectations']:
                lines += [f"预期：{item['excel']}"]
            for claim in step['claims']:
                where = ''
                if claim.get('evidence'):
                    where = f"（{claim['evidence']['file']}:{claim['evidence']['line']}）"
                lines += [f"主张 {claim['id']} 置信度：{claim['confidence']}{where}"]
            lines.append('')
        lines += ['清理：按用例原文；没有写明的写入不追加恢复步骤。', '']
    return '\n'.join(lines).rstrip() + '\n'


def render_evidence(requirement, models, fingerprint):
    lines = [f'# 证据附录 v2 · {requirement}', '', f'索引指纹：{fingerprint}。', '']
    found = False
    for model in models:
        for step in model['steps']:
            for item in step['claims']:
                if not item.get('evidence'):
                    continue
                found = True
                ev = item['evidence']
                lines += [f"## EV-{item['id'].replace('/', '-')}", '',
                          f"主张 {item['id']}。文件 {ev['file']} 第 {ev['line']} 行。",
                          f"定位策略：{ev.get('strategy') or 'text'}；值：{ev.get('value') or ''}", '']
    if not found:
        lines += ['没有可升为高置信的代码证据。', '']
    return '\n'.join(lines).rstrip() + '\n'


def render_upgrade(models):
    lines = ['# v1 → v2 升级记录', '', '每条主张一行：原置信度不超过中，高只来自唯一代码命中。', '']
    for model in models:
        for claim in model['claims']:
            previous = claim.get('v1_confidence') or '中'
            action = '升级' if claim['confidence'] == '高' and previous != '高' else ('打回' if claim.get('doubt') else '保持')
            reason = claim.get('doubt') or ((claim.get('evidence') or {}).get('file') or '无新证据')
            lines.append(f"- {claim['id']}：{previous} → {claim['confidence']}，{action}。{reason}。")
    lines.append('')
    return '\n'.join(lines)


def _fingerprint(index_dir):
    blobs = []
    for name in ('routes.json', 'template-elements.json', 'actions.json'):
        path = Path(index_dir) / name
        blobs.append(path.read_bytes() if path.is_file() else b'')
    return digest(blobs)[:12]


def _run_index(base, code_root):
    root = Path(code_root).resolve()
    require(root.is_dir(), '项目代码路径不是目录')
    script = REPO / 'skills' / 'spec-pathfinder' / 'scripts' / 'build-index.mjs'
    require(script.is_file(), '缺少 spec-pathfinder 索引脚本')
    index_dir = output_dir(base) / 'index'
    _owned(base, index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(['node', str(script), str(root), '--out', str(index_dir)],
                          capture_output=True, text=True, check=False)
    require(proc.returncode == 0, 'spec-pathfinder 代码索引失败', (proc.stderr or proc.stdout)[-400:])
    elements = json.loads((index_dir / 'template-elements.json').read_text(encoding='utf-8'))
    routes = json.loads((index_dir / 'routes.json').read_text(encoding='utf-8'))
    actions = json.loads((index_dir / 'actions.json').read_text(encoding='utf-8'))
    return {'elements': elements.get('entries') or [], 'routes': routes.get('entries') or [],
            'actions': actions.get('entries') or [], 'dir': index_dir,
            'fingerprint': _fingerprint(index_dir)}


def _safe_human(text):
    prose = []
    for line in text.splitlines():
        if line.startswith('### SRC-') or line.startswith('- S') or line.startswith('- '):
            continue
        if line.startswith('步骤原文') or line.startswith('预期原文') or line.startswith('工作表：'):
            continue
        prose.append(line)
    require(not CODEISH.search('\n'.join(prose)), '人审版或存疑说明混入了代码串')
    return text


def _write(base, path, text):
    _owned(base, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _publish(base, m, name, group, stage, code_root=None, fingerprint=None):
    slug = _requirement_slug(name)
    folder = output_dir(base) / slug
    human = scrub_text(render_human(name, group, stage), m.get('config'))
    doubts = scrub_text(render_doubts(name, group, stage), m.get('config'))
    if stage == 'v1':
        require('置信度：高' not in human and '置信度：高' not in doubts, 'v1 置信度不得超过中')
    _safe_human(human)
    _safe_human(doubts)
    files = {'human': f'spec-pathfinder/{slug}/SPEC-human-{stage}.md',
             'doubts': f'spec-pathfinder/{slug}/DOUBTS-{stage}.md'}
    _write(base, folder / f'SPEC-human-{stage}.md', human)
    _write(base, folder / f'DOUBTS-{stage}.md', doubts)
    if stage == 'v2':
        agent = render_agent(name, group, fingerprint)
        evidence = render_evidence(name, group, fingerprint)
        upgrade = render_upgrade(group)
        blob = agent + evidence + upgrade + human
        require(str(Path(code_root).resolve()) not in blob, '执行版不能写入代码绝对路径')
        files.update(agent=f'spec-pathfinder/{slug}/SPEC-agent-v2.md',
                     evidence=f'spec-pathfinder/{slug}/EVIDENCE-v2.md',
                     upgrade=f'spec-pathfinder/{slug}/UPGRADE-v1-v2.md')
        _write(base, folder / 'SPEC-agent-v2.md', agent)
        _write(base, folder / 'EVIDENCE-v2.md', evidence)
        _write(base, folder / 'UPGRADE-v1-v2.md', upgrade)
    return slug, files


def compile_run(base, m, code_root=None):
    """Compile v1 for every imported case. Pass code_root to index and upgrade to v2."""
    loaded = _load_sources(base, m)
    if not loaded:
        m['pathfinder'] = {'stage': 'skipped', 'reason': '导入结果里没有步骤', 'checklist': [], 'requirements': []}
        return m['pathfinder']
    pages = _pages_catalog()
    models = [build_case(cid, case, source, pages) for cid, case, source, steps, expected in loaded]
    v1_models = copy.deepcopy(models)
    stage = 'v1'
    index = None
    if code_root:
        index = _run_index(base, code_root)
        upgrade_models(models, index)
        stage = 'v2'
    def grouped(rows):
        groups = {}
        for model in rows:
            groups.setdefault(_requirement_name(model), []).append(model)
        return groups
    v1_groups = grouped(v1_models)
    active_groups = grouped(models)
    requirements = []
    checklist = []
    for name in sorted(active_groups):
        slug = _requirement_slug(name)
        _, v1_files = _publish(base, m, name, v1_groups[name], 'v1')
        files = {'v1_' + key: value for key, value in v1_files.items()}
        if stage == 'v2':
            _, v2_files = _publish(base, m, name, active_groups[name], 'v2', code_root, index['fingerprint'])
            files.update({'v2_' + key: value for key, value in v2_files.items()})
        note = ['v1 未读取项目代码。', '人审版已扫描代码串。低置信项进入存疑清单。']
        if stage == 'v2':
            note.insert(0, 'v2 已运行 build-index.mjs，索引只在 run 目录。')
        _write(base, output_dir(base) / slug / 'SELFCHECK.md', '# SELFCHECK\n\n' + '\n'.join('- ' + line for line in note) + '\n')
        requirements.append({'name': name, 'slug': slug, 'cases': [model['case_id'] for model in active_groups[name]], 'files': files})
        for model in active_groups[name]:
            if model['locked']:
                continue
            for doubt in model['doubts']:
                if doubt['kind'] == 'entry':
                    from .entries import key
                    if _known_page(doubt['subject'], _pages_catalog()) or remembered('entry', doubt['subject']):
                        continue
                    row = {'key': 'entry:' + key(doubt['subject']), 'block': 'D', 'page': doubt['subject'],
                           'label': doubt['subject'], 'cases': list(doubt['cases']), 'options': ['大概路径即可'],
                           'doubt_id': doubt['id']}
                elif doubt['kind'] == 'guided_exploration':
                    if remembered('guided_exploration', doubt['subject']):
                        continue
                    row = {'key': resolution_key('guided_exploration', doubt['subject']), 'block': 'E',
                           'label': doubt['summary'], 'cases': list(doubt['cases']),
                           'options': ['已记录探索结论', '挂起'], 'doubt_id': doubt['id'],
                           'kind': 'guided_exploration', 'subject': doubt['subject'],
                           'claim_ids': list(doubt['claim_ids'])}
                else:
                    if remembered(doubt['kind'], doubt['subject']):
                        continue
                    row = {'key': resolution_key(doubt['kind'], doubt['subject']), 'block': 'E',
                           'label': doubt['summary'], 'cases': list(doubt['cases']),
                           'options': ['按原文可观察', '挂起'], 'doubt_id': doubt['id'],
                           'kind': doubt['kind'], 'subject': doubt['subject'],
                           'claim_ids': list(doubt['claim_ids'])}
                previous = next((item for item in checklist if item['key'] == row['key']), None)
                if previous:
                    previous['cases'] = sorted(set(previous['cases']) | set(row['cases']))
                    previous['claim_ids'] = list(dict.fromkeys([*(previous.get('claim_ids') or []), *(row.get('claim_ids') or [])]))
                else:
                    checklist.append(row)
    compiled = {'schema_version': COMPILED, 'stage': stage, 'generated_at': now(),
                'requirements': requirements,
                'cases': {model['case_id']: _brief(model, stage) for model in models}}
    compiled_path = output_dir(base) / 'compiled.json'
    _write(base, compiled_path, json.dumps(compiled, ensure_ascii=False, indent=2) + '\n')
    summary = {'stage': stage, 'output_dir': 'spec-pathfinder', 'compiled': 'spec-pathfinder/compiled.json',
               'requirements': requirements, 'checklist': checklist,
               'guided': [row['doubt_id'] for row in checklist if row.get('kind') == 'guided_exploration'],
               'index': 'spec-pathfinder/index' if index else None,
               'fingerprint': index['fingerprint'] if index else None}
    m['pathfinder'] = summary
    return summary


def _brief(model, stage):
    return {'case_id': model['case_id'], 'title': model['title'], 'stage': stage, 'entry': model['entry'],
            'entry_page': model['entry_page'], 'known_entry': model['known_entry'], 'locked': model['locked'],
            'steps': [{'id': step['id'], 'action': step['text'], 'verb': step['verb'], 'target': step['target'],
                       'value': step['value'], 'claims': step['claims']} for step in model['steps']],
            'expected_lines': model['expected_lines'],
            'expectations': [item for step in model['steps'] for item in step['expectations']]}


def load_compiled(base):
    path = Path(base) / 'spec-pathfinder' / 'compiled.json'
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def generation_brief(base, cid):
    compiled = load_compiled(base)
    brief = (compiled.get('cases') or {}).get(cid)
    if not brief or brief.get('locked'):
        return None
    return brief


def checklist_rows(m, existing):
    from .entries import matches
    pages = _pages_catalog()
    rows = []
    for row in (m.get('pathfinder') or {}).get('checklist') or []:
        if row['block'] == 'D':
            # A control whose name is a short fragment is not an entry route.
            if _known_page(row.get('page', ''), pages) or any(existing_row['block'] == 'D' and matches(row.get('page', ''), existing_row.get('page', '')) for existing_row in existing):
                continue
        elif remembered(row.get('kind') or 'expected', row.get('subject', '')):
            continue
        rows.append(row)
    return rows


def project_specs(base, m):
    """Write case-spec from the compiled brief. Never replace a hand-written or legacy spec."""
    compiled = load_compiled(base)
    pages = _pages_catalog()
    written = []
    for cid, brief in (compiled.get('cases') or {}).items():
        case = m['cases'].get(cid)
        if not case or brief.get('locked') or _legacy_locked(case):
            continue
        spec = _case_spec(cid, brief, pages)
        path = Path(base) / 'cases' / cid / 'case-spec.yaml'
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, spec, as_yaml=True)
        case['case_spec'] = str(path.relative_to(base))
        case['spec_origin'] = 'pathfinder'
        case['spec_hash'] = file_hash(path)
        written.append(cid)
    if m.get('pathfinder') is not None:
        m['pathfinder']['projected'] = written
    return written


def _start_page(brief, pages):
    page = brief.get('entry_page') or ''
    known = _known_page(page, pages) if page else None
    if known:
        if known.get('open_target') in pages.get('pages', {}):
            return known['open_target']
        if known.get('key') in pages.get('pages', {}):
            return known['key']
        if known.get('node') in pages.get('pages', {}):
            return known['node']
    return _slug_target(page, 'start')


def _case_spec(cid, brief, pages):
    steps = []
    for step in brief['steps']:
        row = {'id': step['id'], 'verb': step['verb'], 'target': step['target']}
        if step['verb'] in {'fill', 'select', 'press', 'upload'}:
            row['value'] = step['value'] if isinstance(step['value'], str) else ''
        steps.append(row)
    if not steps:
        steps = [{'id': 'S1', 'verb': 'assert', 'target': '?start'}]
    assertions = []
    expectations = brief.get('expectations') or []
    if not expectations and brief.get('expected_lines'):
        expectations = [{'excel': line, 'value': _observable_value(line), 'vague': _vague(line),
                         'target': _slug_target('结果' + cid, '结果')} for line in brief['expected_lines']]
    for index, item in enumerate(expectations, 1):
        after = steps[min(index, len(steps)) - 1]['id'] if len(expectations) == len(steps) else steps[-1]['id']
        # Attach in order when counts match; otherwise the last step carries every expectation.
        if len(expectations) == len(steps):
            after = steps[index - 1]['id']
        blocked = bool(re.search(r'blocked|cannot save|无法保存|不能保存|不可保存|不可用|置灰|禁用|被拦截', item['excel'], re.I))
        if blocked:
            host = next(step for step in steps if step['id'] == after)
            host['verb'] = 'assert'
            host.pop('value', None)
            checks = [{'target': host['target'], 'op': 'disabled'}]
        elif item.get('value') and not item.get('vague'):
            checks = [{'target': item['target'], 'op': 'text', 'value': item['value']}]
        else:
            checks = [{'target': item['target'], 'op': 'visible'}]
        if steps[-1]['verb'] == 'close' and after == steps[-1]['id']:
            checks.append({'target': steps[-1]['target'], 'op': 'hidden'})
        assertions.append({'id': 'A' + str(index), 'after': after, 'excel': item['excel'], 'checks': checks})
    questions = []
    if not assertions:
        questions = ['预期原文为空，需确认什么算对']
    return {'schema_version': 'case-spec.v1', 'case_id': cid, 'intent': brief.get('title') or cid,
            'automatable': {'status': 'yes', 'reason': '由 spec-pathfinder 确认的操作路径'},
            'required_env': [], 'data_prep': {}, 'mutation_scope': [],
            'start_page': _start_page(brief, pages), 'steps': steps, 'assertions': assertions, 'questions': questions}


def save_checklist_answers(m, rows, answers):
    """Write E-block and guided-exploration answers into the knowledge base once."""
    saved = []
    for row in rows:
        if row.get('block') != 'E':
            continue
        kind = row.get('kind') or 'expected'
        subject = row.get('subject')
        answer = answers.get(row['key'])
        if not subject or not answer or answer == '挂起':
            continue
        remember(m, kind, subject, answer, row.get('claim_ids') or [])
        if kind == 'guided_exploration':
            _seed_entry(m, row, answer)
        saved.append(row['key'])
    return saved


def _seed_entry(m, row, answer):
    """A guided-exploration note that includes 页面=路径 becomes a normal entry hint."""
    if '=' not in answer and '＝' not in answer:
        return
    from .entries import parse, store
    try:
        hints = parse(answer)
    except UiaError:
        return
    store(m, hints, 'exploration')
