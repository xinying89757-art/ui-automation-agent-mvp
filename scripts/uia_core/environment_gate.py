"""Live environment preflight: login, target site, and the content editor."""
from __future__ import annotations

import os
import time
from pathlib import Path

from .common import ROOT, UiaError, event, now, read_json, require
from .secrets import scrub_text


def assert_private_credentials(cfg):
    """Passwords stay in ``.auth/`` or named environment variables, never on the command line."""
    auth = cfg.get("auth") or {}
    credential = auth.get("credentials_file")
    names = [name for name in auth.get("secret_env") or [] if isinstance(name, str) and name.strip()]
    if credential:
        path = Path(credential).resolve()
        root = (ROOT / ".auth").resolve()
        require(root == path or root in path.parents, "Credentials must live under .auth/")
        require(path.is_file(), "Credentials file is missing")
        require(path.stat().st_mode & 0o077 == 0, "Credentials file must not be group or world readable")
        return
    require(bool(names), "Credentials must come from .auth/ or environment variables")
    missing = [name for name in names if not os.environ.get(name)]
    require(not missing, "Required credential environment variable is missing")


def block_run(m, error):
    """Mark every case environment-blocked and record the redacted reason."""
    reason = scrub_text(str(error), m.get("config"))[:500]
    details = error.details if isinstance(getattr(error, "details", None), dict) else {}
    code = details.get("code")
    timings = details.get("timings") if isinstance(details.get("timings"), dict) else {}
    timings = {key: int(value) for key, value in timings.items()
               if key in {"authenticated_ms", "editor_ms", "total_ms"}
               and isinstance(value, (int, float)) and not isinstance(value, bool)}
    auth_path = details.get("auth_path") if details.get("auth_path") in {"session", "password"} else None
    if code and code not in reason:
        reason = f"{code}: {reason}"
    m["preflight"] = {**(m.get("preflight") or {}), "status": "blocked", "checked_at": now(),
                      "errors": [reason], "failure_class": "environment",
                      **({"timings_ms": timings} if timings else {}),
                      **({"auth_path": auth_path} if auth_path else {})}
    for case in m.get("cases", {}).values():
        case.update(result="environment_blocked", stage="finished", work_status="finished",
                    pass_streak=0, stability="not_run" if not case.get("attempts") else "unstable",
                    failure_class="environment",
                    classification={"reason": reason, "failure_class": "environment", "at": now(),
                                    **({"code": code} if code else {})})
    m.setdefault("history", [])
    event(m, "environment_blocked", reason=reason, code=code)
    return {"status": "blocked", "failure_class": "environment", "reason": reason, "code": code,
            **({"timings_ms": timings} if timings else {}),
            **({"auth_path": auth_path} if auth_path else {})}


def enforce_editor(base, evidence_rel):
    path = Path(base) / evidence_rel
    if not path.is_file():
        return
    proof = read_json(path)
    if "editor" not in proof:
        return
    require(proof.get("editor", {}).get("opened") is True, "内容编辑器没有打开")
    admin = (proof.get("targets") or {}).get("admin") or {}
    require(admin.get("reachable") is True and admin.get("authenticated") is True, "目标网站不可达或未登录")
    require(admin.get("selected_site") or admin.get("selection"), "目标网站不可选择")


def public_preflight_result(proof, elapsed_seconds):
    """Safe summary. Omits storage paths, cookies, accounts, and page URLs."""
    proof = proof or {}
    editor = proof.get("editor") or {}
    admin = (proof.get("targets") or {}).get("admin") or {}
    environment = proof.get("environment") or {}
    login_ok = proof.get("status") in {"authenticated", "environment_verified"} or environment.get("verified") is True
    site_reachable = admin.get("reachable") is True
    site_selected = bool(admin.get("selected_site") or admin.get("selection"))
    editor_opened = editor.get("opened") is True
    passed = bool(login_ok and site_reachable and site_selected and editor_opened)
    timings = proof.get("timings") or {}
    safe_timings = {key: int(timings[key]) for key in ("authenticated_ms", "editor_ms", "total_ms")
                    if isinstance(timings.get(key), (int, float)) and not isinstance(timings.get(key), bool)}
    return {
        "status": "passed" if passed else "blocked",
        "failure_class": None if passed else "environment",
        "auth_path": "session" if proof.get("reused") else "password" if proof.get("refreshed") else None,
        "checks": {
            "login": bool(login_ok),
            "site_reachable": bool(site_reachable),
            "site_selected": site_selected,
            "editor_opened": editor_opened,
        },
        "environment": environment.get("environment") or environment.get("id"),
        "timings_ms": safe_timings,
        "elapsed_seconds": round(float(elapsed_seconds), 3),
    }


