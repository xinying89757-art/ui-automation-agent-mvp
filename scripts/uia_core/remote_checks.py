"""Credential-free file hand-off; run.json owns pending checks and ingestion history."""
import copy
import datetime as dt
import hashlib
import re
import shutil
import time
import urllib.request
import urllib.error
import statistics
from pathlib import Path
from .common import ROOT, atomic_write, digest, event, file_hash, now, read_json, require
from .secrets import scrub_text

LABELS = {'pending': '待远程检查', 'pass': '远程通过', 'fail': '远程业务失败',
          'pass_reevaluated': '本机证据复核通过', 'still-cached': '公开文件仍在缓存期', 'unreachable': '远程不可达或无法验证'}

def evaluate_condition(body_or_section, condition):
    """Python port of the credential-free checker evaluator (version 2)."""
    body = str(body_or_section); op = condition.get('op'); value = condition.get('value')
    if op == 'contains': return str(value) in body
    if op == 'equals': return body == value
    if op != 'ordered_pairs': raise ValueError('Unsupported condition')
    lines = body.splitlines(); wanted = str(condition.get('section', '')).strip().lower()
    start = None; level = 0
    for i, line in enumerate(lines):
        match = re.match(r'^(#{2,6})\s+(.+?)\s*#*\s*$', line)
        if match and match.group(2).strip().lower() == wanted:
            start, level = i, len(match.group(1)); break
    if start is None: return False
    end = len(lines)
    for i in range(start + 1, len(lines)):
        match = re.match(r'^(#{1,6})\s+', lines[i])
        if match and len(match.group(1)) <= level: end = i; break
    pairs, question = [], None
    def strip(line):
        line = re.sub(r'^(?:[-*+]\s+|\d+\.\s+)', '', line.strip()).strip()
        line = line.replace('**', '').replace('__', '')
        return re.sub(r'(^|\s)\*([^*]+)\*', r'\1\2', line).strip()
    qmark = re.compile(r'^(?:Q\s*[:：]\s*|问\s*[:：]\s*)', re.I)
    amark = re.compile(r'^(?:A\s*[:：]\s*|答\s*[:：]\s*)', re.I)
    combined = re.compile(r'^(?:Q\s*[:：]\s*|问\s*[:：]\s*)([\s\S]*?)\s+(?:A\s*[:：]\s*|答\s*[:：]\s*)([\s\S]*)$', re.I)
    for raw in lines[start + 1:end]:
        line = strip(raw)
        if not line: continue
        both = combined.match(line)
        if both: pairs.append([both.group(1).strip(), both.group(2).strip()]); question = None; continue
        q, a = qmark.match(line), amark.match(line)
        if q: question = line[q.end():].strip(); continue
        if a and question is not None: pairs.append([question, line[a.end():].strip()]); question = None; continue
        if question is not None: pairs.append([question, line]); question = None; continue
        question = line
    if question is not None: pairs.append([question, None])
    return pairs == value

def redact_evidence(value, config=None):
    text = scrub_text(value, config)
    text = re.sub(r'(?i)\bbearer\s+[^&\s"\']+', 'Bearer [REDACTED]', text)
    text = re.sub(r'(?i)\b(authorization|access_token|token|password)\s*[:=]\s*[^&\s"\']+', r'\1=[REDACTED]', text)
    return re.sub(r'\d{7,}', '[REDACTED]', text)


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
        immediate = bool(item.get('max_latency_seconds'))
        request = {**item, 'id': identity, 'case_id': cid,
                   'cache_bust': True, 'immediate': immediate,
                   'earliest_check_at': (saved if immediate else saved + dt.timedelta(hours=1)).isoformat(),
                   'deadline': (saved + dt.timedelta(hours=2)).isoformat(), 'timeout_ms': 10000}
        registry[identity] = {'request': request, 'status': 'pending', 'batch_id': batch['id'],
                              'version': attempt['version'], 'active': True, 'history': []}
    fold(m, cid)
    if any(c.get('attempts') and c['attempts'][-1].get('cleanup_pending') for c in m['cases'].values()):
        persist_hold(m)
    # The caller exports only after independent cases and all deferred preparations finish.


