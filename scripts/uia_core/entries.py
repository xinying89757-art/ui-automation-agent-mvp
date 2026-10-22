"""Shared, non-secret page entry hints; run.json alone owns run progress."""
import json
import re
import shlex
from pathlib import Path

from . import common
from .common import atomic_write, now, read_yaml, require
from .preconditions import normalize
from .secrets import scrub_text
from .specs import has_snapshot_ref


def key(page):
    return normalize(page).lstrip('?？').casefold()


def matches(left, right):
    a, b = key(left), key(right)
    return bool(a and b and (a == b or min(len(a), len(b)) >= 3 and (a in b or b in a)))


def knowledge_path(name):
    return common.ROOT / 'assets/playwright-runner/knowledge' / name


def load():
    path = knowledge_path('entries.yaml')
    return read_yaml(path) if path.is_file() else {'schema_version': 'entry-hints.v1', 'entries': {}}


def safe(value, cfg):
    text = json.dumps(value, ensure_ascii=False)
    require(not has_snapshot_ref(value), 'Entry hints cannot contain snapshot refs')
    require(scrub_text(text, cfg) == text, 'Entry hints contain sensitive metadata')


def parse(text):
    """Only explicit page=path lines; selector notes remain part of path_text."""
    text = re.sub(r'^\s*入口提示\s*[:：]\s*', '', text.strip())
    result = []
    for line in re.split(r'[\n；;]+', text):
        if not line.strip():
            continue
        pair = re.split(r'[=＝]', line.strip(), maxsplit=1)
        require(len(pair) == 2 and all(x.strip() for x in pair), '入口提示格式：页面=大概路径')
        label, path = (x.strip() for x in pair)
        require(key(label), '入口页面名称不能为空')
        frame = re.search(r'(?<![\w.])([#.][\w-]+)', path)
        result.append({'label': label.lstrip('?？'), 'path_text': path,
                       **({'not_a_page': True} if re.search(r'不是(?:后台)?页面|非页面', path) else {}),
                       **({'frame': frame.group(1)} if frame else {})})
    require(result, '入口提示不能为空')
    return result


def resolve(page):
    hints = load()['entries']
    # Exact matches win over fuzzy containment, then the most specific name wins.
    choices = []
    for name, hint in hints.items():
        names = [name, hint['label'], *hint.get('aliases', [])]
        if any(matches(page, x) for x in names):
            choices.append((any(key(page) == key(x) for x in names), len(key(name)), name, hint))
    if choices:
        _, _, name, hint = max(choices, key=lambda x: x[:3])
        return dict(hint, key=name)
    path = knowledge_path('page-map.yaml')
    catalog = read_yaml(path) if path.is_file() else {}
    for section in ('pages', 'targets'):
        for name, row in catalog.get(section, {}).items():
            names = [name, row.get('label', ''), row.get('name', ''), *row.get('aliases', [])]
            if section == 'pages':
                names.append(row.get('entry', ''))
            if any(matches(page, x) for x in names):
                return {'key': name, 'label': page, 'path_text': row.get('path') or row.get('entry') or name,
                        'open_target': name, 'steps': [], 'frame': row.get('frame'), 'source': 'page-map', 'confirmed': True}
    return None


def store(m, hints, source='handoff', confirmed=False):
    safe(hints, m['config'])
    data = load()
    for hint in hints:
        hint = dict(hint, not_a_page=bool(re.search(r'不是(?:后台)?页面|非页面', hint['path_text'])))
        existing = resolve(hint['label'])
        name = existing['key'] if existing and existing['source'] != 'page-map' else key(hint['label'])
        old = data['entries'].get(name, {})
        aliases = list(dict.fromkeys([*old.get('aliases', []), *hint.get('aliases', []),
                                     *([hint['label']] if old and old['label'] != hint['label'] else [])]))
        # A repeated handoff must not discard an already confirmed route.
        route = ({k: old[k] for k in ('steps', 'frame') if k in old}
                 if old.get('confirmed') and old.get('path_text') == hint['path_text'] and not confirmed else {})
        inherited = ({k: v for k, v in old.items() if k not in {'steps', 'frame'}}
                     if old.get('confirmed') and not confirmed and not route else old)
        data['entries'][name] = {**inherited, **hint, **route, 'label': old.get('label', hint['label']), 'aliases': aliases,
                                'source': 'explored' if route else source, 'confirmed': bool(route) or confirmed, 'at': now()}
        changes = m.setdefault('entry_hint_changes', {})
        changes.setdefault(name, {'before': old or None})['after'] = data['entries'][name]
    safe(data, m['config'])
    atomic_write(knowledge_path('entries.yaml'), data, as_yaml=True)
    return {'saved_entries': len(hints), 'knowledge': str(knowledge_path('entries.yaml'))}


