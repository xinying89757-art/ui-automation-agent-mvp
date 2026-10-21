from __future__ import annotations

import copy
import re
import os
import shutil
from pathlib import Path

from .assets import make_plan
from .checks import case_errors, intent_errors
from .common import (ROOT, UiaError, atomic_write, config, digest, elapsed, event,
                     execution_config_fingerprint, env_fingerprints, file_hash, inside, now, read_json,
                     read_yaml, require, reset_case, safe_id, summary)
from .workbooks import extract


def run_config(base, path):
    cfg = config(path)
    if cfg.get("network", {}).get("mode") == "pac" and not cfg["network"].get("pac_file"):
        pac = base / "runner/network/gray.pac"
        if pac.is_file():
            from .profiles import connection_settings
            cfg["network"]["pac_file"] = str(pac.resolve())
            cfg["connection_fingerprint"] = digest(connection_settings(cfg))
    return cfg


def init(run_id, config_path):
    require(run_id == safe_id(run_id), "Run ID must be a safe directory name")
    base = ROOT / "runs" / run_id
    require(not (base / "run.json").exists(), "Run already exists; use status/next to resume")
    cfg = run_config(base, config_path)
    m = {"schema_version": "uia-run.v1", "run_id": run_id, "created_at": now(),
         "updated_at": now(), "config_path": str(Path(config_path).resolve()), "config": cfg,
         "config_hash": execution_config_fingerprint(cfg), "sources": [], "identity_map": {},
         "cases": {}, "archived_cases": [], "questions": {}, "exploration": [],
         "batches": [], "active_batch": None, "contaminated_fixtures": {},
         "history": [], "delivery": {}, "preflight": None, "status": "active"}
    event(m, "initialized")
    atomic_write(base / "run.json", m)
    return {"run": str(base / "run.json"), "next": "import", "status": "not_executed"}


def question(m, kind, subject, prompt, case_ids, key=None, attempted=None, sheet=None, reopen=False):
    require(all(cid in m["cases"] for cid in case_ids), "Question refers to an unknown case")
    require(kind != "column_mapping" or sheet, "A column mapping question needs its source sheet")
    key = key or digest([kind, subject, sheet])[:16]
    existing = m["questions"].get(key)
    if existing and existing["status"] == "answered" and not reopen:
        return existing
    if existing and existing["status"] in {"answered", "closed"}:
        existing.setdefault("previous_answers", []).append({k: existing.get(k) for k in ("created_at", "answer", "answered_at", "wait_seconds")})
        existing.update(status="open", created_at=now(), prompt=prompt)
        existing.pop("answered_at", None)
    q = existing or {"id": key, "kind": kind, "subject": subject, "prompt": prompt,
                     "case_ids": [], "attempted": [], "created_at": now(), "status": "open",
                     "resume_states": {}, "sheet": sheet}
    q["attempted"] = list(dict.fromkeys(q["attempted"] + (attempted or [])))
    for cid in case_ids:
        if cid not in q["case_ids"]:
            q["case_ids"].append(cid)
            q["resume_states"][cid] = m["cases"][cid]["work_status"]
        c = m["cases"][cid]
        if c["work_status"] != "finished":
            c["work_status"] = "waiting_human"
    m["questions"][key] = q
    event(m, "question_queued", question_id=key, case_ids=case_ids)
    return q


