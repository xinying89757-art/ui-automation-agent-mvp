"""Case-spec v1: validate source expectations, compile templates, derive marker coverage.

No model, selector inference or business-expectation rewriting occurs here.
"""
from __future__ import annotations

import copy
import json
import re
import yaml
from pathlib import Path

from .common import ROOT, UiaError, digest, event, file_hash, inside, read_json, read_yaml, require, reset_case

SCHEMA = read_json(Path(__file__).resolve().parents[2] / 'schemas/case-spec.schema.json')
VERBS = tuple(SCHEMA['$defs']['step']['properties']['verb']['enum'])
OPS = tuple(SCHEMA['$defs']['check']['properties']['op']['enum'])
REF = re.compile(r'aria-ref\s*=|\[ref\s*=|["\'](?:f\d+)?e\d+["\']|(?:snapshot_ref|snapshotRef)\s*[":=]', re.I)
ICON = re.compile('[\ue000-\uf8ff\U000f0000-\U000ffffd\U00100000-\U0010fffd]')


def has_snapshot_ref(value):
    return bool(REF.search(json.dumps(value, ensure_ascii=False)))


def catalogs():
    shared = ROOT / 'knowledge/page-map.yaml'
    pages = read_yaml(shared if shared.is_file() else ROOT / 'assets/playwright-runner/knowledge/page-map.yaml')
    networks = read_yaml(ROOT / 'assets/playwright-runner/knowledge/network.yaml')['rules']
    for entry in pages['targets'].values():
        if entry.get('network_rule'):
            entry['network'] = networks[entry['network_rule']]
    return (read_yaml(ROOT / 'preconditions.yaml')['preconditions'],
            read_yaml(ROOT / 'assets/playwright-runner/knowledge/data-prep.yaml')['data'],
            pages)


def spec_path(base, case):
    return inside(base, case.get('case_spec') or f"cases/{case['case_id']}/case-spec.yaml")


def expectation_quotes(source):
    # A quote is an entire imported cell or an entire nonblank line from that cell.
    cells = source.get('expected') or []
    if isinstance(cells, str):
        cells = [cells]
    return {quote for cell in cells for quote in [cell, *cell.splitlines()] if quote.strip()}


