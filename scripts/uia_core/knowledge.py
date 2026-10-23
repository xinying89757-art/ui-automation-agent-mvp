"""Shared knowledge catalogs, safe source merging, run matching and verified write-back."""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

from . import common
from .common import atomic_write, now, read_json, read_yaml, require
from .secrets import scrub_text

ROOT = common.ROOT / 'knowledge'
PATTERNS = {
    'FRAME_JOIN': {'description': 'Enter each iframe in order; use frameLocator for every frame in the chain.'},
    'RERENDER_RELOCATE': {'description': 'Wait for stable UI, re-resolve the locator, retry a bounded number of times.'},
    'OCCLUDED_SCROLL_OR_COLLAPSE': {'description': 'Scroll into view; if still occluded, collapse the covering panel before clicking.'},
}


def catalog(name):
    path = ROOT / name
    return read_yaml(path) if path.is_file() else {}


def _slug(value):
    value = re.sub(r'[^A-Za-z0-9._-]+', '-', str(value)).strip('.-').lower()
    return value[:100] or 'item'


def sync_layout(pages=None, entries=None, patterns=None, experience=None):
    """Migrate compatibility catalogs into page/component/flow/pattern resources and compact index."""
    pages = pages if pages is not None else catalog('page-map.yaml')
    entries = entries if entries is not None else catalog('entries.yaml')
    patterns = patterns if patterns is not None else catalog('patterns.yaml')
    experience = experience if experience is not None else catalog('experience.yaml')
    previous = {x['id']: x for x in (catalog('index.yaml').get('entries') or [])}
    rows, files = [], []
    known_pages = set(pages.get('pages', {}))
    def put(ident, kind, page, value, labels, route='', frame=None):
        old_index = previous.get(ident, {})
        filename = kind + 's/' + _slug(ident.replace('.', '-')) + '.yaml'
        old_path = ROOT / old_index.get('path', filename)
        old_body = read_yaml(old_path) if old_path.is_file() else {}
        verified = []
        provenance = value.get('provenance') if isinstance(value, dict) else None
        for proof in provenance if isinstance(provenance, list) else ([provenance] if provenance else []):
            if isinstance(proof, dict) and proof.get('verified_by') != 'unverified': verified.append(proof)
        last_verified = old_index.get('last_verified') or value.get('last_verified')
        for proof in verified:
            date_value = proof.get('verified_at') or proof.get('last_verified')
            if date_value: last_verified = max(filter(None, [last_verified, str(date_value)[:10]]))
        component_summary = (value.get('summary') or value.get('label') or value.get('name') or value.get('entry') or value.get('description') or ident)
        summary = re.sub(r'\s+', ' ', str(component_summary)).strip()[:140]
        tags = list(dict.fromkeys(str(x) for x in labels if isinstance(x, str) and x.strip()))
        version = str(value.get('version') or value.get('site_version') or catalog('config.yaml').get('site_version') or 'unknown')
        version_changed = bool(old_index.get('version') and old_index.get('version') != version)
        status = str((None if version_changed else old_index.get('status')) or value.get('status') or ('stable' if verified else 'unverified'))
        row = {'id': ident, 'page': page, 'route': str(route or ''), 'frame': frame or '', 'tags': tags,
               'version': version, 'status': status, 'last_verified': None if version_changed else last_verified,
               'last_hit': None if version_changed else old_index.get('last_hit'), 'summary': summary,
               'path': filename, 'hit_count': 0 if version_changed else int(old_index.get('hit_count', 0)),
               'pass_count': 0 if version_changed else int(old_index.get('pass_count', 0)),
               'fail_count': 0 if version_changed else int(old_index.get('fail_count', 0)),
               'observed_runs': [] if version_changed else list(old_index.get('observed_runs', [])),
               'failure_runs': [] if version_changed else list(old_index.get('failure_runs', []))}
        payload = {'id': ident, 'kind': kind, **value,
                   'created_at': old_body.get('created_at') or now()[:10],
                   **({'stale': True} if old_body.get('stale') else {})}
        if kind == 'component' and payload.get('alias_of') and not str(payload['alias_of']).startswith('target.'):
            payload['alias_of'] = 'target.' + str(payload['alias_of'])
        rows.append(row); files.append((filename, payload))
    for section in ('pages', 'targets'):
        for name, row in pages.get(section, {}).items():
            labels = [name, row.get('label'), row.get('name'), row.get('entry'), *row.get('aliases', [])]
            if section == 'pages':
                ident, page, kind = 'page.' + name, name, 'page'
            else:
                page = row.get('page') or name.split('.', 1)[0]
                if page not in known_pages: page = next(iter(known_pages), 'unknown')
                kind, ident = 'component', 'target.' + name
            frame = row.get('frame') or (','.join(row.get('nested_frames', [])) if row.get('nested_frames') else '')
            put(ident, kind, page, row, labels, row.get('route_prefix') or row.get('path') or row.get('entry'), frame)
    for name, row in entries.get('entries', {}).items():
        put('entry.' + name, 'flow', row.get('page') or name, row, [name, row.get('label'), *row.get('aliases', [])], row.get('path_text'), row.get('frame'))
    for name, row in patterns.get('patterns', {}).items():
        put('pattern.' + name, 'pattern', row.get('page') or '*', row, [name, row.get('description')], row.get('route'), row.get('frame'))
    for name, row in experience.get('entries', {}).items():
        put('experience.' + name, 'flow', row.get('page') or '*', row, [name, row.get('summary')], row.get('route'), row.get('frame'))
    for relative, payload in files:
        atomic_write(ROOT / relative, payload, as_yaml=True)
    atomic_write(ROOT / 'index.yaml', {'schema_version': 'uia-knowledge-index.v2', 'entries': rows}, as_yaml=True)
    return rows