def answer(m, qid, value, base):
    require(qid in m["questions"], "Unknown question")
    q = m["questions"][qid]
    require(q["status"] == "open", "Question already answered")
    require(q["kind"] != "login" or not isinstance(value, dict) or
            not any(k in value for k in ("password", "token", "cookie")), "Answer with a login-state reference, not a secret")
    if q["kind"] == "preconditions":
        require(isinstance(value, dict) and set(value) <= {"available", "unavailable"},
                "Answer with available and unavailable precondition ids")
        for key in ("available", "unavailable"):
            require(isinstance(value.get(key, []), list) and all(isinstance(item, str) for item in value.get(key, [])),
                    "Precondition answer lists must be string arrays")
        q.update(status="answered", answer=value, answered_at=now(), wait_seconds=elapsed(q["created_at"]))
        from .preconditions import apply_precondition_answer
        apply_precondition_answer(m, q)
        event(m, "question_answered", question_id=qid)
        waiting = [cid for cid in q["case_ids"] if m["cases"][cid]["work_status"] == "waiting_human"]
        return {"question_id": qid, "next": "next", "waiting": waiting}
    if q["kind"] == "demo":
        require(isinstance(value, dict) and value.get("script"), "Demo answer requires a script path")
        src = Path(value["script"]).expanduser().resolve()
        require(src.is_file() and src.suffix in {".ts", ".js", ".mjs"}, "Provide a Playwright action script, not a Trace")
        dest = base / "demonstrations" / qid / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        dest.chmod(0o600)
        value = {"script": str(dest.relative_to(base)), "sha256": file_hash(dest), "replay": "pending"}
    q.update(status="answered", answer=value, answered_at=now(), wait_seconds=elapsed(q["created_at"]))
    for cid in q["case_ids"]:
        c = m["cases"][cid]
        others = [x for x in m["questions"].values() if x["status"] == "open" and cid in x["case_ids"]]
        if not others and c["work_status"] != "finished":
            c["work_status"] = "runnable" if c.get("registration") and c["stage"] == "execution" and q["kind"] != "demo" else "pending"
            if q["kind"] == "demo":
                c["stage"] = "discovery"
    if q["kind"] in {"login", "environment"}:
        m["preflight"] = None
    event(m, "question_answered", question_id=qid)
    return {"question_id": qid, "next": "next", "replay_required": q["kind"] == "demo"}


def import_excel(base, m, excel, mapping=None):
    require(not m.get("active_batch"), "Finish or recover the active batch before importing")
    mappings = copy.deepcopy(mapping or {})
    for q in m["questions"].values():
        if q["kind"] == "column_mapping" and q["status"] == "answered":
            require(isinstance(q["answer"], dict), "Column mapping answer must be a JSON object")
            mappings[q["sheet"]] = q["answer"]
    source = Path(excel).resolve()
    require(source.is_file(), "Source workbook does not exist")
    parsed = extract(source, mappings)
    # Keep one active Excel per run. Importing a changed version reconciles by stable identity.
    old = m["cases"]
    new, used = {}, set()
    counts = {"added": 0, "changed": 0, "unchanged": 0, "archived": 0}
    for raw in parsed["cases"]:
        identity = raw["identity_key"]
        cid = m["identity_map"].get(identity, raw["suggested_id"])
        reserved = {v for k, v in m["identity_map"].items() if k != identity}
        if cid in used or cid in reserved:
            cid += "--" + digest(identity)[:8]
        used.add(cid)
        m["identity_map"][identity] = cid
        raw["case_id"] = cid
        folder = Path("cases") / cid
        source_path = folder / "source.json"
        atomic_write(base / source_path, raw)
        if cid in old:
            c = old[cid]
            changed = c["source_hash"] != raw["content_hash"]
            counts["changed" if changed else "unchanged"] += 1
            if changed:
                reset_case(c, "source_case_changed")
                c["registration"] = None
                c["intent_hash"] = None
                c["plan_hash"] = None
                c["repair_rounds"] = 0
        else:
            counts["added"] += 1
            c = {"case_id": cid, "stage": "intent", "work_status": "pending", "result": None,
                 "stability": "not_run", "pass_streak": 0, "version": None,
                 "flow_ids": ["case:" + cid], "fixture_ids": [], "isolated": False,
                 "registration": None, "intent_hash": None, "plan_hash": None,
                 "attempts": [], "repair_rounds": 0, "feedback": None,
                 "intent": str(folder / "automation-intent.yaml"),
                 "reuse_plan": str(folder / "reuse-plan.slim.yaml")}
        c.update(source=str(source_path), source_hash=raw["content_hash"], original_id=raw["original_id"],
                 title=raw["title"], module=raw["module"], priority=raw["priority"],
                 sheet=raw["sheet"], rows=raw["rows"])
        new[cid] = c
    incomplete_sheets = {g["sheet"] for g in parsed["gaps"]}
    for cid, c in old.items():
        if cid not in new:
            if c["sheet"] in incomplete_sheets:
                new[cid] = c  # Unreadable sheets must not silently delete previously known cases.
            else:
                m["archived_cases"].append({"at": now(), "reason": "removed_from_source", "case": c})
                counts["archived"] += 1
    m["cases"] = new
    if not new and not parsed["gaps"]:
        question(m, "product", "no_source_cases", "No source cases were identified. Confirm the workbook and intended sheets.", [], reopen=True)
    elif new:
        for q in m["questions"].values():
            if q["subject"] == "no_source_cases" and q["status"] == "open":
                q.update(status="closed", answered_at=now())
    for gap in parsed["gaps"]:
        affected = [c["case_id"] for c in new.values() if c["sheet"] == gap["sheet"]]
        question(m, "column_mapping", gap["sheet"], gap["prompt"], affected,
                 attempted=gap["errors"], sheet=gap["sheet"], reopen=True)
    for q in m["questions"].values():
        q["case_ids"] = [cid for cid in q["case_ids"] if cid in new]
    m["sources"] = [{"path": str(source), "sha256": file_hash(source), "sheets": parsed["sheets"],
                     "mapping": mappings, "imported_at": now(), "unresolved_sheets": sorted(incomplete_sheets)}]
    m["source_update_required"] = False
    m["delivery"] = {}
    event(m, "excel_imported", **counts)
    from .preconditions import sync_preconditions
    preconditions = sync_preconditions(base, m)
    return {**counts, "total": len(new), "unresolved_sheets": sorted(incomplete_sheets),
            "source_rows_preserved": True, "preconditions": preconditions, "next": "next"}


