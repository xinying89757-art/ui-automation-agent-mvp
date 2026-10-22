"""Credential-free file hand-off; run.json owns pending checks and ingestion history."""
import copy
import datetime as dt
import shutil
from pathlib import Path
from .common import ROOT, atomic_write, digest, event, file_hash, now, read_json, require
from .secrets import scrub_text

LABELS = {'pending': '待远程检查', 'pass': '远程通过', 'fail': '远程业务失败',
          'still-cached': '公开文件仍在缓存期', 'unreachable': '远程不可达或无法验证'}


def timestamp(value):
    try:
        result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(result.tzinfo is not None, 'Remote timestamp must include timezone')
        return result
    except (ValueError, TypeError, AttributeError):
        require(False, 'Invalid remote timestamp')


def export(base, m):
    checks = [row['request'] for row in m.get('remote_checks', {}).values() if row.get('active', True)]
    if not checks:
        return None
    directory = base / 'remote-checks'
    directory.mkdir(exist_ok=True)
    payload = {'schema_version': 'uia-remote-request.v1', 'run_id': m['run_id'], 'checks': checks}
    require(scrub_text(__import__('json').dumps(payload, ensure_ascii=False), m['config']) == __import__('json').dumps(payload, ensure_ascii=False), 'Remote request contains sensitive data')
    current = directory / 'request.json'
    if current.is_file():
        archive = directory / 'requests'
        archive.mkdir(exist_ok=True)
        shutil.copyfile(current, archive / (file_hash(current) + '.json'))
    atomic_write(current, payload)
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'templates/remote-check.mjs', directory / 'check.mjs')
    return str(directory / 'request.json')


def collect(base, m, batch, cid, attempt):
    file = base / batch['directory'] / ('remote-' + cid + '.json')
    if not file.is_file() or attempt['result'] != 'passed':
        return
    rows = read_json(file)
    require(isinstance(rows, list), 'Invalid deferred checks')
    registry = m.setdefault('remote_checks', {})
    for old in registry.values():
        if old['request']['case_id'] == cid:
            old['active'] = False
    from .common import read_yaml
    spec = read_yaml(base / m['cases'][cid]['case_spec'])
    assertions = {a['id']: a for a in spec['assertions']}
    for item in rows:
        require(item.get('assertion_id') in assertions and item.get('expected') == assertions[item['assertion_id']]['excel'], 'Deferred expectation differs from Excel contract')
        require(item.get('method') == 'GET' and isinstance(item.get('conditions'), list) and item['conditions'], 'Invalid deferred file check')
        saved = timestamp(item['saved_at'])
        identity = digest([m['run_id'], batch['id'], cid, item['assertion_id']])[:24]
        request = {**item, 'id': identity, 'case_id': cid,
                   'earliest_check_at': (saved + dt.timedelta(hours=1)).isoformat(),
                   'deadline': (saved + dt.timedelta(hours=2)).isoformat(), 'timeout_ms': 10000}
        registry[identity] = {'request': request, 'status': 'pending', 'batch_id': batch['id'],
                              'version': attempt['version'], 'active': True, 'history': []}
    fold(m, cid)
    export(base, m)


def fold(m, cid):
    c = m['cases'][cid]
    entries = [r for r in m.get('remote_checks', {}).values() if r.get('active', True) and r['request']['case_id'] == cid]
    if not entries:
        return
    statuses = {r['status'] for r in entries}
    status = next((s for s in ('fail', 'unreachable', 'still-cached', 'pending') if s in statuses), 'pass')
    c['remote_status'] = status
    c['classification'] = {'reason': LABELS[status], 'at': now()}
    if status == 'pass' and not c['attempts'][-1].get('cleanup_verified'):
        c.update(result='remote_pending', pass_streak=0, stability='not_run', stage='remote', work_status='remote_pending')
        c['classification']['reason'] = '远程通过，等待本机恢复数据并核验'
        return
    if status == 'pass':
        # Only an independently clean local batch plus all remote assertions can pass.
        attempt = c['attempts'][-1]
        require(attempt['result'] == 'passed' and attempt['cleanup_verified'] and attempt['setup_verified'], 'Local lifecycle did not pass')
        streak = 0
        for a in reversed(c['attempts']):
            if a['version'] != c['version'] or a['result'] != 'passed' or a.get('remote_status') != 'pass' and a is not attempt:
                break
            streak += 1
        attempt['remote_status'] = 'pass'
        stable = streak >= m['config']['execution']['stability_passes']
        c.update(result='passed', pass_streak=streak, stability='stable' if stable else 'candidate',
                 stage='feedback' if stable else 'execution', work_status='finished' if stable else 'runnable')
    elif status == 'fail':
        c.update(result='business_failure', pass_streak=0, stability='unstable', stage='finished', work_status='finished')
    else:
        c.update(result={'pending':'remote_pending', 'unreachable':'remote_unreachable', 'still-cached':'remote_cached'}[status],
                 pass_streak=0, stability='not_run', stage='remote', work_status='remote_pending')


