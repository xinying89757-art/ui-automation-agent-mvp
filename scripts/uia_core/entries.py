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


def save_catalog(name, data):
    """Single write path: the runner (legacy) catalog, the shared knowledge/ catalog that spec gen and
    retrieval read, and the split index are updated together so no reader sees a stale copy."""
    validate_match_counts(name, data)
    atomic_write(knowledge_path(name), data, as_yaml=True)
    from . import knowledge
    if knowledge._root().is_dir():
        atomic_write(knowledge._root() / name, data, as_yaml=True)
        knowledge.sync_layout(**({'pages': data} if name == 'page-map.yaml' else {'entries': data}))


def validate_match_counts(name, data):
    """Reject locator/route evidence already known to be ambiguous at every catalog write."""
    if name == 'page-map.yaml':
        rows = (data.get('targets') or {}).items()
        for ident, row in rows:
            count = row.get('match_count') if isinstance(row, dict) else None
            require(count is None or count == 1,
                    f'UIA_LOCATOR_AMBIGUOUS: {ident} evidence matched {count} elements; use a scoped or exact locator')
    elif name == 'entries.yaml':
        for ident, row in (data.get('entries') or {}).items():
            counts = row.get('step_match_counts') if isinstance(row, dict) else None
            if isinstance(counts, dict):
                for step, count in counts.items():
                    require(count is None or count == 1,
                            f'UIA_LOCATOR_AMBIGUOUS: {ident} route step {step} evidence matched {count} elements; use a scoped or exact locator')


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
        return literal_route(dict(hint, key=name))
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


