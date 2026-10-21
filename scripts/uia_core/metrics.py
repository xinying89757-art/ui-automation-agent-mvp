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
    explored_known = sum(1 for item in m.get("exploration", []) if item.get("known_page") or item.get("re_explored"))
    first_lints = [c["spec_first_lint"] for c in cases if c.get("spec_first_lint") and c["spec_first_lint"].get("automatable") != "manual"]
    first_passed = sum(bool(row.get("passed")) for row in first_lints)
    return {
        "spec_lint_first_pass": {"passed": first_passed, "automatable": len(first_lints),
                                 "rate": first_passed / len(first_lints) if first_lints else None},
        "unplanned_interventions": sum(x.get('kind') == 'session_turn' and x.get('category') == '计划外' for x in m.get('interaction_events', [])),
        "session_turns": sum(x.get('kind') == 'session_turn' for x in m.get('interaction_events', [])),
        "checklist_answers": sum(x.get('kind') == 'checklist_answer' for x in m.get('interaction_events', [])),
        "checklist_questions": m.get('checklist_question_count', 0),
        "mid_run_questions": sum(x.get('kind') == 'mid_run_question' for x in m.get('interaction_events', [])),
        "import_to_first_result_seconds": elapsed(imported_at, first_at) if imported_at and first_at else None,
        "import_to_final_report_seconds": elapsed(imported_at, review_at) if imported_at and review_at else None,
        "script_coverage": {"scripted": len(scripted), "executed": len(executed), "eligible": len(eligible),
                            "ratio": len(executed) / len(eligible) if eligible else 0.0},
        "new_scripts_generated": len(new_scripts), "new_script_paths": new_scripts,
        "re_explored_known_pages": explored_known,
        "scope_violations": int(m.get("scope_violations", 0)),
        "leak_hits": len(m.get("leak_hits", [])),
        "unreviewed_assertion_changes": max(int(m.get("unreviewed_assertion_changes", 0)), assertion_changes),
        "measured_at": now(),
    }
