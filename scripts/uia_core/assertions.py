"""Determine whether confirmed expectations actually ran with reporter evidence."""


def assess(spec, reporter_row):
    assertions = (spec or {}).get('assertions', [])
    is_remote = lambda item: bool(item.get('checks')) and all(check.get('op') == 'remote_file' for check in item.get('checks', []))
    expected = [item.get('id') for item in assertions
                if not is_remote(item)]
    deferred = [item.get('id') for item in assertions
                if is_remote(item)]
    observed = {item.get('id'): item for item in reporter_row.get('assertions', []) if isinstance(item, dict)}
    remote_observed = {item.get('id'): item for item in reporter_row.get('deferred_assertions', []) if isinstance(item, dict)}
    complete = bool(expected or deferred or not spec and observed)
    missing = [identity for identity in expected if not (
        observed.get(identity, {}).get('passed') is True and
        isinstance(observed.get(identity, {}).get('evidence'), dict) and
        observed[identity]['evidence'].get('source') and observed[identity]['evidence'].get('started_at'))]
    missing.extend(identity for identity in deferred if not (
        remote_observed.get(identity, {}).get('recorded') is True and
        isinstance(remote_observed.get(identity, {}).get('evidence'), dict) and
        remote_observed[identity]['evidence'].get('source')))
    return {'complete': complete and not missing, 'expected': expected, 'missing': missing}