def add(m, text, source='handoff'):
    return store(m, parse(text), source)


def handoff(m, file_or_text):
    try:
        path = Path(file_or_text)
        is_file = '\n' not in file_or_text and path.is_file()
    except OSError:
        is_file = False
    return add(m, path.read_text(encoding='utf-8') if is_file else file_or_text)


def confirm(m, page, steps, frame=None):
    hint = resolve(page)
    require(hint, '页面入口未知：请先 hints add')
    require(steps and all(re.match(r'^(goto|click|hover|fill|press|wait):.+', x) for x in steps), '请提供具体 --step 动作')
    require(all(not x.startswith('goto:') for x in steps[1:]), 'goto 仅允许作为首个入口步骤')
    return store(m, [{'label': page, 'path_text': hint['path_text'], 'steps': steps,
                      **({'frame': frame or hint.get('frame')} if frame or hint.get('frame') else {})}], 'explored', True)


GENERIC_PAGES = {'页面', '目标页面', '测试页面', '当前页面', '该页面', '此页面', '新页面', '详情', '详情页', '列表', '面板', '弹窗', '后台'}
LEADING = re.compile(r'^(?:已经|已|并|再|先)?(?:登录|使用|启用|进入|打开|访问|切换到|位于|在|开启)?(?:了)?(?:一个|一篇|一条|某个)?')


def phrases(text):
    """Conservative Chinese page noun phrases; explicit --page always takes precedence."""
    result = []
    for chunk in re.split(r'[\s，,。；;：:、/→（）()]+|并且|并|以及|和|及|等|的', text or ''):
        previous = None
        while chunk and chunk != previous:
            previous, chunk = chunk, LEADING.sub('', chunk)
            chunk = re.sub(r'^.*?(?:设置)?已启用', '', chunk) if '已启用' in chunk else chunk
        match = re.match(r'([\w\u4e00-\u9fff-]{1,30}?(?:页面|编辑器|弹窗|面板|列表|后台|详情页|详情|页))$', chunk)
        if match and match.group(1) not in GENERIC_PAGES and len(match.group(1)) >= 3:
            result.append(match.group(1))
    return list(dict.fromkeys(result))


def page_rows(base, m):
    path = knowledge_path('page-map.yaml')
    pages = (read_yaml(path) if path.is_file() else {}).get('pages', {})
    page_names = {key(n) for name, row in pages.items()
                  for n in [name, row.get('label', ''), row.get('entry', ''), *row.get('aliases', [])] if n}
    candidates = list(m.get('entry_pages', {}).items())
    for row in m.get('precondition_triage', []):
        if row['classification'] in {'explore', 'ai_prepare', 'unclassified'}:
            for page in ([row['page']] if row.get('page') else phrases(row['text'])):
                candidates.append((page, row['cases']))
    for cid, case in m['cases'].items():
        path = base / case.get('case_spec', f'cases/{cid}/case-spec.yaml')
        spec = read_yaml(path) if path.is_file() else {}
        nodes = [spec.get('start_page')]
        candidates += [(p.lstrip('?？'), [cid]) for p in nodes if isinstance(p, str) and p.strip()]
    grouped = []
    for page, cases in candidates:
        safe(page, m['config'])
        if key(page) not in page_names and not re.search(r'(页面|页|编辑器|弹窗|面板|列表|后台|详情)$', page):
            continue
        if resolve(page):
            continue
        row = next((r for r in grouped if matches(page, r['page'])), None)
        if row:
            row['cases'] = sorted(set(row['cases']) | set(cases))
        else:
            grouped.append({'key': 'entry:' + key(page), 'block': 'D', 'page': page, 'label': page,
                            'cases': sorted(set(cases)), 'options': ['大概路径即可']})
    return grouped


