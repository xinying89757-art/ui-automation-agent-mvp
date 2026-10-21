from __future__ import annotations

import os
import re
import signal
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .checks import case_errors
from .common import (RESULTS, atomic_write, digest, elapsed, event, file_hash, inside,
                     now, read_json, read_yaml, redact, require, reset_case)
from .workflow import case_version, code_files, question, refresh
from .profiles import network_fingerprint


def process_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return ctypes.get_last_error() == 5
        code = wintypes.DWORD()
        try:
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False


def heartbeat_path(base):
    return Path(base) / "heartbeat.json"


def read_heartbeat(base):
    path = heartbeat_path(base)
    if not path.is_file():
        return None
    try:
        return read_json(path)
    except (OSError, ValueError):
        return None


def write_heartbeat(base, batch, running):
    completed = []
    report = inside(base, batch["directory"]) / "case-results.json"
    if report.is_file():
        try:
            payload = read_json(report)
            completed = [{"case_id": row.get("case_id"), "result": row.get("result")}
                         for row in payload.get("cases", []) if isinstance(row, dict)]
        except (OSError, ValueError):
            completed = []
    body = {"batch_id": batch["id"], "updated_at": now(), "running": running,
            "case_ids": list(batch.get("case_ids") or []), "completed": completed}
    atomic_write(heartbeat_path(base), body)
    atomic_write(inside(base, batch["directory"]) / "heartbeat.json", body)
    return body


def batch_running(base, batch):
    """Heartbeat is the source of truth. A missing PID does not mean the batch died."""
    if not batch:
        return False
    beat = read_heartbeat(base)
    if beat and beat.get("batch_id") == batch.get("id"):
        try:
            age = elapsed(beat.get("updated_at"))
        except (TypeError, ValueError):
            age = None
        if age is not None and beat.get("running") is True and age < 180:
            return True
        if age is not None and beat.get("running") is False and age < 30:
            return True
    if elapsed(batch.get("started_at") or now()) < 20 and process_alive(batch.get("owner_pid")):
        return True
    return False


def ensure_stopped(base, batch):
    require(batch, "No active batch")
    require(not batch_running(base, batch), "The batch heartbeat is fresh; use wait instead of recovering")
    receipt = inside(base, batch["directory"]) / "process.json"
    if receipt.is_file():
        require(not process_alive(read_json(receipt).get("pid")), "The Playwright process is still running")


def case_needs_public(base, case):
    registration = case.get("registration") or {}
    if registration.get("needs_public"):
        return True
    script = registration.get("script")
    if not script:
        return False
    try:
        body = inside(base, script).read_text(encoding="utf-8")
    except OSError:
        return False
    return "waitForPublic(" in body