def literal_route(hint):
    """Entry routes replay without inputs: cut at the first ${INPUT} placeholder (the page before it is the entry)."""
    steps = hint.get('steps') or []
    cut = next((i for i, x in enumerate(steps) if '${INPUT}' in x), None)
    if cut is not None:
        hint = dict(hint, steps=steps[:cut], route_truncated_at=steps[cut].split('=')[0])
    return hint


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
    save_catalog('entries.yaml', data)
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
    require(steps and all(re.match(r'^(goto|click|hover|fill|type|press|wait):.+', x) for x in steps), '请提供具体 --step 动作')
    require(all(not x.startswith('goto:') for x in steps[1:]), 'goto 仅允许作为首个入口步骤')
    steps = literal_route({'steps': steps})['steps']
    require(steps, '入口路线不能以需要输入的步骤开头')
    return store(m, [{'label': page, 'path_text': hint['path_text'], 'steps': steps,
                      'step_match_counts': {str(i + 1): 1 for i, step in enumerate(steps) if step.startswith(('click:', 'hover:'))},
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


FRAME_JOIN = ' >> internal:control=enter-frame >> '


def _split_top(text):
    """Split on whitespace outside quotes/brackets."""
    parts, depth, quote, cur = [], 0, None, ''
    for ch in text:
        if quote:
            quote = None if ch == quote else quote
        elif ch in '"\'':
            quote = ch
        elif ch in '[(':
            depth += 1
        elif ch in '])':
            depth -= 1
        elif ch.isspace() and depth == 0:
            if cur:
                parts.append(cur)
            cur = ''
            continue
        cur += ch
    return parts + ([cur] if cur else [])


def _frames_of(value):
    value = value if isinstance(value, list) else [p for p in re.split(r'\s*>>\s*', value or '') if p.strip()]
    return [f.strip() for f in value if isinstance(f, str) and f.strip()]


def _with_frames(row, frames):
    if frames:
        row['frame'] = frames[0]
        if frames[1:]:
            row['nested_frames'] = frames[1:]
    return row


def locator_target(text):
    """Generator locator (structured object, Playwright call text, or 'frame >> ... css') -> page-map target row."""
    if isinstance(text, dict):
        frames = _frames_of(text.get('frames') or text.get('frame') or [])
        match_count = next((text[k] for k in ('match_count', 'matched_count', 'locator_count', 'count')
                            if type(text.get(k)) is int), None)
        if text.get('role'):
            row = {'role': str(text['role']), **({'name': str(text['name'])} if text.get('name') else {})}
        elif text.get('text'):
            row = {'selector': 'text=' + json.dumps(str(text['text']), ensure_ascii=False)}
        else:
            css = text.get('css') or text.get('selector')
            require(isinstance(css, str) and css.strip(), 'target object needs css, role or text')
            row = {'selector': css.strip()}
        if match_count is not None:
            row['match_count'] = match_count
        return _with_frames(row, frames)
    text = text.strip()
    call = re.match(r"^(?:page\.)?getBy(Role|Text|Label|Placeholder)\(\s*(['\"])(.*?)\2\s*(?:,\s*\{(.*?)\})?\s*\)\s*(?:scoped to|in|inside|within)?\s*(.*)$", text, re.S)
    if call:
        kind, arg, opts, rest = call.group(1), call.group(3), call.group(4) or '', call.group(5)
        name = re.search(r"name\s*:\s*(['\"])(.*?)\1", opts)
        if kind == 'Role':
            row = {'role': arg, **({'name': name.group(2)} if name else {})}
        elif kind == 'Text':
            row = {'selector': 'text=' + json.dumps(arg, ensure_ascii=False)}
        elif kind == 'Label':
            row = {'selector': 'internal:label=' + json.dumps(arg, ensure_ascii=False) + 's'}
        else:
            row = {'selector': '[placeholder=' + json.dumps(arg, ensure_ascii=False) + ']'}
        return _with_frames(row, _frames_of(rest))
    exact = re.search(r'\s+filtered by (?:exact )?text\s+["“]?([^"”()]+?)["”]?\s*$', text)
    if exact:
        text = text[:exact.start()]
    text = re.sub(r'\s*\((?:[^()]|\([^()]*\))*\)\s*$', '', text).strip()
    parts = [p.strip() for p in re.split(r'\s*>>\s*', text) if p.strip()]
    frames, last = parts[:-1], parts[-1] if parts else ''
    tokens = _split_top(last)
    while len(tokens) > 1 and re.match(r'^iframe\b', tokens[0]):
        frames.append(tokens.pop(0))
    selector = ' '.join(tokens)
    require(selector and not re.search(r'getBy|scoped to|\(\s*[\'"]', selector), 'unsupported locator: ' + text)
    if exact:
        selector += ':text-is(' + json.dumps(exact.group(1).strip(), ensure_ascii=False) + ')'
    return _with_frames({'selector': selector}, frames)


def same_locator(targets, row, name):
    keys = ('selector', 'role', 'name', 'frame', 'nested_frames', 'scope', 'resource')
    ident = {k: row.get(k) for k in keys}
    return next((other for other, existing in targets.items() if other != name and not existing.get('alias_of')
                 and {k: existing.get(k) for k in keys} == ident), None)


def bind_placeholders(base, m, placeholders, target_name):
    """Bind spec placeholders to a verified catalog target and rewrite run-local specs."""
    if not placeholders:
        return {}
    from .specs import spec_path
    normalized = [str(value).strip() for value in placeholders if str(value).strip()]
    require(normalized and all(value.startswith(('?', '？')) for value in normalized),
            '--for values must be ?case-spec placeholders')
    require(target_name in (read_yaml(knowledge_path('page-map.yaml')) or {}).get('targets', {}),
            'binding target is not in the page-map catalog: ' + str(target_name))
    mapping = {}
    for cid, case in m.get('cases', {}).items():
        path = spec_path(base, case)
        if not path.is_file():
            continue
        spec = read_yaml(path) or {}
        found = set()
        def collect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {'target', 'start_page'} and isinstance(item, str) and item in normalized:
                        found.add(item)
                    else:
                        collect(item)
            elif isinstance(value, list):
                for item in value: collect(item)
        collect(spec)
        if not found:
            continue
        bindings = case.setdefault('target_bindings', {})
        for placeholder in found:
            bindings[placeholder] = target_name
            mapping[placeholder] = target_name
        def rewrite(value):
            if isinstance(value, dict):
                for key, item in list(value.items()):
                    if key in {'target', 'start_page'} and isinstance(item, str) and item in found:
                        value[key] = target_name
                    else:
                        rewrite(item)
            elif isinstance(value, list):
                for item in value: rewrite(item)
        rewrite(spec)
        from .common import atomic_write
        atomic_write(path, spec, as_yaml=True)
    require(mapping, '--for placeholders were not found in any run case-spec')
    return mapping


def _for_values(value):
    return [item.strip() for item in (value or '').split(',') if item.strip()]


def promote(base, m, report, prefix=None, page=None, overwrite=False, for_placeholders=None):
    """Promote a generator report's targets and route into shared knowledge (page-map + confirmed entry)."""
    path = (base / report) if not Path(report).is_absolute() else Path(report)
    require(path.is_file(), 'generator report not found: ' + str(report))
    data = json.loads(path.read_text(encoding='utf-8'))
    route = data.get('route') or {}
    require(route and (route.get('reached') or route.get('reached_entry')), 'report has no reached route to promote')
    prefix = (prefix or data.get('purpose') or 'explored').strip('.')
    slug = lambda name: re.sub(r'[^A-Za-z0-9.-]+', '.', name).strip('.').lower()
    map_path = knowledge_path('page-map.yaml')
    catalog = read_yaml(map_path) if map_path.is_file() else {'schema_version': 'page-map.v1', 'pages': {}, 'targets': {}}
    targets = catalog.setdefault('targets', {})
    added, skipped = [], []
    source = 'generator:' + path.stem.replace('generator-', '')

    def put(name, row, evidence_count=None):
        if evidence_count is not None and 'match_count' not in row:
            row['match_count'] = evidence_count
        count = row.get('match_count') if isinstance(row, dict) else None
        require(count is None or count == 1,
                f'UIA_LOCATOR_AMBIGUOUS: {name} evidence matched {count} elements; use a scoped or exact locator')
        if name in targets and not overwrite:
            skipped.append(name)
            return
        twin = same_locator(targets, row, name)
        targets[name] = dict(row, source=source, confirmed=False, **({'alias_of': twin} if twin else {}))
        added.append(name)
    target_counts = route.get('target_match_counts') or route.get('locator_counts') or {}
    for name, locator in (route.get('targets') or {}).items():
        count = locator.get('match_count', locator.get('count')) if isinstance(locator, dict) else None
        if type(count) is not int and isinstance(target_counts, dict):
            count = target_counts.get(name)
        put(prefix + '.' + slug(name), locator_target(locator), count if type(count) is int else None)
    steps = []
    counts = route.get('step_match_counts') or route.get('match_counts') or {}
    for index, step in enumerate(route.get('route') or [], 1):
        count = (step.get('match_count', step.get('count')) if isinstance(step, dict) else None)
        count = count if type(count) is int else counts.get(str(index), counts.get(index)) if isinstance(counts, dict) else None
        require(count is None or count == 1,
                f'UIA_LOCATOR_AMBIGUOUS: route step {index} evidence matched {count} elements; use a scoped or exact locator')
        if isinstance(step, dict):
            verb, target, value = step.get('verb'), step.get('target'), step.get('value')
            require(verb in {'goto', 'click', 'hover', 'fill', 'type', 'press', 'wait'} and target, 'unsupported route step: ' + json.dumps(step, ensure_ascii=False))
            if isinstance(target, str) and (verb in {'goto', 'press', 'wait'} or target in targets or re.match(r'^(text|role)=', target)):
                steps.append(verb + ':' + target + ('=' + str(value) if verb in {'fill', 'type'} and value is not None else ''))
                continue
            name = prefix + '.route.' + str(index)
            put(name, locator_target(target))
            steps.append(verb + ':' + name + ('=' + (str(value) if value is not None else '${INPUT}') if verb in {'fill', 'type'} else ''))
            continue
        verb, _, rest = step.partition(':')
        require(verb in {'goto', 'click', 'hover', 'fill', 'type', 'press', 'wait'} and rest, 'unsupported route step: ' + step)
        rest = rest.strip()
        if verb in {'goto', 'press', 'wait'} or re.match(r'^(text|role)=', rest) and '>>' not in rest or rest in targets:
            steps.append(verb + ':' + re.sub(r'\s*\([^()]*\)\s*$', '', rest))
            continue
        if verb in {'fill', 'type'}:
            split = re.match(r'^(.*?)=([^=\]\)"\']*)$', rest)
            target, value = (split.group(1), '=' + split.group(2)) if split else (rest, '=${INPUT}')
        else:
            target, value = rest, ''
        name = prefix + '.route.' + str(index)
        put(name, locator_target(target))
        steps.append(verb + ':' + name + value)
    safe(catalog, m['config'])
    save_catalog('page-map.yaml', catalog)
    placeholder_mapping = {}
    placeholders = _for_values(for_placeholders)
    if placeholders:
        candidates = list(dict.fromkeys(added + skipped))
        for placeholder in placeholders:
            tail = re.sub(r'[^a-z0-9]+', '.', placeholder.lstrip('?？').lower()).strip('.')
            matches = [name for name in candidates if name.endswith(tail) or tail.endswith(name.rsplit('.', 1)[-1])]
            chosen = matches[0] if len(matches) == 1 else candidates[0] if len(candidates) == 1 else None
            require(chosen, '--for placeholder must identify one promoted target; use hints target for explicit binding')
            placeholder_mapping.update(bind_placeholders(base, m, [placeholder], chosen))
    result = {'page_map': str(map_path), 'targets_added': added, 'targets_skipped': skipped, 'route_steps': steps}
    page = page or data.get('entry')
    if page and route.get('reached_entry') and steps:
        hint = resolve(page)
        require(hint, '页面入口未知：请先 hints add')
        node = navigation_hint(hint).get('node')
        lead = ['click:' + node] if node and not steps[0].startswith(('goto:', 'click:' + node)) else []
        frames = route.get('frames') or []
        frame = FRAME_JOIN.join(frames) if frames else hint.get('frame')
        result.update(confirm(m, page, lead + steps, frame))
        result['entry_confirmed'] = page
    m.setdefault('knowledge_promotions', []).append({'at': now(), 'report': str(report), 'targets': added, 'entry': result.get('entry_confirmed')})
    if placeholder_mapping:
        result['placeholder_bindings'] = placeholder_mapping
    return result


def add_target(base, m, name, locator, evidence, overwrite=False, resource=None, saved_by=None, for_placeholders=None):
    """Register one observed target (from a snapshot/generator artifact) without fabricating a report."""
    require(re.fullmatch(r'[a-z0-9][a-z0-9.-]*', name or ''), 'target name: lowercase dotted, e.g. faq-editor.add')
    path = base / evidence
    require(evidence and path.is_file() and base.resolve() in path.resolve().parents, '--evidence must be an existing artifact inside the run (exploration/... or evidence/...)')
    if resource:
        require(re.fullmatch(r'/[^\s?#]*(?:\?[^\s#]*)?', resource) and '://' not in resource, '--resource 需为公开站点相对路径，如 /products/x.html')
        row = {'resource': {'path': resource, **({'saved_by': saved_by} if saved_by else {})}}
    else:
        require(locator, '--locator or --resource required')
        try:
            value = json.loads(locator)
        except ValueError:
            value = locator
        row = locator_target(value)
        evidence_doc = None
        try:
            evidence_doc = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            pass
        if isinstance(evidence_doc, dict):
            evidence_count = evidence_doc.get('match_count', evidence_doc.get('matched_count'))
            if type(evidence_count) is int and 'match_count' not in row:
                row['match_count'] = evidence_count
        count = row.get('match_count')
        require(count is None or count == 1,
                f'UIA_LOCATOR_AMBIGUOUS: {name} evidence matched {count} elements; use a scoped or exact locator')
    map_path = knowledge_path('page-map.yaml')
    catalog = read_yaml(map_path) if map_path.is_file() else {'schema_version': 'page-map.v1', 'pages': {}, 'targets': {}}
    targets = catalog.setdefault('targets', {})
    require(name not in targets or overwrite, 'target exists; pass --overwrite to replace it')
    twin = same_locator(targets, row, name)
    targets[name] = dict(row, source='observed:' + str(evidence), confirmed=False, **({'alias_of': twin} if twin else {}))
    safe(catalog, m['config'])
    save_catalog('page-map.yaml', catalog)
    m.setdefault('knowledge_promotions', []).append({'at': now(), 'target': name, 'evidence': str(evidence)})
    placeholder_mapping = bind_placeholders(base, m, _for_values(for_placeholders), name) if for_placeholders else {}
    return {'target': name, 'row': targets[name], 'page_map': str(map_path), **({'placeholder_bindings': placeholder_mapping} if placeholder_mapping else {})}
