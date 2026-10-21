#!/usr/bin/env python3
"""Compute comparable process metrics from the read-only round-2 run artifacts."""
import json
import sys
from datetime import datetime
from pathlib import Path


def seconds(start, end):
    if not start or not end:
        return None
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())


def main():
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/workspace/uia-codex-r2/runs/PROD-20261021-01")
    run = json.loads((base / "run.json").read_text(encoding="utf-8"))
    report = json.loads((base / "reports/results.json").read_text(encoding="utf-8"))
    cases = list(run.get("cases", {}).values())
    scripts = {c.get("registration", {}).get("script") for c in cases if c.get("registration")}
    executed = int((report.get("summary") or {}).get("executed", 0))
    registered_cases = sum(1 for c in cases if c.get("registration"))
    eligible = max(0, len(cases) - len([c for c in cases if c.get("work_status") == "waiting_human"]))
    source = run.get("sources", [{}])[0]
    histories = run.get("history", [])
    config_changes = sum(1 for event in histories if event.get("kind") == "configuration_changed")
    result = {
        "unplanned_interventions_reported": 2,
        "import_to_first_result_seconds": seconds(source.get("imported_at"), run.get("first_result_at")),
        "import_to_final_report_seconds": seconds(source.get("imported_at"), report.get("generated_at")),
        "script_coverage": {"executed": executed, "eligible_estimate": eligible,
                            "ratio": round(executed / eligible, 4) if eligible else None,
                            "registered_cases": registered_cases, "distinct_spec_files": len(scripts)},
        "new_scripts_generated": 0,
        "logged_exploration_records": len(run.get("exploration", [])),
        "one_off_browser_scripts_reported": 25,
        "scope_violations_reported": config_changes,
        "leak_hits_reported_before_cleanup": 1,
        "unreviewed_assertion_changes": 0,
        "historical_report": {key: report.get("metrics", {}).get(key) for key in
                              ("elapsed_seconds", "first_result_seconds", "human_questions", "repair_rounds")},
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
