"""Exploration evidence and the focused demonstration escalation gate."""
from .common import inside, require, now, read_yaml
from .secrets import scrub_text


def save_snapshot_evidence(base, relative, args, result, cfg=None):
    """Persist outcome-only snapshot evidence; never copy DOM contents or locator values."""
    import json
    from .common import atomic_write
    path = inside(base, relative)
    structure = result.get('structure', {}) if isinstance(result, dict) else {}
    frame_hint = result.get('frame_hint') if isinstance(result, dict) else None
    payload = {
        'method': 'snapshot', 'node': args.node, 'entry': args.entry,
        'purpose': scrub_text(args.purpose, cfg), 'goto': args.goto, 'frame': args.frame or frame_hint,
        'entry_reached': bool(result.get('entry_reached')) if isinstance(result, dict) else False,
        'failed_step': result.get('failed_step', structure.get('failed_step')) if isinstance(result, dict) else None,
        'frame_reached': structure.get('frame_reached') if isinstance(structure, dict) else None,
        'result': result.get('result', 'ok') if isinstance(result, dict) else 'ok',
        'error': result.get('error') if isinstance(result, dict) else None,
    }
    text = json.dumps(payload, ensure_ascii=False)
    require(scrub_text(text, cfg) == text, 'Snapshot evidence contains sensitive metadata')
    atomic_write(path, payload)
    return str(path.relative_to(base))


def log(m, method, purpose, result, note, base=None, case_id=None, target=None, evidence=None):
    require(purpose and purpose.strip(), 'Exploration purpose must name a specific node')
    require(method in {'snapshot', 'generator', 'midscene'} and result in {'ok', 'failed'}, 'Invalid exploration method/result')
    row = {'at': now(), 'method': method, 'purpose': purpose, 'result': result, 'note': note}
    if case_id is not None:
        require(base is not None and case_id in m.get('cases', {}), 'Exploration case is unknown')
        require(isinstance(target, str) and target.strip(), 'Case exploration reports require --target')
        require(isinstance(evidence, str) and evidence.strip(), 'Case exploration reports require --evidence')
        evidence_path = inside(base, evidence)
        require(evidence_path.is_file(), 'Exploration evidence file does not exist')
        target_name = target.strip().lstrip('?？')
        require(target_name, 'Exploration target is empty')
        row.update(case_id=case_id, target=target_name, evidence=str(evidence_path.relative_to(base)))
        attempt = {key: row[key] for key in ('at', 'method', 'purpose', 'result', 'target', 'evidence', 'note')}
        m['cases'][case_id].setdefault('explore_attempts', []).append(attempt)
    import json
    require(scrub_text(json.dumps(row, ensure_ascii=False), m['config']) == json.dumps(row, ensure_ascii=False), 'Exploration metadata contains sensitive values')
    m.setdefault('exploration', []).append(row)
    return {'recorded': row, 'target_attempts': sum(1 for item in m.get('cases', {}).get(case_id, {}).get('explore_attempts', [])
                                                     if item.get('target') == row.get('target')) if case_id else None}


def demo_gate(m, node, cases, interaction=None, base=None, page=None):
    import re
    from .entries import resolve, request, matches
    require(node and node.strip() and node not in {'page', 'editor', '*'}, 'Demo must name the specific unknown node')
    rows = [row for row in m.get('exploration', []) if row.get('purpose') == node]
    page = page or next((r['entry'] for r in reversed(rows) if r.get('entry')), node)
    if not resolve(page):
        request(m, page, cases, base)
        require(False, '页面入口未知：请走入口提示问题（清单 D 块），不要请求演示')
    rows = [r for r in rows if r.get('entry') and matches(page, r['entry'])]
    require(any(r.get('entry_reached') is True for r in rows),
            '演示被拒绝：先用 snapshot --entry / generator --entry 到达页面入口')
    generators = [r for r in rows if r.get('method') == 'generator' and r.get('source') == 'generator-cli'
                  and r.get('failure_class') != 'subagent_start'
                  and r.get('reached_entry') is True and r.get('result') == 'failed' and r.get('failed_interaction')]
    require(generators, '演示被拒绝：需要 uia.py generator --entry 在到达入口后报告具体交互失败')
    require(interaction and re.fullmatch(r'drag|clipboard|gesture|file-dialog|canvas|other:.+', interaction),
            '演示被拒绝：必须指定 --interaction drag|clipboard|gesture|file-dialog|canvas|other:<text>')
    require(any(r['failed_interaction'] == interaction for r in generators),
            '演示被拒绝：--interaction 必须对应 generator 报告的具体失败交互')
    from .entries import safe
    safe(interaction, m['config'])
    require(bool(cases), 'Demo must name affected cases')
    require(all(node in m['cases'].get(cid, {}).get('unknown_nodes', []) for cid in cases),
            'Demo refused; every case-spec must reference this specific unknown node')


