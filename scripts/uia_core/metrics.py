from __future__ import annotations

import re
import difflib
from pathlib import Path

from .common import elapsed, now

TOKEN = re.compile(r"(?i)(?:bearer\s+[a-z0-9._-]{12,}|eyJ[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\.[a-z0-9_-]{8,})")
QUERY_SECRET = re.compile(r"(?i)(?:access_token|refresh_token|password|cookie|authorization)=([^&\s\"']+)")
BUSINESS_LABEL = re.compile(r"businessAssertion\(\s*(['\"])(.*?)\1", re.S)
MATCHER = re.compile(r"\.(to(?:Be|Equal|Have|Contain|Match|Start|End|Include)[A-Za-z]*)\s*\(([^)]{0,500})\)", re.S)
STRING_LITERAL = re.compile(r"(['\"])(.*?)(?<!\\)\1", re.S)


def assertion_signature(source):
    text = Path(source).read_text(encoding="utf-8") if isinstance(source, (str, Path)) and Path(source).is_file() else str(source)
    labels = BUSINESS_LABEL.findall(text)
    matchers = []
    for method, argument in MATCHER.findall(text):
        values = [value for _quote, value in STRING_LITERAL.findall(argument)]
        matchers.append((method, values))
    return {"labels": sorted(label for _quote, label in labels),
            "matchers": sorted([method, values] for method, values in matchers)}


def locator_wait_only(before, after):
    """Accept a repair only when assertions are unchanged and edited lines are locators/waits."""
    old = Path(before).read_text(encoding="utf-8")
    new = Path(after).read_text(encoding="utf-8")
    if assertion_signature(old) != assertion_signature(new):
        return False
    allowed = re.compile(r"(?:locator|getBy|frameLocator|waitFor|waitUntil|timeout|waitForLoadState|waitForURL)", re.I)
    changed = [line[1:].strip() for line in difflib.ndiff(old.splitlines(), new.splitlines())
               if line.startswith(("+ ", "- "))]
    return bool(changed) and all(allowed.search(line) for line in changed)


def _eligible(case):
    if case.get("work_status") == "waiting_human":
        return False
    intent = case.get("intent_data") or {}
    automation = intent.get("automation", {}) if isinstance(intent, dict) else {}
    if automation.get("suitable") is False or case.get("result") == "not_suitable":
        return False
    return True


def leak_scan(base, cfg):
    """Scan run-owned text outputs. Never traverse the shared runner or private auth directory."""
    hits = []
    excluded = {"runner", ".auth", "node_modules"}
    for file in Path(base).rglob("*"):
        if file.is_symlink() or not file.is_file():
            continue
        try:
            relative = file.relative_to(base)
        except ValueError:
            continue
        if any(part in excluded for part in relative.parts) or file.suffix.lower() in {".png", ".jpg", ".jpeg", ".zip", ".webm"}:
            continue
        try:
            value = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if TOKEN.search(value):
            hits.append({"file": str(relative), "category": "token_pattern"})
        if QUERY_SECRET.search(value):
            hits.append({"file": str(relative), "category": "credential_parameter"})
        credential = cfg.get("auth", {}).get("credentials_file")
        if credential and Path(credential).is_file():
            try:
                import json
                secrets = json.loads(Path(credential).read_text(encoding="utf-8"))
                for key, secret in secrets.items():
                    if isinstance(secret, str) and secret and secret in value:
                        hits.append({"file": str(relative), "category": "credential_value"})
                        break
            except (OSError, ValueError):
                pass
    return hits