def bind(m, case_ids, flow_ids, fixture_ids, isolated):
    require(flow_ids, "Provide at least one business flow ID")
    for cid in case_ids:
        require(cid in m["cases"], "Unknown case: " + cid)
        c = m["cases"][cid]
        c.update(flow_ids=flow_ids, fixture_ids=fixture_ids, isolated=isolated)
    event(m, "flow_bound", case_ids=case_ids, flow_ids=flow_ids)
    return {"bound": case_ids}


def advance(base, m, cid, stage):
    c = m["cases"][cid]
    require(c["work_status"] != "running", "Cannot advance a running case")
    if stage == "matching":
        errors, warnings = intent_errors(inside(base, c["intent"]))
        require(not errors, "Intent gate failed", errors)
        intent = read_yaml(inside(base, c["intent"]))["intent"]
        require(intent["case"]["id"] == cid and intent.get("validation", {}).get("ready_for_asset_matching") is True,
                "Intent identity/readiness is not confirmed")
        intent_hash = file_hash(inside(base, c["intent"]))
        if c.get("intent_hash") and c["intent_hash"] != intent_hash:
            reset_case(c, "intent_changed", "matching")
            c.update(registration=None, plan_hash=None)
        c["intent_hash"] = intent_hash
    elif stage == "discovery":
        errors, warnings = case_errors(base, c, m["config"])
        require(not errors, "Reuse-plan gate failed", errors)
        p = read_yaml(inside(base, c["reuse_plan"]))["reuse_plan"]
        require(all(x.get("selection_confirmed") for x in p["capabilities"]), "Confirm every matcher decision first")
        plan_hash = file_hash(inside(base, c["reuse_plan"]))
        if c.get("plan_hash") and c["plan_hash"] != plan_hash:
            reset_case(c, "plan_changed", "discovery")
            c["registration"] = None
        c["plan_hash"] = plan_hash
    else:
        require(False, "advance supports matching or discovery; registration opens execution")
    c.update(stage=stage, work_status="pending")
    event(m, "stage_advanced", case_id=cid, stage=stage)
    return {"case_id": cid, "stage": stage, "warnings": warnings}


def match(base, m, cid):
    c = m["cases"][cid]
    require(c["intent_hash"] == file_hash(inside(base, c["intent"])), "Advance the validated Intent first")
    target = inside(base, c["reuse_plan"])
    require(not target.exists() or c["plan_hash"] != file_hash(target),
            "Confirmed plan exists; edit it deliberately instead of replacing it")
    atomic_write(target, make_plan(inside(base, c["intent"]), m["config"]), as_yaml=True)
    return {"case_id": cid, "plan": str(target), "status": "semantic_selection_required"}


