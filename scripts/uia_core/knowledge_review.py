"""Reviewed, version-bound publication of run-local knowledge candidates."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from . import common, knowledge
from .common import atomic_write, now, read_json, read_yaml, require


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def candidates(base, m):
    """Only explicitly curated discoveries with existing execution evidence are reviewable."""
    rows = []
    for item in m.get('knowledge_review_candidates', []):
        row = copy.deepcopy(item)
        require(row.get('kind') in {'entry', 'target', 'experience'}, 'Unsupported knowledge candidate kind')
        require(isinstance(row.get('id'), str) and row['id'], 'Candidate requires stable id')
        require(row.get('scope') and isinstance(row.get('after'), dict), 'Candidate requires scope and content')
        refs = row.get('evidence') or []
        require(isinstance(refs, list) and refs, 'Candidate requires evidence')
        for ref in refs:
            evidence = common.inside(base, ref)
            require(evidence.is_file(), 'Knowledge evidence is missing', ref)
        filename, section = {'entry': ('entries.yaml', 'entries'), 'target': ('page-map.yaml', 'targets'), 'experience': ('experience.yaml', 'entries')}[row['kind']]
        row['before'] = knowledge.catalog(filename).get(section, {}).get(row['id'])
        row['source_run'] = m['run_id']
        row['evidence_hashes'] = {ref: common.file_hash(common.inside(base, ref)) for ref in refs}
        row['version'] = fingerprint(row)
        rows.append(row)
    require(len({x['id'] for x in rows}) == len(rows), 'Duplicate candidate id')
    return rows



def propose(base, m, row, replace=False):
    """Record an evidence-backed candidate in this run, without changing shared knowledge."""
    from .secrets import scrub_text
    require(isinstance(row, dict) and row.get('kind') in {'entry', 'target', 'experience'}, 'Invalid candidate')
    from .specs import has_snapshot_ref
    require(not has_snapshot_ref(row), 'Candidate cannot contain a temporary snapshot reference')
    text = json.dumps(row, ensure_ascii=False)
    require(scrub_text(text, m['config']) == text, 'Candidate contains sensitive metadata')
    evidence = row.get('evidence') or []
    require(isinstance(evidence, list) and evidence, 'Candidate requires batch evidence')
    after = row.get('after') or {}
    proof = after.get('provenance') or {}
    case_ids = proof.get('verified_by')
    require(isinstance(case_ids, list) and case_ids and all(isinstance(x, str) for x in case_ids),
            'Candidate requires verified case IDs')
    require(proof.get('source_run') == m.get('run_id') and proof.get('verified_at') and after.get('last_verified'),
            'Candidate requires source run and verification date')
    require(set(proof.get('evidence') or []) == set(evidence), 'Candidate provenance must match evidence')
    require(row.get('kind') != 'entry' or after.get('arrival_signal'), 'Entry requires an arrival signal')
    passed_cases = set()
    for ref in evidence:
        path = common.inside(base, ref)
        require(path.is_file(), 'Knowledge evidence is missing', ref)
        if path.name == 'case-results.json':
            document = read_json(path)
            passed_cases.update(x.get('case_id') for x in document.get('cases', []) if x.get('result') == 'passed')
    require(set(case_ids) <= passed_cases, 'Candidate case IDs require successful batch evidence')
    rows = m.setdefault('knowledge_review_candidates', [])
    existing = next((i for i, item in enumerate(rows) if item.get('id') == row.get('id')), None)
    require(existing is None or replace, 'Candidate ID already exists; use --replace')
    previous = copy.deepcopy(rows)
    if existing is None:
        rows.append(copy.deepcopy(row))
    else:
        rows[existing] = copy.deepcopy(row)
    try:
        candidate = next(x for x in candidates(base, m) if x['id'] == row.get('id'))
    except Exception:
        rows[:] = previous
        raise
    return {'candidate': candidate, 'writeback': 'not_applied'}


def _reject_conflicts(base, m, current, ids):
    refreshed = {'schema_version': 'uia-asset-review-conflicts.v1', 'run_id': m['run_id'],
                 'generated_at': now(), 'candidates': [current[item] for item in ids if item in current],
                 'missing': [item for item in ids if item not in current]}
    path = Path(base) / 'reports/asset-review-conflicts.json'
    atomic_write(path, refreshed)
    require(False, 'Candidate or shared knowledge changed; regenerate report and review', str(path))

def writeback(base, m, review_file):
    """Apply exactly the approved reviewed differences, or leave the shared library unchanged."""
    require(review_file, 'Knowledge writeback requires --review FILE')
    review = read_json(Path(review_file))
    require(review.get('schema_version') == 'uia-knowledge-review.v1' and review.get('run_id') == m['run_id'], 'Review does not match this run')
    selections = review.get('items')
    require(isinstance(selections, list), 'Review items must be a list')
    require(len({x.get('id') for x in selections}) == len(selections), 'Duplicate review item')
    require(all(x.get('decision') in {'approve', 'defer', 'reject'} for x in selections), 'Invalid review decision')
    review_hash = fingerprint(review)
    if any(x.get('review_sha256') == review_hash for x in m.get('knowledge_writebacks', [])):
        return {'already_applied': True, 'review_sha256': review_hash}
    current = {x['id']: x for x in candidates(base, m)}
    conflicts = [item.get('id') for item in selections
                 if item.get('id') not in current or current[item['id']]['version'] != item.get('version')]
    if conflicts:
        _reject_conflicts(base, m, current, conflicts)
    approved = [current[x['id']] for x in selections if x['decision'] == 'approve']
    if not approved:
        m.setdefault('knowledge_writebacks', []).append({'review_sha256': review_hash, 'at': now(), 'applied': []})
        return {'applied': [], 'review_sha256': review_hash}
    root = knowledge._root()
    import fcntl
    lock_file = root.parent / '.uia-knowledge-writeback.lock'
    with lock_file.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        docs = {name: knowledge.catalog(name) for name in ('entries.yaml', 'page-map.yaml', 'experience.yaml')}
        mapping = {'entry': ('entries.yaml', 'entries'), 'target': ('page-map.yaml', 'targets'), 'experience': ('experience.yaml', 'entries')}
        for row in approved:
            filename, section = mapping[row['kind']]
            actual = docs[filename].setdefault(section, {}).get(row['id'])
            if actual != row.get('before'):
                refreshed = {item['id']: item for item in candidates(base, m)}
                _reject_conflicts(base, m, refreshed, [row['id']])
            docs[filename][section][row['id']] = row['after']
        targets = docs['page-map.yaml'].get('targets', {})
        for row in approved:
            if row['kind'] == 'target':
                alias = row['after'].get('alias_of')
                require(not alias or alias in targets, 'Missing referenced knowledge target', alias)
            if row['kind'] == 'entry':
                for step in row['after'].get('steps', []):
                    verb, _, target = step.partition(':')
                    if verb in {'click', 'hover', 'fill', 'type'} and target and not target.startswith(('text=', 'role=')):
                        target = target.split('=', 1)[0]
                        require(target in targets, 'Missing referenced knowledge target', target)
        with tempfile.TemporaryDirectory(prefix='uia-kb-stage-', dir=root.parent) as tmp:
            stage = Path(tmp) / 'knowledge'
            shutil.copytree(root, stage)
            for name, data in docs.items():
                atomic_write(stage / name, data, as_yaml=True)
            old_root = knowledge.ROOT
            try:
                knowledge.ROOT = stage
                knowledge.sync_layout(pages=docs['page-map.yaml'], entries=docs['entries.yaml'], experience=docs['experience.yaml'])
            finally:
                knowledge.ROOT = old_root
            selected_ids = {('target.' if row['kind'] == 'target' else row['kind'] + '.') + row['id'] for row in approved}
            staged_index = read_yaml(stage / 'index.yaml')
            new_items = {row['id']: row for row in staged_index.get('entries', []) if row['id'] in selected_ids}
            require(set(new_items) == selected_ids, 'Approved entries could not be indexed')
            original_index = knowledge.catalog('index.yaml')
            original_rows = original_index.get('entries', [])
            rows = [new_items.pop(row['id'], row) for row in original_rows]
            rows.extend(new_items.values())
            index = dict(original_index, schema_version=original_index.get('schema_version', 'uia-knowledge-index.v2'), entries=rows)
            atomic_write(stage / 'approved-index.yaml', index, as_yaml=True)
            writes = {root / 'index.yaml': (stage / 'approved-index.yaml').read_bytes()}
            for item in staged_index.get('entries', []):
                if item['id'] in selected_ids:
                    resource = common.inside(stage, item['path'])
                    writes[root / item['path']] = resource.read_bytes()
            runner = common.ROOT / 'assets/playwright-runner/knowledge'
            for name in {mapping[row['kind']][0] for row in approved}:
                writes[root / name] = (stage / name).read_bytes()
                writes[runner / name] = (stage / name).read_bytes()
            backups = {p: p.read_bytes() if p.exists() else None for p in writes}
            try:
                for path, content in writes.items():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.uia-')
                    with os.fdopen(fd, 'wb') as f:
                        f.write(content)
                    os.replace(temporary, path)
            except Exception:
                for path, old in backups.items():
                    if old is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.write_bytes(old)
                raise
        record = {'review_sha256': review_hash, 'at': now(), 'applied': [{'id': x['id'], 'version': x['version'], 'evidence': x['evidence']} for x in approved]}
        m.setdefault('knowledge_writebacks', []).append(record)
        return record