def load_index():
    path = ROOT / 'index.yaml'
    if not path.is_file():
        sync_layout()
    return catalog('index.yaml').get('entries', [])


def load_item(item):
    path = ROOT / item.get('path', item.get('file', ''))
    return read_yaml(path) if path.is_file() else None


def prompt_budget(default=8000):
    raw = os.environ.get('UIA_KNOWLEDGE_BUDGET_CHARS')
    if raw and raw.isdigit(): return max(500, min(int(raw), 100000))
    config = catalog('config.yaml')
    value = config.get('prompt_budget_chars', default)
    return int(value) if type(value) is int and value >= 500 else default


def safe_tree(value, config=None):
    text = json.dumps(value, ensure_ascii=False)
    require(scrub_text(text, config) == text, 'Knowledge contains sensitive metadata')
    require(not re.search(r'(?i)(?:[\w.+-]+@[\w.-]+\.[a-z]{2,}|\b\d{7,}\b|(?:password|passwd|token|jwt|pin|邮箱|电话)\s*[:=])', text),
            'Knowledge contains personal or credential-like data')
    require(not re.search(r'(?i)(?:aria-ref\s*=|\[ref\s*=|["\'](?:f\d+)?e\d+["\']|(?:snapshot_ref|snapshotRef)\s*[":=])', text),
            'Knowledge cannot contain ephemeral snapshot references')


def _source_evidence(source_root, run_id):
    path = Path(source_root) / 'runs' / run_id / 'run.json'
    if not path.is_file():
        return {}
    manifest = read_json(path)
    verified = {}
    for cid, case in manifest.get('cases', {}).items():
        passed = any(a.get('executed') and a.get('result') == 'passed' for a in case.get('attempts', []))
        if not passed:
            continue
        spec_ref = case.get('case_spec')
        if not spec_ref:
            continue
        spec_path = Path(source_root) / 'runs' / run_id / spec_ref
        if not spec_path.is_file():
            continue
        spec = read_yaml(spec_path) or {}
        for row in [spec.get('start_page'), *(x.get('target') for x in spec.get('steps', []) if isinstance(x, dict))]:
            if isinstance(row, str):
                verified.setdefault(row, set()).add(cid)
    return {key: sorted(value) for key, value in verified.items()}


