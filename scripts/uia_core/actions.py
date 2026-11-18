"""Shared step normalization for keyboard actions and catalog names."""
from __future__ import annotations

import re

# Catalog ids may include underscores. Dots and hyphens stay valid.
CATALOG_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")

_PREFIX = re.compile(r"^(?:步骤|操作|然后|再|并|并且|最后|请)\s*[:：]?\s*")
_NUMBER = re.compile(r"^\d+\s*[.、)]\s*")
_PRESS_ENTER = re.compile(
    r"(?i)^(?:按(?:下)?|敲(?:一下|下)?|press|hit|strike|tap)\s*(?:the\s+|一下\s*)?(?:enter|return|回车)(?:\s*键)?$"
)


def keyboard_step(text):
    """Return ``press:Enter`` when the whole step is a natural-language Enter keypress."""
    if not isinstance(text, str):
        return None
    raw = text.strip().strip("。.")
    raw = _NUMBER.sub("", raw).strip()
    previous = None
    while raw and raw != previous:
        previous = raw
        raw = _PREFIX.sub("", raw).strip()
    raw = re.sub(r"^click:", "", raw).strip()
    raw = re.sub(r"^(?:text|role)=", "", raw).strip()
    if _PRESS_ENTER.match(raw):
        return "press:Enter"
    return None


def normalize_route_step(step):
    """Keep a press-Enter step from being stored or replayed as a click."""
    if isinstance(step, str):
        return keyboard_step(step) or step
    if isinstance(step, dict):
        blob = " ".join(str(step.get(key) or "") for key in ("target", "value", "text", "name", "action"))
        if step.get("verb") in {None, "click", "press"} and (
            keyboard_step(blob) or keyboard_step(str(step.get("target") or "")) or keyboard_step(str(step.get("value") or ""))
        ):
            return {"verb": "press", "target": "Enter", "value": "Enter"}
    return step