def _watch_assertion(base, m, cid):
    from .common import read_yaml
    case = m['cases'][cid]
    spec = read_yaml(base / case.get('case_spec', ''))
    pages = read_yaml(base / 'runner/knowledge/page-map.yaml')
    attached = {s.get('id'): s for s in spec.get('steps', []) if isinstance(s, dict)}
    for assertion in spec.get('assertions', []):
        checks = assertion.get('checks', [])
        remote = [c for c in checks if isinstance(c, dict) and c.get('op') == 'remote_file']
        if not remote:
            continue
        step = attached.get(assertion.get('after'), {})
        target = step.get('target')
        resource = pages.get('targets', {}).get(target, {}).get('resource', {})
        latency = resource.get('max_latency_seconds')
        if latency is None:
            continue
        require(type(latency) in {int, float} and latency > 0, 'Cannot arm watch: invalid max_latency_seconds')
        conditions = []
        for check in remote:
            condition = check.get('value')
            serialized = __import__('json').dumps(condition, ensure_ascii=False)
            require('$fixture.' not in serialized and '${' not in serialized,
                    'Cannot arm watch: remote_file condition values must be static in case-spec')
            require(isinstance(condition, dict) and condition.get('op') in {'contains', 'equals', 'ordered_pairs'} and
                    isinstance(condition.get('value'), (str, list)), 'Cannot arm watch: invalid static remote_file condition')
            conditions.append(condition)
        require(conditions, 'Cannot arm watch: no remote_file assertion conditions')
        target_resource = pages.get('targets', {}).get(target, {}).get('resource', {})
        public = m.get('config', {}).get('targets', {}).get('public')
        require(public and target_resource.get('path'), 'Cannot arm watch: public target URL is unavailable')
        url = __import__('urllib.parse', fromlist=['urljoin']).urljoin(public.rstrip('/') + '/', target_resource['path'].lstrip('/'))
        return assertion, conditions, latency, url
    require(False, 'Cannot arm watch: case has no remote_file assertion with max_latency_seconds in page-map')


def _clock_offset(entry_url):
    """Backend Date minus local midpoint in milliseconds; null means unavailable."""
    try:
        start = time.time() * 1000
        request = urllib.request.Request(entry_url, method='HEAD')
        with urllib.request.urlopen(request, timeout=2) as response:
            date = response.headers.get('Date')
        end = time.time() * 1000
        parsed = dt.datetime.strptime(date, '%a, %d %b %Y %H:%M:%S GMT').replace(tzinfo=dt.timezone.utc) if date else None
        # Date is truncated to whole seconds; +500 ms centres the estimate.
        return int(parsed.timestamp() * 1000 + 500 - (start + end) / 2) if parsed else None
    except Exception:
        return None