def preflight(base, m, evidence):
    require(not m.get("active_batch"), "An execution batch is still active")
    cfg = m["config"]
    proof_path = inside(base, evidence)
    require(proof_path.is_file(), "Save real browser preflight evidence inside the run")
    proof = read_json(proof_path)
    targets = cfg.get("targets", {})
    errors = []
    if cfg.get("environment"):
        observed_environment = proof.get("environment", {})
        if (observed_environment.get("environment") != cfg["environment"]["id"] or
                observed_environment.get("entry_url") != cfg["environment"]["entry_url"] or
                observed_environment.get("verified") is not True or
                observed_environment.get("network_fingerprint") != network_fingerprint(cfg)):
            errors.append("Selected environment and network were not verified")
        if cfg["environment"]["id"] == "gray" and "ld-gray" not in observed_environment.get("x_via", "").lower():
            errors.append("Gray response marker is missing")
    if not targets:
        errors.append("Target URLs missing")
    public_error = None
    for name, url in targets.items():
        observed = proof.get("targets", {}).get(name, {})
        if urlsplit(url).hostname.endswith(".invalid"):
            errors.append("Replace the example target: " + name)
        if name == "public":
            reachable = observed.get("url") == url and observed.get("reachable") is True and observed.get("target_visible") is True
            if not reachable:
                public_error = redact(str(observed.get("error") or "public frontend unreachable"), cfg)[:300]
            continue
        if observed.get("url") != url or observed.get("reachable") is not True or observed.get("target_visible") is not True:
            errors.append("Target not verified in the current browser: " + name)
        if observed.get("authenticated") is not True:
            errors.append("Authenticated target access not verified: " + name)
    for name in cfg.get("auth", {}).get("secret_env", []):
        if not os.environ.get(name):
            errors.append("Required environment variable missing: " + name)
    auth = cfg.get("auth", {}).get("storage_state")
    if auth and not Path(auth).is_file():
        errors.append("Storage state reference missing")
    status = "blocked" if errors else "passed"
    public_ok = bool(targets.get("public")) and not public_error
    m["preflight"] = {"status": status, "checked_at": now(), "config_hash": m["config_hash"],
                      "auth_sha256": file_hash(auth) if auth else None,
                      "proxy_sha256": network_fingerprint(cfg),
                      "evidence": evidence, "sha256": file_hash(proof_path), "errors": errors,
                      "capabilities": {"public_frontend": public_ok, "public_error": public_error}}
    if status == "passed" and not public_ok and targets.get("public"):
        affected = [cid for cid, c in m["cases"].items()
                    if c["work_status"] != "finished" and case_needs_public(base, c)]
        if affected:
            question(m, "environment", "public-frontend",
                     "Public front end is unreachable. Only cases that read the public site are waiting. " + (public_error or ""),
                     affected, attempted=[public_error or "public frontend unreachable"], reopen=True)
    if errors:
        affected = [cid for cid, c in m["cases"].items() if c["work_status"] != "finished" and c["stage"] in {"discovery", "execution", "repair"}]
        question(m, "environment", "preflight", "Restore the listed environment prerequisites, then repeat browser preflight.",
                 affected, attempted=errors, reopen=True)
    event(m, "preflight", status=status)
    return m["preflight"]