def scaffold(base):
    dest = base / "runner"
    for file in (ROOT / "assets/playwright-runner").rglob("*"):
        relative = file.relative_to(ROOT / "assets/playwright-runner")
        if (not file.is_file() or file.is_symlink() or
                any(part in {"node_modules", ".auth", "results", "test-results", "playwright-report"} for part in relative.parts) or
                ".local." in file.name):
            continue
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(file, target)
    if not (dest / "cases.json").exists():
        atomic_write(dest / "cases.json", {})
    return {"runner": str(dest), "dependencies_installed": False, "next": "generate_final_scripts"}


def code_files(base, registration):
    """Resolve static local TS/JS imports; include explicit dynamic dependencies."""
    runner = base / "runner"
    pending = [inside(base, registration["script"]),
               inside(runner, registration["fixture"]["hooks"])]
    pending += [inside(runner, p) for p in registration.get("dependencies", [])]
    pending += [runner / name for name in ("playwright.config.ts", "package-lock.json", "package.json", "tsconfig.json")]
    pending.append(runner / "support/uia-reporter.ts")
    pending += [file for folder in ("network", "scripts") for file in (runner / folder).rglob("*") if file.is_file()]
    if (runner / "environments.json").is_file():
        pending.append(runner / "environments.json")
    visited = set()
    while pending:
        file = pending.pop()
        file = inside(runner, file)
        require(file.is_file(), "Script dependency missing", str(file))
        if file in visited:
            continue
        visited.add(file)
        if file.suffix not in {".ts", ".js", ".mjs"}:
            continue
        content = file.read_text()
        refs = re.findall(r'(?:from\s*|import\s*\(\s*|import\s*)[\'"]([^\'"]+)[\'"]', content)
        for ref in refs:
            if not ref.startswith("."):
                continue
            raw = file.parent / ref
            options = [raw, raw.with_suffix(".ts") if raw.suffix == ".js" else Path(str(raw) + ".ts"),
                       Path(str(raw) + ".js"), raw / "index.ts"]
            resolved = next((x for x in options if x.is_file()), None)
            require(resolved is not None, "Local import cannot be resolved", {"file": str(file), "import": ref})
            pending.append(resolved)
    return {str(p.relative_to(runner)): file_hash(p) for p in sorted(visited)}


def case_version(base, m, c):
    registration = c["registration"]
    cfg = m["config"]
    data = cfg.get("data_rules", {})
    relevant_data = {fid: data.get(fid) for fid in c["fixture_ids"]} if c["fixture_ids"] else data
    relevant_config = {k: cfg.get(k) for k in ("targets", "mutation", "proxy_env", "connection_fingerprint")}
    relevant_config["data_rules"] = relevant_data
    relevant_config["data_env_fingerprints"] = env_fingerprints(relevant_data)
    relevant_config["execution"] = {k: cfg["execution"][k] for k in ("workers", "timeout_ms")}
    from .profiles import network_fingerprint
    relevant_config["proxy_fingerprint"] = network_fingerprint(cfg)
    return digest({"files": code_files(base, registration), "source": c["source_hash"],
                   "intent": file_hash(inside(base, c["intent"])),
                   "plan": file_hash(inside(base, c["reuse_plan"])),
                   "config": digest(relevant_config), "fixture": registration["fixture"],
                   "flow_ids": c["flow_ids"], "fixture_ids": c["fixture_ids"]})