def knowledge_hit_rate(base, m):
    """Share of retrieved knowledge entries that the case spec or script actually references."""
    path = Path(base) / (m.get("knowledge_match") or {}).get("file", "knowledge-match.json")
    empty = {"retrieved": 0, "used": 0, "rate": None}
    if not path.is_file():
        return empty
    try:
        import json
        matched = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return empty
    retrieved = used = 0
    for cid, selected in (matched.get("matched") or {}).items():
        if not isinstance(selected, dict):
            continue
        case = (m.get("cases") or {}).get(cid) or {}
        blobs = []
        spec_rel = case.get("case_spec")
        if spec_rel and (Path(base) / spec_rel).is_file():
            try:
                blobs.append((Path(base) / spec_rel).read_text(encoding="utf-8"))
            except OSError:
                pass
        script = (case.get("registration") or {}).get("script")
        if script and (Path(base) / script).is_file():
            try:
                body = (Path(base) / script).read_text(encoding="utf-8")
            except OSError:
                body = ""
            blobs.append(re.sub(r"^// Knowledge targets:.*$", "", body, flags=re.M))
        explicit = {item for item in (case.get("knowledge_used") or []) if isinstance(item, str)}
        blob = "\n".join(blobs)
        for kid, item in selected.items():
            retrieved += 1
            if kid in explicit:
                used += 1
                continue
            needles = [kid]
            if isinstance(item, dict):
                needles.extend(value for key in ("id", "name", "page", "target", "label")
                               if isinstance((value := item.get(key)), str) and value)
            if any(needle and needle in blob for needle in needles):
                used += 1
    return {"retrieved": retrieved, "used": used, "rate": (used / retrieved) if retrieved else None}


def exploration_counts(m):
    known_count = 0
    missing_count = 0
    for item in m.get('exploration', []):
        if 'missing_targets' in item or 'exploration_for_missing_controls' in item:
            known_count += bool(item.get('re_explored'))
            missing_count += bool(item.get('exploration_for_missing_controls') or item.get('missing_targets'))
        elif item.get('purpose'):
            from .knowledge import exploration_knowledge
            state = exploration_knowledge(item.get('purpose'), item.get('entry'))
            known_count += bool(state['re_explored'])
            missing_count += bool(state['exploration_for_missing_controls'])
        else:
            known_count += bool(item.get('re_explored'))
    durations = [attempt['duration_ms'] for case in m.get('cases', {}).values()
                 for attempt in case.get('explore_attempts', [])
                 if type(attempt.get('duration_ms')) is int and attempt['duration_ms'] >= 0]
    if not durations:
        durations = [item['duration_ms'] for item in m.get('exploration', [])
                     if type(item.get('duration_ms')) is int and item['duration_ms'] >= 0]
    ordered = sorted(durations)
    percentile = lambda p: ordered[max(0, min(len(ordered) - 1, int((len(ordered) - 1) * p + .5)))] if ordered else None
    return {'re_explored_known_pages': known_count,
            'exploration_for_missing_controls': missing_count,
            'exploration_duration_ms': {'count': len(ordered), 'total': sum(ordered),
                                        'p50': percentile(.50), 'p95': percentile(.95)}}