def begin_batch(base, m, case_ids):
    require(not m.get("active_batch"), "Recover the active batch before starting another")
    refresh(base, m)
    require(case_ids and len(case_ids) == len(set(case_ids)), "Select distinct case IDs")
    require(len(case_ids) <= m["config"]["execution"]["batch_size"], "Selected batch exceeds configured batch size")
    pre = m.get("preflight")
    require(pre and pre["status"] == "passed" and pre["config_hash"] == m["config_hash"], "Run browser preflight first")
    require(file_hash(inside(base, pre["evidence"])) == pre["sha256"], "Preflight evidence changed")
    auth = m["config"].get("auth", {}).get("storage_state")
    require(pre.get("auth_sha256") == (file_hash(auth) if auth else None), "Login state changed; repeat preflight")
    require(all(os.environ.get(name) for name in m["config"].get("auth", {}).get("secret_env", [])),
            "Required secret environment variables are missing")
    cli = base / "runner/node_modules/@playwright/test/cli.js"
    require(cli.is_file(), "Install runner dependencies with npm ci before execution")
    require(all(cid in m["cases"] for cid in case_ids), "Unknown selected case ID")
    selected = [m["cases"][cid] for cid in case_ids]
    caps = (m.get("preflight") or {}).get("capabilities") or {}
    for c in selected:
        require(c["work_status"] == "runnable", "Case is not runnable", c["case_id"])
        require(not set(c["fixture_ids"] or ["case:" + c["case_id"]]) & set(m["contaminated_fixtures"]), "Fixture requires verified recovery", c["case_id"])
        if caps.get("public_frontend") is False and case_needs_public(base, c):
            require(False, "This case reads the public site, which is unreachable",
                    {"case_id": c["case_id"], "error": caps.get("public_error")})
        errors, _ = case_errors(base, c, m["config"], execution=True)
        require(not errors, "Execution gate failed", {"case_id": c["case_id"], "errors": errors})
    # Runtime bindings are a projection of the manifest, not a second mutable truth.
    from .bindings import case_bindings
    bindings = case_bindings(base, m)
    cases_file = base / "state/cases.json"
    atomic_write(cases_file, bindings)
    knowledge_source = base / "runner/knowledge/llms-txt.json"
    knowledge_overlay = base / "state/knowledge/llms-txt.json"
    if knowledge_source.is_file() and not knowledge_overlay.is_file():
        knowledge_overlay.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copyfile(knowledge_source, knowledge_overlay)
    if m["config"]["execution"]["workers"] > 1:
        require(all(c["isolated"] and c["registration"].get("isolation_evidence") and
                    inside(base, c["registration"]["isolation_evidence"]).is_file() for c in selected),
                "Parallel execution requires per-case isolation evidence")
    batch_id = uuid.uuid4().hex
    directory = base / "batches" / batch_id
    directory.mkdir(parents=True)
    versions, snapshot = {}, {}
    for c in selected:
        version = case_version(base, m, c)
        if c.get("version") != version:
            reset_case(c, "execution_version_changed", "execution")
        c.update(version=version, work_status="running")
        versions[c["case_id"]] = version
        for name, sha in code_files(base, c["registration"]).items():
            snapshot[name] = sha
    # Capture the exact source files for this attempt, not just pointers to mutable files.
    import shutil
    for name in snapshot:
        dest = directory / "snapshot/files" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inside(base / "runner", name), dest)
    atomic_write(directory / "snapshot/versions.json", {"versions": versions, "files": snapshot})
    atomic_write(directory / "snapshot/cases.json", {cid: bindings[cid] for cid in case_ids})
    import copy
    snapshot_config = copy.deepcopy(m["config"])
    if snapshot_config.get("network", {}).get("mode") == "pac":
        from .profiles import runtime_root
        pac_source = snapshot_config["network"].get("pac_file") or runtime_root() / "network/gray.pac"
        shutil.copyfile(pac_source, directory / "active.pac")
        snapshot_config["network"]["pac_file"] = str((directory / "active.pac").resolve())
    atomic_write(directory / "config.json", snapshot_config)
    # Playwright compiles file and title filters with the unicode flag, which rejects escaped hyphens.
    pattern = lambda value: re.escape(value).replace("\\-", "-")
    escaped = "|".join(pattern("[" + cid + "]") for cid in case_ids)
    selected_scripts = sorted({str(inside(base, c["registration"]["script"]).relative_to((base / "runner").resolve())).replace("\\", "/") for c in selected})
    # Title grep cannot be anchored: Playwright joins the file suite title in front of the case title.
    command = ["node", str(cli), "test"] + [pattern(name) + "$" for name in selected_scripts] + ["--grep", "(?:" + escaped + ")\\s"]
    batch = {"id": batch_id, "case_ids": case_ids, "versions": versions,
             "owner_pid": os.getpid(),
             "started_at": now(), "directory": str(directory.relative_to(base)),
             "report": str((directory / "case-results.json").relative_to(base)), "command": command}
    m["active_batch"] = batch
    event(m, "batch_started", batch_id=batch_id, case_ids=case_ids)
    return batch