def index_unknown_nodes(base, m):
    for cid, case in m['cases'].items():
        path = base / case.get('case_spec', f'cases/{cid}/case-spec.yaml')
        spec = read_yaml(path) if path.is_file() else {}
        nodes = [step.get('target') for step in spec.get('steps', [])]
        nodes += [check.get('target') for assertion in spec.get('assertions', []) for check in assertion.get('checks', [])]
        nodes += [spec.get('start_page')]
        case['unknown_nodes'] = sorted({node[1:] for node in nodes if isinstance(node, str) and node.startswith('?')})


def save_route(base, m, args, result):
    from .common import atomic_write
    from .specs import has_snapshot_ref
    from urllib.parse import urlsplit
    import json
    # Fill data is session input; candidates carry placeholders, never its value.
    steps = ['click:' + x for x in args.click] + (['hover:' + args.hover] if args.hover else []) + list(args.step)
    def candidate_step(step):
        if not step.startswith('fill:'):
            return step
        target = step[5:]
        depth, quote = 0, None
        start = 5 if target.startswith(('text=', 'role=')) else 0
        for index in range(start, len(target)):
            char = target[index]
            if quote:
                if char == quote and (index == 0 or target[index - 1] != chr(92)):
                    quote = None
            elif char in ('"', "'"):
                quote = char
            elif char in '[(':
                depth += 1
            elif char in '])':
                depth -= 1
            elif char == '=' and depth == 0:
                return 'fill:' + target[:index] + '=${INPUT}'
        return 'fill:${TARGET}=${INPUT}'
    steps = [candidate_step(step) for step in steps]
    route = {'name': args.save_as, 'purpose': args.purpose, 'node': args.node,
             'goto': urlsplit(args.goto).path if args.goto else None, 'open_target': args.open_target,
             'frame': args.frame, 'scope': args.scope, 'steps': steps,
             'status': 'candidate', 'failed_step': result.get('structure', {}).get('failed_step')}
    text = json.dumps(route, ensure_ascii=False)
    require(not has_snapshot_ref(route), 'Routes cannot contain snapshot refs')
    require(scrub_text(text, m['config']) == text, 'Route contains sensitive metadata; use named targets')
    m.setdefault('exploration_routes', {})[args.save_as] = route
    atomic_write(base / 'exploration-routes.yaml', {'routes': m['exploration_routes']}, as_yaml=True)


GENERATOR_PROMPT = """You are a Playwright Test Agents generator used ONLY for exploration of one unknown page node.
Node: {purpose}
Goal / plan: {plan}
Starting entry (reach this route before exploring the interaction): {entry_hint}
Rules: call generator_setup_page with seedFile "tests/seed.spec.ts" first (the page is the authenticated backend area), then
follow Starting entry's node/open_target and ordered steps FIRST. The seed already opens its node area;
do not switch to another area. Entry clicks run outside frame_hint; use that frame only after reaching entry.
Use the shared knowledge below before exploring. Known targets and their interaction patterns are authoritative; explore only gaps.
Shared knowledge match: {knowledge_context}
use browser_* tools to reach the node and its observable completion signal. {mutation_rule}
do not type credentials, do not print cookies/storage. Do not edit files except writing the generated test via
generator_write_test to tests/explore/{slug}.spec.ts if you get that far. Stop after at most {max_actions} browser actions.
Checkpoint: the moment you reach the Starting entry, send one short progress message with a ```json block
{{"checkpoint": "entry", "reached": false, "reached_entry": true, "route": [...], "frames": [...]}} and then continue.
Final answer: ONE fenced ```json block {{"reached": true|false, "reached_entry": true|false,
"failed_interaction": "drag|clipboard|gesture|file-dialog|canvas|other:<specific text> or null; only after reaching entry",
"route": [ordered steps; "goto:/path" or "click:text=<visible text>" strings, or objects
{{"verb": "click|hover|fill|press", "target": <TARGET>, "value": "<literal non-secret text typed, e.g. / for a slash menu>"}}],
"frames": [iframe selectors on the way], "completion_signal": "<locator + visible text>",
"targets": {{"<proposed.name>": <TARGET>}}, "notes": "<=3 short sentences"}}.
<TARGET> is a JSON object, never Playwright code: {{"frames": [outer iframe css, ..., innermost], "css": "<stable css>"}}
or {{"frames": [...], "role": "button", "name": "<accessible name>"}} or {{"frames": [...], "text": "<exact visible text>"}}."""