def arm_watch(base, m, cid, lead_minutes=20, watch_minutes=40, interval_ms=1000):
    require(cid in m['cases'], 'Unknown case: ' + cid)
    require(type(lead_minutes) is int and 0 <= lead_minutes <= 60 and type(watch_minutes) is int and 1 <= watch_minutes <= 120 and
            type(interval_ms) is int and 100 <= interval_ms <= 60000, 'Invalid watch timing')
    assertion, conditions, latency, url = _watch_assertion(base, m, cid)
    armed = dt.datetime.now(dt.timezone.utc)
    save_not_before = armed + dt.timedelta(minutes=lead_minutes)
    until = save_not_before + dt.timedelta(minutes=watch_minutes)
    watch_id = digest([m['run_id'], cid, assertion['id'], armed.isoformat()])[:24]
    directory = base / 'remote-checks' / 'watch' / watch_id
    request = {'schema_version': 'uia-remote-watch.v1', 'run_id': m['run_id'], 'watch_id': watch_id,
               'case_id': cid, 'assertion_id': assertion['id'], 'expected': assertion['excel'], 'url': url,
               'method': 'GET', 'conditions': conditions, 'armed_at': armed.isoformat(),
               'save_not_before': save_not_before.isoformat(), 'watch_until': until.isoformat(),
               'interval_ms': interval_ms, 'timeout_ms': 10000, 'max_latency_seconds': latency,
               'max_clock_offset_ms': 1000}
    serialized = __import__('json').dumps(request, ensure_ascii=False)
    require(scrub_text(serialized, m['config']) == serialized, 'Watch request contains sensitive data')
    parsed_url = __import__('urllib.parse', fromlist=['urlsplit']).urlsplit(url)
    require(parsed_url.scheme in {'http', 'https'} and not parsed_url.username and not parsed_url.password and not parsed_url.query,
            'Cannot arm watch: unsafe public URL')
    directory.mkdir(parents=True, exist_ok=False)
    atomic_write(directory / 'request.json', request)
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'templates/remote-check.mjs', directory / 'check.mjs')
    offset = _clock_offset(m.get('config', {}).get('environment', {}).get('entry_url', ''))
    record = {'watch_id': watch_id, 'case_id': cid, 'assertion_id': assertion['id'], 'status': 'armed',
              'armed_at': armed.isoformat(), 'save_not_before': save_not_before.isoformat(),
              'watch_until': until.isoformat(), 'request_sha256': file_hash(directory / 'request.json'),
              'box_clock_offset_ms': offset, 'request_file': str((directory / 'request.json').relative_to(base))}
    m.setdefault('remote_watches', {})[watch_id] = record
    event(m, 'remote_watch_armed', case_id=cid, watch_id=watch_id)
    return {'watch_id': watch_id, 'request': record['request_file'], 'status': 'armed'}


def wait_for_watch(base, watch, clock=None, sleeper=None, heartbeat=None):
    """Wait until save window; helper is injectable for scheduler unit tests."""
    clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
    sleeper = sleeper or time.sleep
    target = timestamp(watch['save_not_before'])
    while (target - clock()).total_seconds() > 0:
        remaining = (target - clock()).total_seconds()
        require(remaining <= 3600, 'Armed watch is more than 60 minutes away; refusing to wait')
        if heartbeat:
            heartbeat(watch, remaining)
        sleeper(min(5, remaining))


