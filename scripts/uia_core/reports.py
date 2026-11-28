from __future__ import annotations

import copy
import html
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill

from .common import atomic_write, elapsed, file_hash, inside, now, read_json, read_yaml, summary
from .secrets import drop_unsafe_artifacts, scrub_text, unsafe_attachment
from . import metrics as run_metrics


STATUS_ZH = {"remote_pending": "待远程检查", "remote_cached": "公开文件仍在缓存期", "remote_unreachable": "远程不可达或无法验证","passed": "通过", "business_failure": "业务失败", "save_not_persisted": "保存未生效（后台读回不一致）", "automation_failure": "自动化失败",
             "environment_blocked": "环境阻断", "product_confirmation": "待业务确认", "not_suitable": "不适合自动化", "suspended": "挂起（流程/知识缺口）",
             "interrupted": "已中断", "stable": "已稳定", "unstable": "未稳定", "candidate": "待复验",
             "not_run": "未执行", "pending": "待处理", "runnable": "可执行", "running": "执行中",
             "waiting_human": "等待前置", "finished": "已完成", "open": "待回答", "answered": "已回答",
             "closed": "已关闭", "deferred": "待异步审核", "active": "进行中", "delivery_pending": "待交付",
             "completed": "已完成", "waiting": "等待前置"}


def zh(value):
    return STATUS_ZH.get(value, value) if value is not None else "未执行"


def opening(m, metrics, review):
    from collections import Counter
    counts = Counter(zh(c.get('result')) if c.get('work_status') != 'waiting_human' else '等待前置' for c in m['cases'].values())
    conclusion = '本次共 ' + str(len(m['cases'])) + ' 条：' + '，'.join(str(n) + ' 条' + label for label, n in counts.items()) + '。'
    waiting = [cid + '：' + c.get('classification', {}).get('reason', '见审核单') for cid, c in m['cases'].items() if c.get('work_status') == 'waiting_human']
    duplicates = [cid + '：' + c['duplicate_script_warning'] + ' 执行 ' + (c.get('registration') or {}).get('script', '')
                  for cid, c in m['cases'].items() if c.get('duplicate_script_warning')]
    if duplicates:
        waiting.append('重复脚本选择：' + '；'.join(duplicates))
    remote = [cid for cid, c in m['cases'].items() if c.get('work_status') == 'remote_pending']
    if remote:
        waiting.append('公开文件待远程验证：' + '、'.join(remote) + '；见 remote-checks/request.json，不计通过。')
    needs = waiting + ([f"异步审核单 {len(review['items'])} 项；断言建议默认不应用。"] if review['items'] else [])
    if m.get('initial_review_required'):
        interaction_text = f"HTML 审核 {metrics.get('human_review_submissions', 0)} 次，中途提问 {metrics['mid_run_questions']} 次，中途答复 {metrics.get('mid_run_answers', 0)} 次，"
    else:
        interaction_text = f"清单问题 {metrics['checklist_questions']}（入口问题 {metrics.get('entry_question_count', 0)}），清单回答 {metrics['checklist_answers']}，中途提问 {metrics['mid_run_questions']}，"
    metrics_text = (interaction_text + f"计划外人工介入 {metrics['unplanned_interventions']}，会话轮次 {metrics['session_turns']}；"
                    f"脚本实际执行覆盖率 {metrics['script_coverage']['ratio']:.1%}；"
                    f"越权 {metrics['scope_violations']}，泄露 {metrics['leak_hits']}，未审核断言变更 {metrics['unreviewed_assertion_changes']}。")
    metrics_text += (''.join(f"{label} {value / 1000:.1f} 秒。" if value is not None else f"{label} 未记录。"
                               for label, value in [('前置准备', metrics.get('preparation_duration_ms')),
                                                    ('正式执行', metrics.get('execution_duration_ms'))]))
    if metrics.get('timing_unrecorded_attempts'):
        metrics_text += f" 另有 {metrics['timing_unrecorded_attempts']} 次历史执行缺少准备计时，未计入分阶段耗时。"
    if metrics.get('time_to_first_result_seconds') is not None:
        metrics_text += f"首个结果耗时 {metrics['time_to_first_result_seconds']:.1f} 秒。"
    if metrics.get('pass_rate') is not None:
        metrics_text += f"通过率 {metrics['pass_rate']:.1%}。"
    shares = metrics.get('failure_class_shares') or {}
    if shares:
        metrics_text += "失败分类占比：" + "，".join(
            f"{name} {shares.get(name, 0):.1%}" for name in ("environment", "automation", "product", "suspended")) + "。"
    if metrics.get('human_interventions_per_case') is not None:
        metrics_text += f"每条用例人工介入 {metrics['human_interventions_per_case']:.2f}。"
    hit = metrics.get('kb_hit_rate') or {}
    if hit.get('rate') is not None:
        metrics_text += f"知识检索 {hit.get('retrieved', 0)} 条，规格或脚本文本匹配 {hit.get('used', 0)} 条。"
    verified = metrics.get('verified_knowledge_use') or {}
    metrics_text += f"有执行证据的知识使用 {verified.get('count', 0)} 条。"
    if metrics.get('rescued_by_midscene') is not None:
        metrics_text += f"Midscene 挽救 {metrics['rescued_by_midscene']}。"
    smoke = m.get('smoke') or {}
    if smoke:
        rate = smoke.get('pass_rate')
        rate_text = '无结果' if rate is None else f"{rate:.0%}"
        metrics_text += f"冒烟 {smoke.get('status')}，通过率 {rate_text}，门槛 {smoke.get('bar')}。"
    abort = m.get('abort') or {}
    if abort.get('reason') == 'first_result_budget':
        metrics_text += f"已停止：首个结果超过 {abort.get('budget_minutes')} 分钟。"
    if metrics.get('re_explored_known_pages', 0):
        metrics_text += f"流程问题：已知页面重复探索 {metrics['re_explored_known_pages']} 次（re_explored_known_pages）。"
    if metrics.get('exploration_for_missing_controls', 0):
        metrics_text += f"缺控件探索 {metrics['exploration_for_missing_controls']} 次（exploration_for_missing_controls）。"
    if metrics.get('knowledge_injected_tokens', {}).get('count'):
        kb = metrics['knowledge_injected_tokens']
        metrics_text += f"知识注入 token p50/p95：{kb['p50']}/{kb['p95']}（{kb['count']} 条用例）。"
    writeback = m.get('knowledge_writeback', {})
    if writeback.get('count'):
        metrics_text += ' 历史知识写回记录：' + '、'.join(x['name'] for x in writeback.get('added_or_updated', [])) + '；当前入库状态以长期库及审核记录为准。'
    if writeback.get('partial_count'):
        metrics_text += f" 历史记录中有 {writeback['partial_count']} 项成功步骤的部分知识写回。"
    checklist = m.get('questions', {}).get('run-preconditions', {})
    if (checklist.get('entry_count', 0) and checklist.get('memory_answer_count') == checklist.get('entry_count')
            and checklist.get('status') == 'answered' and metrics['checklist_questions'] == 0):
        metrics_text += f" 清单全部来自环境记忆（{checklist['memory_answer_count']} 项），本次 0 问。"
    return [{'title': '结论', 'text': conclusion}, {'title': '需要你处理', 'text': '\n'.join(needs) or '无。'},
            {'title': '流程指标', 'text': metrics_text}]