def _provenance(source_run, verified_by):
    return {'source_run': source_run, 'verified_by': verified_by or 'unverified'}


def _unique_records(rows):
    result, seen = [], set()
    for row in rows:
        key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if key not in seen: seen.add(key); result.append(row)
    return result


def _locator_key(row):
    selector = re.sub(r'\s+', ' ', str(row.get('selector') or '').strip())
    if selector:
        locator = ('selector', selector)
    elif row.get('role') and row.get('name'):
        locator = ('role', str(row['role']).strip().casefold(), re.sub(r'\s+', ' ', str(row['name']).strip()).casefold())
    else:
        logical = row.get('resource') or row.get('network_rule') or row.get('open') or row.get('text')
        locator = ('logical', json.dumps(logical if logical is not None else row, ensure_ascii=False, sort_keys=True))
    return tuple(json.dumps(value, ensure_ascii=False, sort_keys=True) for value in
                 (locator, str(row.get('frame') or '').strip(),
                  [str(x).strip() for x in row.get('nested_frames', [])], str(row.get('scope') or '').strip(),
                  row.get('page'), row.get('version')))


def merge(source_dir, run_id):
    source_dir = Path(source_dir).resolve()
    source_root = source_dir.parent.parent.parent
    evidence = _source_evidence(source_root, run_id)
    source_entries = read_yaml(source_dir / 'entries.yaml') or {'entries': {}}
    source_pages = read_yaml(source_dir / 'page-map.yaml') or {'pages': {}, 'targets': {}}
    dest_entries = catalog('entries.yaml') or {'schema_version': 'entry-hints.v1', 'entries': {}}
    dest_pages = catalog('page-map.yaml') or {'schema_version': 'page-map.v1', 'pages': {}, 'targets': {}}
    counts = {'new': 0, 'deduplicated': 0, 'unverified': 0}

    for name, row in (source_entries.get('entries') or {}).items():
        item = copy.deepcopy(row)
        verified = evidence.get(name, [])
        item['provenance'] = _provenance(run_id, verified)
        safe_tree(item)
        if name in dest_entries['entries']:
            old = dest_entries['entries'][name]
            old.setdefault('aliases', [])
            old['aliases'] = list(dict.fromkeys([*old['aliases'], *item.get('aliases', [])]))
            old['provenance'] = _unique_records([*(old.get('provenance') if isinstance(old.get('provenance'), list) else [old.get('provenance')]), item['provenance']])
            counts['deduplicated'] += 1
        else:
            dest_entries['entries'][name] = item; counts['new'] += 1
        counts['unverified'] += not bool(verified)

    for section in ('pages', 'targets'):
        dest = dest_pages.setdefault(section, {})
        for name, row in (source_pages.get(section) or {}).items():
            item = copy.deepcopy(row)
            verified = evidence.get(name, [])
            item['provenance'] = _provenance(run_id, verified)
            safe_tree(item)
            if name in dest:
                if section == 'targets' and _locator_key(dest[name]) == _locator_key(item):
                    dest[name].setdefault('alias_of', name)
                counts['deduplicated'] += 1
                # Preserve canonical locator; merge evidence without replacing existing contract.
                old = dest[name]
                old_prov = old.get('provenance')
                old['provenance'] = _unique_records([*(old_prov if isinstance(old_prov, list) else ([old_prov] if old_prov else [])), item['provenance']])
                if section == 'targets' and _locator_key(old) == _locator_key(item) and name != old.get('alias_of'):
                    old['alias_of'] = item.get('alias_of', old.get('alias_of'))
            else:
                twin = next((n for n, existing in dest.items() if section == 'targets' and _locator_key(existing) == _locator_key(item) and not existing.get('alias_of')), None)
                if twin:
                    item['alias_of'] = twin; counts['deduplicated'] += 1
                else:
                    counts['new'] += 1
                dest[name] = item
            counts['unverified'] += not bool(verified)
    canonical = {}
    for name, row in sorted(dest_pages.get('targets', {}).items()):
        key = _locator_key(row)
        if key in canonical:
            row['alias_of'] = canonical[key]
        else:
            canonical[key] = name
    safe_tree(dest_entries); safe_tree(dest_pages)
    atomic_write(ROOT / 'entries.yaml', dest_entries, as_yaml=True)
    atomic_write(ROOT / 'page-map.yaml', dest_pages, as_yaml=True)
    # Keep the legacy runner catalog in sync while callers migrate to the root catalog.
    legacy = common.ROOT / 'assets/playwright-runner/knowledge'
    atomic_write(legacy / 'entries.yaml', dest_entries, as_yaml=True)
    atomic_write(legacy / 'page-map.yaml', dest_pages, as_yaml=True)
    sync_layout(dest_pages, dest_entries)
    validate()
    return {'source_run': run_id, **counts, 'entries': len(dest_entries['entries']),
            'pages': len(dest_pages.get('pages', {})), 'targets': len(dest_pages.get('targets', {}))}


