"""Cross-round run creation and per-environment comparison."""
import copy
import shutil

from .common import ROOT, atomic_write, event, load_run, now, read_json, read_yaml, require, safe_id


def create(previous_run, round_number, run_id, profile, excel=None):
    from . import workflow, profiles
    require(type(round_number) is int and round_number >= 1, 'Round number must be a positive integer')
    require(run_id == safe_id(run_id), 'Run ID must be a safe directory name')
    new_base = ROOT / 'runs' / run_id
    require(not (new_base / 'run.json').exists(), 'Run already exists')
    if round_number == 1:
        require(not previous_run, 'Round 1 cannot have a previous-round baseline')
        require(excel, 'Round 1 requires --excel')
        workflow.init(run_id, profiles.profile_path(profile))
        workflow.scaffold(new_base)
        manifest_path = new_base / 'run.json'
        current = read_json(manifest_path)
        current['round'] = {'number': 1, 'requirement_id': run_id,
                            'environment': current['config'].get('environment', {}).get('id', 'legacy'),
                            'previous_run': None, 'created_from': None}
        imported = workflow.import_excel(new_base, current, excel)
        from .preconditions import sync_preconditions
        sync_preconditions(new_base, current)
        event(current, 'round_created', previous_run=None, round=1, reused=0)
        atomic_write(manifest_path, current)
        return {'run': str(manifest_path), 'round': current['round'], 'reused_scripts': [],
                'rerun_existing': [], 're_explore': list(current.get('cases', {})), 'import': imported}
    require(previous_run, 'Follow-up rounds require --from-run')
    previous_path, previous = load_run(previous_run)
    require(round_number >= 2, 'A follow-up round must be numbered 2 or greater')
    expected_round = int((previous.get('round') or {}).get('number', 1)) + 1
    require(round_number == expected_round, 'Round number must follow the selected prior run')
    workflow.init(run_id, profiles.profile_path(profile))
    workflow.scaffold(new_base)
    manifest_path = new_base / 'run.json'
    current = read_json(manifest_path)
    current['round'] = {'number': round_number, 'requirement_id': previous.get('round', {}).get('requirement_id', previous['run_id']),
                        'environment': current['config'].get('environment', {}).get('id', 'legacy'),
                        'previous_run': previous['run_id'], 'created_from': previous['run_id']}
    current['identity_map'] = copy.deepcopy(previous.get('identity_map', {}))
    current['sources'] = copy.deepcopy(previous.get('sources', []))
    current['pipeline'] = previous.get('pipeline', 'case-spec.v1')
    current['precondition_catalog'] = copy.deepcopy(previous.get('precondition_catalog', {}))
    current['cases'] = {}
    for cid, original in previous.get('cases', {}).items():
        case = copy.deepcopy(original)
        source_rel = case.get('source')
        if source_rel and (previous_path.parent / source_rel).is_file():
            target = new_base / source_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(previous_path.parent / source_rel, target)
        spec_rel = case.get('case_spec')
        if spec_rel and (previous_path.parent / spec_rel).is_file():
            target = new_base / spec_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(previous_path.parent / spec_rel, target)
        previous_result = original.get('result')
        passing = previous_result == 'passed' and bool(original.get('registration'))
        script_exists = False
        if (original.get('registration') or {}).get('script'):
            script_exists = (ROOT / 'assets/playwright-runner' / original['registration']['script'].removeprefix('runner/')).is_file()
        reused = passing and script_exists
        rerun = not reused and script_exists and bool(original.get('case_spec'))
        case['round_previous_result'] = previous_result
        case['round_script_action'] = 'reused' if reused else 'rerun_existing' if rerun else 're_explore'
        case['attempts'] = []
        case.update(result=None, pass_streak=0, stability='not_run', work_status='runnable' if reused or rerun else 'pending')
        case['stage'] = 'execution' if reused or rerun else ('spec' if spec_rel else 'discovery')
        case.pop('delivery_pass_streak', None)
        case.pop('cleanup_recovery', None)
        case.pop('classification', None)
        case.pop('failure_class', None)
        case.pop('remote_status', None)
        if not (reused or rerun):
            case['registration'] = None
            case['version'] = None
        current['cases'][cid] = case
    old_checklist = next((item for item in previous.get('questions', {}).values()
                          if item.get('subject') == 'run-preconditions'), {})
    preset_keys = {row['key'] for row in old_checklist.get('entries', []) if row.get('prep_method') == 'user_preset'}
    carried = {key: value for key, value in old_checklist.get('answer', {}).get('entries', {}).items() if key in preset_keys}
    current['round_memory'] = {'user_preset_answers': carried, 'source_round': previous.get('round', {}).get('number', 1)}
    current['questions'] = {}
    current['status'] = 'active'
    current['preflight'] = None
    from .bindings import case_bindings
    atomic_write(new_base / 'state/cases.json', case_bindings(new_base, current))
    if excel:
        imported = workflow.import_excel(new_base, current, excel)
        for cid, case in current['cases'].items():
            old = previous.get('cases', {}).get(cid)
            if not old or case.get('source_hash') != old.get('source_hash'):
                case['round_script_action'] = 're_explore'
                case['registration'] = None
                case['stage'] = 'spec'
                case['work_status'] = 'pending'
                stale_spec = case.get('case_spec')
                if stale_spec:
                    (new_base / stale_spec).unlink(missing_ok=True)
                for field in ('case_spec', 'spec_lint', 'spec_first_lint', 'spec_hash', 'spec_generation_blocked'):
                    case.pop(field, None)
        atomic_write(new_base / 'state/cases.json', case_bindings(new_base, current))
        from .preconditions import sync_preconditions
        sync_preconditions(new_base, current)
    else:
        imported = None
    event(current, 'round_created', previous_run=previous['run_id'], round=round_number,
          reused=sum(c['round_script_action'] == 'reused' for c in current['cases'].values()))
    atomic_write(manifest_path, current)
    return {'run': str(manifest_path), 'round': current['round'],
            'reused_scripts': [cid for cid, c in current['cases'].items() if c['round_script_action'] == 'reused'],
            'rerun_existing': [cid for cid, c in current['cases'].items() if c['round_script_action'] == 'rerun_existing'],
            're_explore': [cid for cid, c in current['cases'].items() if c['round_script_action'] == 're_explore'],
            'import': imported}