def schema_errors(spec, source, env, data, pages):
    errors, unknown = [], set()
    if not isinstance(spec, dict):
        return ['case-spec must be a mapping'], []
    def fail(condition, message):
        if not condition:
            errors.append(message)
    required = set(SCHEMA['required'])
    fail(required <= set(spec) and not (set(spec) - set(SCHEMA['properties'])), 'case-spec fields must match v1 schema')
    fail(spec.get('schema_version') == 'case-spec.v1', 'schema_version must be case-spec.v1')
    fail(spec.get('case_id') == source.get('case_id'), 'case_id differs from imported source')
    fail(isinstance(spec.get('intent'), str) and bool(spec['intent'].strip()), 'intent is required')
    auto = spec.get('automatable')
    fail(isinstance(auto, dict) and set(auto) == {'status', 'reason'} and auto.get('status') in {'yes', 'needs-env', 'manual'} and isinstance(auto.get('reason'), str) and bool(auto['reason'].strip()), 'automatable needs status yes|needs-env|manual and reason')
    for key in ('required_env', 'mutation_scope', 'questions', 'steps', 'assertions'):
        fail(isinstance(spec.get(key), list), key + ' must be a list')
    if errors:
        return errors, []
    fail(all(isinstance(x, str) and x in env for x in spec['required_env']), 'required_env contains unknown vocabulary items')
    fail(all(isinstance(x, str) and x.strip() for x in spec['mutation_scope']), 'mutation_scope must contain names')
    fail(all(isinstance(x, str) and x.strip() for x in spec['questions']), 'questions must contain nonempty business questions')
    fail(isinstance(spec['data_prep'], dict), 'data_prep must be a mapping')
    for key, value in (spec['data_prep'].items() if isinstance(spec['data_prep'], dict) else []):
        entry = data.get(key)
        fail(bool(entry), 'unknown data-prep item: ' + key)
        if entry:
            fail(entry.get('scope') in spec['mutation_scope'], 'data-prep scope must be declared: ' + key)
            kind = entry.get('type')
            fail((kind == 'integer' and type(value) is int and value >= 0) or (kind == 'boolean' and type(value) is bool) or
                 (kind == 'string' and isinstance(value, str)) or (kind == 'array' and isinstance(value, list)), 'wrong data-prep type: ' + key)
    fail(spec['start_page'] in pages['pages'], 'unknown start_page')
    entry_doc = read_yaml(ROOT / 'knowledge/entries.yaml') or {}
    entry_routes = entry_doc.get('entries', {})
    if spec.get('entry_route'):
        fail(spec['entry_route'] in entry_routes and bool(entry_routes.get(spec['entry_route'], {}).get('confirmed')),
             'entry_route must reference a confirmed knowledge entry route')
    def target(value):
        if isinstance(value, str) and re.fullmatch(r'\?[\w.\-\u4e00-\u9fff]+', value):
            unknown.add(value)
        else:
            fail(isinstance(value, str) and value in pages['targets'], 'target must be a page-map name or ?name')
    step_ids, assertion_ids = set(), set()
    for step in spec['steps']:
        if not isinstance(step, dict):
            errors.append('step must be a mapping'); continue
        fail(not set(step) - {'id', 'verb', 'target', 'value'}, 'unknown step fields')
        sid = step.get('id')
        fail(isinstance(sid, str) and bool(re.fullmatch(r'S[1-9]\d*', sid)) and sid not in step_ids, 'unique S-number required')
        step_ids.add(str(sid))
        fail(step.get('verb') in VERBS, 'step verb is not supported')
        if not (step.get('verb') == 'open' and step.get('target') in entry_routes and entry_routes[step.get('target')].get('confirmed')):
            target(step.get('target'))
        entry = pages['targets'].get(step.get('target'), {})
        if entry.get('mutation') and step.get('verb') in {'click', 'double_click', 'attempt_click', 'fill', 'select', 'check', 'uncheck', 'press', 'upload'}:
            fail(entry['mutation'] in spec['mutation_scope'], 'step mutation scope must be declared: ' + str(sid))
        if step.get('verb') == 'observe':
            fail(isinstance(entry.get('observe_text'), str), 'observe needs a catalog text')
        if step.get('verb') == 'network_delay':
            fail(isinstance(step.get('value'), str) and step['value'].isdigit() and 1 <= int(step['value']) <= 30000, 'network delay must be 1..30000 ms')
            fail(bool(entry.get('network')), 'network verb requires a catalog rule')
        if step.get('verb') == 'network_release':
            fail(bool(entry.get('network')), 'network verb requires a catalog rule')
        if step.get('verb') == 'defer_public':
            fail(bool(entry.get('resource')), 'deferred check requires a public resource')
        if step.get('verb') in {'fill', 'select', 'press', 'upload'}:
            fail(isinstance(step.get('value'), str), 'step value must be an explicit string (blank allowed)')
    for assertion in spec['assertions']:
        if not isinstance(assertion, dict):
            errors.append('assertion must be a mapping'); continue
        fail(set(assertion) == {'id', 'after', 'excel', 'checks'}, 'assertion needs id/after/excel/checks')
        aid = assertion.get('id')
        fail(isinstance(aid, str) and bool(re.fullmatch(r'A[1-9]\d*', aid)) and aid not in assertion_ids, 'unique A-number required')
        assertion_ids.add(str(aid))
        fail(assertion.get('after') in step_ids, 'assertion.after must name its step')
        fail(isinstance(assertion.get('excel'), str) and assertion['excel'] in expectation_quotes(source), 'assertion must quote an exact Excel expectation cell or line verbatim')
        checks = assertion.get('checks')
        fail(isinstance(checks, list) and bool(checks), 'assertion needs nonempty checks')
        # A blocked action is an observation, never an actionable click. Keep the
        # original Excel clauses (including error messages) alongside this check.
        quote = assertion.get('excel', '')
        blocked = bool(re.search(r'blocked|cannot save|无法保存|不能保存|不可保存|不可用|置灰|禁用|被拦截', quote, re.I))
        attached = next((s for s in spec['steps'] if isinstance(s, dict) and s.get('id') == assertion.get('after')), {})
        blocked = blocked or bool(re.search(r'为空|空白|仅空格|empty', spec.get('intent', ''), re.I) and re.search(r'被拦截|blocked|无法保存|不能保存', spec.get('intent', ''), re.I) and attached.get('verb') == 'click' and re.search(r'save|submit|保存|提交', str(attached.get('target')), re.I))
        if blocked and isinstance(checks, list):
            fail(any(isinstance(c, dict) and c.get('op') in {'disabled', 'blocked'} for c in checks),
                 'blocked/cannot-save expectation requires a disabled-state assertion')
            fail(attached.get('verb') != 'click' or bool(re.search(r'保存中|处理中|processing', quote, re.I)), 'blocked action must be observed, not clicked')
        if isinstance(checks, list) and not re.search(r'保存中|处理中|processing', quote, re.I):
            fail(not any(isinstance(c, dict) and c.get('op') == 'disabled' and c.get('target') == attached.get('target')
                         for c in checks) or attached.get('verb') != 'click',
                 'cannot click a target whose expected state is disabled')
        for check in checks if isinstance(checks, list) else []:
            if not isinstance(check, dict):
                errors.append('check must be a mapping'); continue
            fail(not set(check) - {'target', 'op', 'value', 'attribute'}, 'unknown check fields')
            target(check.get('target'))
            fail(check.get('op') in OPS, 'unknown assertion operator')
            if check.get('op') == 'occurrence_count':
                fail(type(check.get('value')) is int and check['value'] >= 0 and bool(pages['targets'].get(check.get('target'), {}).get('observe_text')), 'occurrence_count needs an observable target and integer')
            if check.get('op') == 'visible_text':
                fail(isinstance(check.get('value'), str), 'visible_text needs an explicit string')
            if check.get('op') == 'remote_file':
                fail(all(isinstance(c, dict) and c.get('op') == 'remote_file' for c in checks), 'deferred assertions cannot mix local checks')
                value = check.get('value', {})
                fail(attached.get('verb') == 'defer_public' and check.get('target') == attached.get('target'), 'remote_file needs its deferred resource step')
                fail(isinstance(value, dict) and value.get('op') in {'contains', 'not_contains', 'equals', 'ordered_pairs', 'max_length', 'truncated_at', 'faq_page'} and isinstance(value.get('value'), (str, list, int, dict)), 'invalid remote file condition')
                if isinstance(value, dict):
                    if value.get('op') in {'contains', 'not_contains', 'equals'}: fail(isinstance(value.get('value'), str), 'remote text condition needs string value')
                    if value.get('op') == 'ordered_pairs': fail(isinstance(value.get('section'), str) and isinstance(value.get('value'), list) and all(isinstance(p, list) and len(p) == 2 and all(isinstance(x, str) for x in p) for p in value.get('value', [])), 'ordered_pairs needs section and ordered string pairs')
                    if value.get('op') == 'max_length': fail(type(value.get('value')) is int and value['value'] >= 0, 'max_length needs a nonnegative integer')
                    if value.get('op') == 'truncated_at': fail(type(value.get('value')) is int and value['value'] >= 0 and isinstance(value.get('text'), str) and len(value['text']) > value['value'], 'truncated_at needs N and the expected full text')
                    if value.get('op') == 'faq_page':
                        expected = value.get('value')
                        fail(isinstance(expected, dict) and type(expected.get('count')) is int and expected['count'] >= 0 and isinstance(expected.get('objects'), list) and len(expected['objects']) == expected.get('count'), 'faq_page needs count and one expected object per FAQPage')
                        if isinstance(expected, dict):
                            fail(all(isinstance(obj, dict) and isinstance(obj.get('pairs'), list) and all(isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, str) for x in pair) for pair in obj.get('pairs', [])) for obj in expected.get('objects', [])), 'faq_page objects need question/answer pairs')
            if check.get('op') == 'request_count':
                fail(type(check.get('value')) is int and check['value'] >= 0 and bool(pages['targets'].get(check.get('target'), {}).get('network')), 'request_count requires a network rule and integer')
            if check.get('op') == 'left_of':
                target(check.get('value'))
            if check.get('op') in {'text', 'contains', 'value', 'attribute', 'count'}:
                fail('value' in check, 'assertion operator requires value')
                fail(type(check.get('value')) is int if check.get('op') == 'count' else (isinstance(check.get('value'), str) or check.get('op') == 'text' and isinstance(check.get('value'), list) and all(isinstance(x, str) for x in check['value'])), 'invalid assertion value type')
            if check.get('op') == 'attribute':
                fail(isinstance(check.get('attribute'), str), 'attribute name required')
    read_ids = set()
    for rb in spec.get('read_back', []):
        fail(isinstance(rb, dict) and set(rb) == {'id', 'after', 'target', 'value', 'reopen', 'save_target'}, 'read_back needs id/after/target/value/reopen/save_target')
        if not isinstance(rb, dict):
            continue
        fail(isinstance(rb.get('id'), str) and bool(re.fullmatch(r'R[1-9]\d*', rb['id'])) and rb['id'] not in read_ids, 'unique R-number required')
        read_ids.add(rb.get('id'))
        fail(rb.get('after') in step_ids, 'read_back.after must name its save step')
        target(rb.get('target'))
        fail(isinstance(rb.get('value'), str), 'read_back.value must be a string')
        fail(isinstance(rb.get('reopen'), list) and bool(rb['reopen']), 'read_back.reopen must be a nonempty target sequence')
        for name in rb.get('reopen', []): target(name)
        fail(bool(pages['targets'].get(rb.get('save_target'), {}).get('network')), 'read_back.save_target must reference a network-rule target')
    fail(bool(spec['steps']) or auto['status'] == 'manual', 'automatable case needs steps')
    fail(bool(spec['assertions']) or bool(spec['questions']) or auto['status'] == 'manual', 'missing Excel expectations must become a question')
    for step in spec['steps']:
        if isinstance(step, dict) and step.get('verb') == 'close':
            fail(any(a.get('after') == step.get('id') and any(c.get('op') == 'hidden' for c in a.get('checks', [])) for a in spec['assertions'] if isinstance(a, dict)), 'close step requires its own hidden assertion')
    disabled_targets = set()
    for step in spec['steps']:
        if not isinstance(step, dict):
            continue
        if step.get('verb') == 'click':
            fail(step.get('target') not in disabled_targets, 'cannot click a previously asserted disabled target')
        if step.get('verb') in {'fill', 'select', 'check', 'uncheck', 'press', 'open'}:
            disabled_targets.clear()  # Input/navigation may legitimately change actionability.
        for a in spec['assertions']:
            if not isinstance(a, dict) or a.get('after') != step.get('id'):
                continue
            for c in a.get('checks', []) if isinstance(a.get('checks'), list) else []:
                if isinstance(c, dict) and c.get('op') == 'disabled':
                    disabled_targets.add(c.get('target'))
                elif isinstance(c, dict) and c.get('op') == 'enabled':
                    disabled_targets.discard(c.get('target'))
    fail(not has_snapshot_ref(spec), 'snapshot refs cannot be persisted in case-spec')
    return errors, sorted(unknown)