def validate():
    pages = catalog('page-map.yaml')
    patterns = catalog('patterns.yaml')
    errors = []
    try: safe_tree(patterns)
    except Exception: errors.append('patterns contain unsafe metadata')
    schema_path = common.ROOT / 'schemas/knowledge-index.schema.json'
    if not schema_path.is_file(): errors.append('knowledge index schema file missing')
    pattern_schema = common.ROOT / 'schemas/knowledge-patterns.schema.json'
    if not pattern_schema.is_file(): errors.append('knowledge patterns schema file missing')
    try:
        index_schema = json.loads(schema_path.read_text(encoding='utf-8'))
        schema_required = set(index_schema['properties']['entries']['items']['required'])
        if schema_required != {'id','page','route','frame','tags','version','status','last_verified','last_hit','summary','path','hit_count','pass_count','fail_count','observed_runs','failure_runs'}:
            errors.append('knowledge index schema fields do not match validator')
    except (OSError, ValueError, KeyError, TypeError):
        errors.append('knowledge index schema is invalid JSON or shape')
    try:
        pattern_doc = json.loads(pattern_schema.read_text(encoding='utf-8'))
        strategies = pattern_doc['properties']['patterns']['additionalProperties']['properties']['strategy']['enum']
        if set(strategies) != {'frame_chain','stable_relocate','scroll_collapse'}: errors.append('knowledge patterns schema strategy mismatch')
    except (OSError, ValueError, KeyError, TypeError):
        errors.append('knowledge patterns schema is invalid JSON or shape')
    if patterns.get('schema_version') != 'uia-patterns.v1' or not isinstance(patterns.get('patterns'), dict):
        errors.append('patterns schema_version/patterns is invalid')
    else:
        for name, row in patterns['patterns'].items():
            if (not isinstance(row, dict) or not isinstance(row.get('description'), str) or
                    row.get('strategy') not in {'frame_chain','stable_relocate','scroll_collapse'}): errors.append('invalid pattern: ' + name)
    for name, row in pages.get('targets', {}).items():
        refs = row.get('patterns', [])
        if not isinstance(refs, list) or any(ref not in patterns.get('patterns', {}) for ref in refs): errors.append('invalid patterns reference: ' + name)
        for record in row.get('provenance', []) if isinstance(row.get('provenance'), list) else [row.get('provenance')]:
            if record and (not record.get('source_run') or not ('verified_by' in record)): errors.append('invalid provenance: ' + name)
    index = catalog('index.yaml')
    if index and index.get('schema_version') != 'uia-knowledge-index.v2': errors.append('invalid knowledge index schema')
    allowed = {'id', 'page', 'route', 'frame', 'tags', 'version', 'status', 'last_verified', 'last_hit', 'summary', 'path', 'hit_count', 'pass_count', 'fail_count', 'observed_runs', 'failure_runs'}
    seen_ids, seen_paths, locators = set(), set(), {}
    for item in index.get('entries', []):
        if set(item) != allowed or not isinstance(item.get('tags'), list) or not isinstance(item.get('observed_runs'), list) or not isinstance(item.get('failure_runs'), list) or any(type(item.get(k)) is not int for k in ('hit_count','pass_count','fail_count')):
            errors.append('invalid knowledge index row')
            continue
        if item['id'] in seen_ids: errors.append('duplicate knowledge id: ' + item['id'])
        if item['path'] in seen_paths: errors.append('duplicate knowledge path: ' + item['path'])
        seen_ids.add(item['id']); seen_paths.add(item['path'])
        path = ROOT / item['path']
        if not path.is_file(): errors.append('knowledge index file missing: ' + item['id']); continue
        if path.stat().st_size > 48 * 1024: errors.append('knowledge entry exceeds 48 KiB: ' + item['id'])
        record = read_yaml(path) or {}
        try: safe_tree(record)
        except Exception: errors.append('unsafe knowledge entry: ' + item['id'])
        if record.get('id') != item['id']: errors.append('knowledge id/file mismatch: ' + item['id'])
        if not isinstance(item.get('summary'), str) or len(item['summary']) > 180: errors.append('knowledge summary exceeds 180 chars: ' + item['id'])
        if not isinstance(item.get('id'), str) or len(item['id']) > 160: errors.append('knowledge id exceeds 160 chars')
        if item.get('last_hit') is not None and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(item['last_hit'])): errors.append('invalid last_hit date: ' + item['id'])
        if item.get('status') not in {'stable','verified','unverified','needs_review','stale','deprecated'}: errors.append('invalid knowledge status: ' + item['id'])
        if record.get('kind') == 'component':
            locator = record.get('locator') or record
            key = (item.get('page'), item.get('frame'), item.get('version'), _locator_key(locator))
            if key in locators and not record.get('alias_of'): errors.append('duplicate locator without alias_of: ' + item['id'])
            locators[key] = item['id']
            if record.get('alias_of') and record['alias_of'] not in seen_ids and not any(x.get('id') == record['alias_of'] for x in index.get('entries', [])):
                errors.append('alias_of target missing: ' + item['id'])
    if len(index.get('entries', [])) > 5000: errors.append('knowledge index exceeds 5000 entries')
    index_path = ROOT / 'index.yaml'
    if index_path.exists() and index_path.stat().st_size > 2 * 1024 * 1024: errors.append('knowledge index exceeds 2 MiB')
    for kind in ('pages','components','flows','patterns'):
        for file in (ROOT / kind).glob('*.yaml') if (ROOT / kind).is_dir() else []:
            if file.relative_to(ROOT).as_posix() not in seen_paths: errors.append('unindexed knowledge file: ' + file.name)
    require(not errors, 'Knowledge validation failed', errors)
    return {'valid': True, 'patterns': len(patterns.get('patterns', {})), 'errors': []}