def ingest_watch(base, m, file):
    require(not m.get('active_batch'), 'Wait for the active batch before ingesting')
    payload = read_json(file)
    required = {'schema_version', 'run_id', 'watch_id', 'request_sha256', 'first_poll_at', 'last_poll_at',
                'poll_count', 'error_count', 'max_gap_ms', 'baseline_absent', 'last_absent_at',
                'first_present_at', 'confirmed_present', 'clock_offset_ms', 'evidence', 'timeline', 'polls'}
    require(isinstance(payload, dict) and set(payload) == required and payload.get('schema_version') == 'uia-remote-watch-results.v1' and
            payload.get('run_id') == m['run_id'], 'Invalid watch result envelope')
    watch_id = payload.get('watch_id'); watches = m.get('remote_watches', {})
    require(watch_id in watches, 'Unknown watch_id')
    watch = watches[watch_id]
    request_file = base / watch['request_file']
    require(request_file.is_file() and payload['request_sha256'] == file_hash(request_file) == watch.get('request_sha256'), 'Watch request hash mismatch')
    receipt = digest(Path(file).read_bytes())
    if receipt in m.get('remote_watch_ingests', []):
        return {'ingested': 0, 'duplicate': True}
    for key in ('poll_count', 'error_count', 'max_gap_ms'):
        require(type(payload[key]) is int and payload[key] >= 0, 'Invalid watch counters')
    require(type(payload['baseline_absent']) is bool and type(payload['confirmed_present']) is bool and
            isinstance(payload['polls'], list) and len(payload['polls']) == payload['poll_count'], 'Invalid watch polls')
    require((payload['poll_count'] == 0 and payload['first_poll_at'] is None and payload['last_poll_at'] is None) or
            (payload['poll_count'] > 0 and payload['first_poll_at'] is not None and payload['last_poll_at'] is not None),
            'Invalid watch timestamp envelope')
    for value in (payload['first_poll_at'], payload['last_poll_at'], payload['last_absent_at'], payload['first_present_at']):
        if value is not None: timestamp(value)
    require(payload['clock_offset_ms'] is None or type(payload['clock_offset_ms']) is int, 'Invalid watch clock offset')
    for poll in payload['polls']:
        require(isinstance(poll, dict) and set(poll) == {'t_ms', 'ok', 'present'} and type(poll['t_ms']) is int and
                type(poll['ok']) is bool and type(poll['present']) is bool, 'Invalid watch poll')
    require(all(payload['polls'][i]['t_ms'] >= payload['polls'][i-1]['t_ms'] for i in range(1, len(payload['polls']))) and
            payload['error_count'] == sum(not p['ok'] for p in payload['polls']), 'Inconsistent watch poll sequence')
    gaps = [payload['polls'][i]['t_ms'] - payload['polls'][i-1]['t_ms'] for i in range(1, len(payload['polls']))]
    require(payload['max_gap_ms'] == max(gaps, default=0), 'Inconsistent watch gap')
    first_success = next((p for p in payload['polls'] if p['ok']), None)
    require(payload['baseline_absent'] == bool(first_success and not first_success['present']), 'Inconsistent watch baseline')
    confirmed = any(all(p['ok'] and p['present'] for p in payload['polls'][i:i+3]) for i in range(max(0, len(payload['polls'])-2)))
    require(payload['confirmed_present'] == confirmed, 'Inconsistent watch confirmation')
    require(isinstance(payload['timeline'], list) and len(payload['timeline']) <= len(payload['polls']), 'Invalid watch timeline')
    expected_timeline = []
    previous_state = None
    for poll in payload['polls']:
        state = 'error' if not poll['ok'] else 'present' if poll['present'] else 'absent'
        if state != previous_state:
            expected_timeline.append({'t_ms': poll['t_ms'], 'state': state}); previous_state = state
    require(payload['timeline'] == expected_timeline, 'Inconsistent watch timeline')
    if payload['evidence'] is not None:
        ev = payload['evidence']
        require(isinstance(ev, dict) and set(ev) == {'excerpt', 'section_sha256'} and isinstance(ev['excerpt'], str) and
                len(ev['excerpt']) <= 2000 and ev['section_sha256'] == hashlib.sha256(ev['excerpt'].encode()).hexdigest() and
                redact_evidence(ev['excerpt']) == ev['excerpt'], 'Invalid watch evidence')
    require(not payload['first_present_at'] or payload['evidence'] is not None, 'First-present evidence is missing')
    request = read_json(request_file)
    require(request.get('schema_version') == 'uia-remote-watch.v1' and request.get('watch_id') == watch_id and
            request.get('run_id') == m['run_id'], 'Stored watch request is invalid')
    entries = [(key, row) for key, row in m.get('remote_checks', {}).items()
               if row.get('request', {}).get('case_id') == watch['case_id'] and
               row.get('request', {}).get('assertion_id') == watch['assertion_id'] and
               row.get('active', True) and
               timestamp(row['request']['saved_at']) >= timestamp(watch['armed_at'])]
    require(entries, 'No matching regular remote check produced after watch was armed')
    key, entry = entries[-1]; req = entry['request']; saved = timestamp(req['saved_at'])
    require(req.get('max_latency_seconds') == request.get('max_latency_seconds') and req.get('url') == request.get('url') and
            req.get('conditions') == request.get('conditions'), 'Watch does not match the regular remote assertion')
    first = timestamp(payload['first_poll_at']) if payload['first_poll_at'] else None
    latency_ms = req.get('max_latency_seconds', 0) * 1000
    latency = int((timestamp(payload['first_present_at']) - saved).total_seconds() * 1000) if payload.get('first_present_at') else None
    code = None; status = 'unreachable'
    if first is None: code = 'watch_gap'
    elif first > saved: code = 'watch_started_late'
    elif not any(p['ok'] for p in payload['polls']): code = 'watch_gap'
    elif not payload['baseline_absent']: code = 'baseline_present'
    elif payload['clock_offset_ms'] is None or abs(payload['clock_offset_ms']) > request.get('max_clock_offset_ms', 1000): code = 'clock_offset'
    elif watch.get('box_clock_offset_ms') is not None and abs(watch['box_clock_offset_ms']) > request.get('max_clock_offset_ms', 1000): code = 'clock_offset'
    elif watch.get('box_clock_offset_ms') is None:
        watch['clock_offset_note'] = 'box_clock_offset_unavailable'
    if code is None:
        first_ms = first.timestamp() * 1000; saved_ms = saved.timestamp() * 1000
        # Poll t_ms is measured from the first poll start; any successful sample inside (saved, saved+window] counts.
        in_window = any(p['ok'] and 0 < (first_ms + p['t_ms'] - saved_ms) <= latency_ms for p in payload['polls'])
        if not in_window and not payload['confirmed_present']:
            code = 'watch_gap'
        elif payload['confirmed_present'] and payload.get('first_present_at'):
            if latency < -request.get('max_clock_offset_ms', 1000): code = 'clock_offset'
            elif latency <= latency_ms: code, status = 'immediate_met', 'pass'
            elif payload.get('last_absent_at') and timestamp(payload['last_absent_at']) > saved + dt.timedelta(milliseconds=latency_ms):
                code, status = 'immediate_not_met', 'fail'
            else: code = 'watch_gap'  # late first-present without an absent sample after the window is not proof
        elif payload.get('last_absent_at') and timestamp(payload['last_absent_at']) > saved + dt.timedelta(milliseconds=latency_ms):
            code, status = 'immediate_not_met', 'fail'
        else:
            code = 'watch_gap'
    chinese = {'immediate_met':'立即生效已确认', 'immediate_not_met':'最终内容在 {n} 秒后生效',
               'watch_started_late':'监听启动晚于保存，无法验证立即生效', 'baseline_present':'首个有效采样已包含新内容，无法验证变化时间',
               'clock_offset':'时钟偏差超出允许范围，无法验证立即生效', 'watch_gap':'保存后的时效窗口内没有有效采样，无法验证立即生效'}
    reason = ('最终 ' + str(round(latency/1000, 3)) + ' 秒后生效' if code == 'immediate_not_met' and latency is not None
              else '超过时效窗口仍未出现新内容' if code == 'immediate_not_met' else chinese[code])
    archive = base / 'remote-checks' / 'watch' / watch_id / ('ingested-' + receipt + '.json')
    row = {'id': key, 'checked_at': payload['last_poll_at'] or now(), 'status': status, 'http_status': None,
           'conditions': [bool(payload['confirmed_present'])] * len(req.get('conditions', [])),
           'reason': code, 'variant': 'cache_busted',
           'latency_ms': latency, 'watch_result_sha256': receipt,
           'watch_result_file': str(archive.relative_to(base))}
    if Path(file).resolve() != archive.resolve(): shutil.copyfile(file, archive)
    entry.setdefault('history', []).append(row); entry['status'] = status
    entry['watch_verdict'] = {'reason': code, 'report': reason, 'latency_ms': latency, 'receipt_sha256': receipt}
    watch.update(status='ingested', verdict=code, result_sha256=receipt, ingested_at=now())
    m.setdefault('remote_watch_ingests', []).append(receipt)
    cleanup = restore(base, m) if all(r['status'] in {'pass', 'fail', 'unreachable'} for r in m.get('remote_checks', {}).values() if r.get('active', True)) else None
    fold(m, req['case_id'])
    event(m, 'remote_watch_ingested', case_id=req['case_id'], watch_id=watch_id, verdict=code)
    return {'ingested': 1, 'duplicate': False, 'case_id': req['case_id'], 'status': status, 'reason': code,
            'report': reason, 'latency_ms': latency, 'cleanup': cleanup}