def register(base, m, cid, registration):
    c = m["cases"][cid]
    require(not m.get("active_batch"), "Cannot register while a batch is active")
    require(not any(q["status"] == "open" and cid in q["case_ids"] for q in m["questions"].values()),
            "Resolve this case's pending questions before registration")
    require(c["stage"] in {"discovery", "execution", "feedback"}, "Complete Intent and matching gates first")
    require(not any(q["kind"] == "demo" and cid in q["case_ids"] and
                    (q["status"] != "answered" or q.get("answer", {}).get("replay") != "verified")
                    for q in m["questions"].values()), "Replay imported demonstrations before registering affected cases")
    require(c["intent_hash"] == file_hash(inside(base, c["intent"])) and
            c["plan_hash"] == file_hash(inside(base, c["reuse_plan"])), "Intent/plan changed; re-run the relevant gate")
    require(registration.get("case_id") == cid, "Registration case ID mismatch")
    require(isinstance(registration.get("fixture", {}).get("mutates"), bool), "Declare whether this fixture mutates data")
    script = inside(base, registration.get("script", "__missing__"))
    inside(base / "runner/tests", script)
    require(script.is_file() and script.suffix == ".ts", "Final spec must exist inside runner/tests")
    require("[" + cid + "]" in script.read_text(), "Test title must contain [case_id]")
    previous = c.get("registration")
    c["registration"] = registration
    try:
        errors, warnings = case_errors(base, c, m["config"], execution=True)
        require(not errors, "Script registration gate failed", errors)
        version = case_version(base, m, c)
    except Exception:
        c["registration"] = previous
        raise
    if c.get("version") != version:
        reset_case(c, "script_or_dependency_version_changed", "execution")
    c.update(version=version, stage="execution", work_status="runnable")
    cases_file = base / "runner/cases.json"
    entries = read_json(cases_file) if cases_file.exists() else {}
    entries[cid] = {"case_id": cid, "hooks": registration["fixture"]["hooks"],
                    "mutates": registration["fixture"]["mutates"], "isolated": c["isolated"],
                    "fixture_ids": c["fixture_ids"], "flow_ids": c["flow_ids"]}
    atomic_write(cases_file, entries)
    event(m, "script_registered", case_id=cid, version=version)
    return {"case_id": cid, "status": "runnable", "version": version, "warnings": warnings}


def refresh(base, m):
    cfg = run_config(base, m["config_path"])
    new_hash = execution_config_fingerprint(cfg)
    if new_hash != m["config_hash"]:
        old = m["config"]
        target_changed = old.get("targets") != cfg.get("targets")
        changed_data = {k for k in set(old.get("data_rules", {})) | set(cfg.get("data_rules", {}))
                        if old.get("data_rules", {}).get(k) != cfg.get("data_rules", {}).get(k)}
        other = any(old.get(k) != cfg.get(k) for k in ("mutation", "proxy_env", "connection_fingerprint"))
        for c in m["cases"].values():
            if target_changed or other or bool(changed_data & set(c["fixture_ids"])) or (changed_data and not c["fixture_ids"]):
                reset_case(c, "environment_or_data_rules_changed", "discovery" if target_changed else "execution")
                if target_changed:
                    c["registration"] = None
        m["preflight"] = None
        m["delivery"] = {}
        event(m, "configuration_changed")
    m["config"], m["config_hash"] = cfg, new_hash
    m["source_update_required"] = bool(m["sources"] and file_hash(m["sources"][0]["path"]) != m["sources"][0]["sha256"])
    auth = cfg.get("auth", {}).get("storage_state")
    if m.get("preflight") and m["preflight"].get("auth_sha256") != (file_hash(auth) if auth else None):
        m["preflight"] = None
    from .profiles import network_fingerprint
    if m.get("preflight") and m["preflight"].get("proxy_sha256") != network_fingerprint(cfg):
        m["preflight"] = None
    for c in m["cases"].values():
        if c.get("intent_hash") and file_hash(inside(base, c["intent"])) != c["intent_hash"]:
            reset_case(c, "intent_changed", "intent")
            c.update(intent_hash=None, plan_hash=None, registration=None)
        elif c.get("plan_hash") and file_hash(inside(base, c["reuse_plan"])) != c["plan_hash"]:
            reset_case(c, "reuse_plan_changed", "matching")
            c.update(plan_hash=None, registration=None)
        elif c.get("registration") and c.get("result") not in {None, "passed"}:
            # A code edit is not permission to bypass failure classification or repair limits.
            # Explicit repair/source/config changes establish a new actionable attempt.
            continue
        elif c.get("registration") and c["stage"] == "execution" and c["work_status"] not in {"waiting_human", "finished", "running"}:
            # Only a case's actual data rules participate in its version.
            try:
                version = case_version(base, m, c)
            except UiaError as exc:
                reset_case(c, "dependency_unavailable: " + str(exc), "discovery")
                c["registration"] = None
                continue
            if version != c["version"]:
                reset_case(c, "code_or_dependency_changed", "execution")
                c["version"] = version
                c["work_status"] = "runnable"
        elif c.get("registration") and c.get("version"):
            try:
                version = case_version(base, m, c)
            except UiaError as exc:
                reset_case(c, "dependency_unavailable: " + str(exc), "discovery")
                c["registration"] = None
                continue
            if version != c["version"]:
                reset_case(c, "code_or_dependency_changed", "execution")
                c.update(version=version, work_status="runnable")
    for q in m["questions"].values():
        if q["status"] == "open":
            for cid in q["case_ids"]:
                if cid in m["cases"] and m["cases"][cid]["work_status"] != "finished":
                    m["cases"][cid]["work_status"] = "waiting_human"


