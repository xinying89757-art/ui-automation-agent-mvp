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
                     now, read_json, redact, require, reset_case)
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


def ensure_stopped(base, batch):
    require(batch, "No active batch")
    require(not process_alive(batch.get("owner_pid")), "The batch owner is still running; monitor instead of recovering")
    receipt = inside(base, batch["directory"]) / "process.json"
    if receipt.is_file():
        require(not process_alive(read_json(receipt).get("pid")), "The Playwright process is still running")


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
    for name, url in targets.items():
        observed = proof.get("targets", {}).get(name, {})
        if urlsplit(url).hostname.endswith(".invalid"):
            errors.append("Replace the example target: " + name)
        if observed.get("url") != url or observed.get("reachable") is not True or observed.get("target_visible") is not True:
            errors.append("Target not verified in the current browser: " + name)
        if name != "public" and observed.get("authenticated") is not True:
            errors.append("Authenticated target access not verified: " + name)
    for name in cfg.get("auth", {}).get("secret_env", []):
        if not os.environ.get(name):
            errors.append("Required environment variable missing: " + name)
    auth = cfg.get("auth", {}).get("storage_state")
    if auth and not Path(auth).is_file():
        errors.append("Storage state reference missing")
    status = "blocked" if errors else "passed"
    m["preflight"] = {"status": status, "checked_at": now(), "config_hash": m["config_hash"],
                      "auth_sha256": file_hash(auth) if auth else None,
                      "proxy_sha256": network_fingerprint(cfg),
                      "evidence": evidence, "sha256": file_hash(proof_path), "errors": errors}
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
    for c in selected:
        require(c["work_status"] == "runnable", "Case is not runnable", c["case_id"])
        require(not set(c["fixture_ids"] or ["case:" + c["case_id"]]) & set(m["contaminated_fixtures"]), "Fixture requires verified recovery", c["case_id"])
        errors, _ = case_errors(base, c, m["config"], execution=True)
        require(not errors, "Execution gate failed", {"case_id": c["case_id"], "errors": errors})
    # Runtime bindings are a projection of the manifest, not a second mutable truth.
    bindings = {cid: {"case_id": cid, "hooks": c["registration"]["fixture"]["hooks"],
                      "mutates": c["registration"]["fixture"]["mutates"], "isolated": c["isolated"],
                      "fixture_ids": c["fixture_ids"], "flow_ids": c["flow_ids"]}
                for cid, c in m["cases"].items() if c.get("registration")}
    atomic_write(base / "runner/cases.json", bindings)
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
    escaped = "|".join(re.escape("[" + cid + "]") for cid in case_ids)
    selected_scripts = sorted({str(inside(base, c["registration"]["script"]).relative_to(base / "runner")).replace("\\", "/") for c in selected})
    command = ["node", str(cli), "test"] + [re.escape(name) + "$" for name in selected_scripts] + ["--grep", "^(?:" + escaped + ")\\s"]
    batch = {"id": batch_id, "case_ids": case_ids, "versions": versions,
             "owner_pid": os.getpid(),
             "started_at": now(), "directory": str(directory.relative_to(base)),
             "report": str((directory / "case-results.json").relative_to(base)), "command": command}
    m["active_batch"] = batch
    event(m, "batch_started", batch_id=batch_id, case_ids=case_ids)
    return batch


def execute_process(base, batch, cfg):
    directory = inside(base, batch["directory"])
    env = dict(os.environ, UIA_BATCH_ID=batch["id"], UIA_CONFIG=str(directory / "config.json"),
               UIA_RESULTS_DIR=str(directory), UIA_CONTAMINATION_DIR=str(base / "state/contaminated"))
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


def consume_batch(base, m, exit_code=None):
    batch = m.get("active_batch")
    require(batch, "No active execution batch")
    report_path = inside(base, batch["report"])
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
                   "attachments": row.get("attachments", [])}
        prior = c["attempts"][-1] if c["attempts"] else None
        c["attempts"].append(attempt)
        if attempt["executed"] and not m.get("first_result_at"):
            m["first_result_at"] = now()
        c["result"] = result
        if result == "passed":
            c["pass_streak"] = (c["pass_streak"] + 1 if prior and prior["version"] == version and prior["result"] == "passed" else 1)
            stable = c["pass_streak"] >= 2
            c.update(stability="stable" if stable else "candidate", work_status="finished" if stable else "runnable",
                     stage="feedback" if stable else "execution")
            if not m.get("first_pass_at"):
                m["first_pass_at"] = now()
        else:
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
    return {"batch_id": batch["id"], "results": {cid: m["cases"][cid]["result"] for cid in batch["case_ids"]}, "next": "next"}


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
    c["repair_rounds"] += 1
    c.update(stage="discovery", work_status="pending", pass_streak=0, result=None, stability="unstable")
    event(m, "repair_started", case_id=cid, round=c["repair_rounds"], evidence=evidence)
    return {"case_id": cid, "repair_round": c["repair_rounds"], "next": "generate_and_register"}