def request(m, page, cases, base=None):
    """Queue an entry, never a demonstration or another mid-run question."""
    from .experience import add_review, sync_checklist
    from .preconditions import QUESTION_KEY
    safe(page, m['config'])
    m.setdefault('entry_pages', {}).setdefault(page, [])
    m['entry_pages'][page] = sorted(set(m['entry_pages'][page]) | set(cases))
    if m.get('checklist_issued'):
        add_review(m, 'page_entry', cases, page + ' 大概在哪里进入？（例：内容管理 → 产品 → 编辑）', page=page)
        if base:
            sync_checklist(base, m)
    elif base:
        sync_checklist(base, m)
    else:
        q = m.setdefault('questions', {}).setdefault(QUESTION_KEY, {'id': QUESTION_KEY, 'kind': 'preconditions',
            'subject': 'run-preconditions', 'status': 'open', 'entries': [], 'case_ids': [], 'answer': {'entries': {}}})
        if not any(r.get('page') == page for r in q['entries']):
            q['entries'].append({'key': 'entry:' + key(page), 'block': 'D', 'page': page, 'label': page,
                                 'cases': cases, 'number': 1 + sum(r['block'] == 'D' for r in q['entries']), 'options': ['大概路径即可']})
        q['case_ids'] = sorted(set(q['case_ids']) | set(cases))


def navigation_hint(hint):
    """Project a handoff into navigation without persisting guessed selectors."""
    hint = dict(hint)
    if hint.get('not_a_page') or hint.get('steps') or hint.get('open_target'):
        return hint
    parts = re.split(r'→|->|>|＞', hint.get('path_text', ''))
    def label(text):
        return re.sub(r'（[^）]*）|\([^)]*\)', '', text).split('，')[0].split(',')[0].strip()
    first = label(parts[0])
    node = {'内容管理': 'content-admin', '编辑网站': 'editor', '网站编辑': 'editor'}.get(first)
    if node:
        hint['node'] = node
    else:
        known = resolve(first)
        if not known or not known.get('open_target'):
            return hint
        hint['open_target'] = known['open_target']
    hint['steps'] = ['click:text=' + label(p) for p in parts[1:] if label(p)]
    hint['route_source'] = 'path_text'
    return hint


def confirmation(run, page, hint):
    steps = list(hint.get('steps', []))
    # Named page-map areas are valid targets for the shared navigator.
    if hint.get('open_target') or hint.get('node'):
        steps.insert(0, 'click:' + (hint.get('open_target') or hint['node']))
    command = ['python3', 'scripts/uia.py', 'hints', 'confirm', '--run', run, '--page', page]
    for step in steps:
        command += ['--step', step]
    if hint.get('frame'):
        command += ['--frame', hint['frame']]
    return shlex.join(command)


def snapshot_route(args, cfg):
    hint = resolve(args.entry)
    require(hint, '页面入口未知：请走入口提示问题（清单 D 块），不要请求演示')
    safe({'hint': hint, 'entry': args.entry, 'purpose': args.purpose}, cfg)
    hint = navigation_hint(hint)
    if hint.get('not_a_page'):
        return hint, None
    steps = list(hint.get('steps', []))
    if not steps and not hint.get('open_target') and not hint.get('node'):
        return hint, None
    require(not args.goto and not args.open_target and not args.click and not args.hover,
            '--entry 的后续动作请使用 --step；入口导航由知识提供')
    args.goto = steps.pop(0)[5:] if steps and steps[0].startswith('goto:') else None
    args.open_target = hint.get('open_target')
    args.node = hint.get('node', 'page')
    args.frame = args.frame or hint.get('frame')
    count = len(steps) + bool(args.goto) + bool(args.open_target)
    args.step = steps + args.step
    return hint, count