def ingest(base, m, file):
    require(not m.get('active_batch'), 'Wait for the active batch before ingesting')
    payload = read_json(file)
    receipt = digest(payload)
    if receipt in m.get('remote_ingests', []):
        return {'ingested': 0, 'duplicate': True}
    require(isinstance(payload, dict) and set(payload) == {'schema_version', 'run_id', 'request_sha256', 'results'}, 'Invalid remote result envelope')
    request_file = base / 'remote-checks/request.json'
    require(request_file.is_file() and payload['schema_version'] == 'uia-remote-results.v1' and payload['run_id'] == m['run_id'] and
            payload['request_sha256'] == file_hash(request_file), 'Remote result is not for the current request')
    require(isinstance(payload['results'], list) and payload['results'], 'Empty remote results')
    ids = set()
    registry = m.get('remote_checks', {})
    # Validate every row before mutating anything. No arbitrary body/error fields accepted.
    for row in payload['results']:
        require(isinstance(row, dict) and set(row) == {'id', 'checked_at', 'status', 'http_status', 'conditions', 'reason'}, 'Invalid remote result row')
        key = row['id']; require(isinstance(key, str) and key in registry and key not in ids and registry[key].get('active', True), 'Unknown, stale or duplicate remote check')
        ids.add(key); entry = registry[key]; req = entry['request']; c = m['cases'][req['case_id']]
        require(entry['version'] == c['version'] and entry['batch_id'] == c['attempts'][-1]['batch_id'], 'Remote result targets an obsolete attempt')
        if c.get('registration'):
            from .workflow import case_version
            require(case_version(base, m, c) == entry['version'], 'Remote result targets changed executable dependencies')
        checked = timestamp(row['checked_at'])
        require(not entry['history'] or checked >= timestamp(entry['history'][-1]['checked_at']), 'Remote observation is older than the previous receipt')
        require(timestamp(req['saved_at']) <= checked <= timestamp(now()) + dt.timedelta(minutes=5), 'Remote check time outside execution window')
        require(isinstance(row['status'], str) and row['status'] in {'pass', 'fail', 'still-cached', 'unreachable'}, 'Invalid remote status')
        require(isinstance(row['reason'], str) and row['reason'] in {'network', 'deadline', 'data_restored', 'immediate_timing_unverified', 'conditions_met', 'cache_window', 'http_unavailable', 'conditions_mismatch'}, 'Invalid remote reason')
        require(row['http_status'] is None or type(row['http_status']) is int and 100 <= row['http_status'] <= 599, 'Invalid HTTP status')
        require(isinstance(row['conditions'], list) and all(type(x) is bool for x in row['conditions']), 'Invalid condition outcomes')
        if row['status'] != 'unreachable':
            require(len(row['conditions']) == len(req['conditions']), 'Incomplete condition outcomes')
            require(checked <= timestamp(req['deadline']), 'Expired remote result cannot settle a case')
            require(not req.get('restored_at') or checked < timestamp(req['restored_at']), 'Test data was already restored; rerun preparation')
        if row['status'] == 'pass':
            local = c['attempts'][-1]
            require(local['result'] == 'passed' and local['setup_verified'] and (local['cleanup_verified'] or local.get('cleanup_pending')), 'Local lifecycle did not pass')
            require(row['http_status'] is not None and 200 <= row['http_status'] < 300 and all(row['conditions']), 'Pass contradicts observations')
            require(not req.get('max_latency_seconds') or (checked - timestamp(req['saved_at'])).total_seconds() <= req['max_latency_seconds'], 'Late fetch cannot prove immediate update')
        if row['status'] == 'still-cached':
            require(checked < timestamp(req['earliest_check_at']), 'Cache grace period already ended')
        if row['status'] == 'fail':
            require(checked >= timestamp(req['earliest_check_at']) or req.get('max_latency_seconds'), 'Mismatch inside cache window is still-cached')
            require(not (row['http_status'] is not None and 200 <= row['http_status'] < 300 and all(row['conditions'])), 'Failure contradicts observations')
    receipt = digest(payload)
    receipts = m.setdefault('remote_ingests', [])
    if receipt in receipts:
        return {'ingested': 0, 'duplicate': True}
    destination = base / 'remote-checks' / ('ingested-' + receipt + '.json')
    atomic_write(destination, payload)
    affected = set()
    for row in payload['results']:
        entry = registry[row['id']]
        require(not entry['history'] or timestamp(row['checked_at']) >= timestamp(entry['history'][-1]['checked_at']), 'Remote observation is older than the previous receipt')
        entry['history'].append(copy.deepcopy(row))
        entry['status'] = row['status']; affected.add(entry['request']['case_id'])
    receipts.append(receipt)
    active = [r for r in registry.values() if r.get('active', True)]
    cleanup = None
    if all(r['status'] in {'pass', 'fail', 'unreachable'} for r in active):
        cleanup = restore(base, m)
    for cid in affected:
        fold(m, cid)
    event(m, 'remote_checks_ingested', receipt=receipt, case_ids=sorted(affected))
    return {'ingested': len(payload['results']), 'cleanup': cleanup, 'cases': {cid: m['cases'][cid]['result'] for cid in sorted(affected)}}