def compare(run):
    path, current = load_run(run)
    prior_id = (current.get('round') or {}).get('previous_run')
    require(prior_id, 'This run has no previous round to compare')
    _, previous = load_run(prior_id)
    reused = [cid for cid, case in current.get('cases', {}).items() if case.get('round_script_action') == 'reused']
    rerun = [cid for cid, case in current.get('cases', {}).items() if case.get('round_script_action') == 'rerun_existing']
    explored = [cid for cid, case in current.get('cases', {}).items() if case.get('round_script_action') != 'reused']
    explored = [cid for cid in explored if cid not in rerun]
    old_pass = {cid for cid, case in previous.get('cases', {}).items() if case.get('result') == 'passed'}
    new_pass = {cid for cid, case in current.get('cases', {}).items() if case.get('result') == 'passed'}
    old_fail = {cid for cid, case in previous.get('cases', {}).items() if case.get('result') in {'business_failure', 'save_not_persisted'}}
    new_fail = {cid for cid, case in current.get('cases', {}).items() if case.get('result') in {'business_failure', 'save_not_persisted'}}
    report = {'schema_version': 'uia-round-comparison.v1', 'requirement_id': current['round']['requirement_id'],
              'previous_run': previous['run_id'], 'run_id': current['run_id'], 'round': current['round']['number'],
              'environment': current['round']['environment'],
              'scripts_reused': reused, 'scripts_rerun': rerun, 'scripts_re_explored': explored,
              'pass_delta': len(new_pass) - len(old_pass), 'pass_gained': sorted(new_pass - old_pass),
              'pass_lost': sorted(old_pass - new_pass), 'failure_delta': len(new_fail) - len(old_fail),
              'failures_added': sorted(new_fail - old_fail), 'failures_cleared': sorted(old_fail - new_fail)}
    atomic_write(path.parent / 'reports/round-comparison.json', report)
    lines = ['# 轮次对比', '', f"需求：{report['requirement_id']}；轮次：{report['round']}；环境：{report['environment']}。", '',
             f"复用通过脚本 {len(reused)} 条；原脚本重跑 {len(rerun)} 条；重新探索 {len(explored)} 条；通过变化 {report['pass_delta']:+d}；失败变化 {report['failure_delta']:+d}。", '',
             '## 脚本复用 / 重新探索', '', '复用：' + ('、'.join(reused) or '无'), '', '重新探索：' + ('、'.join(explored) or '无'), '',
             '## 结果变化', '', '新增通过：' + ('、'.join(report['pass_gained']) or '无'),
             '通过转出：' + ('、'.join(report['pass_lost']) or '无'),
             '新增失败：' + ('、'.join(report['failures_added']) or '无'),
             '失败清除：' + ('、'.join(report['failures_cleared']) or '无'), '']
    (path.parent / 'reports/round-comparison.md').write_text('\n'.join(lines), encoding='utf-8')
    return report
