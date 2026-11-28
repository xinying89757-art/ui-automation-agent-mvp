from __future__ import annotations

import re
from pathlib import Path

from .common import ROOT, RESULTS, file_hash, inside, read_json, read_yaml



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
        if not any(name in body for name in ("support/test", "support/fixtures")) or "businessAssertion" not in body:
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
    mutation = cfg.get("mutation", {})
    broad_editor = mutation.get("scope") == ["*"] and mutation.get("authorization_profile") == {
        "mode": "editor_any_data_restore", "approved_by": "Xinying"}
    if fixture.get("mutates") and (not fixture.get("mutation_scope") or
            (not broad_editor and not set(fixture["mutation_scope"]) <= set(mutation.get("scope", [])))):
        errors.append("Fixture mutation scope must be within the configured authorized operations")
    for dep in registration.get("dependencies", []):
        if not inside(base / "runner", dep).is_file():
            errors.append("Daily dependency missing: " + dep)
    return errors, warnings


def review_binding_errors(base, case, spec_file):
    binding = case.get('review_binding')
    if binding and (binding.get('spec_sha256') != file_hash(spec_file) or
                    binding.get('source_file_sha256') != file_hash(inside(base, case['source']))):
        return ['Reviewed case spec or source changed; reconcile the review binding']
    return []


def case_errors(base, case, cfg, execution=False):
    if (case.get("registration") or {}).get("case_spec"):
        from .specs import catalogs, spec_path, schema_errors, locator_errors, coverage
        env, data, pages = catalogs(base)
        path = spec_path(base, case)
        if not path.is_file():
            return ["case-spec missing"], []
        spec = read_yaml(path)
        errors, unknown = schema_errors(spec, read_json(inside(base, case["source"])), env, data, pages, base,
                                        approved_expectation=(case.get('review_binding') or {}).get('approved_expectation'))
        errors.extend(review_binding_errors(base, case, path))
        if unknown:
            errors.append("Unknown targets require exploration")
        registration = case["registration"]
        # Reuse established lifecycle/mutation checks, with the shared fixture import.
        errors2, warnings = daily_case_errors(base, case, cfg, execution)
        errors.extend(errors2)
        script = inside(base, registration["script"])
        if execution and script.is_file():
            body = script.read_text()
            errors.extend(locator_errors(body, pages))
            if "TODO explore:" in body:
                errors.append("Exploration TODO prevents execution")
            refs = coverage(body, str(script.relative_to((base / "runner").resolve())))
            for field in ("steps", "assertions"):
                if set(refs[field]) != {x["id"] for x in spec[field]}:
                    errors.append("Marker coverage differs from case-spec " + field)
            registration["coverage"] = refs
        return errors, warnings
    if case.get("daily_spec") or (case.get("registration") or {}).get("daily_spec"):
        return daily_case_errors(base, case, cfg, execution)
    return ['历史 Intent 用例仅供查看，请使用原始项目版本复跑'], []


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
            if c.get("remote_status") and c.get("remote_status") not in {"pass", "pass_reevaluated"}:
                errors.append(cid + ": stable without remote checks passing")
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
