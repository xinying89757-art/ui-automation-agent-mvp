"""Keep a redacted Playwright action trace without network/resource payloads."""
import json
import re
import sys
import zipfile


SECRET_KEY = re.compile(r"cookie|authorization|token|password|session|secret", re.I)
PRIVATE_FIELDS = {"snapshot", "snapshots", "storagestate", "localstorage", "sessionstorage"}
REDACTIONS = [
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}[.]([A-Za-z0-9_-]{8,})[.]([A-Za-z0-9_-]{8,})"), "[REDACTED]"),
    (re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9_.-]+[.][A-Za-z]{2,}"), "[email]"),
    (re.compile(r"(?<![0-9])1[3-9][0-9]{9}(?![0-9])"), "[phone]"),
    (re.compile(r"\b(?:demo|test|user)[-_][A-Za-z0-9_-]{4,}\b", re.I), "[account]"),
]


def clean(value):
    if isinstance(value, dict):
        return {key: "[REDACTED]" if SECRET_KEY.search(key) else clean(item)
                for key, item in value.items() if key.lower() not in PRIVATE_FIELDS}
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, str):
        for pattern, replacement in REDACTIONS:
            value = pattern.sub(replacement, value)
    return value


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: sanitize-trace.py INPUT.zip OUTPUT.zip")
    # Build the single trace entry after all rows are sanitized.
    source, destination = sys.argv[1:]
    with zipfile.ZipFile(source) as archive:
        rows = []
        for line in archive.read("trace.trace").decode("utf-8", "replace").splitlines():
            try:
                rows.append(json.dumps(clean(json.loads(line)), ensure_ascii=False))
            except (TypeError, ValueError):
                rows.append("[redacted trace record]")
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as output:
        output.writestr("trace.trace", "\n".join(rows) + "\n")