def locator_expression(name, pages):
    entry = pages['targets'].get(name)
    if not entry:
        return None
    root = 'page'
    if entry.get('frame'):
        root += '.frameLocator(' + json.dumps(entry['frame']) + ')'
    for frame in entry.get('nested_frames', []):
        root += '.frameLocator(' + json.dumps(frame) + ')'
    if entry.get('scope'):
        root += '.locator(' + json.dumps(entry['scope']) + ')'
    if 'selector' in entry:
        return root + '.locator(' + json.dumps(entry['selector']) + ')'
    if 'role' in entry and 'name' in entry:
        name = ICON.sub('', entry['name']).strip()
        if ICON.search(entry['name']):
            escaped = re.sub(r'([.*+?^${}()|\[\]\\])', r'\\\1', name)
            options = '{ name: new RegExp(' + json.dumps(escaped, ensure_ascii=False) + ', "u") }'
        else:
            options = '{ name: ' + json.dumps(name, ensure_ascii=False) + ', exact: true }'
        return root + '.getByRole(' + json.dumps(entry['role']) + ', ' + options + ')'
    return None


def interaction_patterns_for_target(target_row, action, target_name=''):
    patterns = list((target_row or {}).get('patterns', []))
    selector = str((target_row or {}).get('selector') or '')
    role = (target_row or {}).get('role')
    menu_target = ('MENU_KEYBOARD' in patterns or
        role in {'option', 'menuitem', 'menuitemcheckbox', 'menuitemradio'} or
        bool(re.search(r'\[role\s*=\s*["\']?(?:option|menuitem|menuitemcheckbox|menuitemradio)', selector, re.I)) or
        bool(re.search(r'menu|listbox|suggest|command|slash|dropdown', str(target_name), re.I)) or
        bool(re.search(r'menu|listbox|suggest|command|slash|dropdown', selector, re.I)))
    if action == 'click' and menu_target:
        patterns = list(dict.fromkeys([*patterns, 'MENU_KEYBOARD']))
    return patterns