def codex_binary():
    import os, shutil
    from pathlib import Path
    explicit = os.environ.get('UIA_CODEX_BIN')
    for candidate in (explicit, shutil.which('codex'), str(Path.home() / '.local/bin/codex')):
        if candidate and Path(candidate).is_file():
            return candidate
    require(False, 'Codex CLI not found; set UIA_CODEX_BIN')


def generator_command(binary, cwd, env, prompt, model):
    import os
    sandboxed = any(os.environ.get(k) for k in ('CODEX_SANDBOX', '__CURSOR_SANDBOX_ENV_RESTORE'))
    sandbox = ['--dangerously-bypass-approvals-and-sandbox'] if sandboxed else ['-s', 'workspace-write']
    command = ['timeout', '2h', binary, 'exec', '-C', cwd, *sandbox, '-m', model,
               '-c', 'model_reasoning_effort="high"', '-c', 'sandbox_workspace_write.network_access=true',
               '-c', 'mcp_servers.playwright-test.command="npx"',
               '-c', 'mcp_servers.playwright-test.args=["playwright","run-test-mcp-server"]',
               '-c', 'mcp_servers.playwright-test.cwd="' + cwd + '"',
               '-c', 'mcp_servers.playwright-test.default_tools_approval_mode="approve"']
    for key, value in sorted(env.items()):
        command += ['-c', 'mcp_servers.playwright-test.env.' + key + '="' + value + '"']
    return command + ['--json', prompt]


def parse_generator_output(text):
    """Return (final_message, usage, route_json_or_None) from codex --json output."""
    import json, re
    final, usage, checkpoint = '', {}, None
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get('item') or {}
        if event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
            final = item.get('text', '')
            hit = re.search(r'```json\s*(\{.*?\})\s*```', final, re.S)
            if hit and '"checkpoint"' in hit.group(1):
                try:
                    checkpoint = json.loads(hit.group(1))
                except ValueError:
                    pass
        if event.get('type') == 'turn.completed':
            usage = event.get('usage') or {}
    match = re.search(r'```json\s*(\{.*?\})\s*```', final, re.S)
    route = None
    if match:
        try:
            route = json.loads(match.group(1))
        except ValueError:
            route = None
    if route is None and checkpoint:
        route = dict(checkpoint, reached=False, failed_interaction=None)
    return final, usage, route


READ_ONLY_RULE = 'Read-only: do not click save/publish/delete,'
DRAFT_RULE = ('Draft mode: you MAY click save/confirm/delete INSIDE an editor or component form and submit empty forms '
              'to observe validation, but never save the outer page/record, never publish, and leave via the page cancel/back,')


