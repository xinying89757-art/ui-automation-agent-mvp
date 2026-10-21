from __future__ import annotations

import contextlib
import copy
import datetime as dt
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RESULTS = {"passed", "business_failure", "automation_failure", "environment_blocked",
           "product_confirmation", "not_suitable", "interrupted"}
DEFAULTS = {"batch_size": 10, "workers": 1, "stability_passes": 2, "repair_rounds": 2,
            "exploration_minutes_per_flow": 10, "strategies_per_gap": 2, "timeout_ms": 180000}


class UiaError(Exception):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details


def require(condition, message, details=None):
    if not condition:
        raise UiaError(message, details)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def elapsed(start, end=None):
    return max(0.0, (dt.datetime.fromisoformat(end or now()) -
                     dt.datetime.fromisoformat(start)).total_seconds())


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(value).hexdigest()


def file_hash(path):
    p = Path(path)
    return digest(p.read_bytes()) if p.is_file() else None


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def atomic_write(path, value, as_yaml=False):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    content = (yaml.safe_dump(value, allow_unicode=True, sort_keys=False) if as_yaml else
               json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def safe_id(text):
    slug = re.sub(r"[^\w.-]+", "-", str(text), flags=re.UNICODE).strip(".-")[:72]
    return slug or "case"


def inside(base, value):
    base = Path(base).resolve()
    target = (base / value).resolve()
    require(target == base or base in target.parents, "Path escapes its workspace", str(value))
    return target


def run_path(value):
    p = Path(value)
    if p.is_file():
        return p.resolve()
    if p.is_dir():
        return (p / "run.json").resolve()
    require(p.name == str(value) and value not in {".", ".."}, "Use a run ID or manifest path")
    return ROOT / "runs" / value / "run.json"


def load_run(value):
    p = run_path(value)
    require(p.is_file(), "Run does not exist", str(p))
    m = read_json(p)
    require(m.get("schema_version") == "uia-run.v1", "Unsupported run manifest")
    return p, m


@contextlib.contextmanager
def locked_run(value):
    path = run_path(value)
    lock = path.with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    # OS locks release automatically after interruption; support both local desktop families.
    with lock.open("a") as handle:
        if os.name == "nt":
            import msvcrt
            if lock.stat().st_size == 0:
                handle.write(" ")
                handle.flush()
        else:
            import fcntl
        deadline = time.monotonic() + 10
        while True:
            try:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                require(time.monotonic() < deadline, "Run is busy; retry after the current command")
                time.sleep(0.05)
        try:
            p, m = load_run(path)
            yield p, m
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def config(path):
    p = Path(path).resolve()
    data = read_yaml(p)
    require(data.get("schema_version") == "uia-config.v1", "Expected uia-config.v1")
    from .profiles import presets, site_url, connection_settings
    supplied = data.get("environment")
    if supplied:
        supplied = {"id": supplied} if isinstance(supplied, str) else supplied
        require(isinstance(supplied, dict) and supplied.get("id") in presets(), "Unknown environment")
        preset = presets()[supplied["id"]]
        data["environment"] = {k: copy.deepcopy(v) for k, v in {**preset, **supplied}.items() if k != "network"}
        data["network"] = {**preset["network"], **data.get("network", {})}
        data["targets"] = {"admin": data["environment"]["cloud_url"], **data.get("targets", {})}
        if data.get("site"):
            from urllib.parse import urlsplit
            url = site_url(data["site"], urlsplit(data["environment"]["entry_url"]).scheme)
            data["site"] = urlsplit(url).netloc
            data["targets"].setdefault("public", url)
        for key in ("entry_url", "login_url", "cloud_url"):
            from urllib.parse import urlsplit
            u = urlsplit(data["environment"][key])
            require(u.scheme in {"http", "https"} and u.hostname and not u.username and not u.password,
                    "Environment entries must be HTTP(S) URLs without credentials")
            if supplied["id"] == "production":
                require(u.scheme == "https", "Production entries require HTTPS")
        if supplied["id"] == "gray":
            require(urlsplit(data["environment"]["entry_url"]).scheme == "http", "Gray must start from HTTP")
            data["environment"]["required_header"] = copy.deepcopy(preset["required_header"])
        require(data["targets"]["admin"] == data["environment"]["cloud_url"],
                "Override environment.cloud_url to change the admin target")
    network = data.get("network")
    if network:
        require(isinstance(network, dict) and network.get("mode") in {"direct", "proxy", "pac"}, "Invalid network mode")
        if data.get("environment", {}).get("id") == "production":
            require(network["mode"] == "direct" and not network.get("ignore_https_errors"), "Production requires direct access and certificate validation")
        if network["mode"] == "proxy":
            from urllib.parse import urlsplit
            u = urlsplit(network.get("server", ""))
            require(u.scheme in {"http", "https", "socks5"} and u.hostname and not u.username and not u.password,
                    "Proxy URL must not contain credentials")
        if network.get("pac_file"):
            network["pac_file"] = str((p.parent / network["pac_file"]).resolve())
    for key in ("targets", "auth", "data_rules", "execution", "mutation"):
        require(isinstance(data.get(key, {}), dict), "Config section must be a mapping", key)
    require(set(data.get("auth", {})) <= {"storage_state", "secret_env", "provider", "credentials_file", "identity"},
            "Authentication accepts local references only")
    require(isinstance(data.get("auth", {}).get("secret_env", []), list) and
            all(isinstance(name, str) for name in data.get("auth", {}).get("secret_env", [])),
            "auth.secret_env must be a list of environment variable names")
    require(isinstance(data.get("mutation", {}).get("scope", []), list), "mutation.scope must be a list")
    require(isinstance(data.get("mutation", {}).get("allowed", False), bool), "mutation.allowed must be a boolean")
    require(all(isinstance(scope, str) for scope in data.get("mutation", {}).get("scope", [])), "Mutation scopes must be strings")
    require(isinstance(data.get("source_roots", []), list) and all(isinstance(r, str) for r in data.get("source_roots", [])),
            "source_roots must be a list of directory references")
    def secret_refs(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if re.search(r"password|passwd|token|secret|credential", str(key), re.I) and child is not None:
                    require(isinstance(child, dict) and isinstance(child.get("env"), str),
                            "Sensitive data rules must use an env reference", str(key))
                secret_refs(child)
        elif isinstance(value, list):
            for child in value:
                secret_refs(child)
    secret_refs(data.get("data_rules", {}))
    for target in data.get("targets", {}).values():
        from urllib.parse import urlsplit
        u = urlsplit(str(target))
        require(u.scheme in {"http", "https"} and u.hostname and not u.username and not u.password,
                "Targets must be HTTP(S) URLs without credentials")
    require(not any(k in data.get("auth", {}) for k in ("password", "token", "cookies")),
            "Use secret_env names and a local storage_state reference")
    cfg = copy.deepcopy(data)
    cfg["proxy_env"] = cfg.get("proxy_env") or "UI_PROXY"
    cfg["execution"] = {**DEFAULTS, **cfg.get("execution", {})}
    for key, value in cfg["execution"].items():
        if key in DEFAULTS:
            require(isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0,
                    "Execution budgets must be positive numbers", key)
    for key in ("batch_size", "workers", "stability_passes", "repair_rounds", "strategies_per_gap", "timeout_ms"):
        require(isinstance(cfg["execution"][key], int), "Execution count must be an integer", key)
    require(cfg["execution"]["stability_passes"] in {1, 2},
            "stability_passes must be 1 for a daily deliverable or 2 for nightly regression")
    state = cfg.get("auth", {}).get("storage_state")
    if state:
        cfg["auth"]["storage_state"] = str((p.parent / state).resolve())
    credential = cfg.get("auth", {}).get("credentials_file")
    if credential:
        credential = (p.parent / credential).resolve()
        cfg["auth"]["credentials_file"] = str(credential)
        require(credential.is_file(), "Local credential reference is missing")
        account = read_json(credential).get("account")
        require(isinstance(account, str) and account.strip(), "Local credentials need an account")
        cfg["auth"]["identity"] = hashlib.sha256(account.strip().encode()).hexdigest()
    cfg["connection_fingerprint"] = digest(connection_settings(cfg))
    cfg["source_roots"] = [str((p.parent / r).resolve()) for r in cfg.get("source_roots", [])]
    return cfg


def execution_config_fingerprint(cfg):
    # Restoring authentication does not rewrite historical business results.
    return digest({k: cfg.get(k) for k in ("targets", "data_rules", "mutation", "proxy_env", "connection_fingerprint")})


def env_fingerprints(value):
    """Fingerprint environment-backed data without copying its values into artifacts."""
    found = {}
    if isinstance(value, dict):
        if isinstance(value.get("env"), str):
            found[value["env"]] = digest(os.environ.get(value["env"]))
        for child in value.values():
            found.update(env_fingerprints(child))
    elif isinstance(value, list):
        for child in value:
            found.update(env_fingerprints(child))
    return found


def sensitive_env_names(cfg):
    names = set(cfg.get("auth", {}).get("secret_env", []))
    def visit(value, sensitive=False):
        if isinstance(value, dict):
            if sensitive and isinstance(value.get("env"), str):
                names.add(value["env"])
            for key, child in value.items():
                visit(child, sensitive or bool(re.search(r"password|passwd|secret|token|credential|api_key", str(key), re.I)))
        elif isinstance(value, list):
            for child in value:
                visit(child, sensitive)
    visit(cfg.get("data_rules", {}))
    return names


def event(m, kind, **details):
    m["history"].append({"at": now(), "kind": kind, **details})


def summary(m):
    cases = list(m["cases"].values())
    counts = {result: sum(c.get("result") == result for c in cases) for result in sorted(RESULTS)}
    attempted = sum(any(a.get("executed") and a.get("version") == c.get("version")
                        for a in c.get("attempts", [])) for c in cases)
    stable = sum(c.get("stability") == "stable" for c in cases)
    passed = counts["passed"]
    total = len(cases)
    return {"total": total, "finished": sum(c["work_status"] == "finished" for c in cases),
            "results": counts, "executed": attempted, "stable": stable,
            "execution_coverage": attempted / total if total else 0,
            "pass_rate": passed / attempted if attempted else 0,
            "stability_rate": stable / total if total else 0}


def save(path, m):
    m["updated_at"] = now()
    m["summary"] = summary(m)
    cases = list(m["cases"].values())
    source_gaps = any(src.get("unresolved_sheets") for src in m["sources"])
    open_questions = any(q["status"] == "open" for q in m["questions"].values())
    if m.get("source_update_required"):
        m["status"] = "active"
    elif source_gaps and not any(c["work_status"] not in {"finished", "waiting_human"} for c in cases):
        m["status"] = "waiting_human"
    elif cases and all(c["work_status"] == "finished" for c in cases):
        ready = all(m.get("delivery", {}).get(k) for k in ("json", "html", "xlsx", "scripts", "asset_diff"))
        reviewed = all(c.get("feedback") for c in cases if c.get("result") == "passed")
        m["status"] = "completed" if ready and reviewed and not open_questions else "delivery_pending"
    elif cases and all(c["work_status"] in {"finished", "waiting_human"} for c in cases):
        m["status"] = "waiting_human"
    else:
        m["status"] = "active"
    atomic_write(path, m)


def reset_case(c, reason, stage="intent"):
    c.update(stage=stage, work_status="pending", result=None, stability="not_run",
             pass_streak=0, version=None, feedback=None, invalidation_reason=reason)


def redact(text, cfg):
    result = str(text)
    names = sensitive_env_names(cfg)
    credential = cfg.get("auth", {}).get("credentials_file")
    if credential and Path(credential).is_file():
        for value in read_json(credential).values():
            if isinstance(value, str) and value:
                result = result.replace(value, "[REDACTED]")
    for name in names:
        value = os.environ.get(name)
        if value:
            result = result.replace(value, "[REDACTED]")
    return re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~-]+", r"\1[REDACTED]", result)