def locator_errors(body, pages):
    errors = []
    if not re.search(r"import\s*\{[^}]*\btest\b[^}]*\}\s*from\s*['\"][^'\"]*support/fixtures(?:\.js|\.ts)?['\"]", body):
        errors.append('spec must import test from support/fixtures')
    if re.search(r"import\s*\{[^}]*\btest\b[^}]*\}\s*from\s*['\"]@playwright/test", body):
        errors.append('spec cannot import test directly from @playwright/test')
    if ICON.search(body):
        errors.append('strip icon glyphs from accessible names')
    if has_snapshot_ref(body):
        errors.append('snapshot refs cannot be persisted in specs')
    for name, entry in pages['targets'].items():
        if entry.get('dialog') and entry.get('scope') != pages['targets'].get(entry['dialog'], {}).get('selector'):
            errors.append('dialog target must be scoped: ' + name)
        if entry.get('dialog'):
            selector = entry.get('selector')
            if selector and re.search(r"\bpage\.locator\(\s*(['\"])" + re.escape(selector) + r"\1\s*[,)]", body):
                errors.append('dialog-internal CSS locator must use dialog scope: ' + name)
            # Names may accompany CSS targets to lint AI role/text locator alternatives.
            clean_name = ICON.sub('', entry.get('name', '')).strip()
            if clean_name and re.search(r'\bpage\.getBy(?:Role|Text|Label)\([^\n]*' + re.escape(clean_name), body):
                errors.append('dialog-internal named locator must use dialog scope: ' + name)
        if entry.get('role') and entry.get('name'):
            clean = ICON.sub('', entry['name']).strip()
            # Includes map observations of duplicates, even when only one alias is stored.
            peers = [e for e in pages['targets'].values() if e.get('role') == entry['role'] and ICON.sub('', e.get('name', '')).strip() == clean and e.get('frame') == entry.get('frame') and e.get('scope') == entry.get('scope')]
            # Knowledge write-back registers the same control once per exploration; identical written-back rows are aliases.
            written = lambda e: e.get('alias_of') or str(e.get('source', '')).startswith(('generator:', 'observed:'))
            peers = [e for e in peers if not written(e)] or peers[:1]
            if (entry.get('matches', 1) > 1 or len(peers) > 1) and not entry.get('scope'):
                if re.search(r'getByRole\([^\n]*' + re.escape(clean), body):
                    errors.append('non-unique role/name needs a container scope: ' + name)
            if entry.get('dialog') and re.search(r'\bpage\.getByRole\([^\n]*' + re.escape(clean), body):
                errors.append('dialog-internal locator must use dialog scope: ' + name)
    for observed in pages.get('observations', {}).get('duplicate_names', []):
        if observed.get('matches', 0) < 2:
            continue
        for line in body.splitlines():
            match = re.search(r"getByRole\(\s*['\"]" + re.escape(observed['role']) + r"['\"][^;]*" + re.escape(observed['name']), line)
            if match:
                prefix = line[:match.start()]
                if not re.search(r"(?:\.locator\([^)]*\)|\.getByRole\([^)]*\))\.$", prefix):
                    errors.append('observed non-unique role/name requires a container scope: ' + observed['name'])
    # Explicit AI close actions must be followed by an expect hidden assertion.
    for segment in re.split(r'//\s*@step\s+S\d+', body)[1:]:
        if re.search(r'(?:取消|关闭|cancel|close)[^\n]*(?:\.click\(|Dialog\()', segment, re.I) and not re.search(r'\bexpect\([^;]+\)\.toBe(?:Hidden|Visible)\(', segment, re.S):
            errors.append('close action requires an explicit visibility assertion')
    return sorted(set(errors))


def coverage(body, file):
    result = {'steps': {}, 'assertions': {}}
    for line, text in enumerate(body.splitlines(), 1):
        for field, pattern in [('steps', r'^\s*//\s*@step\s+(S\d+)\s*$'), ('assertions', r"(?:\bawait\s+businessAssertion\(['\"]|//\s*@deferred\s+)(A\d+)")]:
            for match in re.finditer(pattern, text):
                require(match[1] not in result[field], 'Duplicate coverage marker: ' + match[1])
                result[field][match[1]] = {'file': file, 'line': line}
    return result


