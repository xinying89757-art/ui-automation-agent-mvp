"""Exploration evidence and the focused demonstration escalation gate."""
from .common import require, now, read_yaml
from .secrets import scrub_text


def log(m, method, purpose, result, note):
    require(purpose and purpose.strip(), 'Exploration purpose must name a specific node')
    require(method in {'generator', 'midscene'} and result in {'ok', 'failed'}, 'Invalid exploration method/result')
    row = {'at': now(), 'method': method, 'purpose': purpose, 'result': result, 'note': note}
    import json
    require(scrub_text(json.dumps(row, ensure_ascii=False), m['config']) == json.dumps(row, ensure_ascii=False), 'Exploration metadata contains sensitive values')
    m.setdefault('exploration', []).append(row)
    return {'recorded': row}


def demo_gate(m, node, cases):
    require(node and node.strip() and node not in {'page', 'editor', '*'}, 'Demo must name the specific unknown node')
    rows = [row for row in m.get('exploration', []) if row.get('purpose') == node]
    missing = []
    if not any(row.get('method') == 'snapshot' and (row.get('goto') or row.get('open_target') or row.get('steps_count') or row.get('clicks')) for row in rows):
        missing.append('snapshot --goto/--open-target/--step navigation')
    # Only a real sub-agent run counts; a self-reported "tool unavailable" note is not a generator attempt.
    if not any(row.get('method') == 'generator' and row.get('source') == 'generator-cli' for row in rows):
        missing.append('generator via `uia.py generator --purpose NODE --plan ...`')
    require(not missing, 'Demo refused; missing rungs: ' + ', '.join(missing))
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
Rules: call generator_setup_page with seedFile "tests/seed.spec.ts" first (the page is the authenticated editor), then
use browser_* tools to reach the node and its observable completion signal. Read-only: do not click save/publish/delete,
do not type credentials, do not print cookies/storage. Do not edit files except writing the generated test via
generator_write_test to tests/explore/{slug}.spec.ts if you get that far. Stop after at most {max_actions} browser actions.
Final answer: ONE fenced ```json block {{"reached": true|false, "route": [ordered steps as "goto:/path" | "click:<css or text=...>" |
"hover:..." | "fill:<target>=${{INPUT}}"], "frames": [iframe selectors on the way], "completion_signal": "<locator + visible text>",
"targets": {{"<proposed.name>": "<stable css/role locator, scoped by frame>"}}, "notes": "<=3 short sentences"}}."""


def codex_binary():
    import os, shutil
    from pathlib import Path
    explicit = os.environ.get('UIA_CODEX_BIN')
    for candidate in (explicit, shutil.which('codex'), str(Path.home() / '.local/bin/codex')):
        if candidate and Path(candidate).is_file():
            return candidate
    require(False, 'Codex CLI not found; set UIA_CODEX_BIN')


def generator_command(binary, cwd, env, prompt, model):
    command = [binary, 'exec', '-C', cwd, '-s', 'workspace-write', '-m', model,
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
    final, usage = '', {}
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get('item') or {}
        if event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
            final = item.get('text', '')
        if event.get('type') == 'turn.completed':
            usage = event.get('usage') or {}
    match = re.search(r'```json\s*(\{.*?\})\s*```', final, re.S)
    route = None
    if match:
        try:
            route = json.loads(match.group(1))
        except ValueError:
            route = None
    return final, usage, route


def run_generator(base, m, purpose, plan, minutes=20, model=None, max_actions=40, runner=None):
    """Launch an isolated Codex sub-agent with the Test Agents MCP + seed; record a real generator rung."""
    import json, re, subprocess, time
    from .common import atomic_write
    from .profiles import agent_env
    require(purpose and purpose.strip() and plan and plan.strip(), 'generator requires --purpose and --plan')
    setup = agent_env(base, m)
    slug = re.sub(r'[^A-Za-z0-9_.-]+', '-', purpose).strip('-')[:60] or 'node'
    prompt = GENERATOR_PROMPT.format(purpose=purpose, plan=plan, slug=slug, max_actions=max_actions)
    model = model or 'gpt-6-luna'
    command = generator_command(codex_binary(), setup['cwd'], setup['env'], prompt, model)
    started, t0 = now(), time.monotonic()
    runner = runner or (lambda cmd, timeout: subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL))
    try:
        result = runner(command, minutes * 60)
        output, code = result.stdout, result.returncode
    except subprocess.TimeoutExpired as exc:
        output, code = (exc.stdout or b'').decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ''), 124
    final, usage, route = parse_generator_output(output)
    reached = bool(route and route.get('reached'))
    clean = lambda value: scrub_text(json.dumps(value, ensure_ascii=False), m['config'])
    out_dir = base / 'exploration'
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {'purpose': purpose, 'plan': plan, 'model': model, 'exit_code': code, 'reached': reached,
              'route': json.loads(clean(route)) if route else None, 'final_message': scrub_text(final, m['config'])[-4000:]}
    atomic_write(out_dir / ('generator-' + slug + '.json'), report)
    row = {'at': now(), 'started_at': started, 'method': 'generator', 'source': 'generator-cli', 'purpose': purpose,
           'result': 'ok' if reached else 'failed', 'duration_ms': int((time.monotonic() - t0) * 1000),
           'model': model, 'exit_code': code,
           'tokens': {k: usage.get(k) for k in ('input_tokens', 'cached_input_tokens', 'output_tokens') if k in usage},
           'note': 'route' if reached else ('no route; exit ' + str(code))}
    m.setdefault('exploration', []).append(row)
    return {'recorded': row, 'report': str((out_dir / ('generator-' + slug + '.json')).relative_to(base)),
            'route': report['route']}