def prune(stale_after_days=90, candidate_after_days=180):
    """Mark old records stale and report deletion candidates; never delete files."""
    from datetime import date, timedelta
    require(type(stale_after_days) is int and 1 <= stale_after_days <= 36500, 'stale_after_days must be 1..36500')
    require(type(candidate_after_days) is int and stale_after_days <= candidate_after_days <= 36500,
            'candidate_after_days must be >= stale_after_days and <= 36500')
    today = date.today(); stale_cutoff = today - timedelta(days=stale_after_days)
    candidate_cutoff = today - timedelta(days=candidate_after_days)
    index = load_index(); changed, candidates = [], []
    for item in index:
        stamp = item.get('last_verified')
        try: verified = date.fromisoformat(str(stamp)[:10]) if stamp else None
        except ValueError: verified = None
        record = load_item(item) or {}
        try: created = date.fromisoformat(str(record.get('created_at'))[:10]) if record.get('created_at') else None
        except ValueError: created = None
        try: last_hit = date.fromisoformat(str(item.get('last_hit'))[:10]) if item.get('last_hit') else None
        except ValueError: last_hit = None
        if verified and verified < stale_cutoff and item.get('status') not in {'stale', 'deprecated'}:
            item['status'] = 'stale'; record['status'] = 'stale'
            atomic_write(ROOT / item['path'], record, as_yaml=True); changed.append(item['id'])
        hit_recentness = last_hit or verified or created
        if hit_recentness and hit_recentness < candidate_cutoff:
            candidates.append(item['id'])
    atomic_write(ROOT / 'index.yaml', {'schema_version':'uia-knowledge-index.v2','entries':index}, as_yaml=True)
    return {'stale_marked': changed, 'stale_count': len(changed), 'deletion_candidates': candidates,
            'candidate_count': len(candidates), 'stale_after_days': stale_after_days,
            'candidate_after_days': candidate_after_days, 'deleted': []}