def lint(base, m, case_ids=None, record=True, check_scripts=True):
    env, data, pages = catalogs()
    selected = case_ids or [cid for cid, c in m['cases'].items() if spec_path(base, c).is_file()]
    # Cross-case duplication cannot be bypassed with --cases or a single-case generation.
    chosen = list(dict.fromkeys([*selected, *[cid for cid, c in m['cases'].items() if spec_path(base, c).is_file()]]))
    results, seen, explore, business = {}, {}, {}, {}
    for cid in chosen:
        require(cid in m['cases'], 'Unknown case: ' + cid)
        case = m['cases'][cid]; path = spec_path(base, case)
        try:
            spec = read_yaml(path)
            errors, unknown = schema_errors(spec, read_json(inside(base, case['source'])), env, data, pages)
        except (OSError, ValueError, TypeError, yaml.YAMLError):
            spec, errors, unknown = {}, ['missing or malformed case-spec'], []
        auto = spec.get('automatable') if isinstance(spec, dict) else None
        results[cid] = {'errors': errors, 'automatable': auto.get('status', 'invalid') if isinstance(auto, dict) else 'invalid'}
        if errors:
            continue
        saves = [s for s in spec['steps'] if s.get('verb') in {'click', 'double_click', 'attempt_click'} and
                 (pages['targets'].get(s.get('target'), {}).get('mutation') or re.search(r'save|保存|submit|提交', s.get('target', ''), re.I))]
        tracked_save = any(pages['targets'].get(s.get('target'), {}).get('resource', {}).get('saved_by')
                           for s in spec['steps'] if s.get('verb') == 'defer_public')
        if not spec.get('read_back') and (tracked_save or saves and (spec['mutation_scope'] or any(s.get('verb') == 'fill' for s in spec['steps']))):
            results[cid]['warnings'] = ['保存步骤缺少读回检查']
        for target in unknown:
            explore.setdefault(target, []).append(cid)
        for text in spec['questions']:
            business.setdefault(text, []).append(cid)
        for assertion in spec['assertions']:
            signature = digest(sorted(assertion['checks'], key=lambda check: json.dumps(check, sort_keys=True, ensure_ascii=False)))
            if signature in seen and seen[signature][0] != cid:
                other, aid = seen[signature]
                results[cid]['errors'].append('identical assertion across cases: ' + other + '/' + aid)
                results[other]['errors'].append('identical assertion across cases: ' + cid + '/' + assertion['id'])
            else:
                seen[signature] = (cid, assertion['id'])
        reg = case.get('registration') or {}
        script = inside(base, reg['script']) if reg.get('case_spec') else base / 'runner/tests/generated' / (cid + '.spec.ts')
        if script.is_file() and check_scripts:
            body = script.read_text()
            errors.extend(locator_errors(body, pages))
            try:
                refs = coverage(body, str(script.resolve().relative_to((base / 'runner').resolve())))
                for field in ('steps', 'assertions'):
                    if set(refs[field]) != {x['id'] for x in spec[field]}:
                        errors.append('marker coverage differs from case-spec ' + field)
            except (ValueError, UiaError):
                errors.append('invalid coverage markers')
    knowledge_errors = []
    # Check all knowledge files, including the run-local overlay, without printing contents.
    for root in [ROOT / 'knowledge', ROOT / 'ui-knowledge', ROOT / 'automation-assets', ROOT / 'assets/playwright-runner/knowledge', base / 'state/knowledge']:
        for path in root.rglob('*') if root.exists() else []:
            if path.is_file() and path.suffix in {'.json', '.yaml', '.yml', '.md'} and has_snapshot_ref(path.read_text()):
                knowledge_errors.append('knowledge contains snapshot refs: ' + path.name)
    if record:
        require(not m.get('active_batch'), 'Cannot lint/update specs during an active batch')
        from .workflow import question
        for cid, row in results.items():
            case = m['cases'][cid]
            case['case_spec'] = str(spec_path(base, case).relative_to(base))
            if case.get('spec_first_lint', {}).get('source_hash') != case['source_hash']:
                case['spec_first_lint'] = {'passed': not row['errors'], 'automatable': row['automatable'], 'source_hash': case['source_hash']}
            case['spec_lint'] = copy.deepcopy(row)
            if not row['errors']:
                spec = read_yaml(spec_path(base, case))
                from .preconditions import local_env
                case['precondition_items'] = local_env(spec)
                if not case.get('registration'):
                    case['stage'] = 'spec'
                if spec['automatable']['status'] == 'manual':
                    case.update(stage='finished', work_status='finished', result='not_suitable', classification={'reason': spec['automatable']['reason']})
        from .preconditions import sync_preconditions, QUESTION_KEY
        sync_preconditions(base, m)
        if business and m.get('interaction_mode') != 'once':
            owners = sorted({c for ids in business.values() for c in ids})
            q = m['questions'].get(QUESTION_KEY)
            if not q:
                q = question(m, 'preconditions', 'run-preconditions', '执行前业务确认清单', owners, key=QUESTION_KEY)
            q['business_questions'] = [{'question': text, 'case_ids': ids} for text, ids in business.items()]
            q['prompt'] = q['prompt'].split('\n业务歧义：', 1)[0] + '\n业务歧义：\n' + '\n'.join(
                '- ' + text + ' (' + ', '.join(ids) + ')' for text, ids in business.items())
            q['case_ids'] = sorted(set(q['case_ids']) | set(owners))
            for cid in owners:
                m['cases'][cid]['work_status'] = 'waiting_human'
        m['pipeline'] = 'case-spec.v1'
        m['spec_explore'] = [{'target': target, 'case_ids': ids} for target, ids in explore.items()]
        event(m, 'spec_linted', case_ids=chosen, passed=sum(not x['errors'] for x in results.values()))
    auto = [m['cases'][cid].get('spec_first_lint', row) for cid, row in results.items() if row['automatable'] != 'manual']
    passed = sum(x.get('passed', not x.get('errors')) for x in auto)
    return {'valid': not knowledge_errors and all(not r['errors'] for r in results.values()), 'errors': knowledge_errors, 'cases': results, 'explore': [{'target': k, 'case_ids': v} for k, v in explore.items()],
            'questions': [{'question': k, 'case_ids': v} for k, v in business.items()],
            'first_pass': {'passed': passed, 'automatable': len(auto), 'rate': passed / len(auto) if auto else None}}


