from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from .assets import catalog, dependency_issues, verified_direct
from .common import ROOT, RESULTS, file_hash, inside, read_json, read_yaml


def intent_errors(path):
    module_path = ROOT / ".agents/skills/uia-automation-intent/scripts/validate_automation_intent.py"
    spec = importlib.util.spec_from_file_location("uia_intent_validator", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    v = module.Validator(read_yaml(path), intent_path=Path(path), ui_knowledge_root=ROOT / "ui-knowledge")
    v.check()
    return v.errors, v.warnings


def daily_case_errors(base, case, cfg, execution=False):
    """Daily specs skip the intent registry. They still have to call the lifecycle and keep assertions reviewable."""
    errors, warnings = [], []
    registration = case.get("registration") or {}
    if not execution:
        return errors, warnings
    script = inside(base, registration.get("script", "__missing__"))
    if not script.is_file():
        errors.append("Final script missing")
    else:
        body = script.read_text(encoding="utf-8")
        if "support/test" not in body or "businessAssertion" not in body:
            errors.append("Final spec must use the lifecycle fixture and businessAssertion wrapper")
        if "[" + case["case_id"] + "]" not in body:
            errors.append("Test title must contain [case_id]")
        if re.search(r"waitForTimeout|xpath=|\.nth\(|test\.fixme|test\.skip", body):
            errors.append("Daily spec uses a skipped case or a disallowed locator pattern")
    fixture = registration.get("fixture") or {}
    hooks = inside(base / "runner", fixture.get("hooks", "__missing__"))
    if not hooks.is_file():
        errors.append("Fixture hooks module missing")
    else:
        hook_body = hooks.read_text(encoding="utf-8")
        for name in ("prepare", "verifyPrepared", "cleanup", "verifyCleanup"):
            if name not in hook_body:
                errors.append("Fixture hooks missing " + name)
    if fixture.get("mutates") and (not cfg.get("mutation", {}).get("allowed") or not cfg.get("mutation", {}).get("scope")):
        errors.append("Mutating case needs configured operation scope")
    if fixture.get("mutates") and (not fixture.get("mutation_scope") or
            not set(fixture["mutation_scope"]) <= set(cfg.get("mutation", {}).get("scope", []))):
        errors.append("Fixture mutation scope must be within the configured authorized operations")
    for dep in registration.get("dependencies", []):
        if not inside(base / "runner", dep).is_file():
            errors.append("Daily dependency missing: " + dep)
    return errors, warnings


def case_errors(base, case, cfg, execution=False):
    if case.get("daily_spec") or (case.get("registration") or {}).get("daily_spec"):
        return daily_case_errors(base, case, cfg, execution)
    errors, warnings = [], []
    intent_path = inside(base, case["intent"])
    if not intent_path.is_file():
        return ["Intent does not exist"], warnings
    err, warn = intent_errors(intent_path)
    errors.extend(err)
    warnings.extend(warn)
    intent = read_yaml(intent_path).get("intent", {})
    if intent.get("case", {}).get("id") != case["case_id"]:
        errors.append("Intent case ID differs from manifest case ID")
    plan_path = inside(base, case["reuse_plan"])
    if not plan_path.is_file():
        if execution:
            errors.append("Reuse plan missing")
        return errors, warnings
    plan = read_yaml(plan_path).get("reuse_plan", {})
    if plan.get("source", {}).get("case_id") != case["case_id"]:
        errors.append("Reuse plan belongs to another case")
    caps = {cap["id"] for cap in intent.get("required_capabilities", [])}
    planned = [cap.get("ref") for cap in plan.get("capabilities", [])]
    if set(planned) != caps or len(planned) != len(set(planned)):
        errors.append("Reuse plan must cover each required capability exactly once")
    assets, _ = catalog()
    for item in plan.get("capabilities", []):
        if item.get("decision") not in {"DIRECT_REUSE", "ADAPT_BEFORE_REUSE", "DISCOVERY_REQUIRED", "MISSING"}:
            errors.append("Invalid reuse decision: " + str(item.get("ref")))
        aid = item.get("asset")
        if item.get("decision") in {"DIRECT_REUSE", "ADAPT_BEFORE_REUSE"} and not aid:
            errors.append("Selected reuse decision needs an asset ID: " + str(item.get("ref")))
        if aid and aid not in assets:
            errors.append("Unknown selected asset: " + aid)
        if item.get("decision") == "DIRECT_REUSE" and aid in assets:
            issues = dependency_issues(aid, assets, cfg)
            if not verified_direct(assets[aid], cfg, item.get("verification"), base):
                issues.append("Direct reuse requires current source/signature/export/runtime proof: " + aid)
            errors.extend(issues)
        if execution and not item.get("selection_confirmed"):
            errors.append("Asset matcher must confirm decision for " + str(item.get("ref")))
    if execution:
        registration = case.get("registration", {})
        script = inside(base, registration.get("script", "__missing__"))
        if not script.is_file():
            errors.append("Final script missing")
        elif "support/test" not in script.read_text() or "businessAssertion" not in script.read_text():
            errors.append("Final spec must use the lifecycle fixture and businessAssertion wrapper")
        resolutions = registration.get("runtime_resolutions", {})
        for unknown in intent.get("runtime_unknowns", []):
            if unknown.get("blocking"):
                resolution = resolutions.get(unknown["id"], {})
                if resolution.get("status") != "resolved" or not resolution.get("evidence"):
                    errors.append("Blocking runtime unknown unresolved: " + unknown["id"])
                for ref in resolution.get("evidence", []):
                    if not inside(base, ref).is_file():
                        errors.append("Runtime resolution evidence missing: " + ref)
        coverage = registration.get("coverage", {})
        for field, ids in (("steps", {s["id"] for s in intent.get("steps", [])}),
                           ("capabilities", caps),
                           ("assertions", {a["id"] for a in intent.get("assertions", [])})):
            refs = coverage.get(field, {})
            if set(refs) != ids:
                errors.append("Script coverage differs from Intent " + field)
            for ref, location in refs.items():
                if not isinstance(location, dict) or not location.get("file") or not isinstance(location.get("line"), int):
                    errors.append("Coverage needs file/line evidence for " + ref)
                    continue
                f = inside(base / "runner", location["file"])
                if not f.is_file() or not 1 <= location["line"] <= len(f.read_text().splitlines()):
                    errors.append("Coverage location missing/out of range for " + ref)
        fixture = registration.get("fixture", {})
        hooks = inside(base / "runner", fixture.get("hooks", "__missing__"))
        if not hooks.is_file():
            errors.append("Fixture hooks module missing")
        if fixture.get("mutates") and (not cfg.get("mutation", {}).get("allowed") or not cfg.get("mutation", {}).get("scope")):
            errors.append("Mutating case needs configured operation scope")
        if fixture.get("mutates") and (not fixture.get("mutation_scope") or
                not set(fixture["mutation_scope"]) <= set(cfg.get("mutation", {}).get("scope", []))):
            errors.append("Fixture mutation scope must be within the configured authorized operations")
        for ref in registration.get("evidence", []):
            if not inside(base, ref).is_file():
                errors.append("Runtime evidence missing: " + ref)
        if not registration.get("evidence"):
            errors.append("Registration needs runtime discovery/replay evidence")
    return errors, warnings


def skill_errors():
    errors = []
    root = ROOT / ".agents/skills"
    names = []
    for file in root.glob("*/SKILL.md"):
        body = file.read_text()
        pieces = body.split("---", 2)
        if len(pieces) < 3:
            errors.append("Missing skill frontmatter: " + str(file))
            continue
        import yaml
        meta = yaml.safe_load(pieces[1]) or {}
        names.append(meta.get("name"))
        if not meta.get("name", "").startswith("uia-") or not meta.get("description"):
            errors.append("Invalid project skill metadata: " + str(file))
        for ref in re.findall(r"\]\(([^)]+)\)", body):
            ref = ref.split("#", 1)[0]
            if ref and "://" not in ref and not (file.parent / ref).exists():
                errors.append("Missing skill reference: " + str(file.parent / ref))
    if len(names) != len(set(names)):
        errors.append("Duplicate project skill names")
    return errors


def run_errors(base, m):
    errors, warnings = [], []
    if m.get("active_batch"):
        warnings.append("An active batch needs recovery before another execution")
    for cid, c in m["cases"].items():
        if c["work_status"] == "finished" and c.get("result") not in RESULTS:
            errors.append(cid + ": finished without a classified result")
        if c.get("stability") == "stable":
            need = int(m["config"]["execution"].get("stability_passes") or 2)
            passes = c.get("attempts", [])[-need:]
            if len(passes) != need or any(a.get("result") != "passed" or not a.get("cleanup_verified") for a in passes):
                errors.append(cid + ": stable without the configured clean passing attempts")
            elif len({a.get("version") for a in passes}) != 1 or len({a.get("batch_id") for a in passes}) != need:
                errors.append(cid + ": stability attempts are not independent and identical in version")
        for attempt in c.get("attempts", []):
            evidence = inside(base, attempt.get("evidence", "__missing__"))
            if not evidence.is_file() or file_hash(evidence) != attempt.get("evidence_sha256"):
                errors.append(cid + ": execution evidence missing or changed")
        if c.get("daily_spec") or inside(base, c["intent"]).is_file():
            e, w = case_errors(base, c, m["config"], execution=bool(c.get("registration")))
            errors.extend(cid + ": " + item for item in e)
            warnings.extend(cid + ": " + item for item in w)
    return errors, warnings
