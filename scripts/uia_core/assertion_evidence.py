"""Reconcile a batch's frozen assertion contract with its execution receipts."""
from urllib.parse import urljoin, urlsplit

from .common import UiaError, read_json
from .secrets import scrub_text


def remote_requirements(spec, pages):
    targets = (pages or {}).get('targets', {})
    return {a['id']: targets.get(a['checks'][0]['target'], {}).get('resource', {})
            for a in spec.get('assertions', []) if is_remote(a)}


def is_remote(assertion):
    return bool(assertion.get('checks')) and all(check.get('op') == 'remote_file' for check in assertion['checks'])


def remote_matches(receipt, assertion, resource, public_url):
    from .remote_checks import timestamp
    try:
        stamp = timestamp(receipt['saved_at'])
        expected_url = urljoin(public_url, resource['path'])
        parsed = urlsplit(expected_url)
        if not (stamp and parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username
                and not parsed.password and not parsed.query and receipt['url'] == expected_url
                and receipt['method'] == 'GET' and receipt['expected'] == assertion['excel']
                and receipt.get('max_latency_seconds') == resource.get('max_latency_seconds')):
            return False
        expected = [check['value'] for check in assertion['checks']]
        actual = receipt['conditions']
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        for condition, wanted in zip(actual, expected):
            # Only value can be resolved from a runtime fixture by deferPublic.
            if isinstance(wanted.get('value'), str) and wanted['value'].startswith('$fixture.'):
                if not isinstance(condition, dict) or not isinstance(condition.get('value'), (str, int, list, dict)):
                    return False
                wanted = {**wanted, 'value': condition['value']}
            if condition != wanted:
                return False
        return True
    except (KeyError, TypeError, ValueError, UiaError):
        return False


def read_remote(path):
    if not path.is_file():
        return []
    try:
        return read_json(path)
    except (OSError, ValueError):
        return None


def reconcile(binding, local_rows, remote_rows, public_url, cfg):
    """Produce a reportable row per spec assertion, plus any receipt discrepancies."""
    spec = binding['spec']
    assertions = spec.get('assertions', [])
    methods = binding.get('assertion_methods', {})
    rows, problems = [], []
    local_ids = {a['id'] for a in assertions if not is_remote(a)}
    remote_ids = {a['id'] for a in assertions if is_remote(a)}

    def by_id(receipts, field, allowed, label):
        indexed = {}
        if not isinstance(receipts, list):
            problems.append(f'{label}回执格式错误')
            return indexed
        for item in receipts:
            key = item.get(field) if isinstance(item, dict) else None
            if not isinstance(key, str) or key not in allowed:
                ident = key if isinstance(key, str) and len(key) <= 24 and key.isascii() and key.isalnum() else '未知编号'
                problems.append(f'{label}回执编号不符 {ident}')
                continue
            indexed.setdefault(key, []).append(item)
        return indexed

    local = by_id(local_rows, 'id', local_ids, '本地')
    remote = by_id(remote_rows, 'assertion_id', remote_ids, '远程')
    for assertion in assertions:
        aid = assertion['id']
        deferred = is_remote(assertion)
        matches = (remote if deferred else local).get(aid, [])
        status, observations = 'not_run', []
        if len(matches) != 1:
            problems.append(f'{aid} 回执{"重复" if matches else "缺失"}')
            if matches:
                status = 'invalid'
        elif deferred:
            resource = binding.get('remote_resources', {}).get(aid, {})
            if remote_matches(matches[0], assertion, resource, public_url):
                status = 'remote_pending'
            else:
                status = 'invalid'
                problems.append(f'{aid} 远程请求与规格不符')
        else:
            observed = matches[0].get('observations', [])
            if isinstance(observed, list):
                observations = [scrub_text(v, cfg)[:200] if isinstance(v, str) else v for v in observed[:8]
                                if type(v) in (str, int, float, bool) and (not isinstance(v, str) or v.strip())]
            passed = matches[0].get('passed')
            status = 'passed' if passed is True else 'failed' if passed is False else 'invalid'
            if passed is not True:
                problems.append(f'{aid} 无通过回执')
            elif aid in methods and not observations:
                problems.append(f'{aid} 缺少关键观察值')
        checks = [{'target': scrub_text(check.get('target', ''), cfg), 'operation': check['op'],
                   **({'expected': scrub_text(check['value'], cfg)[:240]} if 'value' in check else {})}
                  for check in assertion.get('checks', [])]
        rows.append({'id': aid, 'original_expectation': scrub_text(assertion['excel'], cfg), 'spec_checks': checks,
                     'reviewed_methods': methods.get(aid, []), 'status': status, 'observations': observations})
    return rows, problems