def generate(base, m, cid):
    require(not m.get('active_batch'), 'Cannot generate during an active batch')
    require(not any(c.get('attempts') and c['attempts'][-1].get('cleanup_pending') for c in m['cases'].values()), 'Restore held remote data before generating another version')
    result = lint(base, m, [cid], check_scripts=False)
    require(not result['errors'] and not result['cases'][cid]['errors'], 'case-spec lint failed', result)
    case = m['cases'][cid]; spec = read_yaml(spec_path(base, case)); _, catalog, pages = catalogs()
    scopes = set(spec['mutation_scope'])
    for key in spec['data_prep']:
        require(catalog[key].get('scope') in scopes, 'data-prep scope must be declared: ' + key)
    if scopes:
        mutation = m.get('config', {}).get('mutation', {})
        require(mutation.get('allowed') and (scopes <= set(mutation.get('scope', [])) or
                mutation.get('scope') == ['*'] and mutation.get('authorization_profile', {}).get('approved_by') == 'Xinying'),
                'case-spec mutation scope exceeds configured authorization')
    require(spec['automatable']['status'] != 'manual', 'Manual case cannot generate executable code')
    from .knowledge import match_run, matched_context
    if not (base / 'knowledge-match.json').is_file():
        match_run(base, m)
    knowledge_context = matched_context(base, m, cid)
    lines = ["// Generated deterministically from case-spec.v1 and shared interaction patterns.",
             '// Knowledge targets: ' + ', '.join(sorted(item['id'] for item in knowledge_context.get('selected', []))),
             "import { test, expect, businessAssertion } from '../../support/fixtures.js';",
             "import { openTarget } from '../../support/case-spec.js';",
             "import { delayRequests, doubleClick, attemptClick, observeOccurrences } from '../../flows/network-control.mjs';",
             "import { performWithPatterns } from '../../support/interaction-patterns.mjs';",
             "import { deferPublic, trackSave, verifyPersisted, readFieldValue, assertSaveBusinessOk } from '../../support/remote-checks.mjs';", '',
             'test(' + json.dumps('[' + cid + '] ' + spec['intent'], ensure_ascii=False) + ', async ({ page, caseContext }) => {', '  const networks: Record<string, any> = {};', '  const observations: Record<string, any> = {};', '  try {']
    if spec.get('entry_route') and not any(step.get('verb') == 'open' and step.get('target') == spec['entry_route']
                                            for step in spec['steps']):
        lines.append('  page = await openTarget(page, ' + json.dumps(spec['entry_route']) + ');')
    tracked_rules = set()
    for name in dict.fromkeys(s['target'] for s in spec['steps'] if s['verb'] == 'defer_public'):
        resource = pages['targets'].get(name, {}).get('resource', {})
        if resource.get('saved_by'):
            rule = pages['targets'][resource['saved_by']]['network']
            key = (rule['method'], rule['path'])
            if key not in tracked_rules:
                tracked_rules.add(key)
                lines.append('  observations[' + json.dumps('save-clock:' + name) + '] = trackSave(page, caseContext, ' + json.dumps(rule) + ');')
    for rb in spec.get('read_back', []):
        rule = pages['targets'][rb['save_target']]['network']
        key = (rule['method'], rule['path'])
        if key not in tracked_rules:
            tracked_rules.add(key)
            lines.append('  observations[' + json.dumps('save-clock:' + rb['id']) + '] = trackSave(page, caseContext, ' + json.dumps(rule) + ');')
    todos = []
    def todo(label):
        todos.append(label)
        lines.append('  // TODO explore: ' + label)
        lines.append('  throw new Error(' + json.dumps('UIA_EXPLORATION_REQUIRED: ' + label) + ');')
    for step in spec['steps']:
        sid, verb, name = step['id'], step['verb'], step['target']
        lines.append('  await test.step(' + json.dumps('uia-step:' + sid) + ', async () => {')
        lines.append('  // @step ' + sid)
        loc = locator_expression(name, pages)
        if verb == 'observe':
            lines.append('  observations[' + json.dumps(name) + '] = await observeOccurrences(page, ' + json.dumps(pages['targets'][name]['observe_text'], ensure_ascii=False) + ');')
        elif verb == 'defer_public':
            lines.append('  await assertSaveBusinessOk(caseContext);')
            lines.append('  // Public assertions are handed off after the editor save.')
        elif verb == 'network_delay':
            rule = pages['targets'][name]['network']
            lines.append('  networks[' + json.dumps(name) + '] = await delayRequests(page, ' + json.dumps(rule) + ', ' + step['value'] + ');')
        elif verb == 'network_release':
            lines.append('  networks[' + json.dumps(name) + '].release();')
        elif verb in {'double_click', 'attempt_click'}:
            lines.append('  await ' + ('doubleClick' if verb == 'double_click' else 'attemptClick') + '(page, ' + loc + ');')
        elif (not loc and verb != 'open') or name.startswith('?'):
            todo(sid + ' ' + name)
        elif verb == 'open':
            lines.append('  page = await openTarget(page, ' + json.dumps(name) + ');')
        elif verb in {'click', 'hover', 'check', 'uncheck', 'close'}:
            action = 'click' if verb == 'close' else verb
            target_patterns = interaction_patterns_for_target(pages['targets'].get(name, {}), action, name)
            if target_patterns:
                lines.append('  await performWithPatterns(page, () => ' + loc + ', ' + json.dumps(target_patterns) +
                             ', target => target.' + action + '());')
            else:
                lines.append('  await ' + loc + '.' + action + '();')
        elif verb in {'fill', 'select', 'press', 'upload'}:
            method = {'select': 'selectOption', 'upload': 'setInputFiles'}.get(verb, verb)
            target_patterns = pages['targets'].get(name, {}).get('patterns', [])
            value = json.dumps(step['value'], ensure_ascii=False)
            if target_patterns:
                lines.append('  await performWithPatterns(page, () => ' + loc + ', ' + json.dumps(target_patterns) +
                             ', target => target.' + method + '(' + value + '));')
            else:
                lines.append('  await ' + loc + '.' + method + '(' + value + ');')
        elif verb in {'wait', 'assert'}:
            lines.append('  await expect(' + loc + ').toBeVisible();')
        lines.append('  });')
        for assertion in (a for a in spec['assertions'] if a['after'] == sid):
            lines.append('  // Excel: ' + assertion['excel'].replace('\n', '\n  // '))
            if all(c['op'] == 'remote_file' for c in assertion['checks']):
                resource = pages['targets'][name]['resource']
                conditions = [c['value'] for c in assertion['checks']]
                lines.append('  deferPublic(caseContext, ' + json.dumps({'id': assertion['id'], 'excel': assertion['excel']}, ensure_ascii=False) + ', ' + json.dumps(resource) + ', ' + json.dumps(conditions, ensure_ascii=False) + ');')
                lines.append("  // Deferred marker; not a local businessAssertion PASS.")
                lines.append("  // @deferred " + assertion["id"])
                continue
            lines.append("  await businessAssertion('" + assertion['id'] + "', async () => {")
            for check in assertion['checks']:
                loc = locator_expression(check['target'], pages)
                if check['op'] == 'occurrence_count':
                    lines.append('    await expect.poll(() => observations[' + json.dumps(check['target']) + '].count()).toBe(' + str(check['value']) + ');')
                    continue
                if check['op'] == 'request_count':
                    lines.append('    await expect.poll(() => networks[' + json.dumps(check['target']) + '].count()).toBe(' + str(check['value']) + ');')
                    continue
                if check['op'] == 'visible_text':
                    lines.append('    await expect.poll(() => ' + loc + '.innerText()).toBe(' + json.dumps(check['value'], ensure_ascii=False) + ');')
                    continue
                if check['op'] == 'blocked':
                    lines.append('    expect(await ' + loc + '.evaluate(el => el.matches(":disabled") || el.getAttribute("aria-disabled") === "true" || /disabled/i.test(el.className) || getComputedStyle(el).pointerEvents === "none")).toBe(true);')
                    continue
                if not loc:
                    todo(assertion['id'] + ' ' + check['target']); continue
                if check['op'] == 'left_of':
                    other = locator_expression(check['value'], pages)
                    if not other:
                        todo(assertion['id'] + ' ' + check['value']); continue
                    lines.append('    expect((await ' + loc + '.boundingBox())!.x).toBeLessThan((await ' + other + '.boundingBox())!.x);')
                    continue
                method = {'visible':'toBeVisible', 'hidden':'toBeHidden', 'text':'toHaveText', 'contains':'toContainText', 'value':'toHaveValue',
                          'attribute':'toHaveAttribute', 'count':'toHaveCount', 'enabled':'toBeEnabled', 'disabled':'toBeDisabled'}[check['op']]
                args = [check['attribute']] if check['op'] == 'attribute' else []
                if 'value' in check:
                    args.append(check['value'])
                lines.append('    await expect(' + loc + ').' + method + '(' + ', '.join(json.dumps(x, ensure_ascii=False) for x in args) + ');')
            lines.append('  });')
        for rb in (item for item in spec.get('read_back', []) if item['after'] == sid):
            lines.append('  await page.reload();')
            for index, target_name in enumerate(rb['reopen']):
                entry = pages['targets'][target_name]
                if index == 0 and entry.get('open'):
                    lines.append('  page = await openTarget(page, ' + json.dumps(target_name) + ');')
                else:
                    reopen_loc = locator_expression(target_name, pages)
                    if not reopen_loc:
                        todo(rb['id'] + ' ' + target_name)
                    else:
                        lines.append('  await ' + reopen_loc + '.click();')
            field_loc = locator_expression(rb['target'], pages)
            lines.append('  await verifyPersisted(page, caseContext, ' + json.dumps(rb, ensure_ascii=False) + ', ' + json.dumps(pages['targets'][rb['save_target']]['network']) + ', async () => await readFieldValue(' + field_loc + '));')
    lines += ['  await assertSaveBusinessOk(caseContext);', '  } finally {', '    for (const network of Object.values(networks)) await network.dispose();', '    for (const observation of Object.values(observations)) await observation.dispose();', '  }', '});', '']
    body = '\n'.join(lines)
    require(not locator_errors(body, pages), 'Generated locator lint failed', locator_errors(body, pages))
    relative = 'tests/generated/' + cid + '.spec.ts'
    script = base / 'runner' / relative
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(body)
    unsupported_data = [key for key in spec['data_prep'] if not catalog[key].get('handler')]
    if unsupported_data:
        markers = ['  // TODO explore: data-prep ' + key + '\n  throw new Error(' + json.dumps('UIA_EXPLORATION_REQUIRED: data-prep ' + key) + ');' for key in unsupported_data]
        body = body.replace('  try {', '  try {\n' + '\n'.join(markers))
        script.write_text(body)
    todos += ['data-prep ' + key for key in unsupported_data]
    if todos or spec['questions']:
        case.update(stage='discovery', work_status='pending')
        event(m, 'spec_generated_todo', case_id=cid, todos=todos)
        return {'case_id': cid, 'script': 'runner/' + relative, 'todos': todos, 'runnable': False}
    return register_script(base, m, cid, 'runner/' + relative)


