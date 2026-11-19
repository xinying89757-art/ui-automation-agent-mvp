"""Compact, run-local process observations for delivery review."""
from collections import defaultdict


def build(base, manifest, metrics):
    interventions = []
    for item in manifest.get('interaction_events', []):
        if item.get('kind') not in {'checklist_answer', 'mid_run_question', 'session_turn'}:
            continue
        if item.get('kind') == 'session_turn' and item.get('category') != '计划外':
            continue
        question = manifest.get('questions', {}).get(item.get('question_id'), {})
        topics = [entry.get('label') for entry in item.get('entries', []) if entry.get('label')]
        cases = sorted({cid for entry in item.get('entries', []) for cid in entry.get('cases', [])})
        interventions.append({
            'kind': item.get('kind'), 'at': item.get('at'),
            'for': '、'.join(topics) or question.get('subject') or question.get('prompt') or item.get('category') or '清单答复',
            'case_ids': cases or question.get('case_ids', []),
        })
    prep = []
    for cid, case in manifest.get('cases', {}).items():
        for attempt in case.get('attempts', []):
            duration = attempt.get('prep_time_ms')
            if isinstance(duration, (int, float)) and duration >= 0:
                prep.append({'case_id': cid, 'batch_id': attempt.get('batch_id'), 'duration_ms': duration,
                             'check': attempt.get('precondition_check'), 'action': attempt.get('preparation')})
    not_run = []
    for cid, case in manifest.get('cases', {}).items():
        if not any(a.get('executed') for a in case.get('attempts', [])):
            reason = (case.get('classification') or {}).get('reason') or case.get('work_status') or '未调度'
            if case.get('result') in {'passed', 'business_failure', 'automation_failure', 'unasserted'}:
                continue
            state = case.get('work_status') or 'pending'
            kind = 'frontend' if state == 'frontend' else 'waiting_human' if state == 'waiting_human' else 'not_ready' if state in {'pending', 'runnable'} else 'not_run'
            not_run.append({'case_id': cid, 'classification': kind, 'reason': reason})
    signatures = defaultdict(set)
    labels = defaultdict(set)
    for cid, case in manifest.get('cases', {}).items():
        spec_path = case.get('case_spec')
        if not spec_path:
            continue
        try:
            from .common import read_yaml
            spec = read_yaml(base / spec_path)
        except (OSError, ValueError):
            continue
        for step in spec.get('steps', []):
            key = (step.get('verb'), step.get('target'))
            signatures[key].add(cid)
            labels[key].add(step.get('id', ''))
    common = [{'verb': verb, 'target': target, 'case_ids': sorted(cases),
               'step_ids': sorted(x for x in labels[(verb, target)] if x)}
              for (verb, target), cases in signatures.items() if len(cases) >= 2]
    return {'schema_version': 'uia-process-issues.v1', 'run_id': manifest['run_id'],
            'human_intervention_count': len(interventions), 'human_interventions': interventions,
            'data_prep_time_ms_total': sum(x['duration_ms'] for x in prep), 'data_preparation': prep,
            'not_run_cases': not_run, 'common_step_candidates': sorted(common, key=lambda x: (x['verb'], x['target'])),
            'metrics': {'unplanned_interventions': metrics.get('unplanned_interventions', 0),
                        'human_interventions': metrics.get('human_interventions', 0),
                        'failure_class_counts': metrics.get('failure_class_counts', {})}}


def markdown(report):
    lines = ['# 流程问题与指标', '',
             f"人工介入：{report['human_intervention_count']} 次；数据准备耗时：{report['data_prep_time_ms_total']} ms。", '',
             '## 人工介入', '']
    lines += [f"- {row['at'] or '时间未知'}：{row['for']}（{'、'.join(row['case_ids']) or '整轮'}）" for row in report['human_interventions']] or ['- 无']
    lines += ['', '## 未运行用例', '']
    lines += [f"- {row['case_id']}（{row['classification']}）：{row['reason']}" for row in report['not_run_cases']] or ['- 无']
    lines += ['', '## 公共步骤候选', '']
    lines += [f"- {row['verb']} {row['target']}：{'、'.join(row['case_ids'])}" for row in report['common_step_candidates']] or ['- 暂无']
    return '\n'.join(lines) + '\n'