def waiting_seconds(m):
    entries = [q for q in m["questions"].values()]
    entries += [prior for q in m["questions"].values() for prior in q.get("previous_answers", []) if prior.get("created_at")]
    intervals = sorted((q["created_at"], q.get("answered_at") or now()) for q in entries)
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return sum(elapsed(start, end) for start, end in merged)


def brief_error(attempt, cfg=None):
    return scrub_text(" ".join(attempt.get("errors") or []), cfg)[:180]


def excel_safe(value):
    """Remove terminal escapes and Excel-forbidden controls from presentation only."""
    if not isinstance(value, str):
        return value
    return ILLEGAL_CHARACTERS_RE.sub('', re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', value))


def append_excel(sheet, values):
    sheet.append([excel_safe(value) for value in values])

def cleanup_label(attempt):
    return {True: '已核验', False: '未通过'}.get(attempt.get('cleanup_verified'), '未记录')


def attempt_classification(case, attempt):
    decisions = case.get('classification_history') or ([case['classification']] if case.get('classification') else [])
    return next((row for row in reversed(decisions) if row.get('result') and
                 ((row.get('batch_id') and row['batch_id'] == attempt.get('batch_id')) or
                  (row.get('evidence') and row['evidence'] == attempt.get('evidence')))), {})


def recorded_outcomes(m):
    """Project the last recorded attempt and its review without promoting a current version."""
    view = copy.deepcopy(m)
    from .failures import judge_result
    required = m['config']['execution']['stability_passes']
    for case in view['cases'].values():
        attempts = case.get('attempts') or []
        if not attempts:
            continue
        attempt = attempts[-1]
        decision = attempt_classification(case, attempt)
        result = decision.get('result') or attempt.get('result')
        if not decision and case.get('version') == attempt.get('version') and case.get('remote_status'):
            result = case.get('result') or result
        if result is None:
            continue
        streak = 0
        if result == 'passed':
            for prior in reversed(attempts):
                if prior.get('result') != 'passed' or prior.get('version') != attempt.get('version'):
                    break
                streak += 1
        stability = ('stable' if streak >= required else 'candidate') if result == 'passed' else 'unstable'
        case.update(result=result, version=attempt.get('version'), stage='finished', work_status='finished', stability=stability,
                    pass_streak=streak, classification=decision or None,
                    failure_class=judge_result(result, [])[1] if decision else
                    (judge_result(result, [])[1] or attempt.get('failure_class')))
    return view


def recorded_script(base, attempt):
    script = Path(attempt.get('script') or '')
    if script.parts[:1] != ('runner',) or not attempt.get('evidence') or '..' in script.parts:
        return None
    batch = inside(base, attempt['evidence']).parent
    frozen = batch / 'snapshot/files' / script.relative_to('runner')
    return frozen.relative_to(base).as_posix() if frozen.is_file() else None


def make_report(base, m, writeback=False, *, as_run=False):
    if writeback:
        raise ValueError("Knowledge writeback requires an explicit reviewed selection")
    if as_run:
        m = recorded_outcomes(m)
    from .experience import review as build_review
    review = build_review(base, m, persist=not as_run)
    removed = 0 if as_run else drop_unsafe_artifacts(base / "batches")
    out = base / "reports" / "as-run" if as_run else base / "reports"
    evidence_prefix = '../../' if as_run else '../'
    out.mkdir(parents=True, exist_ok=True)
    for c in m["cases"].values():
        for attempt in c.get("attempts") or []:
            attempt["errors"] = [scrub_text(item, m["config"]) for item in (attempt.get("errors") or [])]
            attempt["attachments"] = [item for item in (attempt.get("attachments") or []) if not unsafe_attachment(item)]
    from .failures import failure_class_for_case
    records = []
    text_request = next((row for row in m['sources'] if row.get('kind')), None)
    for c in m["cases"].values():
        records.append({k: c.get(k) for k in ("case_id", "original_id", "title", "module", "priority",
                       "sheet", "rows", "stage", "work_status", "result", "stability", "pass_streak",
                       "flow_ids", "fixture_ids", "repair_rounds", "attempts", "feedback", "classification", "classification_history", "case_spec", "review_binding", "spec_first_lint", "spec_lint", "remote_status")})
        records[-1]['failure_class'] = failure_class_for_case(c)
        records[-1]['result_label'] = zh(c.get('result'))
        records[-1]['script_binding'] = c.get('script_binding')
        records[-1]['read_back'] = (c.get('attempts') or [{}])[-1].get('read_back')
        records[-1]['duplicate_script_warning'] = c.get('duplicate_script_warning')
        records[-1]['work_status_label'] = zh(c.get('work_status'))
        records[-1]['stability_label'] = zh(c.get('stability'))
        attempt = c["attempts"][-1] if c.get("attempts") else None
        records[-1]["script"] = (c.get("registration") or {}).get("script")
        if as_run:
            records[-1]["script"] = recorded_script(base, attempt) if attempt else None
        classification = c.get("classification") or {}
        records[-1]["reason"] = classification.get("reason", "") if isinstance(classification, dict) else ""
        if c.get("result") == "save_not_persisted":
            records[-1]["reason"] = "保存未生效（后台读回不一致）"
        elif attempt and attempt.get("executed") and c.get("result") == "passed":
            records[-1]["reason"] = brief_error(attempt, m["config"])
        elif attempt and attempt.get("executed") and c.get("result") in {"business_failure", "save_not_persisted", "automation_failure", "interrupted"}:
            records[-1]["reason"] = brief_error(attempt, m["config"]) or records[-1]["reason"]
        elif not records[-1]["reason"] and attempt:
            records[-1]["reason"] = brief_error(attempt, m["config"])
        records[-1]["reason"] = scrub_text(records[-1]["reason"], m["config"])
        evidence = records[-1].get('read_back')
        if evidence and evidence.get('ok'):
            records[-1]["reason"] = (records[-1]["reason"] + "；" if records[-1]["reason"] else "") + "后台读回：" + str(evidence.get("actual", "")) + " ✓"
        records[-1]["media"] = [evidence_prefix + a['redacted_screenshot'] for a in c.get('attempts', []) if a.get('redacted_screenshot')]
        remote = {(entry.get('batch_id'), entry['request']['assertion_id']): entry
                  for entry in m.get('remote_checks', {}).values()
                  if entry.get('request', {}).get('case_id') == c['case_id'] and entry['request'].get('assertion_id')}
        assertion_attempts = []
        for attempt in c.get('attempts', []):
            detail = attempt.get('assertion_evidence')
            if detail is not None:
                detail = [dict(item) for item in detail]
                for item in detail:
                    entry = remote.get((attempt.get('batch_id'), item['id']))
                    if entry and item['status'] == 'remote_pending':
                        item.update(remote_status=entry['status'], remote_request_id=entry['request'].get('id'))
                        if entry.get('history'):
                            observed = entry['history'][-1]
                            item['remote_observation'] = {key: observed.get(key) for key in ('checked_at', 'http_status', 'conditions')}
            assertion_attempts.append({'batch_id': attempt.get('batch_id'), 'evidence': attempt.get('evidence'),
                                       'assertions': detail, 'errors': attempt.get('assertion_evidence_errors', [])})
        records[-1]['assertion_attempts'] = assertion_attempts
        if text_request and c.get('source'):
            source_case = read_json(inside(base, c['source']))
            human_review = m.get('human_review') or {}
            records[-1]['request_verification'] = {
                'expectations': source_case.get('expectations', []),
                'review_decisions': [item for item in human_review.get('decisions', []) if c['case_id'] in item['cases']],
                'pending_review': [item['title'] for item in human_review.get('pending', []) if c['case_id'] in item['cases']],
            }
    m["final_report_at"] = now()
    m["leak_hits"] = run_metrics.leak_scan(base, m["config"])
    flow_metrics = run_metrics.calculate(base, m, m["final_report_at"])
    if not as_run:
        atomic_write(base / "metrics.json", flow_metrics)
    atomic_write(out / "metrics.json", flow_metrics)
    blocks = opening(m, flow_metrics, review)
    opening_md = "\n\n".join("## " + b['title'] + "\n\n" + b['text'] for b in blocks) + "\n"
    (out / 'summary.md').write_text(opening_md, encoding='utf-8')
    s = summary(m)
    metrics = {"elapsed_seconds": elapsed(m["created_at"]), "human_wait_seconds": waiting_seconds(m),
               "first_result_seconds": elapsed(m["created_at"], m["first_result_at"]) if m.get("first_result_at") else None,
               "first_pass_seconds": elapsed(m["created_at"], m["first_pass_at"]) if m.get("first_pass_at") else None,
               "exploration_seconds": sum(a.get("seconds", 0) for a in m["exploration"]),
               "exploration_attempts": len(m["exploration"]),
               "human_questions": len(m["questions"]),
               "cases_with_asset_reuse": sum(bool((c.get("registration") or {}).get("reused_assets")) for c in m["cases"].values()),
               "repair_rounds": sum(c["repair_rounds"] for c in m["cases"].values()),
               **flow_metrics}
    questions = [{k: q.get(k) for k in ("id", "kind", "subject", "prompt", "case_ids", "status", "attempted")}
                 for q in m["questions"].values()]
    payload = {"schema_version": "uia-results.v1", "run_id": m["run_id"], "generated_at": now(),
               "report_mode": "as_run" if as_run else "current",
               "remote_checks": m.get("remote_checks", {}), "opening": blocks, "summary": s, "metrics": metrics, "flow_metrics": flow_metrics, "source": m["sources"], "cases": records,
               "questions": questions, "unresolved_sheets": [x for src in m["sources"] for x in src.get("unresolved_sheets", [])],
               "source_update_required": m.get("source_update_required", False), "delivery_complete": False}
    if text_request:
        payload['text_request'] = {key: text_request[key] for key in ('kind', 'title', 'references', 'historical_actual', 'sha256')}
        if text_request['kind'] == 'bug':
            payload['text_request']['before_fix'] = '修复前未由 Agent 复现'
    diff = {"schema_version": "uia-asset-review.v1", "writeback": "not_applied", "cases": []}
    from .knowledge_review import candidates as knowledge_candidates
    diff['candidates'] = knowledge_candidates(base, m)
    diff['entry_hints'] = {'file': 'assets/playwright-runner/knowledge/entries.yaml',
                           'changes': m.get('entry_hint_changes', {})}
    for c in m["cases"].values():
        if c.get("feedback"):
            file = inside(base, c["feedback"])
            diff["cases"].append({"case_id": c["case_id"], "review": c["feedback"],
                                  "sha256": file_hash(file), "content": read_json(file)})
    atomic_write(out / "asset-review.json", diff)
    atomic_write(out / "results.json", payload)
    wb = Workbook()
    overview = wb.active
    overview.title = "报告开头"
    for block in blocks:
        append_excel(overview, [block['title'], block['text']])
    sheet = wb.create_sheet("逐条结果")
    sheet.title = "逐条结果"
    append_excel(sheet, ["用例ID", "原始ID", "工作表", "源行号", "标题", "优先级", "进度", "结果", "稳定性", "连续成功", "脚本", "执行次数", "最近证据", "原因"])
    for r in records:
        append_excel(sheet, [r["case_id"], r["original_id"], r["sheet"], ",".join(map(str, r["rows"])),
                      r["title"], r["priority"], zh(r["work_status"]), zh(r["result"]), zh(r["stability"]), r["pass_streak"],
                      r["script"], len(r["attempts"]), r["attempts"][-1]["evidence"] if r["attempts"] else "", r.get("reason", "")])
    history_sheet = wb.create_sheet('历史尝试')
    append_excel(history_sheet, ['用例ID', '批次', '原始结果', '证据', '重分类结果', '重分类依据', '最后成功步骤', '失败步骤', '清理核验'])
    for row in records:
        for attempt in row.get('attempts') or []:
            decision = attempt_classification(row, attempt)
            steps = attempt.get('successful_steps') or []
            append_excel(history_sheet, [row['case_id'], attempt.get('batch_id'), zh(attempt.get('result')),
                         attempt.get('evidence'), zh(decision['result']) if decision else '', decision.get('reason', ''),
                         steps[-1] if steps else '未记录', attempt.get('failed_step') or '未记录', cleanup_label(attempt)])
    stats = wb.create_sheet("汇总")
    append_excel(stats, ["指标", "值"])
    for key, value in {**s, **metrics}.items():
        append_excel(stats, [key, json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value])
    qs = wb.create_sheet("人工问题")
    append_excel(qs, ["问题ID", "类型", "问题", "影响用例", "状态", "已尝试"])
    for q in questions:
        append_excel(qs, [q["id"], q["kind"], q["prompt"], ", ".join(q["case_ids"]), zh(q["status"]), "\n".join(q["attempted"])])
    for ws in wb:
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for cell in ws[1]:
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = PatternFill("solid", fgColor="23415A")
        for row in ws.iter_rows():
            for cell in row:
                # Source text must never become an executable spreadsheet formula.
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(64, max(14, max(len(str(c.value or "")) for c in col[:100]) + 2))
    wb.save(out / "results.xlsx")
    escape = lambda value: html.escape(str(value if value is not None else ""))
    def link(ref):
        if not ref:
            return ""
        return '<a href="' + evidence_prefix + quote(str(ref), safe="/") + '">' + escape(ref) + '</a>'
    rows = []
    for r in records:
        source = escape(r['sheet']) + (' · ' + escape(r['original_id']) if text_request else ':' + escape(','.join(map(str, r['rows']))))
        shots = " ".join('<a href="' + escape(ref) + '">截图</a>' for ref in r.get("media") or [])
        rows.append("<tr>" + "".join("<td>" + x + "</td>" for x in [escape(r["case_id"]), source, escape(r["title"]),
                    escape(zh(r["work_status"])), escape(zh(r["result"])), escape(zh(r["stability"])), str(r["pass_streak"]),
                    link(r["script"]), link(r["attempts"][-1]["evidence"] if r["attempts"] else None),
                    escape(r.get("reason", "")) + (" " + shots if shots else "")]) + "</tr>")
    body = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>UI 自动化结果</title><style>body{font:15px system-ui;margin:32px;color:#193348;background:#f5f8fb}
table{border-collapse:collapse;width:100%;background:white}th,td{padding:10px;text-align:left;border:1px solid #dbe4eb;vertical-align:top}
th{background:#23415a;color:white}a{color:#0069a3}pre{white-space:pre-wrap}section{overflow:auto}input{padding:10px;min-width:260px;margin:12px 0}</style>
<h1>UI 自动化结果</h1>"""
    body += ''.join('<h2>' + escape(b['title']) + '</h2><p>' + escape(b['text']).replace('\n', '<br>') + '</p>' for b in blocks)
    if text_request:
        body += '<h2>文字提测来源</h2><p>' + escape(text_request['title']) + '</p>'
        if text_request['references']:
            body += '<ul>' + ''.join('<li>' + escape(ref) + '</li>' for ref in text_request['references']) + '</ul>'
        if text_request['kind'] == 'bug':
            body += '<p>修复前未由 Agent 复现</p>'
            if text_request['historical_actual']:
                body += '<p>提测材料中的历史表现　' + escape(text_request['historical_actual']) + '</p>'
        for record in records:
            info = record.get('request_verification', {})
            body += '<details><summary>' + escape(record['original_id']) + ' · ' + escape(record['title']) + '</summary>'
            for item in info.get('expectations', []):
                body += '<p>来源　' + escape(item['source']) + '<br>原始预期　' + escape(item['quote']) + '</p>'
            for item in info.get('review_decisions', []):
                status = {'confirmed': '已确认', 'edited': '已修改', 'deferred': '暂缓'}[item['status']]
                body += '<p>' + status + '　' + escape(item['value']) + '</p>'
            for title in info.get('pending_review', []):
                body += '<p>待审核　' + escape(title) + '</p>'
            body += '</details>'
    body += '<h2>历史尝试与重分类</h2><ul>'
    for row in records:
        for attempt in row.get('attempts') or []:
            decision = attempt_classification(row, attempt)
            body += '<li>' + escape(row['case_id']) + ' · ' + escape(attempt.get('batch_id')) + ' · ' + escape(zh(attempt.get('result'))) + ' ' + link(attempt.get('evidence'))
            steps = attempt.get('successful_steps') or []
            body += ' · 最后成功步骤 ' + escape(steps[-1] if steps else '未记录')
            body += ' · 失败步骤 ' + escape(attempt.get('failed_step') or '未记录')
            body += ' · 清理核验 ' + cleanup_label(attempt)
            if decision:
                body += ' · 重分类 ' + escape(zh(decision['result']) if decision.get('result') else '结果未记录') + ' ' + escape(decision.get('reason'))
            body += '</li>'
    body += '</ul>'
    body += '<h2>逐断言证据</h2>'
    assertion_labels = {'passed': '通过', 'failed': '失败', 'not_run': '未执行',
                        'invalid': '验证不完整', 'remote_pending': '待远程验证'}
    from .remote_checks import LABELS as remote_labels
    for record in records:
        if not record['assertion_attempts']:
            continue
        body += '<details><summary>' + escape(record['case_id']) + ' · ' + escape(record['title']) + '</summary>'
        for attempt in reversed(record['assertion_attempts']):
            body += '<p>' + escape(attempt['batch_id']) + ' · ' + link(attempt['evidence']) + '</p>'
            for problem in attempt['errors']:
                body += '<p>验证不完整 · ' + escape(problem) + '</p>'
            if attempt['assertions'] is None:
                body += '<p>逐断言证据未记录</p>'
                continue
            body += '<ol>'
            for item in attempt['assertions']:
                label = remote_labels.get(item.get('remote_status'), assertion_labels[item['status']])
                methods = '\n'.join(method['method'] for method in item['reviewed_methods']) or '未记录'
                observed = item.get('remote_observation') or item['observations']
                checks = [' '.join(part for part in (check['target'], check['operation'], check.get('expected', '')) if part)
                          for check in item.get('spec_checks', [])]
                body += ('<li><strong>' + escape(item['id']) + ' · ' + escape(label) + '</strong>' +
                         '<p>' + ('审核答复补充的预期' if item.get('expectation_origin') == 'human_review' else '原始预期') +
                         '　' + escape(item['original_expectation']) + '</p>' +
                         '<p>审核验法　' + escape(methods) + '</p>' +
                         ('<p>规格检查　' + escape('；'.join(checks)) + '</p>' if checks else '') +
                         '<p>本次观察　' + (escape(json.dumps(observed, ensure_ascii=False)) if observed else '未记录') + '</p></li>')
            body += '</ol>'
        body += '</details>'
    passes = m["config"]["execution"].get("stability_passes", 2)
    standard = "每日交付：同版本一次成功即可。" if passes == 1 else "夜间回归：同一版本独立运行两次成功。"
    body += "<p>运行：" + escape(m["run_id"]) + "；源用例总数：" + str(s["total"]) + "。稳定标准：" + standard + "</p>"
    body += "<p>仅保留白名单控件文字的脱敏弹窗截图可进入报告；原始截图、trace 和页面快照不进入报告或脚本包。本轮已清除快照文件 " + str(removed) + " 个。</p>"
    body += "<p>执行覆盖率：{:.1%}；已执行用例通过率：{:.1%}；全部用例稳定率：{:.1%}。</p>".format(s["execution_coverage"], s["pass_rate"], s["stability_rate"])
    if as_run:
        body += '<p>历史报告依据已记录的批次与更正生成。脚本版本变更可在当前运行状态中查看。</p>'
    body += '<p><a href="results.json">JSON</a> · <a href="results.xlsx">Excel</a>'
    if not as_run:
        body += ' · <a href="scripts.zip">脚本工程</a>'
    body += ' · <a href="asset-review.json">资产回写候选</a></p>'
    if diff['candidates']:
        body += '<section><h2>知识候选</h2><p>逐项选择后导出审核文件。只有批准的内容会在运行写回命令时更新共享库。</p>'
        for item in diff['candidates']:
            body += '<article class="knowledge-candidate" data-id="' + html.escape(str(item['id']), quote=True) + '" data-version="' + html.escape(str(item['version']), quote=True) + '">'
            body += '<h3>' + escape(item['id']) + ' · ' + escape(item['kind']) + '</h3>'
            body += '<p>适用范围：' + escape(str(item['scope'])) + '；证据：' + escape(', '.join(item['evidence'])) + '</p>'
            body += '<details><summary>查看修改前后</summary><pre>' + escape(json.dumps({'before': item.get('before'), 'after': item['after']}, ensure_ascii=False, indent=2)) + '</pre></details>'
            body += '<label>决定 <select><option value="defer">暂缓</option><option value="approve">批准</option><option value="reject">拒绝</option></select></label></article>'
        body += '<button id="export-knowledge">导出知识审核 JSON</button></section>'
        body += '<script>document.getElementById("export-knowledge").onclick=()=>{const items=[...document.querySelectorAll(".knowledge-candidate")].map(e=>({id:e.dataset.id,version:e.dataset.version,decision:e.querySelector("select").value}));const data={schema_version:"uia-knowledge-review.v1",run_id:' + json.dumps(m['run_id']) + ',items};const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"}));a.download=data.run_id+"-knowledge-review.json";a.click();URL.revokeObjectURL(a.href)};</script>'
    body += '<label>筛选 <input id="filter" placeholder="用例 ID、标题或状态"></label><section><table><thead><tr>'
    body += "".join("<th>" + h + "</th>" for h in ("用例ID", "来源", "标题", "进度", "结果", "稳定性", "连续成功", "脚本", "证据", "原因"))
    body += "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></section><h2>耗时与人工问题</h2><pre>"
    previews = sorted((base / "batches").glob("*/preview.json"), key=lambda item: item.stat().st_mtime)
    review = base / "state/heal-review.json"
    memory = base / "state/knowledge/llms-txt.json"
    extra = {}
    if previews:
        extra["preview"] = read_json(previews[-1])
    if review.is_file():
        extra["heal_review"] = read_json(review)
    if memory.is_file():
        remembered = read_json(memory)
        extra["locator_memory"] = {"environment": remembered.get("environment"), "updated_at": remembered.get("updated_at"),
                                   "written_back": [key for key, entry in remembered.get("entries", {}).items() if entry.get("last_success")]}
    body += escape(json.dumps({"metrics": metrics, "questions": questions, "snapshots_removed": removed, **extra}, ensure_ascii=False, indent=2)) + "</pre>"
    body += '<script>document.getElementById("filter").addEventListener("input",e=>document.querySelectorAll("tbody tr").forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(e.target.value.toLowerCase())))</script></html>'
    (out / "index.html").write_text(scrub_text(body, m["config"]), encoding="utf-8")
    runner = base / "runner"
    script_package = None
    if runner.exists() and not as_run:
        with zipfile.ZipFile(out / "scripts.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
            from .bindings import case_bindings
            archive.writestr("runner/cases.json", scrub_text(json.dumps(case_bindings(base, m), ensure_ascii=False), m["config"]))
            overlay = base / 'state/page-map-overlay.yaml'
            if overlay.is_file():
                archive.writestr('runner/state/page-map-overlay.yaml', scrub_text(overlay.read_text(encoding='utf-8'), m['config']))
                archive.writestr('runner/state/OVERLAY-README.txt',
                                 'The runner automatically reads state/page-map-overlay.yaml.\n')
            entries_overlay = base / 'state/entries-overlay.yaml'
            if entries_overlay.is_file():
                archive.writestr('runner/state/entries-overlay.yaml', scrub_text(entries_overlay.read_text(encoding='utf-8'), m['config']))
                archive.writestr('runner/state/ENTRIES-README.txt',
                                 'The runner automatically reads state/entries-overlay.yaml.\n')
            archive.writestr('runner/batch-knowledge/README.txt',
                             'Set UIA_BATCH_KNOWLEDGE_ID to a batch ID to load its frozen shared and run-local knowledge.\n')
            for batch in m.get('batches', []):
                directory = inside(base, batch['directory'])
                for filename in ('page-map-overlay.yaml', 'entries-overlay.yaml'):
                    snapshot = directory / filename
                    if snapshot.is_file():
                        archive.writestr('runner/batch-knowledge/' + batch['id'] + '/' + filename,
                                         scrub_text(snapshot.read_text(encoding='utf-8'), m['config']))
                for filename in ('page-map.yaml', 'entries.yaml'):
                    snapshot = directory / 'snapshot/knowledge' / filename
                    if snapshot.is_file():
                        archive.writestr('runner/batch-knowledge/' + batch['id'] + '/shared/' + filename,
                                         scrub_text(snapshot.read_text(encoding='utf-8'), m['config']))
            protected = {Path(m["config_path"]).resolve()}
            if m["config"].get("auth", {}).get("storage_state"):
                protected.add(Path(m["config"]["auth"]["storage_state"]).resolve())
            credential = m["config"].get("auth", {}).get("credentials_file")
            if credential:
                protected.add(Path(credential).resolve())
            if m["config"].get("auth", {}).get("storage_state"):
                protected.add(Path(m["config"]["auth"]["storage_state"] + ".meta.json").resolve())
            declared = set()
            for case in m.get('cases', {}).values():
                if case.get('case_spec'):
                    spec = read_yaml(inside(base, case['case_spec']))
                    declared.update(spec.get('file_dependencies', []))
            for file in runner.rglob("*"):
                rel = file.relative_to(runner)
                if not file.is_file() or file.is_symlink() or file.resolve() in protected or any(part in {"node_modules", "results", ".auth", "test-results", "playwright-report"} for part in rel.parts):
                    continue
                if file.name.startswith(".env") or file.name in {"cases.json", "auth.json", "storage-state.json", "error-context.md", "trace.zip", "playwright-results.json"} or ".local." in file.name:
                    continue
                if str(rel) in declared:
                    content = file.read_bytes()
                    try:
                        decoded = content.decode('utf-8')
                    except UnicodeDecodeError:
                        decoded = None
                    if decoded is not None and scrub_text(decoded, m['config']) != decoded:
                        raise ValueError('Declared test file contains sensitive data')
                    archive.writestr('runner/' + str(rel), content)
                    continue
                if file.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".webm"} or any(part in {"playwright-report", "traces", "test-results"} for part in rel.parts):
                    continue
                if file.suffix in {".ts", ".js", ".mjs", ".json", ".md", ".markdown", ".pac", ".txt", ".yaml", ".yml"}:
                    overlay = base / "state/knowledge/llms-txt.json" if str(rel) == "knowledge/llms-txt.json" else None
                    content = overlay.read_text(encoding="utf-8") if overlay and overlay.is_file() else file.read_text(encoding="utf-8")
                    archive.writestr("runner/" + str(rel), scrub_text(content, m["config"]))
        script_package = str((out / "scripts.zip").relative_to(base))
    m["delivery"] = {"json": str((out / "results.json").relative_to(base)),
                     "html": str((out / "index.html").relative_to(base)),
                     "xlsx": str((out / "results.xlsx").relative_to(base)),
                     "asset_diff": str((out / "asset-review.json").relative_to(base)),
                     "scripts": script_package, "generated_at": now()}
    from .workflow import pending_feedback_cases
    payload["delivery_complete"] = (bool(records) and all(c["work_status"] == "finished" for c in m["cases"].values())
                                    and not payload["unresolved_sheets"] and (as_run or bool(script_package))
                                    and (as_run or not payload["source_update_required"])
                                    and not any(q["status"] == "open" for q in m["questions"].values())
                                    and not (m.get('human_review') or {}).get('pending')
                                    and (as_run or not pending_feedback_cases(m)))
    payload = json.loads(scrub_text(json.dumps(payload, ensure_ascii=False), m["config"]))
    atomic_write(out / "results.json", payload)
    return {"artifacts": m["delivery"], "summary": s, "delivery_complete": payload["delivery_complete"]}
