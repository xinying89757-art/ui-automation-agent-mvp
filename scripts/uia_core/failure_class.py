"""Separate environment failures from automation, product, and suspended outcomes.

SITE_NOT_ACCESSIBLE / 未找到目标网站, login failures, and timeouts while the
target site is loading are environment. Locator and script failures stay
automation. Business assertions and product confirmation stay product.
"""
from __future__ import annotations

import re

CLASSES = ("environment", "automation", "product", "suspended")

_ENVIRONMENT = re.compile(
    r"UIA_ENVIRONMENT_BLOCKED|SITE_NOT_ACCESSIBLE|未找到目标网站|当前账号下未找到目标网站|"
    r"LOGIN_FAILED|AUTH_REQUIRED|INVALID_CREDENTIALS|CAPTCHA_REQUIRED|LOGIN_FORM_MISSING|"
    r"CREDENTIALS_REQUIRED|MANUAL_LOGIN_TIMEOUT|ACCOUNT_CHANGED|ENVIRONMENT_UNREACHABLE|"
    r"ENVIRONMENT_MISMATCH|ENVIRONMENT_HTTP_ERROR|GRAY_NOT_CONFIRMED|ENVIRONMENT_REQUIRED|"
    r"SITE_PERMISSION_DENIED|SITE_PERMISSION_UNVERIFIED|SITE_AMBIGUOUS|SITE_REQUIRED|"
    r"SITE_AREA_NOT_READY|EDITOR_POPUP_MISSING|登录未完成|登录态已过期|账号或密码错误|"
    r"环境不可达|站点加载超时|net::ERR_|page\.goto:.*Timeout",
    re.I,
)
_LOCATOR = re.compile(
    r"waiting for locator|locator resolved|strict mode violation|UIA_LOCATOR_MISS",
    re.I,
)
_PRODUCT = re.compile(r"UIA_PRODUCT_CONFIRMATION|UIA_SAVE_NOT_PERSISTED|UIA_BUSINESS_FAILURE")
_SUSPENDED = re.compile(r"\bsuspended\b|缺知识|缺控件")
_RESULT = {
    "environment_blocked": "environment",
    "automation_failure": "automation",
    "interrupted": "automation",
    "business_failure": "product",
    "product_confirmation": "product",
    "save_not_persisted": "product",
    "suspended": "suspended",
}


def failure_class(message):
    """Classify an error string. None means the text does not decide a class."""
    text = str(message or "")
    if not text.strip():
        return None
    if _ENVIRONMENT.search(text) and not _LOCATOR.search(text):
        return "environment"
    if _SUSPENDED.search(text) and not _PRODUCT.search(text):
        return "suspended"
    if _PRODUCT.search(text):
        return "product"
    if _LOCATOR.search(text) or re.search(r"UIA_SETUP_FAILED|UIA_CLEANUP_FAILED", text):
        return "automation"
    return None


def class_for_result(result, message=""):
    inferred = failure_class(message)
    mapped = _RESULT.get(result)
    if mapped == "automation" and inferred == "environment":
        return "environment"
    if inferred and not mapped:
        return inferred
    return mapped


def case_class(case):
    explicit = case.get("failure_class")
    if explicit in CLASSES:
        return explicit
    errors = [str(item) for attempt in case.get("attempts") or [] for item in (attempt.get("errors") or [])]
    reason = ""
    classification = case.get("classification") or {}
    if isinstance(classification, dict):
        reason = str(classification.get("reason") or "")
    return class_for_result(case.get("result"), "\n".join([*errors, reason]))


def shares(cases):
    counts = {name: 0 for name in CLASSES}
    for case in cases:
        kind = case_class(case)
        if kind in counts:
            counts[kind] += 1
    total = sum(counts.values())
    return {name: {"count": counts[name], "share": (counts[name] / total if total else 0.0)} for name in CLASSES}