def environment_key(m):
    from .profiles import connection_settings
    return digest(connection_settings(m['config']))


def hold_path(m):
    return ROOT / '.auth' / 'remote-holds' / (environment_key(m) + '.json')


def persist_hold(m, case_ids=None):
    path = hold_path(m)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    active = list(case_ids) if case_ids is not None else [cid for cid, c in m['cases'].items()
              if c.get('attempts') and c['attempts'][-1].get('cleanup_pending')]
    atomic_write(path, {'run_id': m['run_id'], 'environment_key': environment_key(m),
                        'case_ids': sorted(active), 'created_at': now()})
    path.chmod(0o600)


def clear_hold(m):
    path = hold_path(m)
    if path.is_file():
        path.unlink()


def finalize(base, m):
    pending = [cid for cid, c in m['cases'].items()
               if c.get('attempts') and c['attempts'][-1].get('cleanup_pending')]
    if pending:
        persist_hold(m)
    else:
        clear_hold(m)
    return export(base, m)


def fold(m, cid):
    c = m['cases'][cid]
    entries = [r for r in m.get('remote_checks', {}).values() if r.get('active', True) and r['request']['case_id'] == cid]
    if not entries:
        return
    statuses = {r['status'] for r in entries}
    failures = [r for r in entries if r['status'] == 'fail']
    if failures and all(r.get('local_reevaluation', {}).get('all_conditions') is True for r in failures):
        c.update(result='automation_failure', pass_streak=0, stability='unstable', stage='finished', work_status='finished')
        c['remote_status'] = 'fail'
        c['classification'] = {'reason': '远程检查器解析失败，原始证据符合预期：检查器缺陷，非产品缺陷', 'at': now()}
        return
    status = 'pass_reevaluated' if statuses == {'pass_reevaluated'} else next((s for s in ('fail', 'unreachable', 'still-cached', 'pending') if s in statuses), 'pass')
    c['remote_status'] = status
    watch_reasons = [r.get('watch_verdict', {}).get('report') for r in entries if r.get('watch_verdict', {}).get('report')]
    c['classification'] = {'reason': watch_reasons[-1] if watch_reasons else LABELS[status], 'at': now()}
    if status in {'pass', 'pass_reevaluated'} and not c['attempts'][-1].get('cleanup_verified'):
        c.update(result='remote_pending', pass_streak=0, stability='not_run', stage='remote', work_status='remote_pending')
        c['classification']['reason'] = '远程通过，等待本机恢复数据并核验'
        return
    if status in {'pass', 'pass_reevaluated'}:
        # Only an independently clean local batch plus all remote assertions can pass.
        attempt = c['attempts'][-1]
        require(attempt['result'] == 'passed' and attempt['cleanup_verified'] and attempt['setup_verified'], 'Local lifecycle did not pass')
        streak = 0
        for a in reversed(c['attempts']):
            if a['version'] != c['version'] or a['result'] != 'passed' or a.get('remote_status') not in {'pass', 'pass_reevaluated'} and a is not attempt:
                break
            streak += 1
        attempt['remote_status'] = status
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
        required = {'id', 'checked_at', 'status', 'http_status', 'conditions', 'reason', 'variant'}
        require(isinstance(row, dict) and required <= set(row) and set(row) <= required | {'evidence'}, 'Invalid remote result row')
        key = row['id']; require(isinstance(key, str) and key in registry and key not in ids and registry[key].get('active', True), 'Unknown, stale or duplicate remote check')
        ids.add(key); entry = registry[key]; req = entry['request']; c = m['cases'][req['case_id']]
        require(row['variant'] == ('cache_busted' if req.get('cache_bust') else 'default'), 'Remote result used the wrong cache variant')
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
        if 'evidence' in row:
            require(isinstance(row['evidence'], list) and len(row['evidence']) == len(req['conditions']), 'Invalid remote evidence')
            for ev in row['evidence']:
                require(isinstance(ev, dict) and set(ev) == {'section_sha256', 'excerpt'} and
                        isinstance(ev['section_sha256'], str) and re.fullmatch(r'[a-f0-9]{64}', ev['section_sha256']) and
                        isinstance(ev['excerpt'], str) and len(ev['excerpt']) <= 2000 and
                        redact_evidence(ev['excerpt']) == ev['excerpt'] and
                        hashlib.sha256(ev['excerpt'].encode()).hexdigest() == ev['section_sha256'], 'Invalid remote evidence')
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
            if 'evidence' in row and (row['status'] == 'fail' or not all(row['conditions'])):
                outcomes = [evaluate_condition(ev['excerpt'], cond) for ev, cond in zip(row['evidence'], req['conditions'])]
                row['local_reevaluation'] = {'conditions': outcomes, 'all_conditions': all(outcomes), 'evaluator_version': '2'}
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
        if row.get('local_reevaluation', {}).get('all_conditions'):
            entry['local_reevaluation'] = row['local_reevaluation']
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