def execute_process(base, batch, cfg):
    import threading
    directory = inside(base, batch["directory"])
    cases_file = Path(base) / "state/cases.json"
    knowledge_overlay = Path(base) / "state/knowledge/llms-txt.json"
    env = dict(os.environ, UIA_BATCH_ID=batch["id"], UIA_CONFIG=str(directory / "config.json"),
               UIA_CASES_FILE=str(cases_file),
               UIA_KNOWLEDGE_FILE=str(knowledge_overlay),
               UIA_RESULTS_DIR=str(directory), UIA_CONTAMINATION_DIR=str(base / "state/contaminated"))
    stop = threading.Event()

    def pump():
        write_heartbeat(base, batch, True)
        while not stop.wait(5):
            write_heartbeat(base, batch, True)

    writer = threading.Thread(target=pump, name="uia-heartbeat", daemon=True)
    writer.start()
    try:
        with (directory / "process.log").open("w", encoding="utf-8") as log:
            os.chmod(directory / "process.log", 0o600)
            proc = subprocess.Popen(batch["command"], cwd=str(base / "runner"), env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, start_new_session=os.name != "nt")
            atomic_write(directory / "process.json", {"pid": proc.pid, "batch_id": batch["id"], "started_at": now()})
            try:
                for line in proc.stdout:
                    log.write(redact(line, cfg))
                    log.flush()
                return proc.wait()
            except BaseException:
                if os.name == "nt":
                    proc.terminate()
                else:
                    os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        proc.kill()
                    else:
                        os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                raise
    finally:
        stop.set()
        writer.join(timeout=1)
        write_heartbeat(base, batch, False)


def consume_batch(base, m, exit_code=None):
    batch = m.get("active_batch")
    require(batch, "No active execution batch")
    report_path = inside(base, batch["report"])
    from .secrets import drop_unsafe_artifacts
    drop_unsafe_artifacts(report_path.parent)
    require(report_path.is_file(), "Reporter output missing; recover with --abandon and saved evidence")
    report = read_json(report_path)
    require(report.get("schema_version") == "uia-batch-results.v1" and report.get("batch_id") == batch["id"],
            "Reporter output is not from this batch")
    require(report.get("complete") is True, "Reporter is still writing a partial batch; wait or abandon after interruption")
    rows = report.get("cases", [])
    ids = [r.get("case_id") for r in rows]
    require(len(ids) == len(set(ids)) and set(ids) <= set(batch["case_ids"]),
            "Unexpected or duplicate case results; inspect test titles and recover the batch")
    by_id = {r["case_id"]: r for r in rows}
    for cid in batch["case_ids"]:
        c = m["cases"][cid]
        row = by_id.get(cid, {"result": "interrupted", "errors": ["No test result emitted"], "lifecycle": {}})
        lifecycle = row.get("lifecycle", {})
        result = row.get("result")
        require(result in RESULTS, "Unknown reporter result")
        clean = lifecycle.get("cleanup_verified") is True
        prepared = lifecycle.get("setup_verified") is True
        current_version = case_version(base, m, c)
        version = batch["versions"][cid]
        if current_version != version:
            result = "interrupted"
            row.setdefault("errors", []).append("Source/dependency changed during execution")
        if result == "passed" and (not prepared or not clean or lifecycle.get("batch_id") != batch["id"] or row.get("retry") != 0):
            result = "automation_failure"
        attempt = {"batch_id": batch["id"], "at": now(), "version": version, "result": result,
                   "evidence": batch["report"], "evidence_sha256": file_hash(report_path),
                   "executed": cid in by_id and row.get("playwright_status") not in {"skipped", None},
                   "setup_verified": prepared, "cleanup_verified": clean,
                   "setup_started": row.get("setup_started", False),
                   "duration_ms": row.get("duration_ms", 0), "errors": row.get("errors", []),
                   "attachments": row.get("attachments", []),
                   "assertions": row.get("assertions", []), "failure_stage": row.get("failure_stage")}
        prior = c["attempts"][-1] if c["attempts"] else None
        c["attempts"].append(attempt)
        if attempt["executed"] and not m.get("first_result_at"):
            m["first_result_at"] = now()
        c["result"] = result
        if result == "passed":
            need = int(m["config"]["execution"]["stability_passes"])
            if c.get("preserve_delivery"):
                c["pass_streak"] = max(c.get("pass_streak", 0), c.get("delivery_pass_streak", 0)) + 1
                c.pop("preserve_delivery", None)
                c.pop("delivery_pass_streak", None)
                c.pop("repair_baseline_script", None)
            else:
                c["pass_streak"] = (c["pass_streak"] + 1 if prior and prior["version"] == version and prior["result"] == "passed" else 1)
            stable = c["pass_streak"] >= need
            c.update(stability="stable" if stable else "candidate", work_status="finished" if stable else "runnable",
                     stage="feedback" if stable else "execution")
            if not m.get("first_pass_at"):
                m["first_pass_at"] = now()
        else:
            if prior and prior.get("result") == "passed" and c.get("pass_streak", 0):
                c["delivery_pass_streak"] = c["pass_streak"]
            c.update(pass_streak=0, stability="unstable", work_status="finished", stage="finished")
            if result in {"environment_blocked", "product_confirmation"}:
                c["work_status"] = "waiting_human"
                question(m, "environment" if result == "environment_blocked" else "product", cid,
                         "Resolve the execution blocker using the saved evidence, then resume this case.", [cid],
                         attempted=row.get("errors", []), reopen=True)
                c["stage"] = "execution"
            elif result == "automation_failure" and clean and c["repair_rounds"] < m["config"]["execution"]["repair_rounds"]:
                c.update(work_status="pending", stage="repair")
        if not clean and c["registration"]["fixture"]["mutates"] and (row.get("setup_started") or cid not in by_id):
            contaminated = c["fixture_ids"] or ["case:" + cid]
            for fid in contaminated:
                m["contaminated_fixtures"][fid] = {"batch_id": batch["id"], "evidence": batch["report"]}
            affected = [other["case_id"] for other in m["cases"].values()
                        if set(other["fixture_ids"] or ["case:" + other["case_id"]]) & set(contaminated)]
            for other_id in affected:
                other = m["cases"][other_id]
                if other["result"] is None:
                    other.update(stage="execution", work_status="waiting_human")
            question(m, "environment", "fixture:" + ",".join(contaminated),
                     "Restore and verify the affected fixtures before resuming dependent cases.", affected,
                     attempted=["cleanup verification failed"], reopen=True)
    batch.update(finished_at=now(), exit_code=exit_code, report_sha256=file_hash(report_path))
    m["batches"].append(batch)
    m["active_batch"] = None
    m["delivery"] = {}
    event(m, "batch_finished", batch_id=batch["id"])
    absorbed = None
    if any(m["cases"][cid]["result"] == "passed" for cid in batch["case_ids"]):
        from .workflow import absorb_locators
        absorbed = absorb_locators(base, m)
    return {"batch_id": batch["id"], "results": {cid: m["cases"][cid]["result"] for cid in batch["case_ids"]},
            "locators": absorbed, "next": "next"}