def match_run(base, m):
    """Select per-case resources through the replaceable index retrieval interface."""
    from .retrieval import select, resolve_page
    output = {'matched': {}, 'unmatched_cases': [], 'discarded': {}, 'budgets': {}}
    for cid, case in m.get('cases', {}).items():
        source = read_json(base / case['source']) if case.get('source') and (base / case['source']).is_file() else {}
        spec_path = base / case.get('case_spec', '')
        spec = read_yaml(spec_path) if spec_path.is_file() else {}
        text = ' '.join(str(x or '') for x in (case.get('title'), case.get('module'), spec.get('intent'), source.get('title'), source.get('expected')))
        page = spec.get('start_page') or resolve_page(text)
        retrieval = select({'page': page, 'title': case.get('title'), 'module': case.get('module'),
                            'intent': spec.get('intent'), 'text': text}) if page else {'selected': [], 'discarded': [], 'max_tokens': None, 'used_tokens': 0, 'truncated': False}
        selected = {item['id']: item for item in retrieval['selected']}
        if selected:
            output['matched'][cid] = selected
        else:
            output['unmatched_cases'].append(cid)
        output['discarded'][cid] = retrieval['discarded']
        output['budgets'][cid] = {k: retrieval[k] for k in ('max_tokens', 'used_tokens', 'truncated')}
    output = {'schema_version': 'uia-knowledge-match.v1', 'run_id': m.get('run_id', 'unscoped'), **output}
    atomic_write(base / 'knowledge-match.json', output)
    m['knowledge_match'] = {'file': 'knowledge-match.json', 'matched_cases': sorted(output['matched']), 'unmatched_cases': output['unmatched_cases']}
    return output


def matched_context(base, m, cid):
    path = base / (m.get('knowledge_match') or {}).get('file', 'knowledge-match.json')
    if not path.is_file(): return {}
    data = read_json(path)
    matches = data.get('matched', {}).get(cid)
    if matches is None:
        from .retrieval import select, resolve_page
        page = resolve_page(cid)
        return select({'page': page, 'text': cid}) if page else {'selected': [], 'discarded': [], 'max_tokens': None, 'used_tokens': 0, 'truncated': False}
    return {'selected': list(matches.values()), 'discarded': data.get('discarded', {}).get(cid, []),
            **data.get('budgets', {}).get(cid, {})}


def known_page(page):
    if not isinstance(page, str) or not page.strip(): return False
    key = re.sub(r'[^\w\u4e00-\u9fff]+', '', page).casefold()
    for row in load_index():
      if row.get('kind') and row.get('kind') not in {'page','component','flow'}: continue
      for value in [row.get('id'), row.get('page'), row.get('summary'), *(row.get('tags') or [])]:
        if not isinstance(value, str): continue
        candidate = re.sub(r'[^\w\u4e00-\u9fff]+', '', value).casefold()
        if candidate and (candidate == key or min(len(candidate), len(key)) >= 3 and (candidate in key or key in candidate)): return True
    return False


