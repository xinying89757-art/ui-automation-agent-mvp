from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import checks, reports, runtime, workflow
from .common import (RESULTS, UiaError, atomic_write, digest, event, file_hash, inside, load_run,
                     locked_run, now, read_json, redact, require, save, summary)


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        raise UiaError(message)


def parser():
    p = JsonParser(description="Local UI automation workflow; commands emit JSON")
    commands = p.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--run-id", required=True)
    init.add_argument("--config", required=True)
    for name in ("import", "status", "next", "bind", "advance", "match", "scaffold", "register", "preflight",
                 "question", "answer", "explore", "run-batch", "record-run", "recover", "repair", "classify",
                 "feedback", "resolve-fixture", "replay-demo", "report", "validate"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--run", required=name != "validate")
        if name == "import":
            cmd.add_argument("--excel", required=True)
            cmd.add_argument("--mapping")
        if name in {"advance", "match", "register", "repair", "classify", "feedback"}:
            cmd.add_argument("--case", required=True)
        if name == "advance":
            cmd.add_argument("--stage", choices=["matching", "discovery"], required=True)
        if name == "bind":
            cmd.add_argument("--cases", nargs="+", required=True)
            cmd.add_argument("--flows", nargs="+", required=True)
            cmd.add_argument("--fixtures", nargs="*", default=[])
            cmd.add_argument("--isolated", action="store_true")
        if name in {"register", "feedback"}:
            cmd.add_argument("--file", required=True)
        if name in {"preflight", "explore", "repair", "resolve-fixture", "replay-demo"}:
            cmd.add_argument("--evidence", required=True)
        if name == "question":
            cmd.add_argument("--kind", choices=["login", "environment", "product", "demo", "column_mapping"], required=True)
            cmd.add_argument("--subject", required=True)
            cmd.add_argument("--prompt", required=True)
            cmd.add_argument("--cases", nargs="*", default=[])
            cmd.add_argument("--key")
            cmd.add_argument("--sheet")
            cmd.add_argument("--attempted", nargs="*", default=[])
        if name in {"answer", "replay-demo"}:
            cmd.add_argument("--question", required=True)
        if name == "answer":
            cmd.add_argument("--file", required=True, help="JSON value/object containing the non-secret answer")
        if name == "explore":
            cmd.add_argument("--flow", required=True)
            cmd.add_argument("--gap", required=True)
            cmd.add_argument("--strategy", required=True)
            cmd.add_argument("--seconds", type=float, required=True)
            cmd.add_argument("--outcome", choices=["resolved", "unresolved"], required=True)
        if name == "run-batch":
            cmd.add_argument("--cases", nargs="+", required=True)
        if name == "recover":
            cmd.add_argument("--abandon", action="store_true")
            cmd.add_argument("--evidence")
        if name == "classify":
            cmd.add_argument("--result", choices=sorted(RESULTS - {"passed"}), required=True)
            cmd.add_argument("--reason", required=True)
            cmd.add_argument("--evidence", required=True)
        if name == "resolve-fixture":
            cmd.add_argument("--fixture", required=True)
    return p


def dispatch(args, path, m):
    base = path.parent
    cmd = args.command
    if hasattr(args, "case"):
        require(args.case in m["cases"], "Unknown case: " + args.case)
    if cmd == "import":
        return workflow.import_excel(base, m, args.excel, read_json(args.mapping) if args.mapping else None)
    if cmd == "next":
        return workflow.next_task(base, m)
    if cmd == "bind":
        return workflow.bind(m, args.cases, args.flows, args.fixtures, args.isolated)
    if cmd == "advance":
        return workflow.advance(base, m, args.case, args.stage)
    if cmd == "match":
        return workflow.match(base, m, args.case)
    if cmd == "scaffold":
        return workflow.scaffold(base)
    if cmd == "register":
        return workflow.register(base, m, args.case, read_json(args.file))
    if cmd == "preflight":
        workflow.refresh(base, m)
        return runtime.preflight(base, m, args.evidence)
    if cmd == "question":
        return workflow.question(m, args.kind, args.subject, args.prompt, args.cases, args.key, args.attempted, args.sheet)
    if cmd == "answer":
        return workflow.answer(m, args.question, read_json(args.file), base)
    if cmd == "explore":
        return workflow.explore(base, m, args.flow, args.gap, args.strategy, args.seconds, args.outcome, args.evidence)
    if cmd == "record-run":
        runtime.ensure_stopped(base, m.get("active_batch"))
        return runtime.consume_batch(base, m)
    if cmd == "recover":
        runtime.ensure_stopped(base, m.get("active_batch"))
        if args.abandon:
            require(args.evidence, "Abandoning a batch requires --evidence")
            return runtime.abandon_batch(base, m, args.evidence)
        return runtime.consume_batch(base, m)
    if cmd == "repair":
        return runtime.repair(base, m, args.case, args.evidence)
    if cmd == "classify":
        require(not m.get("active_batch"), "Recover the active batch first")
        require(inside(base, args.evidence).is_file(), "Classification requires evidence")
        c = m["cases"][args.case]
        c.update(result=args.result, stage="finished", work_status="finished", pass_streak=0,
                 stability="not_run" if not c["attempts"] else "unstable",
                 classification={"reason": redact(args.reason, m["config"]), "evidence": args.evidence, "at": now()})
        for q in m["questions"].values():
            if q["status"] == "open" and args.case in q["case_ids"]:
                q["case_ids"].remove(args.case)
                if not q["case_ids"]:
                    q.update(status="closed", answered_at=now(), closed_reason="case_classified")
        event(m, "case_classified", case_id=args.case, result=args.result)
        return {"case_id": args.case, "result": args.result}
    if cmd == "feedback":
        c = m["cases"][args.case]
        require(c.get("result") == "passed" and c.get("stability") == "stable", "Feedback requires the two real successful runs")
        review = read_json(args.file)
        require(review.get("case_id") == args.case and isinstance(review.get("items"), list), "Invalid feedback review")
        allowed = {"UPDATE_UI_KNOWLEDGE", "UPDATE_EXISTING_ASSET", "NEW_ASSET_CANDIDATE", "DO_NOT_PERSIST"}
        for item in review["items"]:
            require(item.get("classification") in allowed and item.get("summary") and item.get("evidence"), "Incomplete feedback item")
            for ref in item["evidence"]:
                require(inside(base, ref).is_file(), "Feedback evidence missing: " + ref)
        serialized = json.dumps(review, ensure_ascii=False)
        require(redact(serialized, m["config"]) == serialized, "Feedback includes a configured secret")
        target = inside(base, str(Path("cases") / args.case / "feedback.json"))
        atomic_write(target, review)
        c["feedback"] = str(target.relative_to(base))
        c["stage"] = "finished"
        event(m, "feedback_recorded", case_id=args.case)
        return {"review": c["feedback"], "writeback": "not_applied"}
    if cmd == "resolve-fixture":
        require(args.fixture in m["contaminated_fixtures"], "Fixture is not marked contaminated")
        proof = read_json(inside(base, args.evidence))
        require(proof.get("fixture_id") == args.fixture and proof.get("cleanup_verified") is True,
                "Provide real cleanup verification for the affected fixture")
        restored = m["contaminated_fixtures"].pop(args.fixture)
        marker = base / "state/contaminated" / (digest(args.fixture.encode()) + ".json")
        if marker.exists():
            marker.unlink()
        for c in m["cases"].values():
            if args.fixture in (c["fixture_ids"] or ["case:" + c["case_id"]]):
                c["cleanup_recovery"] = {"batch_id": restored["batch_id"], "evidence": args.evidence}
                if c.get("result") == "automation_failure" and c["repair_rounds"] < m["config"]["execution"]["repair_rounds"]:
                    c.update(stage="repair", work_status="pending")
        event(m, "fixture_restored", fixture_id=args.fixture, evidence=args.evidence)
        # A pending question must still be answered; cleanup proof alone does not close other blockers.
        return {"fixture_id": args.fixture, "restored": True, "next": "answer_related_question"}
    if cmd == "replay-demo":
        require(args.question in m["questions"], "Unknown demonstration question")
        q = m["questions"][args.question]
        require(q["kind"] == "demo" and q["status"] == "answered", "Demo has not been imported")
        proof = read_json(inside(base, args.evidence))
        script = inside(base, q["answer"]["script"])
        require(proof.get("script_sha256") == file_hash(script) == q["answer"]["sha256"] and
                proof.get("result") == "passed" and proof.get("cleanup_verified") is True,
                "A demonstration needs independent successful replay and cleanup evidence")
        q["answer"].update(replay="verified", replay_evidence=args.evidence)
        event(m, "demo_replayed", question_id=q["id"])
        return {"question_id": q["id"], "replay": "verified"}
    if cmd == "report":
        if not m.get("active_batch"):
            workflow.refresh(base, m)
        return reports.make_report(base, m)
    if cmd == "validate":
        errors, warnings = checks.run_errors(base, m)
        errors.extend(checks.skill_errors())
        return {"valid": not errors, "errors": errors, "warnings": warnings}
    raise UiaError("Unknown command")


def execute(args):
    if args.command == "init":
        return workflow.init(args.run_id, args.config)
    if args.command == "validate" and not args.run:
        errors = checks.skill_errors()
        return {"valid": not errors, "errors": errors, "warnings": []}
    if args.command == "status":
        path, m = load_run(args.run)
        active = m["active_batch"]
        progress_file = inside(path.parent, active["report"]) if active else None
        progress = read_json(progress_file) if progress_file and progress_file.is_file() else None
        return {"run": str(path), "status": m["status"], "summary": summary(m),
                "active_batch": m["active_batch"],
                "batch_progress": [{k: row.get(k) for k in ("case_id", "result", "duration_ms")}
                                   for row in progress.get("cases", [])] if progress else [],
                "cases": [{k: c.get(k) for k in ("case_id", "title", "stage", "work_status", "result", "stability", "pass_streak")}
                          for c in m["cases"].values()],
                "questions": [{k: q.get(k) for k in ("id", "kind", "prompt", "case_ids", "status")}
                              for q in m["questions"].values() if q["status"] == "open"]}
    if args.command == "run-batch":
        # Release the manifest lock while Playwright runs; the active receipt prevents another batch.
        with locked_run(args.run) as (path, m):
            batch = runtime.begin_batch(path.parent, m, args.cases)
            cfg = m["config"]
            save(path, m)
        code = runtime.execute_process(path.parent, batch, cfg)
        with locked_run(args.run) as (path, m):
            result = runtime.consume_batch(path.parent, m, code)
            save(path, m)
        return result
    with locked_run(args.run) as (path, m):
        require(not m.get("active_batch") or args.command in {"record-run", "recover", "validate", "report", "next"},
                "An execution batch is active; recover it before changing the run")
        before = digest({k: m[k] for k in ("cases", "questions", "sources", "config", "preflight", "contaminated_fixtures")})
        result = dispatch(args, path, m)
        after = digest({k: m[k] for k in ("cases", "questions", "sources", "config", "preflight", "contaminated_fixtures")})
        if before != after and args.command != "report":
            m["delivery"] = {}
        if args.command != "validate":
            save(path, m)
        return result


def main():
    try:
        result = execute(parser().parse_args())
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2, default=str))
        if result.get("valid") is False:
            raise SystemExit(1)
    except UiaError as error:
        print(json.dumps({"ok": False, "error": str(error), "details": error.details}, ensure_ascii=False, default=str))
        raise SystemExit(2)
    except KeyboardInterrupt:
        print(json.dumps({"ok": False, "error": "Interrupted; use next/recover to inspect saved batch state"}))
        raise SystemExit(130)
    except Exception as error:
        # Do not dump environment, credentials, or subprocess command lines in tracebacks.
        print(json.dumps({"ok": False, "error": type(error).__name__, "message": str(error)}, ensure_ascii=False))
        raise SystemExit(2)