def register_script(base, m, cid, script_path):
    """Register a final template/AI spec; coverage and lifecycle declarations are derived."""
    require(not m.get('active_batch'), 'Cannot register during an active batch')
    case = m['cases'][cid]
    spec = read_yaml(spec_path(base, case))
    result = lint(base, m, [cid])
    require(not result['errors'] and not result['cases'][cid]['errors'], 'case-spec lint failed', result)
    require(not any(cid in item['case_ids'] for item in result['explore']), 'Resolve unknown targets before registration')
    require(not spec['questions'], 'Resolve business questions before registration')
    env, catalog, pages = catalogs()
    require(spec['automatable']['status'] != 'manual', 'Manual case cannot register')
    require(all(catalog[key].get('handler') for key in spec['data_prep']), 'Data preparation handler is not implemented')
    script = inside(base, script_path)
    inside(base / 'runner/tests', script)
    require(script.suffix == '.ts' and script.is_file(), 'Final spec must be a TypeScript file under runner/tests')
    relative = str(script.relative_to((base / 'runner').resolve()))
    body = script.read_text()
    require(not locator_errors(body, pages), 'Final spec locator lint failed', locator_errors(body, pages))
    require('TODO explore:' not in body and 'UIA_EXPLORATION_REQUIRED' not in body, 'Resolve exploration TODO before registration')
    refs = coverage(body, relative)
    for field in ('steps', 'assertions'):
        require(set(refs[field]) == {x['id'] for x in spec[field]}, 'Coverage markers differ from case-spec ' + field)
    reg = {'case_id':cid, 'case_spec':True, 'script':'runner/' + relative,
           'fixture':{'hooks':'fixtures/case-spec.mjs', 'mutates':bool(spec['mutation_scope']), 'mutation_scope':spec['mutation_scope']},
           'dependencies':['knowledge/page-map.yaml', 'knowledge/data-prep.yaml', 'knowledge/network.yaml', 'knowledge/patterns.yaml'], 'needs_public':pages['pages'][spec['start_page']].get('public', False) or ('public_frontend' in spec['required_env'] and not any(s['verb'] == 'defer_public' for s in spec['steps'])),
           'coverage':refs}
    previous = case.get('version')
    case.update(registration=reg, daily_spec=False, case_spec=str(spec_path(base, case).relative_to(base)),
                spec_hash=file_hash(spec_path(base, case)), flow_ids=['case-spec'], fixture_ids=['case-spec:' + cid])
    from .workflow import case_version
    version = case_version(base, m, case)
    if previous != version:
        reset_case(case, 'case_spec_registered', 'execution')
    case.update(version=version, stage='execution', work_status='runnable')
    from .preconditions import sync_preconditions
    sync_preconditions(base, m)
    for question in m.get('questions', {}).values():
        if question['status'] == 'open' and cid in question['case_ids']:
            case['work_status'] = 'waiting_human'
    from .checks import case_errors
    errors, _ = case_errors(base, case, m['config'], execution=True)
    require(not errors, 'Final spec execution gate failed', errors)
    event(m, 'spec_registered', case_id=cid, script=reg['script'])
    return {'case_id':cid, 'script':reg['script'], 'todos':[], 'runnable':case['work_status'] == 'runnable', 'coverage':reg['coverage']}


def render(base, m, cid):
    spec = read_yaml(spec_path(base, m['cases'][cid]))
    lines = ['# ' + cid + ': ' + spec['intent'], '', 'Start: ' + spec['start_page'], '',
             'Environment: ' + ', '.join(spec['required_env']), 'Data: ' + json.dumps(spec['data_prep'], ensure_ascii=False), '', '## Steps', '']
    lines += [f"- {s['id']}: {s['verb']} {s['target']}" + (' = ' + repr(s['value']) if 'value' in s else '') for s in spec['steps']]
    lines += ['', '## Excel expectations', '']
    lines += [f"- {a['id']} after {a['after']}: {a['excel']}" for a in spec['assertions']]
    lines += ['', '## Business questions', ''] + ['- ' + q for q in spec['questions']]
    if spec.get('read_back'):
        lines += ['', '## Save read-back', ''] + [f"- {row['id']} after {row['after']}: {row['target']} = {row['value']}; reopen {' → '.join(row['reopen'])}" for row in spec['read_back']]
    target = spec_path(base, m['cases'][cid]).with_suffix('.md')
    target.write_text('\n'.join(line.rstrip() for line in lines) + '\n')
    return {'markdown':str(target.relative_to(base))}
