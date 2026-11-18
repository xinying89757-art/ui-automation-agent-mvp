"""Natural-language UI actions that must not be compiled as pointer clicks."""
from __future__ import annotations

import re

_KEYS = {
    "enter": "Enter", "return": "Enter", "回车": "Enter",
    "tab": "Tab", "escape": "Escape", "esc": "Escape",
    "arrowdown": "ArrowDown", "arrowup": "ArrowUp",
    "arrowleft": "ArrowLeft", "arrowright": "ArrowRight",
    "space": "Space", "空格": "Space", "backspace": "Backspace", "delete": "Delete",
}
# A key command names the key after a press verb. A bare label such as "Enter"
# can be a button, so it stays a click.
_PHRASE = re.compile(
    r"^(?:please\s+)?(?:press|hit|tap|按下|按|敲)(?:\s*(?:一下|the|键))?\s*"
    r"(enter|return|回车|tab|escape|esc|arrow\s*down|arrow\s*up|arrow\s*left|arrow\s*right|"
    r"space|空格|backspace|delete)(?:\s*键)?$",
    re.I,
)
_BARE = re.compile(r"^(?:按回车键|按回车|按下回车键|按下回车)$")


def key_from_phrase(text):
    """Return the Playwright key for a press-style phrase, or None when it is not one."""
    if not isinstance(text, str):
        return None
    raw = re.sub(r"\s+", " ", text.strip())
    raw = re.sub(r"^(?:click:text=|text=)", "", raw, flags=re.I)
    raw = raw.lstrip("?？").strip()
    if _BARE.fullmatch(raw):
        return "Enter"
    match = _PHRASE.fullmatch(raw)
    if not match:
        return None
    return _KEYS.get(re.sub(r"\s+", "", match.group(1)).casefold())


def normalize_route_step(step):
    """Rewrite a natural-language press step so promotion does not store it as a click."""
    if isinstance(step, str):
        key = key_from_phrase(step)
        return "press:" + key if key else step
    if isinstance(step, dict) and step.get("verb") in {"click", "press", None}:
        key = key_from_phrase(step.get("value")) or (
            key_from_phrase(step.get("target")) if isinstance(step.get("target"), str) else None)
        if key:
            return {**step, "verb": "press", "target": key, "value": key}
    return step
