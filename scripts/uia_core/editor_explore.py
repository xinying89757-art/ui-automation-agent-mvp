"""Turn one editor pass into needs_review knowledge candidates. Humans approve them later."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .common import ROOT, atomic_write, read_yaml, require
from .secrets import scrub_text


def _slug(value):
    value = re.sub(r'[^A-Za-z0-9._-]+', '-', str(value)).strip('.-').lower()
    return (value[:80] or 'control')


def write_candidates(dest, controls, run_id='editor-explore'):
    """Write a run-local catalog. Every row stays needs_review until a person approves it."""
    dest = Path(dest)
    (dest / 'components').mkdir(parents=True, exist_ok=True)
    rows, seen = [], set()
    for item in controls or []:
        if not isinstance(item, dict) or item.get('match_count') != 1:
            continue
        name = scrub_text(str(item.get('name') or '')).strip()
        if not name or any(token in name for token in ('[email]', '[phone]', '[REDACTED]')):
            continue
        selector = item.get('selector') if isinstance(item.get('selector'), str) else ''
        role = item.get('role') if isinstance(item.get('role'), str) else ''
        if not selector and not role:
            continue
        if re.search(r'aria-ref|snapshot_ref|\[ref\s*=', selector, re.I):
            continue
        ident = 'target.editor.' + _slug(selector or (role + '-' + name))
        if ident in seen:
            ident += '-' + str(len(seen))
        seen.add(ident)
        payload = {
            'id': ident, 'kind': 'component', 'page': 'editor', 'status': 'needs_review',
            'name': name[:80], 'frame': str(item.get('frame') or ''),
            'nested_frames': [str(frame) for frame in (item.get('nested_frames') or [])][:6],
            'evidence': {'match_count': 1, 'strategy': str(item.get('strategy') or '')[:40],
                         'source': 'editor-explore', 'midscene': bool(item.get('midscene'))},
            'provenance': [{'source_run': run_id, 'verified_by': 'unverified'}],
        }
        if selector:
            payload['selector'] = selector[:300]
        if role:
            payload['role'] = role[:40]
        relative = 'components/' + _slug(ident) + '.yaml'
        atomic_write(dest / relative, payload, as_yaml=True)
        rows.append({
            'id': ident, 'page': 'editor', 'route': '', 'frame': payload['frame'],
            'tags': ['editor', 'needs_review'], 'version': 'unknown', 'status': 'needs_review',
            'last_verified': None, 'last_hit': None, 'summary': name[:140], 'path': relative,
            'hit_count': 0, 'pass_count': 0, 'fail_count': 0, 'observed_runs': [run_id], 'failure_runs': [],
        })
    atomic_write(dest / 'index.yaml', {'schema_version': 'uia-knowledge-index.v2', 'entries': rows}, as_yaml=True)
    return {'count': len(rows), 'status': 'needs_review', 'ids': [row['id'] for row in rows]}


def validate_candidates(dest):
    index = read_yaml(Path(dest) / 'index.yaml') or {}
    errors = []
    if index.get('schema_version') != 'uia-knowledge-index.v2':
        errors.append('index schema')
    for row in index.get('entries') or []:
        if row.get('status') != 'needs_review':
            errors.append('index status ' + str(row.get('id')))
        record = read_yaml(Path(dest) / row.get('path', '')) or {}
        if record.get('status') != 'needs_review' or record.get('id') != row.get('id'):
            errors.append('record ' + str(row.get('id')))
        if record.get('evidence', {}).get('match_count') != 1:
            errors.append('evidence ' + str(row.get('id')))
    require(not errors, 'Editor candidates are not reviewable needs_review records', errors)
    return {'valid': True, 'count': len(index.get('entries') or [])}


def run_smoke(profile, out=None):
    """Live skeleton smoke. Returns timings and screenshot paths, never credentials."""
    runner = ROOT / 'assets/playwright-runner'
    from .common import config
    from .profiles import profile_path
    private = ROOT / '.auth'
    private.mkdir(exist_ok=True, mode=0o700)
    handle, temporary = tempfile.mkstemp(prefix='smoke-', suffix='.json', dir=private)
    os.close(handle)
    try:
        atomic_write(temporary, config(profile_path(profile)))
        command = ['node', str(runner / 'scripts/editor-live-smoke.mjs'), '--config', temporary]
        if out:
            command.extend(['--out', str(Path(out).resolve())])
        result = subprocess.run(command, cwd=runner, capture_output=True, text=True)
        try:
            payload = json.loads(result.stdout)
        except (ValueError, TypeError):
            require(False, 'Editor smoke did not return JSON', {'exit_code': result.returncode})
        kept = {key: payload.get(key) for key in ('ok', 'code', 'reason', 'error', 'steps', 'screenshots', 'rescued_by_midscene', 'inserted')}
        require(result.returncode == 0 and payload.get('ok'), payload.get('error') or 'Editor smoke failed', kept)
        return kept
    finally:
        Path(temporary).unlink(missing_ok=True)


def run_explore(fixture=None, profile=None, out=None, run_id='editor-explore'):
    runner = ROOT / 'assets/playwright-runner'
    out_dir = Path(out) if out else ROOT / 'runs' / run_id / 'knowledge-candidates'
    command = ['node', str(runner / 'scripts/explore-editor-controls.mjs')]
    temporary = None
    try:
        if fixture:
            command.extend(['--fixture', str(Path(fixture).resolve())])
        elif profile:
            from .common import config
            from .profiles import profile_path
            private = ROOT / '.auth'
            private.mkdir(exist_ok=True, mode=0o700)
            handle, temporary = tempfile.mkstemp(prefix='explore-', suffix='.json', dir=private)
            os.close(handle)
            atomic_write(temporary, config(profile_path(profile)))
            command.extend(['--config', temporary])
        else:
            require(False, 'editor-explore needs --fixture or --profile')
        result = subprocess.run(command, cwd=runner, capture_output=True, text=True)
        try:
            payload = json.loads(result.stdout)
        except (ValueError, TypeError):
            require(False, 'Editor explore did not return JSON', {'exit_code': result.returncode})
        require(result.returncode == 0 and payload.get('ok'), payload.get('error') or 'Editor explore failed',
                {'code': payload.get('code')})
        written = write_candidates(out_dir, payload.get('controls') or [], run_id=run_id)
        validate_candidates(out_dir)
        return {'candidates': written['count'], 'status': 'needs_review', 'midscene': payload.get('midscene'),
                'ids': written['ids'], 'directory': str(out_dir)}
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)