def abandon_batch(base, m, evidence):
    batch = m.get("active_batch")
    require(batch and inside(base, evidence).is_file(), "Recovery needs an active batch and saved interruption evidence")
    for cid in batch["case_ids"]:
        c = m["cases"][cid]
        c.update(pass_streak=0, stability="unstable", work_status="pending", stage="discovery", result=None)
        c["attempts"].append({"batch_id": batch["id"], "at": now(), "version": batch["versions"][cid],
                              "result": "interrupted", "executed": False, "cleanup_verified": False,
                              "evidence": evidence, "evidence_sha256": file_hash(inside(base, evidence))})
        if c["registration"]["fixture"]["mutates"]:
            for fid in c["fixture_ids"] or ["case:" + cid]:
                m["contaminated_fixtures"][fid] = {"batch_id": batch["id"], "evidence": evidence}
            affected = [other["case_id"] for other in m["cases"].values()
                        if set(other["fixture_ids"] or ["case:" + other["case_id"]]) &
                           set(c["fixture_ids"] or ["case:" + cid])]
            question(m, "environment", "interrupted-fixture:" + cid,
                     "Verify that the interrupted process has stopped; restore and verify its owned data.",
                     affected, attempted=["batch interrupted before cleanup was confirmed"], reopen=True)
    batch.update(finished_at=now(), abandoned=True, evidence=evidence)
    m["batches"].append(batch)
    m["active_batch"] = None
    event(m, "batch_abandoned", batch_id=batch["id"])
    return {"batch_id": batch["id"], "next": "next", "cleanup_verification_required": True}