def live_preflight(cfg, runner=None):
    from .profiles import invoke_login
    evidence_dir = ROOT / ".auth" / "preflight"
    evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        evidence_dir.chmod(0o700)
    except OSError:
        pass
    evidence = evidence_dir / ("live-" + now().replace(":", "-") + ".json")
    started = time.perf_counter()
    try:
        invoke_login(cfg, runner=runner, evidence=evidence, open_editor=True)
    except UiaError as error:
        reason = scrub_text(str(error), cfg)[:500]
        code = error.details.get("code") if isinstance(error.details, dict) else None
        if code and code not in reason:
            reason = f"{code}: {reason}"
        details = error.details if isinstance(error.details, dict) else {}
        timings = details.get("timings") if isinstance(details.get("timings"), dict) else {}
        timings = {key: int(value) for key, value in timings.items()
                   if key in {"authenticated_ms", "editor_ms", "total_ms"}
                   and isinstance(value, (int, float)) and not isinstance(value, bool)}
        return {"status": "blocked", "failure_class": "environment", "reason": reason, "code": code,
                "checks": {"login": False, "site_reachable": False, "site_selected": False, "editor_opened": False},
                "timings_ms": timings, "auth_path": details.get("auth_path") if details.get("auth_path") in {"session", "password"} else None,
                "elapsed_seconds": round(time.perf_counter() - started, 3)}
    proof = read_json(evidence) if evidence.is_file() else {}
    result = public_preflight_result(proof, time.perf_counter() - started)
    if result["status"] != "passed":
        result["reason"] = "环境预检未通过：登录、目标网站或内容编辑器未就绪"
    return result


def preflight_run(base, m):
    """Login, select the site, and open the editor. Block the run on failure."""
    from . import runtime
    from .profiles import invoke_login
    from .common import elapsed, file_hash
    # Reuse only a recent passed proof whose evidence, configuration and auth
    # state are unchanged. Any failure falls through to a fresh live check.
    recorded = m.get('preflight') or {}
    evidence = recorded.get('evidence')
    proof_path = Path(base) / evidence if evidence else None
    auth = (m.get('config', {}).get('auth') or {}).get('storage_state')
    try:
        fresh = recorded.get('status') == 'passed' and recorded.get('config_hash') == m.get('config_hash') \
            and recorded.get('auth_sha256') == (file_hash(auth) if auth else None) \
            and proof_path and proof_path.is_file() and file_hash(proof_path) == recorded.get('sha256') \
            and elapsed(recorded.get('checked_at')) <= 300
        if fresh:
            enforce_editor(base, evidence)
            proof = read_json(proof_path)
            summary = public_preflight_result(proof, 0)
            if summary['status'] == 'passed':
                return {**summary, 'evidence': evidence, 'cached': True}
    except (OSError, ValueError, TypeError):
        pass
    evidence = "evidence/go-environment-" + now().replace(":", "-") + ".json"
    try:
        invoke_login(m["config"], base / "runner", evidence=base / evidence, open_editor=True)
        runtime.preflight(base, m, evidence)
        enforce_editor(base, evidence)
    except UiaError as error:
        return block_run(m, error)
    recorded = m.get("preflight") or {}
    if recorded.get("status") == "blocked":
        errors = recorded.get("errors") or ["环境预检未通过"]
        return block_run(m, UiaError("；".join(str(item) for item in errors)))
    proof = read_json(base / evidence) if (base / evidence).is_file() else {}
    if proof.get("editor") is not None:
        summary = public_preflight_result(proof, 0)
        if summary["status"] != "passed":
            return block_run(m, UiaError("环境预检未通过：登录、目标网站或内容编辑器未就绪"))
        return {**summary, "evidence": evidence}
    return {"status": recorded.get("status") or "passed", "evidence": evidence}