def calculate(base, m, final_report_at=None):
    cases = list(m.get("cases", {}).values())
    eligible = [case for case in cases if _eligible(case)]
    scripted = [case for case in eligible if case.get("registration")]
    executed = [case for case in scripted if any(a.get("executed") for a in case.get("attempts", []))]
    imported_at = next((source.get("imported_at") for source in m.get("sources", []) if source.get("imported_at")), None)
    first_at = m.get("first_result_at")
    review_at = final_report_at or m.get("final_report_at")
    prior_specs = set(m.get("initial_spec_files", []))
    current_specs = {case.get("registration", {}).get("script") for case in cases if case.get("registration")}
    new_scripts = sorted(str(item) for item in current_specs - prior_specs)
    assertion_changes = 0
    for relative, original in (m.get("initial_assertion_signatures") or {}).items():
        file = Path(base) / relative
        if file.is_file() and assertion_signature(file) != original:
            assertion_changes += 1
    exploration_metric = exploration_counts(m)
    explored_known = exploration_metric['re_explored_known_pages']
    missing_control_explorations = exploration_metric['exploration_for_missing_controls']
    match_path = Path(base) / (m.get('knowledge_match') or {}).get('file', 'knowledge-match.json')
    injected = []
    if match_path.is_file():
        try:
            import json
            matched = json.loads(match_path.read_text(encoding='utf-8'))
            injected = [int(row.get('used_tokens', 0)) for row in matched.get('budgets', {}).values()]
        except (OSError, ValueError, TypeError):
            injected = []
    def percentile(values, p):
        if not values: return None
        ordered = sorted(values); index = max(0, min(len(ordered)-1, int((len(ordered)-1)*p + .5)))
        return ordered[index]
    from .failures import class_shares
    classes = class_shares(cases)
    executed_cases = [case for case in cases if any(attempt.get("executed") for attempt in case.get("attempts", []))]
    passed_cases = [case for case in executed_cases if case.get("result") == "passed"]
    interventions = (sum(x.get("kind") == "checklist_answer" for x in m.get("interaction_events", []))
                     + sum(x.get("kind") == "mid_run_question" for x in m.get("interaction_events", []))
                     + sum(x.get("kind") == "session_turn" and x.get("category") == "计划外" for x in m.get("interaction_events", [])))
    hit = knowledge_hit_rate(base, m)
    rescued = m.get("rescued_by_midscene", 0)
    rescued_count = rescued if type(rescued) is int else 0
    first_start = imported_at or m.get("created_at")
    first_lints = [c["spec_first_lint"] for c in cases if c.get("spec_first_lint") and c["spec_first_lint"].get("automatable") != "manual"]
    first_passed = sum(bool(row.get("passed")) for row in first_lints)
    return {
        "spec_lint_first_pass": {"passed": first_passed, "automatable": len(first_lints),
                                 "rate": first_passed / len(first_lints) if first_lints else None},
        "unplanned_interventions": sum(x.get('kind') == 'session_turn' and x.get('category') == '计划外' for x in m.get('interaction_events', [])),
        "session_turns": sum(x.get('kind') == 'session_turn' for x in m.get('interaction_events', [])),
        "checklist_answers": sum(x.get('kind') == 'checklist_answer' for x in m.get('interaction_events', [])),
        "checklist_questions": m.get('checklist_question_count', 0),
        "entry_question_count": m.get('entry_question_count', 0),
        "mid_run_questions": sum(x.get('kind') == 'mid_run_question' for x in m.get('interaction_events', [])),
        "time_to_first_result_seconds": elapsed(first_start, first_at) if first_start and first_at else None,
        "import_to_first_result_seconds": elapsed(imported_at, first_at) if imported_at and first_at else None,
        "pass_rate": (len(passed_cases) / len(executed_cases)) if executed_cases else None,
        "import_to_final_report_seconds": elapsed(imported_at, review_at) if imported_at and review_at else None,
        "script_coverage": {"scripted": len(scripted), "executed": len(executed), "eligible": len(eligible),
                            "ratio": len(executed) / len(eligible) if eligible else 0.0},
        "new_scripts_generated": len(new_scripts), "new_script_paths": new_scripts,
        "re_explored_known_pages": explored_known,
        "exploration_for_missing_controls": missing_control_explorations,
        "exploration_duration_ms": exploration_metric['exploration_duration_ms'],
        "failure_class_counts": classes["counts"],
        "failure_class_shares": classes["shares"],
        "human_interventions": interventions,
        "human_interventions_per_case": (interventions / len(cases)) if cases else None,
        "kb_hit_rate": hit,
        "knowledge_injected_tokens": {"count": len(injected), "p50": percentile(injected, .50), "p95": percentile(injected, .95)},
        "rescued_by_midscene": rescued_count,
        "scope_violations": int(m.get("scope_violations", 0)),
        "leak_hits": len(m.get("leak_hits", [])),
        "unreviewed_assertion_changes": max(int(m.get("unreviewed_assertion_changes", 0)), assertion_changes),
        "rescued_by_midscene": sum(int(a.get("rescued_by_midscene") or 0) for c in cases for a in (c.get("attempts") or [])) + int(m.get("rescued_by_midscene") or 0),
        "missing_controls": sum(len(c.get("missing_controls") or []) for c in cases),
        "remote_checks": {status: sum(r.get("active", True) and r["status"] == status for r in m.get("remote_checks", {}).values()) for status in ("pending", "pass", "fail", "still-cached", "unreachable")},
        "measured_at": now(),
    }