def restore(base, m):
    """Restore held baselines in reverse order, including overlapping fixture snapshots."""
    import json
    import os
    import subprocess
    pending = [(cid, c['attempts'][-1]) for cid, c in m['cases'].items()
               if c.get('attempts') and c['attempts'][-1].get('cleanup_pending')]
    if not pending:
        return {'cleanup_verified': True, 'leases': 0}
    pending.sort(key=lambda item: item[1]['at'], reverse=True)
    leases = []
    for cid, attempt in pending:
        snapshot = base / 'state/fixture-snapshots' / (attempt['batch_id'] + '-' + cid + '.json')
        require(snapshot.is_file(), 'Protected fixture snapshot missing; retain cleanup failure evidence')
        leases.append({'case_id': cid, 'snapshot': str(snapshot)})
    control = base / 'state/remote-restore'
    control.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write(control / 'config.json', m['config'])
    atomic_write(control / 'leases.json', leases)
    for f in control.iterdir():
        f.chmod(0o600)
    try:
        output = subprocess.run(['node', str(base / 'runner/scripts/restore-remote.mjs')],
                            env=dict(os.environ, UIA_CONFIG=str(control / 'config.json'),
                                     UIA_REMOTE_LEASES=str(control / 'leases.json')),
                            capture_output=True, text=True, timeout=360)
    except (subprocess.TimeoutExpired, OSError):
        output = type('RestoreOutput', (), {'stdout': '{}'})()
    try:
        proof = json.loads(output.stdout)
    except ValueError:
        proof = {'cleanup_verified': False, 'proofs': []}
    target = base / 'evidence' / ('remote-restore-' + now().replace(':', '-') + '.json')
    atomic_write(target, proof)
    restored = {p['case_id']: p for p in proof.get('proofs', []) if p.get('cleanup_verified')}
    for cid, attempt in pending:
        if cid in restored:
            attempt.update(cleanup_verified=True, cleanup_pending=False, remote_cleanup_evidence=str(target.relative_to(base)))
            for row in m.get('remote_checks', {}).values():
                if row.get('active', True) and row['request']['case_id'] == cid:
                    row['request']['restored_at'] = restored[cid]['restored_at']
                    if row['status'] in {'pending', 'still-cached'}:
                        row['status'] = 'unreachable'
                        row['history'].append({'id': row['request']['id'], 'checked_at': now(), 'status': 'unreachable', 'http_status': None, 'conditions': [], 'reason': 'data_restored'})
            fold(m, cid)
    export(base, m)
    event(m, 'remote_data_restored', case_ids=sorted(restored), evidence=str(target.relative_to(base)))
    return {'cleanup_verified': proof.get('cleanup_verified') is True, 'leases': len(pending), 'evidence': str(target.relative_to(base))}


def expire(base, m):
    expired = [r for r in m.get('remote_checks', {}).values() if r.get('active', True)
               and not r['request'].get('restored_at') and timestamp(now()) > timestamp(r['request']['deadline'])]
    if not expired:
        return None
    for row in expired:
        if row['status'] in {'pending', 'still-cached'}:
            row['status'] = 'unreachable'
            row['history'].append({'id': row['request']['id'], 'checked_at': now(), 'status': 'unreachable',
                                   'http_status': None, 'conditions': [], 'reason': 'deadline'})
    result = restore(base, m)
    for row in expired:
        fold(m, row['request']['case_id'])
    return result
