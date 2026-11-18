"""Environment preflight: login, target site, and the content editor, before any case runs.

Credentials are read only by the login helper from the environment and the gitignored
`.auth/` profile. This module never accepts a password, token, or account value.
"""
from __future__ import annotations

from .common import UiaError, event, now
from .failure_class import failure_class
from .secrets import scrub_text


def _problems(payload):
    """Extra checks the live login helper reports. An empty payload keeps the legacy evidence gate."""
    if not isinstance(payload, dict) or not payload:
        return []
    problems = []
    status = payload.get("status")
    if status and status not in {"authenticated", "environment_verified"}:
        problems.append(payload.get("error") or "登录未完成")
    if "editor" in payload and not (payload.get("editor") or {}).get("opened"):
        problems.append((payload.get("editor") or {}).get("error") or "内容编辑器未打开")
    site = payload.get("site") or {}
    if site and not (site.get("reachable") and site.get("selected")):
        problems.append(site.get("error") or "SITE_NOT_ACCESSIBLE 未找到目标网站")
    if "editor" in payload:
        admin = (payload.get("targets") or {}).get("admin") or {}
        if admin and not admin.get("selected_site") and admin.get("selection") not in {"card", "platform", "selected"}:
            problems.append("SITE_NOT_ACCESSIBLE 未找到目标网站")
    code = payload.get("code")
    if code and failure_class(str(code)) == "environment":
        problems.append(payload.get("error") or str(code))
    return problems


def release_environment_block(m):
    """A later successful preflight returns cases that were stopped only by the environment gate."""
    if m.get("batch_outcome") != "environment_blocked":
        return
    m.pop("batch_outcome", None)
    for case in m.get("cases", {}).values():
        if not case.get("environment_preflight_block"):
            continue
        case.update(result=None, stage="execution", work_status="pending", stability="not_run", failure_class=None)
        case.pop("environment_preflight_block", None)
        case.pop("classification", None)


def block_batch(m, reason, evidence=None):
    """Mark the whole run environment-blocked and finish every case that has not already passed."""
    text = scrub_text(str(reason or "环境预检失败"), m.get("config"))
    m["batch_outcome"] = "environment_blocked"
    m["environment_preflight"] = {
        "status": "blocked", "reason": text, "failure_class": "environment",
        "evidence": evidence, "checked_at": now(),
        "checks": {"login": False, "site": False, "editor": False},
    }
    for case in m.get("cases", {}).values():
        if case.get("result") == "passed" and case.get("work_status") == "finished":
            continue
        case.update(result="environment_blocked", stage="finished", work_status="finished",
                    pass_streak=0, stability="not_run", failure_class="environment",
                    environment_preflight_block=True,
                    classification={"reason": text, "failure_class": "environment", "evidence": evidence,
                                    "source": "environment_preflight", "at": now()})
    event(m, "environment_preflight_blocked", reason=text)
    return m["environment_preflight"]


def ensure_environment(base, m, probe=None):
    """Run login, site selection, and editor open. Return the block record, or None when the gate passes.

    `probe` is a test double `(base, manifest, evidence_path) -> payload`. The default probe
    calls the project login helper, which reads credentials from `.auth/` or the environment.
    """
    evidence = "evidence/environment-preflight-" + now().replace(":", "-") + ".json"
    try:
        if probe:
            payload = probe(base, m, evidence)
        else:
            from . import profiles, runtime
            payload = profiles.invoke_login(m["config"], base / "runner", evidence=base / evidence, open_editor=True)
            runtime.preflight(base, m, evidence)
    except UiaError as error:
        return block_batch(m, str(error), evidence)
    pre = m.get("preflight") or {}
    if pre.get("status") not in {None, "passed"}:
        return block_batch(m, "；".join(pre.get("errors") or ["环境预检未通过"]), pre.get("evidence") or evidence)
    problems = _problems(payload if isinstance(payload, dict) else {})
    if problems:
        return block_batch(m, "；".join(problems), evidence)
    release_environment_block(m)
    m["environment_preflight"] = {
        "status": "passed", "checked_at": now(), "evidence": evidence, "failure_class": None,
        "checks": {"login": True, "site": True, "editor": True},
    }
    event(m, "environment_preflight_passed")
    return None