def reevaluate(base, m, file):
    """Settle a failed remote check from operator-supplied, auditable section text."""
    payload = read_json(file)
    require(isinstance(payload, dict) and set(payload) == {'id', 'section'}, 'Evidence must contain id and section')
    cid = payload['id']; text = payload['section']
    require(isinstance(cid, str) and cid in m.get('remote_checks', {}) and isinstance(text, str) and len(text) <= 2000, 'Invalid reevaluation evidence')
    entry = m['remote_checks'][cid]; req = entry['request']; case = m['cases'][req['case_id']]
    require(entry.get('active', True) and entry.get('status') == 'fail', 'Only active failed checks can be reevaluated')
    attempt = case['attempts'][-1]
    require(attempt['result'] == 'passed' and attempt.get('setup_verified') and attempt.get('cleanup_verified'), 'Local lifecycle and cleanup must be verified')
    outcomes = [evaluate_condition(text, cond) for cond in req['conditions']]
    require(all(outcomes), 'Local reevaluation does not satisfy every condition')
    safe_text = redact_evidence(text, m['config'])
    evidence_hash = hashlib.sha256(safe_text.encode()).hexdigest()
    target = base / 'remote-checks' / ('reevaluated-' + cid + '-' + evidence_hash + '.json')
    atomic_write(target, {'id': cid, 'section': safe_text, 'sha256': evidence_hash})
    row = {'id': cid, 'checked_at': now(), 'status': 'pass_reevaluated', 'http_status': None,
           'conditions': outcomes, 'reason': 'conditions_met', 'variant': 'local_reevaluation',
           'evidence_source': 'local_reevaluation', 'evidence_file': str(target.relative_to(base)),
           'evidence_sha256': evidence_hash,
           'local_reevaluation': {'conditions': outcomes, 'evaluator_version': '2'}}
    entry['history'].append(row); entry['status'] = 'pass_reevaluated'; entry['local_reevaluation'] = row['local_reevaluation']
    fold(m, req['case_id'])
    return {'id': cid, 'case': req['case_id'], 'result': case['result'], 'evidence_sha256': evidence_hash}


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
    if not any(c.get('attempts') and c['attempts'][-1].get('cleanup_pending') for c in m['cases'].values()):
        clear_hold(m)
    finalize(base, m)
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