def next_task(base, m):
    if m.get("active_batch"):
        from .runtime import batch_running
        active = m["active_batch"]
        running = batch_running(base, active)
        return {"action": "monitor" if running else "recover",
                "skill": "uia-runtime", "batch_id": active["id"], "report": active["report"],
                "wait": "python3 scripts/uia.py wait --run " + m["run_id"]}
    refresh(base, m)
    if m["sources"] and file_hash(m["sources"][0]["path"]) != m["sources"][0]["sha256"]:
        return {"action": "import", "reason": "source_workbook_changed", "source": m["sources"][0]["path"]}
    cases = list(m["cases"].values())
    budget = m["config"]["execution"]["batch_size"]
    rank = lambda c: ({"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(c["priority"].upper(), 4), c["case_id"])
    available = sorted([c for c in cases if c["work_status"] not in {"waiting_human", "finished"}], key=rank)
    ready = [c for c in available if c["work_status"] == "runnable"]
    if ready:
        if not m.get("preflight") or m["preflight"]["status"] != "passed":
            return {"action": "preflight", "skill": "uia-runtime", "case_ids": [c["case_id"] for c in ready]}
        return {"action": "run-batch", "skill": "uia-runtime", "case_ids": [c["case_id"] for c in ready[:budget]]}
    repairs = [c for c in available if c["stage"] == "repair"]
    if repairs:
        return {"action": "repair", "skill": "uia-runtime", "case_ids": [c["case_id"] for c in repairs[:budget]]}
    selected = [c for c in available if c["stage"] == "matching"][:budget]
    if selected:
        return {"action": "matching", "skill": "uia-asset-matcher", "case_ids": [c["case_id"] for c in selected],
                "input_paths": [str(base / c["intent"]) for c in selected]}
    flows = {}
    for c in available:
        if c["stage"] == "discovery":
            for fid in c["flow_ids"]:
                flows.setdefault(fid, []).append(c)
    if flows:
        if not m.get("preflight") or m["preflight"]["status"] != "passed":
            return {"action": "preflight", "skill": "uia-runtime", "case_ids": [c["case_id"] for c in available]}
        fid, members = sorted(flows.items(), key=lambda pair: (-len(pair[1]), min(rank(c) for c in pair[1]), pair[0]))[0]
        return {"action": "discover", "skill": "uia-runtime", "flow_id": fid,
                "case_ids": [c["case_id"] for c in sorted(members, key=rank)[:budget]], "unlocks": len(members),
                "verified_flow_sources": [{"case_id": c["case_id"], "flow_ids": c["flow_ids"],
                                           "registration": c["registration"], "evidence": c["attempts"][-1]["evidence"]}
                                          for c in cases if c.get("result") == "passed" and c.get("registration") and
                                          set(c["flow_ids"]) & {flow for member in members for flow in member["flow_ids"]}]}
    selected = [c for c in available if c["stage"] == "intent"][:budget]
    if selected:
        return {"action": "intent", "skill": "uia-excel-prep", "case_ids": [c["case_id"] for c in selected],
                "input_paths": [str(base / c["source"]) for c in selected]}
    feedback = [c for c in cases if c.get("result") == "passed" and c.get("stability") == "stable" and not c.get("feedback")]
    if feedback:
        return {"action": "feedback", "skill": "uia-runtime-feedback-reviewer", "case_ids": [c["case_id"] for c in feedback[:budget]]}
    pending_questions = [q for q in m["questions"].values() if q["status"] == "open"]
    if pending_questions:
        return {"action": "ask_human", "questions": pending_questions,
                "message": "All currently independent work has been processed; consolidate these requests."}
    if not cases:
        return {"action": "import", "reason": "no_source_cases"}
    return {"action": "report", "summary": summary(m)}


def explore(base, m, flow_id, gap_id, strategy, seconds, outcome, evidence):
    require(outcome in {"resolved", "unresolved"}, "Exploration outcome must be resolved or unresolved")
    require(seconds > 0, "Record actual positive exploration duration")
    require(evidence and inside(base, evidence).is_file(), "Exploration requires saved runtime evidence")
    previous = [a for a in m["exploration"] if a["flow_id"] == flow_id]
    per_gap = [a for a in previous if a["gap_id"] == gap_id]
    require(not any(a["strategy"] == strategy and a["evidence_sha256"] == file_hash(inside(base, evidence)) for a in per_gap),
            "Do not repeat the same strategy without new evidence")
    limits = m["config"]["execution"]
    require(sum(a["seconds"] for a in previous) < limits["exploration_minutes_per_flow"] * 60,
            "Flow exploration budget exhausted; request a focused demonstration")
    require(len({a["strategy"] for a in per_gap}) < limits["strategies_per_gap"],
            "Gap strategy budget exhausted; request a focused demonstration")
    attempt = {"at": now(), "flow_id": flow_id, "gap_id": gap_id, "strategy": strategy,
               "seconds": seconds, "outcome": outcome, "evidence": evidence,
               "evidence_sha256": file_hash(inside(base, evidence))}
    m["exploration"].append(attempt)
    exhausted = (sum(a["seconds"] for a in previous) + seconds >= limits["exploration_minutes_per_flow"] * 60 or
                 len({a["strategy"] for a in per_gap} | {strategy}) >= limits["strategies_per_gap"])
    if exhausted and outcome != "resolved":
        affected = [c["case_id"] for c in m["cases"].values() if flow_id in c["flow_ids"] and c["work_status"] != "finished"]
        question(m, "demo", flow_id + ":" + gap_id,
                 "Demonstrate the unresolved operation from its documented start state; provide a Playwright action script.",
                 affected, attempted=[a["strategy"] for a in per_gap] + [strategy])
    return {"recorded": attempt, "budget_exhausted": exhausted}


def bind_specs(base, m):
    """Point imported cases at Playwright specs. This is the daily path: no intent YAML."""
    require(not m.get("active_batch"), "Recover the active batch before binding specs")
    runner = base / "runner"
    specs = sorted(path for path in (runner / "tests").rglob("*.spec.ts") if path.name != "healer-rehearsal.spec.ts")
    require(specs, "No Playwright specs to bind")
    found = {}
    for spec in specs:
        body = spec.read_text(encoding="utf-8")
        for match in re.finditer(r"\[([A-Za-z0-9][A-Za-z0-9_.-]*)\]", body):
            cid = match.group(1)
            if cid in found or cid not in m["cases"]:
                continue
            found[cid] = (spec, body[match.end():match.end() + 500])
    require(found, "Specs do not match any imported case id")
    bound = []
    for cid, (spec, window) in found.items():
        c = m["cases"][cid]
        mutates = "uia-mutates" in window
        registration = {
            "case_id": cid, "daily_spec": True,
            "script": spec.relative_to(base).as_posix(),
            "fixture": {"hooks": "fixtures/llms-txt.mjs", "mutates": mutates,
                        "mutation_scope": ["llms.txt"] if mutates else []},
            "dependencies": ["flows/llms-txt.mjs", "support/heal.mjs"],
        }
        c["daily_spec"] = True
        c["registration"] = registration
        c["flow_ids"] = ["llms-txt"]
        c["fixture_ids"] = ["llms-overview"] if mutates else ["llms-readonly"]
        c["isolated"] = False
        errors, _warnings = case_errors(base, c, m["config"], execution=True)
        require(not errors, "Daily spec gate failed", {"case_id": cid, "errors": errors})
        version = case_version(base, m, c)
        if c.get("version") == version and (c.get("result") == "passed" or c.get("work_status") == "runnable"):
            continue
        if c.get("version") and c.get("version") != version:
            reset_case(c, "daily_spec_changed", "execution")
        c.update(version=version, stage="execution", work_status="runnable", intent_hash=None,
                 plan_hash=None, result=None, stability="not_run", pass_streak=0)
        bound.append(cid)
    entries = {}
    for cid, c in m["cases"].items():
        if not c.get("registration"):
            continue
        entries[cid] = {"case_id": cid, "hooks": c["registration"]["fixture"]["hooks"],
                        "mutates": c["registration"]["fixture"]["mutates"], "isolated": c["isolated"],
                        "fixture_ids": c["fixture_ids"], "flow_ids": c["flow_ids"]}
    atomic_write(runner / "cases.json", entries)
    event(m, "specs_bound", case_ids=sorted(found))
    return {"bound": sorted(found), "reopened": bound}


def absorb_locators(base, m):
    """Write fingerprints back only for cases that passed in that batch. Never edit specs."""
    files = sorted((base / "batches").glob("*/locator-hits.json"), key=lambda item: item.stat().st_mtime)
    if not files:
        return {"updated": [], "missing": True}
    hits_path = files[-1]
    hits = read_json(hits_path)
    batch_id = hits_path.parent.name
    passed = {cid for cid, c in m["cases"].items()
              if any(a.get("batch_id") == batch_id and a.get("result") == "passed" for a in c.get("attempts", []))}
    knowledge_path = base / "runner/knowledge/llms-txt.json"
    knowledge = read_json(knowledge_path)
    environment = m["config"].get("environment", {}).get("id")
    updated = []
    for hit in hits:
        key = str(hit.get("key") or "")
        if key.startswith("rehearse.") or hit.get("case_id") not in passed or hit.get("environment") != environment:
            continue
        if hit.get("via") == "preview":
            knowledge["preview"] = {"iframe": "#backstage-innerpage",
                                    **{name: hit.get(name) for name in ("access", "sameOrigin", "parentCanvas", "frameCanvas", "iframeCount")}}
            updated.append("preview")
            continue
        entry = knowledge.get("entries", {}).get(key)
        if not entry or not hit.get("selector"):
            continue
        previous = entry.get("last_success")
        if previous and previous != hit["selector"]:
            entry["history"] = ([{"selector": previous, "at": entry.get("updated_at")}] + entry.get("history", []))[:3]
        entry["last_success"] = hit["selector"]
        for field in ("bbox", "ancestors", "tag"):
            if hit.get(field):
                entry[field] = hit[field]
        text = " ".join(str(hit.get("text") or "").split())
        if text:
            entry["observed_text"] = text[:80]
            current = str(entry.get("name") or "")
            huge = ("\n" in current) or len(current) > 40
            if len(text) <= 40 and (not current or huge):
                entry["name"] = text
            elif huge:
                entry.pop("name", None)
        entry["via"] = hit.get("via")
        entry["updated_at"] = now()
        updated.append(key)
    knowledge["environment"] = environment
    knowledge["updated_at"] = now()
    atomic_write(knowledge_path, knowledge)
    atomic_write(ROOT / "assets/playwright-runner/knowledge/llms-txt.json", knowledge)
    event(m, "locators_absorbed", updated=updated, passed=sorted(passed))
    return {"updated": updated, "passed_cases": sorted(passed), "writeback": "passed_cases_only"}


def heal_review(base, evidence):
    """Classify a proposed repair. The spec file is never written."""
    import subprocess
    payload_path = inside(base, evidence)
    payload = read_json(payload_path)
    spec = inside(base, payload["spec"])
    before = spec.read_bytes()
    out = base / "state" / "heal-review.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    cli = ROOT / "assets/playwright-runner/support/heal-cli.mjs"
    proc = subprocess.run(["node", str(cli), str(payload_path), str(out), str(base)],
                          check=False, capture_output=True, text=True)
    require(proc.returncode == 0 and out.is_file(), "Heal review failed", (proc.stderr or proc.stdout)[-500:])
    require(spec.read_bytes() == before, "Heal review rewrote the spec")
    result = read_json(out)
    require(result.get("applied") is False and result.get("spec_unchanged") is True, "Heal review must leave the spec unchanged")
    return result
