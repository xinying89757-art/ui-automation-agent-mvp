"""Failure classes: environment, automation, product, and suspended."""
from __future__ import annotations

import re

FAILURE_CLASSES = ("environment", "automation", "product", "suspended")

# Site, login, and environment signals. Generic locator timeouts are not included.
ENVIRONMENT_RE = re.compile(
    r"SITE_NOT_ACCESSIBLE|未找到目标网站|LOGIN_FAILED|LOGIN_FORM_MISSING|INVALID_CREDENTIALS|"
    r"AUTH_REQUIRED|CAPTCHA_REQUIRED|CREDENTIALS_REQUIRED|ACCOUNT_CHANGED|MANUAL_LOGIN_TIMEOUT|"
    r"ENVIRONMENT_UNREACHABLE|ENVIRONMENT_MISMATCH|ENVIRONMENT_HTTP_ERROR|GRAY_NOT_CONFIRMED|"
    r"ENVIRONMENT_REQUIRED|SITE_PERMISSION_DENIED|SITE_PERMISSION_UNVERIFIED|SITE_AMBIGUOUS|"
    r"SITE_AREA_NOT_READY|SITE_REQUIRED|EDITOR_POPUP_MISSING|UIA_ENVIRONMENT_BLOCKED|"
    r"net::ERR_|ERR_CONNECTION|ERR_NAME_NOT_RESOLVED|ERR_TIMED_OUT|ERR_INTERNET_DISCONNECTED|"
    r"站点加载超时|网站不可达|入口不可达|登录超时|目标网站不可达|内容编辑器没有打开",
    re.I,
)
_SITE_TIMEOUT = re.compile(r"timeout", re.I)
_SITE_CONTEXT = re.compile(r"site|website|login|page\.goto|环境入口|目标网站|初始入口|内容编辑器", re.I)


def is_environment(text):
    if not text:
        return False
    value = str(text)
    if ENVIRONMENT_RE.search(value):
        return True
    return bool(_SITE_TIMEOUT.search(value) and _SITE_CONTEXT.search(value))


def judge_result(result, errors):
    """Return ``(result, failure_class)``. Environment signals override an automation label."""
    text = "\n".join(str(item) for item in (errors or []))
    if result == "passed":
        return result, None
    if is_environment(text) and result in {"automation_failure", "interrupted", "environment_blocked", None}:
        return "environment_blocked", "environment"
    if result == "environment_blocked":
        return result, "environment"
    if result in {"business_failure", "save_not_persisted", "product_confirmation"}:
        return result, "product"
    if result == "suspended":
        return result, "suspended"
    if result == "automation_failure":
        return result, "automation"
    return result, None


def failure_class_for_case(case):
    errors = []
    for attempt in case.get("attempts") or []:
        errors.extend(attempt.get("errors") or [])
    classification = case.get("classification") or {}
    if isinstance(classification, dict) and classification.get("reason"):
        errors.append(classification["reason"])
    text = "\n".join(str(item) for item in errors)
    result = case.get("result")
    if result == "passed":
        return None
    if is_environment(text) and result in {"automation_failure", "interrupted", "environment_blocked", None}:
        return "environment"
    stored = case.get("failure_class")
    if stored in FAILURE_CLASSES:
        return stored
    if result == "environment_blocked":
        return "environment"
    if result in {"business_failure", "save_not_persisted", "product_confirmation"}:
        return "product"
    if result == "suspended":
        return "suspended"
    if result == "automation_failure":
        return "automation"
    return None


def class_shares(cases):
    counts = {name: 0 for name in FAILURE_CLASSES}
    for case in cases:
        kind = failure_class_for_case(case)
        if kind in counts:
            counts[kind] += 1
    total = sum(counts.values())
    shares = {name: (counts[name] / total if total else 0.0) for name in FAILURE_CLASSES}
    return {"counts": counts, "shares": shares, "classified": total}
