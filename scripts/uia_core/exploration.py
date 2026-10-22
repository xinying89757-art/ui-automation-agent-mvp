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
    if not any(row.get('method') == 'generator' and row.get('result') in {'ok', 'failed'} for row in rows):
        missing.append('generator via tests/seed.spec.ts (exploration-log)')
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
