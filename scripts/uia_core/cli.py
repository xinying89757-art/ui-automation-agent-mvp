from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urlsplit
from pathlib import Path

from . import checks, reports, runtime, workflow, profiles, specs
from .common import (RESULTS, UiaError, atomic_write, digest, event, file_hash, inside, load_run,
                     locked_run, now, read_json, redact, require, save, summary)


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        raise UiaError(message)


def parser():
    p = JsonParser(description="Local UI automation workflow; commands emit JSON")
    commands = p.add_subparsers(dest="command", required=True)
    remote = commands.add_parser("remote-checks")
    remote.add_argument("action", choices=["ingest", "restore", "reevaluate", "arm-watch", "ingest-watch", "reevaluate-watch"])
    remote.add_argument("--run", required=True)
    remote.add_argument("file", nargs="?")
    remote.add_argument("--case", dest="watch_case")
    remote.add_argument("--lead-minutes", type=int, default=20)
    remote.add_argument("--watch-minutes", type=int, default=40)
    remote.add_argument("--interval-ms", type=int, default=1000)
    remote.add_argument("--watch")
    go = commands.add_parser("go")
    go.add_argument("excel")
    go.add_argument("--profile")
    go.add_argument("--cases", help="Comma-separated case IDs")
    go.add_argument("--hints", help="Optional page=rough path lines or a UTF-8 file")
    hints = commands.add_parser("hints")
    hints.add_argument("action", choices=["add", "confirm"])
    hints.add_argument("--run", required=True)
    hints.add_argument("text", nargs="?")
    hints.add_argument("--page")
    hints.add_argument("--step", action="append", default=[])
    hints.add_argument("--frame")
    go.add_argument("--arm-watch", help="Comma-separated case IDs whose max-latency public assertion gets a pre-armed remote watch before the save")
    go.add_argument("--lead-minutes", type=int, default=20)
    go.add_argument("--watch-minutes", type=int, default=10)
    turn = commands.add_parser("session-turn")
    turn.add_argument("--run", required=True)
    turn.add_argument("--id", required=True)
    turn.add_argument("--kind", choices=["发起", "答清单", "审核单", "看报告", "计划外"], required=True)
    environments = commands.add_parser("env")
    environments.add_argument("action", choices=["list"])
    setup = commands.add_parser("setup")
    setup.add_argument("--profile", required=True)
    setup.add_argument("--environment", choices=["p", "gray", "production"], required=True)
    setup.add_argument("--site", required=True)
    setup.add_argument("--account")
    setup.add_argument("--credentials-file")
    setup.add_argument("--password-env")
    profile = commands.add_parser("profile")
    profile.add_argument("action", choices=["set"])
    profile.add_argument("--profile", required=True)
    profile.add_argument("--site")
    profile.add_argument("--mutation-allowed", action="store_true")
    profile.add_argument("--read-only", action="store_true")
    profile.add_argument("--scope", nargs="*")
    profile.add_argument("--stability-passes", type=int, choices=[1, 2])
    profile.add_argument("--editor-data-restorable", action="store_true")
    profile.add_argument("--run")
    login = commands.add_parser("login")
    source = login.add_mutually_exclusive_group(required=True)
    source.add_argument("--profile")
    source.add_argument("--config")
    source.add_argument("--run")
    login.add_argument("--force", action="store_true")
    login.add_argument("--check-only", action="store_true")
    login.add_argument("--manual", action="store_true")
    snapshot = commands.add_parser("snapshot")
    source = snapshot.add_mutually_exclusive_group(required=True)
    source.add_argument("--profile")
    source.add_argument("--config")
    source.add_argument("--run")
    snapshot.add_argument("--node", default="page", choices=["page", "content-admin", "editor"])
    snapshot.add_argument("--manual", action="store_true")
    snapshot.add_argument("--frame", help="iframe selector, e.g. #backstage-innerpage")
    snapshot.add_argument("--scope", help="dialog or container selector")
    snapshot.add_argument("--hover")
    snapshot.add_argument("--click", action="append", default=[])
    snapshot.add_argument("--open-target", help="open a known node before snapshot")
    snapshot.add_argument("--goto")
    snapshot.add_argument("--step", action="append", default=[])
    snapshot.add_argument("--save-as")
    snapshot.add_argument("--purpose", default="")
    snapshot.add_argument("--entry")
    spec = commands.add_parser("spec")
    spec.add_argument("action", choices=["lint", "gen", "render"])
    spec.add_argument("--run", required=True)
    spec.add_argument("--cases", nargs="+")
    init = commands.add_parser("init")
    init.add_argument("--run-id", required=True)
    source = init.add_mutually_exclusive_group(required=True)
    source.add_argument("--config")
    source.add_argument("--profile")
    for name in ("import", "status", "next", "bind", "advance", "match", "scaffold", "register", "preflight",
                 "question", "answer", "explore", "run-batch", "record-run", "recover", "repair", "classify",
                 "feedback", "resolve-fixture", "replay-demo", "report", "validate",
                 "bind-specs", "absorb-locators", "heal-review", "preconditions", "wait", "agent-env", "exploration-log", "generator"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--run", required=name != "validate")
        if name == "preconditions":
            cmd.add_argument("action", nargs="?", choices=["classify"])
            cmd.add_argument("--key")
            cmd.add_argument("--as", dest="classification", choices=["ai_prepare", "explore", "human_env", "ignore"])
            cmd.add_argument("--label")
            cmd.add_argument("--page")
            cmd.add_argument("--match", action="append", default=[])
        if name == "generator":
            cmd.add_argument("--purpose", required=True)
            cmd.add_argument("--plan", required=True)
            cmd.add_argument("--minutes", type=int, default=20)
            cmd.add_argument("--model")
            cmd.add_argument("--entry")
        if name == "exploration-log":
            cmd.add_argument("--method", choices=["generator", "midscene"], required=True)
            cmd.add_argument("--purpose", required=True)
            cmd.add_argument("--result", choices=["ok", "failed"], required=True)
            cmd.add_argument("--note", required=True)
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
        if name in {"preflight", "repair", "resolve-fixture", "replay-demo"}:
            cmd.add_argument("--evidence", required=True)
        if name == "question":
            cmd.add_argument("--kind", choices=["login", "environment", "product", "demo", "record_request", "column_mapping", "preconditions"], required=True)
            cmd.add_argument("--subject", required=True)
            cmd.add_argument("--page", help="Entry page for the specific interaction node")
            cmd.add_argument("--interaction")
            cmd.add_argument("--prompt", required=True)
            cmd.add_argument("--cases", nargs="*", default=[])
            cmd.add_argument("--key")
            cmd.add_argument("--sheet")
            cmd.add_argument("--attempted", nargs="*", default=[])
        if name in {"answer", "replay-demo"}:
            cmd.add_argument("--question", required=name == "replay-demo")
        if name == "answer":
            cmd.add_argument("--file", help="Legacy non-secret JSON answer")
            cmd.add_argument("sentence", nargs="?")
        if name == "explore":
            cmd.add_argument("--evidence", default="")
            cmd.add_argument("--flow", default="")
            cmd.add_argument("--gap", default="")
            cmd.add_argument("--strategy", default="")
            cmd.add_argument("--seconds", type=float, default=0)
            cmd.add_argument("--outcome", choices=["resolved", "unresolved"], default="unresolved")
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
        if name == "heal-review":
            cmd.add_argument("--evidence", required=True)
    return p


def dispatch(args, path, m):
    base = path.parent
    cmd = args.command
    if cmd == "hints":
        from .entries import add, confirm
        from .experience import sync_checklist
        if args.action == "add":
            require(args.text, "hints add requires 页面=路径")
            result = add(m, args.text)
        else:
            require(args.page, "hints confirm requires --page")
            result = confirm(m, args.page, args.step, args.frame)
        return {**result, **sync_checklist(base, m)}
    if hasattr(args, "case"):
        require(args.case in m["cases"], "Unknown case: " + args.case)
    if cmd == "remote-checks":
        from .remote_checks import ingest, restore, reevaluate, arm_watch, ingest_watch, reevaluate_watch
        if args.action == "arm-watch":
            require(args.watch_case, "arm-watch requires --case CID")
            result = arm_watch(base, m, args.watch_case, args.lead_minutes, args.watch_minutes, args.interval_ms)
        elif args.action == "ingest-watch":
            require(args.file, "ingest-watch requires a JSON file")
            result = ingest_watch(base, m, args.file)
        elif args.action == "reevaluate-watch":
            result = reevaluate_watch(base, m, args.watch)
        else:
            require(args.action == "restore" or args.file, args.action + " requires a JSON file")
            result = ingest(base, m, args.file) if args.action == "ingest" else reevaluate(base, m, args.file) if args.action == "reevaluate" else restore(base, m)
        result["report"] = reports.make_report(base, m)
        return result
    if cmd == "spec":
        if args.action == "lint":
            return specs.lint(base, m, args.cases)
        chosen = args.cases or [cid for cid, c in m["cases"].items() if specs.spec_path(base, c).is_file()]
        return {"results": [(specs.generate if args.action == "gen" else specs.render)(base, m, cid) for cid in chosen]}
    if cmd == "import":
        workflow.scaffold(base)
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
        from .exploration import index_unknown_nodes
        index_unknown_nodes(base, m)
        return workflow.question(m, args.kind, args.subject, args.prompt, args.cases, args.key, args.attempted, args.sheet,
                                 interaction=args.interaction, base=base, page=args.page)
    if cmd == "session-turn":
        from .experience import session_turn
        return session_turn(m, args.id, args.kind)
    if cmd == "answer":
        if args.sentence:
            from .experience import answer_sentence
            return answer_sentence(base, m, args.sentence)
        require(args.question and args.file, "请提供中文一句话，或 --question 和 --file")
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
        require(c.get("result") == "passed" and c.get("stability") == "stable",
                "Feedback requires the configured number of clean passes")
        review = read_json(args.file)
        require(review.get("case_id") == args.case and isinstance(review.get("items"), list), "Invalid feedback review")
        allowed = {"UPDATE_UI_KNOWLEDGE", "UPDATE_EXISTING_ASSET", "NEW_ASSET_CANDIDATE", "DO_NOT_PERSIST"}
        for item in review["items"]:
            require(item.get("classification") in allowed and item.get("summary") and item.get("evidence"), "Incomplete feedback item")
            for ref in item["evidence"]:
                require(inside(base, ref).is_file(), "Feedback evidence missing: " + ref)
        require(not specs.has_snapshot_ref(review), "Feedback/write-back cannot contain snapshot refs")
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
    if cmd == "bind-specs":
        workflow.scaffold(base)
        return workflow.bind_specs(base, m)
    if cmd == "agent-env":
        return profiles.agent_env(base, m)
    if cmd == "generator":
        from .exploration import run_generator
        return run_generator(base, m, args.purpose, args.plan, args.minutes, args.model, entry=args.entry)
    if cmd == "exploration-log":
        from .exploration import log
        return log(m, args.method, args.purpose, args.result, args.note)
    if cmd == "preconditions":
        from .preconditions import sync_preconditions, classify_precondition
        if args.action == "classify":
            require(args.key and args.classification and args.label, "classify requires --key --as --label")
            result = classify_precondition(base, m, args.key, args.classification, args.label, args.match, args.page)
            return {**result, **sync_preconditions(base, m)}
        return sync_preconditions(base, m)
    if cmd == "absorb-locators":
        return workflow.absorb_locators(base, m)
    if cmd == "heal-review":
        result = workflow.heal_review(base, args.evidence)
        if not result.get('accept') and result.get('rejected_diff'):
            from .experience import add_review
            payload = read_json(inside(base, args.evidence))
            cases = [cid for cid, c in m['cases'].items() if (c.get('registration') or {}).get('script') == payload.get('spec')]
            add_review(m, 'assertion_change', cases, 'AI 修复提案含断言变更，默认不应用', evidence=args.evidence,
                       proposed_diff=result['rejected_diff'])
        return result
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
    if args.command == "go":
        from .experience import go
        return go(args.excel, args.profile, args.cases, arm_watch=args.arm_watch, lead_minutes=args.lead_minutes, watch_minutes=args.watch_minutes, hints=args.hints)
    if args.command == "env":
        return {"environments": profiles.presets()}
    if args.command == "setup":
        return profiles.setup(args.profile, args.environment, args.site, args.account, args.credentials_file, args.password_env)
    if args.command == "profile":
        require(not (args.mutation_allowed and args.read_only), "Choose either --mutation-allowed or --read-only")
        if args.run and (args.scope is not None or args.mutation_allowed or args.read_only or args.site):
            with locked_run(args.run) as (path, m):
                m["scope_violations"] = int(m.get("scope_violations", 0)) + 1
                event(m, "scope_change_rejected", profile=args.profile)
                save(path, m)
            raise UiaError("Site and mutation scope are locked for this run; update them only in the upfront checklist before init")
        allowed = True if args.mutation_allowed else False if args.read_only else None
        result = profiles.update_profile(args.profile, args.site, allowed, args.scope, args.stability_passes,
                                         args.editor_data_restorable)
        if not args.run:
            return result
        with locked_run(args.run) as (path, m):
            workflow.refresh(path.parent, m)
            save(path, m)
            result["run"] = {"site": m["config"].get("site"), "public": m["config"].get("targets", {}).get("public"),
                             "mutation": m["config"].get("mutation"),
                             "stability_passes": m["config"]["execution"]["stability_passes"],
                             "preflight": (m.get("preflight") or {}).get("status")}
        return result
    if args.command == "wait":
        return runtime.wait_for_batch(args.run)
    if args.command == "login":
        from .common import config
        if not args.run:
            cfg = config(profiles.profile_path(args.profile) if args.profile else args.config)
            return profiles.invoke_login(cfg, check_only=args.check_only, force=args.force, manual=args.manual)
        with locked_run(args.run) as (path, m):
            require(not m.get("active_batch"), "Cannot replace authentication during an active batch")
            workflow.refresh(path.parent, m)
            workflow.scaffold(path.parent)
            workflow.refresh(path.parent, m)
            evidence = Path("evidence") / ("environment-" + now().replace(":", "-") + ".json")
            try:
                result = profiles.invoke_login(m["config"], path.parent / "runner", args.check_only, args.force, path.parent / evidence, args.manual)
            except UiaError as error:
                affected = [cid for cid, c in m["cases"].items() if c["work_status"] != "finished" and
                            c["stage"] in {"discovery", "execution", "repair"}]
                details = error.details if isinstance(error.details, dict) else {}
                q = workflow.question(m, "login", "session", str(error), affected, reopen=True)
                q["choices"] = details.get("choices", [])
                save(path, m)
                raise
            if not args.check_only:
                for q in list(m["questions"].values()):
                    if q["status"] == "open" and (q["subject"] == "session" or q["subject"] == "preflight"):
                        workflow.answer(m, q["id"], {"evidence": str(evidence)}, path.parent)
                result["preflight"] = runtime.preflight(path.parent, m, str(evidence))
            save(path, m)
            return result
    if args.command == "snapshot":
        from .common import config
        require(not args.save_as or args.run, "--save-as requires --run")
        require(not args.entry or args.run, "--entry requires --run")
        if args.run:
            with locked_run(args.run) as (path, m):
                import time as _time
                entry_hint, entry_count = None, None
                if args.entry:
                    from .entries import snapshot_route
                    entry_hint, entry_count = snapshot_route(args, m['config'])
                    if entry_count is None:
                        return {'entry': args.entry, 'entry_hint': entry_hint, 'entry_reached': False,
                                'not_a_page': bool(entry_hint.get('not_a_page')),
                                'instruction': '该项不是页面，跳过导航。' if entry_hint.get('not_a_page') else
                                '将入口路径翻译为 --goto/--step 后执行 snapshot；再用 uia.py hints confirm --run R --page P --step ... [--frame ...] 保存具体步骤。'}
                area = {"page": None, "content-admin": "内容管理", "editor": "编辑网站"}[args.node]
                started, t0 = now(), _time.monotonic()
                try:
                    snapshot_result = profiles.invoke_snapshot(m["config"], path.parent / "runner", area, args.manual, args.frame, args.scope, args.open_target, args.hover, args.click, args.goto, args.step,
                                                              **({'entry_steps': entry_count} if args.entry else {}))
                except UiaError:
                    from .secrets import scrub_text
                    m.setdefault('exploration', []).append({'at': now(), 'method': 'snapshot', 'purpose': scrub_text(args.purpose, m['config']),
                                                          'entry': args.entry, 'entry_reached': False, 'result': 'failed'})
                    save(path, m)
                    raise
                failed = snapshot_result.get('structure', {}).get('failed_step')
                failed_index = failed.get('index') if isinstance(failed, dict) else failed
                entry_reached = bool(args.entry and (not failed or isinstance(failed_index, int) and failed_index > entry_count))
                if entry_hint and entry_hint.get('frame') and snapshot_result.get('structure', {}).get('frame_reached') is False:
                    entry_reached = False
                if args.entry:
                    from .entries import confirmation
                    snapshot_result.update(entry=args.entry, entry_hint=entry_hint, entry_reached=entry_reached,
                                           route_used={'node': args.node, 'goto': args.goto, 'open_target': args.open_target,
                                                       'steps': args.step[:entry_count - bool(args.goto) - bool(args.open_target)]},
                                           frame_hint=entry_hint.get('frame'), failed_step=failed)
                    if entry_reached:
                        snapshot_result['confirm_command'] = confirmation(args.run, args.entry, entry_hint)
                known = any(c.get("registration") for c in m["cases"].values())
                # Exploration baseline: one row per snapshot (method/where/how long); no page content.
                m.setdefault("exploration", []).append({"node": args.node, "known_page": known,
                                                         "re_explored": known, "at": now(), "started_at": started,
                                                         "duration_ms": int((_time.monotonic() - t0) * 1000),
                                                         "method": "snapshot", "frame": args.frame, "scope": args.scope,
                                                         "open_target": args.open_target, "clicks": len(args.click or []),
                                                         "hover": bool(args.hover), "goto": urlsplit(args.goto or "").path or None,
                                                         "steps_count": len(args.step), "purpose": redact(args.purpose, m["config"]),
                                                         "entry": args.entry, "entry_reached": entry_reached,
                                                         "failed_step": snapshot_result.get("structure", {}).get("failed_step")})
                if args.save_as:
                    from .exploration import save_route
                    save_route(path.parent, m, args, snapshot_result)
                event(m, "snapshot_completed", node=args.node, known_page=known)
                save(path, m)
                return snapshot_result
        cfg = config(profiles.profile_path(args.profile) if args.profile else args.config)
        area = {"page": None, "content-admin": "内容管理", "editor": "编辑网站"}[args.node]
        return profiles.invoke_snapshot(cfg, area=area, manual=args.manual, frame=args.frame, scope=args.scope, open_target=args.open_target, hover=args.hover, clicks=args.click, goto=args.goto, steps=args.step)
    if args.command == "init":
        return workflow.init(args.run_id, profiles.profile_path(args.profile) if args.profile else args.config)
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
                "connection": {"environment": m["config"].get("environment", {}).get("id", "legacy"),
                               "entry_url": m["config"].get("environment", {}).get("entry_url"),
                               "site": m["config"].get("site"), "network_mode": m["config"].get("network", {}).get("mode", "legacy")},
                "questions": [{k: q.get(k) for k in ("id", "kind", "prompt", "case_ids", "status", "choices")}
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
            from .remote_checks import finalize
            if any(row.get('active', True) for row in m.get('remote_checks', {}).values()):
                finalize(path.parent, m)
            save(path, m)
        return result
    with locked_run(args.run) as (path, m):
        require(not m.get("active_batch") or args.command in {"record-run", "recover", "validate", "report", "next", "session-turn"},
                "An execution batch is active; recover it before changing the run")
        before = digest({k: m[k] for k in ("cases", "questions", "sources", "config", "preflight", "contaminated_fixtures")})
        try:
            result = dispatch(args, path, m)
        except UiaError:
            # A refused demo may have queued an entry in the single checklist / async review.
            if args.command == 'question' and args.kind in {'demo', 'record_request'}:
                save(path, m)
            raise
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