def run_generator(base, m, purpose, plan, minutes=20, model=None, max_actions=40, runner=None, entry=None, draft=False):
    """Launch an isolated Codex sub-agent with the Test Agents MCP + seed; record a real generator rung."""
    import json, re, subprocess, time
    from .common import atomic_write
    from .profiles import agent_env
    require(purpose and purpose.strip() and plan and plan.strip(), 'generator requires --purpose and --plan')
    from .entries import resolve, safe, navigation_hint
    hint = resolve(entry) if entry else None
    require(not entry or hint, '页面入口未知：请走入口提示问题（清单 D 块），不要请求演示')
    require(not hint or not hint.get('not_a_page'), '该入口不是页面，跳过导航')
    hint = navigation_hint(hint) if hint else None
    safe({'purpose': purpose, 'plan': plan, 'entry': entry, 'hint': hint}, m['config'])
    setup = agent_env(base, m)
    if hint and hint.get('node'):
        setup['env']['UIA_SEED_ENTRY'] = hint['node']
    slug = re.sub(r'[^A-Za-z0-9_.-]+', '-', purpose).strip('-')[:60] or 'node'
    if draft:
        mutation = m['config'].get('mutation', {})
        require(mutation.get('allowed'), '--draft 需要运行配置允许变更（清单 B 块同意）')
    from .knowledge import matched_context
    knowledge_context = matched_context(base, m, purpose)
    prompt = GENERATOR_PROMPT.format(purpose=purpose, plan=plan, slug=slug, max_actions=max_actions,
                                     mutation_rule=DRAFT_RULE if draft else READ_ONLY_RULE,
                                     entry_hint=json.dumps(hint, ensure_ascii=False) if hint else 'No entry supplied; cannot request a demo.',
                                     knowledge_context=json.dumps(knowledge_context, ensure_ascii=False, sort_keys=True))
    model = model or 'gpt-6-luna'
    from .common import DEFAULTS
    requested_minutes = minutes
    minutes = max(int(minutes or 0), int(DEFAULTS['exploration_minutes_per_flow']))
    command = generator_command(codex_binary(), setup['cwd'], setup['env'], prompt, model)
    started, t0 = now(), time.monotonic()
    runner = runner or (lambda cmd, timeout: subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL))
    startup_error = ''
    try:
        result = runner(command, minutes * 60)
        output, code = result.stdout, result.returncode
        startup_error = getattr(result, 'stderr', '') or ''
    except subprocess.TimeoutExpired as exc:
        output, code = (exc.stdout or b'').decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ''), 124
    except OSError as exc:
        output, code, startup_error = '', 127, str(exc)
    final, usage, route = parse_generator_output(output)
    start_failure = (code not in (0, 124) and not usage and not route) or bool(re.search(
        r'(?:sandbox.*(?:failed to start|failed|not permitted)|failed to (?:start|initialize).*sandbox|permission denied.*(?:codex|session)|(?:codex|session).*permission denied)',
        startup_error + output + final, re.I))
    failure_class = 'subagent_start' if start_failure else ('timeout' if code == 124 else None)
    if start_failure:
        route = None
        final = 'Sub-agent failed to start or initialize its sandbox/runtime. ' + scrub_text(startup_error, m['config'])[:500]
    reached = bool(route and route.get('reached'))
    reached_entry = bool(entry and route and route.get('reached_entry') is True)
    failed_interaction = route.get('failed_interaction') if route and reached_entry and not reached else None
    if not isinstance(failed_interaction, str) or not re.fullmatch(r'drag|clipboard|gesture|file-dialog|canvas|other:.+', failed_interaction):
        failed_interaction = None
    if failed_interaction:
        failed_interaction = scrub_text(failed_interaction, m['config'])
    clean = lambda value: scrub_text(json.dumps(value, ensure_ascii=False), m['config'])
    out_dir = base / 'exploration'
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {'purpose': purpose, 'plan': plan, 'model': model, 'exit_code': code, 'reached': reached,
              'failure_class': failure_class,
              'entry': entry, 'reached_entry': reached_entry, 'failed_interaction': failed_interaction,
              'route': json.loads(clean(route)) if route else None, 'final_message': scrub_text(final, m['config'])[-4000:]}
    atomic_write(out_dir / ('generator-' + slug + '.json'), report)
    row = {'at': now(), 'started_at': started, 'method': 'generator', 'source': 'generator-cli', 'purpose': purpose,
           'result': 'ok' if reached else 'failed', 'duration_ms': int((time.monotonic() - t0) * 1000),
           'model': model, 'exit_code': code,
           'failure_class': failure_class,
           'entry': entry, 'entry_reached': reached_entry, 'reached_entry': reached_entry,
           'failed_interaction': failed_interaction,
           'tokens': {k: usage.get(k) for k in ('input_tokens', 'cached_input_tokens', 'output_tokens') if k in usage},
           'budget_minutes': minutes, 'draft': bool(draft), 'requested_minutes': requested_minutes,
           'note': 'route' if reached else ('no route; exit ' + str(code))}
    from .knowledge import known_page
    row.update(known_page=known_page(purpose) or known_page(entry), re_explored=known_page(purpose) or known_page(entry))
    m.setdefault('exploration', []).append(row)
    advice = None
    if failure_class == 'timeout':
        advice = ('generator 超时不是页面不可达的证据：同一入口用默认预算再运行一次（不传 --minutes），'
                  + ('已到达入口，后续计划只写入口之后的交互；' if reached_entry else '')
                  + '不要把超时转成审核问题或演示请求。')
    elif failure_class == 'subagent_start':
        advice = '子代理启动失败属于环境问题：修复后重试，不算演示依据。'
    if (reached or reached_entry) and failure_class is None:
        advice = ('把路线和目标写入共享知识：uia.py hints promote --run <RUN> --report exploration/generator-' + slug
                  + '.json' + (" --page '" + entry + "'" if entry else '') + '；然后在 case-spec 中引用 ' + purpose + '.<名称> 目标，不要手改 page-map 或读框架源码。')
    return {'next': advice, 'recorded': row, 'report': str((out_dir / ('generator-' + slug + '.json')).relative_to(base)),
            'route': report['route']}