def writeback(base, m):
    """Persist only entries backed by successful execution and repeated use."""
    pages = catalog('page-map.yaml') or {'schema_version': 'page-map.v1', 'pages': {}, 'targets': {}}
    experience = catalog('experience.yaml') or {'schema_version': 'uia-experience.v1', 'entries': {}}
    cases = [dict(value, case_id=value.get('case_id') or key) for key, value in m.get('cases', {}).items()]
    counts = {}
    page_counts = {}
    for case in cases:
        if not any(a.get('executed') and a.get('result') == 'passed' for a in case.get('attempts', [])): continue
        spec_path = base / case.get('case_spec', '')
        if not spec_path.is_file(): continue
        spec = read_yaml(spec_path) or {}
        page = spec.get('start_page')
        if page in pages.get('pages', {}):
            page_counts.setdefault(page, {})[case['case_id']] = sum(1 for a in case.get('attempts', []) if a.get('executed') and a.get('result') == 'passed')
        for step in spec.get('steps', []):
            target = step.get('target') if isinstance(step, dict) else None
            if target in pages.get('targets', {}):
                row = counts.setdefault(target, {})
                row[case['case_id']] = sum(1 for a in case.get('attempts', []) if a.get('executed') and a.get('result') == 'passed')
    changes = []
    for name, case_passes in page_counts.items():
        ids = sorted(cid for cid, amount in case_passes.items() if amount)
        if len(ids) < 2 and sum(case_passes.values()) < 2: continue
        row = pages['pages'][name]
        provenance = row.get('provenance')
        provenance = provenance if isinstance(provenance, list) else ([provenance] if provenance else [])
        proof = {'source_run': m['run_id'], 'verified_by': ids, 'verification_count': sum(case_passes.values())}
        if proof not in provenance:
            provenance.append(proof); row['provenance'] = provenance
            changes.append({'kind': 'page_entry', 'name': name, 'case_ids': ids, 'verification_count': sum(case_passes.values())})
    for name, case_passes in counts.items():
        ids = sorted(cid for cid, amount in case_passes.items() if amount)
        if len(ids) < 2 and sum(case_passes.values()) < 2: continue
        row = pages['targets'][name]
        provenance = row.get('provenance')
        provenance = provenance if isinstance(provenance, list) else ([provenance] if provenance else [])
        record = {'source_run': m['run_id'], 'verified_by': ids, 'verification_count': sum(case_passes.values())}
        if record not in provenance:
            provenance.append(record); row['provenance'] = provenance
            changes.append({'kind': 'target', 'name': name, 'case_ids': ids, 'verification_count': sum(case_passes.values())})
    # Aggregate evidence by stable target and independent execution batches.
    index = load_index() if (ROOT / 'index.yaml').is_file() else []
    match_path = base / (m.get('knowledge_match') or {}).get('file', 'knowledge-match.json')
    matched = read_json(match_path).get('matched', {}) if match_path.is_file() else {}
    for item in index:
        if m['run_id'] not in item.get('observed_runs', []):
            hits = sum(1 for rows in matched.values() if item['id'] in rows)
            if hits:
                item['hit_count'] = int(item.get('hit_count', 0)) + hits
                item['last_hit'] = __import__('datetime').date.today().isoformat()
    for item in index:
        target_name = item['id'].removeprefix('target.')
        target_cases = [case for case in cases if target_name in _spec_targets(base, case)]
        all_attempts = [a for case in target_cases for a in case.get('attempts', []) if a.get('executed')]
        observed_runs = item.setdefault('observed_runs', [])
        new_observation = m['run_id'] not in observed_runs
        if new_observation:
            item['pass_count'] = int(item.get('pass_count', 0)) + sum(a.get('result') == 'passed' for a in all_attempts)
            item['fail_count'] = int(item.get('fail_count', 0)) + sum(a.get('result') in {'automation_failure','interrupted'} for a in all_attempts)
            observed_runs.append(m['run_id'])
        independent_failures = {(a.get('batch_id') or a.get('started_at') or a.get('at'), item.get('version'))
                                for a in all_attempts if a.get('result') in {'automation_failure','interrupted'}}
        independent_failures.discard((None, item.get('version')))
        has_failure = any(a.get('result') in {'automation_failure','interrupted'} for a in all_attempts)
        if new_observation and has_failure: item.setdefault('failure_runs', []).append(m['run_id'])
        if len(set(item.get('failure_runs', []))) >= 2 or len(independent_failures) >= 2:
            item['status'] = 'needs_review'
        successful = [a for a in all_attempts if a.get('result') == 'passed']
        # last_verified requires repeated use and a success, matching the write-back threshold.
        repeated = len({case['case_id'] for case in target_cases if any(a.get('executed') and a.get('result') == 'passed' for a in case.get('attempts', []))}) >= 2 or sum(a.get('result') == 'passed' for a in all_attempts) >= 2
        if successful and repeated and new_observation:
            item['last_verified'] = now()[:10]
            if item['status'] in {'stale', 'unverified'}: item['status'] = 'stable'
    if index:
        atomic_write(ROOT / 'index.yaml', {'schema_version':'uia-knowledge-index.v2','entries':index}, as_yaml=True)
    # Persist only a repair strategy inferred from a successful locator/wait-only diff.
    from .metrics import locator_wait_only
    repair_patterns = {}
    for cid, case in m.get('cases', {}).items():
        rows = case.get('attempts', [])
        for pass_position, passed in enumerate(rows):
            if not (passed.get('executed') and passed.get('result') == 'passed' and passed.get('repair_baseline_script') and passed.get('repair_script')): continue
            failure = next((a for a in reversed(rows[:pass_position]) if a.get('executed') and a.get('result') == 'automation_failure'), None)
            category = failure.get('failure_stage') if failure else None
            if not isinstance(category, str) or category.lower() not in {'locator','wait','navigation','interaction','timeout','selector','frame'}: continue
            category = category.lower()
            before, after = base / passed['repair_baseline_script'], base / passed['repair_script']
            if not (before.is_file() and after.is_file() and locator_wait_only(before, after)): continue
            source = before.read_text(encoding='utf-8'); repaired = after.read_text(encoding='utf-8')
            import difflib
            additions = '\n'.join(line[1:] for line in difflib.ndiff(source.splitlines(), repaired.splitlines()) if line.startswith('+ '))
            if re.search(r'waitFor|waitUntil|waitForLoadState', additions):
                strategy = '稳定等待后重新查找目标'
            elif re.search(r'getByRole|getByLabel|getByText|locator|frameLocator', additions):
                strategy = '按当前页面结构更新并限定目标定位器'
            else: continue
            repair_patterns.setdefault((category, strategy), set()).add(cid)
    for (category, strategy), case_ids in repair_patterns.items():
        if len(case_ids) < 2: continue
        key = 'repair-' + _slug(category) + '-' + _slug(strategy)
        item = {'summary': '失败阶段 ' + category + '：' + strategy + '。',
                'provenance': {'source_run': m['run_id'], 'verified_by': sorted(case_ids)}}
        existing = experience['entries'].get(key)
        if existing != item: experience['entries'][key] = item; changes.append({'kind': 'experience', 'name': key, 'case_ids': sorted(case_ids)})
    atomic_write(ROOT / 'page-map.yaml', pages, as_yaml=True)
    atomic_write(common.ROOT / 'assets/playwright-runner/knowledge/page-map.yaml', pages, as_yaml=True)
    atomic_write(ROOT / 'experience.yaml', experience, as_yaml=True)
    sync_layout(pages=pages, experience=experience)
    result = {'added_or_updated': changes, 'count': len(changes), 'at': now()}
    m['knowledge_writeback'] = result
    return result


def _spec_targets(base, case):
    path = base / case.get('case_spec', '')
    if not path.is_file(): return set()
    spec = read_yaml(path) or {}
    return {step.get('target') for step in spec.get('steps', []) if isinstance(step, dict) and step.get('target')}
