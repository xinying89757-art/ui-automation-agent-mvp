"""Remove session snapshots from delivery. Page traces repeat tokens and contact details."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from .common import redact

UNSAFE_NAMES = {"error-context.md", "trace.zip", "playwright-results.json"}
UNSAFE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".webm"}
UNSAFE_DIRS = {"playwright-report", "traces"}
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
QUERY_SECRET = re.compile(r"(?i)(authorization|token|access_token|password)=[^&\s\"']+")
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
PIN = re.compile(r"(PIN码[:：]\s*)\S+")
PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def scrub_text(value, cfg=None):
    text = redact(str(value), cfg or {})
    text = JWT.sub("[REDACTED]", text)
    text = QUERY_SECRET.sub(r"\1=[REDACTED]", text)
    text = EMAIL.sub("[email]", text)
    text = PIN.sub(r"\1[REDACTED]", text)
    text = PHONE.sub("[phone]", text)
    text = ANSI.sub("", text)
    return text


def unsafe_artifact(path: Path) -> bool:
    if path.name in UNSAFE_NAMES or path.suffix.lower() in UNSAFE_SUFFIXES:
        return True
    return any(part in UNSAFE_DIRS for part in path.parts)


def unsafe_attachment(item) -> bool:
    name = str((item or {}).get("name") or "")
    ref = str((item or {}).get("path") or "")
    if name in {"screenshot", "trace", "error-context", "video"}:
        return True
    return bool(ref) and unsafe_artifact(Path(ref))


def drop_unsafe_artifacts(root: Path) -> int:
    """Delete traces, screenshots, and Playwright page snapshots. Keep result JSON."""
    removed = 0
    if not root.exists():
        return removed
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            continue
        if "node_modules" in path.parts:
            continue
        if path.is_dir() and path.name in UNSAFE_DIRS:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
            continue
        if path.is_file() and unsafe_artifact(path):
            path.unlink(missing_ok=True)
            removed += 1
    return removed