def repair(base, m, cid, evidence):
    c = m["cases"][cid]
    require(c.get("attempts") and c["attempts"][-1]["result"] == "automation_failure", "Only automation failures enter repair")
    require(c["attempts"][-1].get("cleanup_verified") or c.get("cleanup_recovery", {}).get("batch_id") == c["attempts"][-1]["batch_id"],
            "Restore the fixture before a repair rerun")
    require(c["repair_rounds"] < m["config"]["execution"]["repair_rounds"], "Repair budget exhausted")
    require(inside(base, evidence).is_file(), "Repair needs a saved diagnosis")
    registration = c.get("registration") or {}
    if registration.get("script"):
        script = Path(registration["script"])
        try:
            relative = script.relative_to("runner")
        except ValueError:
            relative = script
        previous = next((b for b in reversed(m.get("batches", []))
                         if b.get("id") == c["attempts"][-1].get("batch_id")), None)
        if previous:
            snapshot = inside(base, previous["directory"]) / "snapshot/files" / relative
            if snapshot.is_file():
                c["repair_baseline_script"] = str(snapshot.relative_to(base))
    c["repair_rounds"] += 1
    c.update(stage="discovery", work_status="pending", pass_streak=0, result=None, stability="unstable")
    event(m, "repair_started", case_id=cid, round=c["repair_rounds"], evidence=evidence)
    return {"case_id": cid, "repair_round": c["repair_rounds"], "next": "generate_and_register"}


def wait_for_batch(run_id, stale_seconds=180):
    """Block until the active batch finishes. Progress comes from heartbeat.json, never from PIDs."""
    import sys
    import time
    from .common import load_run, summary
    announced = None
    started = time.monotonic()
    while True:
        _path, manifest = load_run(run_id)
        base = _path.parent
        active = manifest.get("active_batch")
        beat = read_heartbeat(base)
        if not active:
            print("heartbeat idle", file=sys.stderr, flush=True)
            return {"status": "idle", "summary": summary(manifest), "heartbeat": beat}
        age = None
        if beat and beat.get("batch_id") == active.get("id") and beat.get("updated_at"):
            try:
                age = elapsed(beat["updated_at"])
            except (TypeError, ValueError):
                age = None
        completed = (beat or {}).get("completed") or []
        signature = (len(completed), completed[-1].get("case_id") if completed else None)
        if signature != announced:
            announced = signature
            last = (str(completed[-1].get("case_id")) + " " + str(completed[-1].get("result"))) if completed else "starting"
            age_text = "n/a" if age is None else str(int(age)) + "s"
            print("heartbeat batch={0} completed={1}/{2} last={3} age={4}".format(
                str(active.get("id"))[:8], len(completed), len(active.get("case_ids") or []), last, age_text),
                file=sys.stderr, flush=True)
        if beat and beat.get("batch_id") == active.get("id") and beat.get("running") is False:
            if age is not None and age < 60:
                time.sleep(2)
                continue
            require(False, "Batch heartbeat says it stopped, but the run is still active. Inspect heartbeat.json before recover")
        fresh = age is not None and age < stale_seconds
        starting = beat is None and elapsed(active.get("started_at") or now()) < stale_seconds
        if not fresh and not starting:
            require(False, "Batch heartbeat is stale. Do not infer death from a missing PID; inspect heartbeat.json")
        if time.monotonic() - started > 6 * 60 * 60:
            require(False, "wait exceeded 6 hours")
        time.sleep(5)
