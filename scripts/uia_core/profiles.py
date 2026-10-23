"""Private operator profiles; public presets and PAC are shipped with the runner."""
from __future__ import annotations

import copy
import getpass
import hashlib
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .common import ROOT, atomic_write, read_json, require, safe_id


def runtime_root():
    return ROOT / "assets/playwright-runner"


def presets():
    return read_json(runtime_root() / "environments.json")


def _skip_probe(host):
    host = host.lower().rstrip(".")
    return host == "localhost" or host.endswith((".test", ".invalid", ".example", ".localhost"))


def _origin_status(scheme, host):
    request = urllib.request.Request(scheme + "://" + host + "/", method="GET", headers={"User-Agent": "uia-scheme-probe"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return None


def detect_scheme(host, fallback):
    """Pick http or https for a bare domain. Offline and reserved names keep the environment scheme."""
    host = host.lower().rstrip(".")
    if fallback not in {"http", "https"}:
        fallback = "https"
    if _skip_probe(host):
        return fallback
    try:
        socket.getaddrinfo(host, 80, type=socket.SOCK_STREAM)
    except OSError:
        return fallback
    http_status, https_status = _origin_status("http", host), _origin_status("https", host)
    ok = lambda code: isinstance(code, int) and code < 400
    if ok(http_status) and not ok(https_status):
        return "http"
    if ok(https_status) and not ok(http_status):
        return "https"
    return fallback


def site_url(value, scheme="https"):
    value = value.strip()
    explicit = "://" in value
    parsed = urlsplit(value if explicit else scheme + "://" + value)
    require(parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password,
            "Provide an HTTP(S) website domain without credentials")
    require(parsed.path in {"", "/"} and not parsed.query and not parsed.fragment, "Provide the website domain without a page path")
    chosen = parsed.scheme if explicit else detect_scheme(parsed.hostname, scheme if scheme in {"http", "https"} else "https")
    return chosen + "://" + parsed.netloc.lower().rstrip(".")


def profile_path(name):
    require(name == safe_id(name), "Profile name must be a safe directory name")
    return ROOT / ".auth/profiles" / (name + ".local.json")


def setup(name, environment, site, account=None, credentials_file=None, password_env=None):
    require(environment in presets(), "Unknown environment")
    if credentials_file:
        value = read_json(Path(credentials_file).expanduser().resolve())
        require(isinstance(value, dict), "Credentials file must contain a JSON object")
        if account:
            require(account == value.get("account"), "Provided account does not match credentials file")
    else:
        if not account:
            require(sys.stdin.isatty(), "Provide --account or --credentials-file")
            account = input_to_stderr("账号: ")
        password = os.environ.get(password_env) if password_env else None
        if password is None:
            require(sys.stdin.isatty(), "Use a local --credentials-file or --password-env for non-interactive setup")
            password = getpass.getpass("密码（隐藏输入）: ", stream=sys.stderr)
        value = {"account": account, "password": password}
    require(isinstance(value.get("account"), str) and value["account"].strip() and
            isinstance(value.get("password"), str) and value["password"], "Account and password are required")
    identity = hashlib.sha256(value["account"].strip().encode()).hexdigest()
    entry = presets()[environment]
    url = site_url(site, urlsplit(entry["entry_url"]).scheme)
    binding = hashlib.sha256((environment + "\n" + identity + "\n" + urlsplit(url).netloc).encode()).hexdigest()
    destination = profile_path(name)
    credential_path = ROOT / ".auth/credentials" / (name + ".local.json")
    for directory in (ROOT / ".auth", destination.parent, credential_path.parent, ROOT / ".auth/sessions"):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    atomic_write(credential_path, {"account": value["account"].strip(), "password": value["password"]})
    cfg = {"schema_version": "uia-config.v1", "environment": environment, "site": url,
           "targets": {"public": url},
           "auth": {"provider": "leadong", "identity": identity,
                    "credentials_file": "../credentials/" + credential_path.name,
                    "storage_state": "../sessions/" + binding + ".json", "secret_env": []},
           "data_rules": {}, "execution": {}, "mutation": {"allowed": False, "scope": []}}
    if destination.is_file():
        previous = read_json(destination)
        for key in ("source_roots", "data_rules", "execution"):
            if key in previous:
                cfg[key] = copy.deepcopy(previous[key])
        old_environment = previous.get("environment")
        old_id = old_environment.get("id") if isinstance(old_environment, dict) else old_environment
        if old_id == environment:
            cfg["environment"] = copy.deepcopy(old_environment)
            if "network" in previous:
                cfg["network"] = copy.deepcopy(previous["network"])
            if previous.get("site") == url and previous.get("auth", {}).get("identity") == identity:
                cfg["mutation"] = copy.deepcopy(previous.get("mutation", cfg["mutation"]))
    atomic_write(destination, cfg)
    return {"profile": name, "config": str(destination), "environment": environment,
            "entry_url": entry["entry_url"], "site": url, "account_alias": name,
            "next": "login", "status": "configured_not_verified"}


def update_profile(name, site=None, mutation_allowed=None, scope=None, stability_passes=None,
                   editor_data_restorable=False):
    """Record test-site scope, including authorized edits/save/publish; restoration aids repeatability. Never print credentials."""
    destination = profile_path(name)
    require(destination.is_file(), "Profile does not exist; run setup first")
    require(site or mutation_allowed is not None or scope is not None or stability_passes is not None,
            "Provide a site, mutation scope, or stability_passes")
    cfg = read_json(destination)
    environment = cfg.get("environment")
    environment_id = environment.get("id") if isinstance(environment, dict) else environment
    require(environment_id in presets(), "Profile environment is invalid")
    if site:
        fallback = urlsplit(presets()[environment_id]["entry_url"]).scheme
        url = site_url(site, fallback)
        cfg["site"] = url
        cfg.setdefault("targets", {})["public"] = url
    mutation = cfg.setdefault("mutation", {"allowed": False, "scope": []})
    if mutation_allowed is not None:
        mutation["allowed"] = bool(mutation_allowed)
    if scope is not None:
        require(all(isinstance(item, str) and item.strip() for item in scope), "Mutation scopes must be non-empty strings")
        mutation["scope"] = list(scope)
    if stability_passes is not None:
        require(stability_passes in {1, 2}, "stability_passes must be 1 for a daily deliverable or 2 for nightly regression")
        cfg.setdefault("execution", {})["stability_passes"] = stability_passes
    if editor_data_restorable:
        cfg.setdefault("mutation", {})["authorization_profile"] = {
            "mode": "editor_any_data_restore", "approved_by": "Xinying"}
    atomic_write(destination, cfg)
    return {"profile": name, "config": str(destination), "site": cfg.get("site"),
            "public": cfg.get("targets", {}).get("public"), "mutation": mutation,
            "stability_passes": cfg.get("execution", {}).get("stability_passes", 1),
            "authorization_profile": cfg.get("mutation", {}).get("authorization_profile")}


def input_to_stderr(prompt):
    print(prompt, end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().strip()


def connection_settings(cfg):
    """Only semantic connection inputs; never include passwords or auth-state contents."""
    return {"environment": cfg.get("environment"), "network": effective_network(cfg),
            "site": cfg.get("site"), "identity": cfg.get("auth", {}).get("identity"),
            "provider": cfg.get("auth", {}).get("provider")}


def effective_network(cfg):
    n = copy.deepcopy(cfg.get("network"))
    if not n:
        proxy = os.environ.get(cfg.get("proxy_env", "UI_PROXY"))
        n = {"mode": "proxy", "server": proxy} if proxy and proxy.lower() not in {"none", "direct", "off", "false"} else {"mode": "direct"}
    if n.get("mode") == "pac":
        pac = Path(n.get("pac_file") or runtime_root() / "network/gray.pac")
        require(pac.is_file(), "PAC file is missing")
        n["pac_sha256"] = hashlib.sha256(pac.read_bytes()).hexdigest()
    return n


def network_fingerprint(cfg):
    n = effective_network(cfg)
    values = [n["mode"], n.get("server"), bool(n.get("ignore_https_errors")), n.get("pac_sha256")]
    return hashlib.sha256(json.dumps(values, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def invoke_login(cfg, runner=None, check_only=False, force=False, evidence=None, manual=False):
    runner = Path(runner or runtime_root()).resolve()
    require((runner / "node_modules/@playwright/test").is_dir(),
            "Install Node dependencies first: npm --prefix " + str(runner) + " ci")
    # A temporary runtime config contains references only, never a credential value.
    import tempfile
    private_dir = ROOT / ".auth"
    private_dir.mkdir(exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix="session-", suffix=".json", dir=private_dir)
    os.close(fd)
    try:
        atomic_write(temp, cfg)
        command = ["node", str(runner / "scripts/session.mjs"), "--config", temp]
        if check_only:
            command.append("--check-only")
        if force:
            command.append("--force")
        if manual:
            command.append("--manual")
            print("将打开浏览器；请使用当前配置的账号完成登录/验证码，最多等待 10 分钟。", file=sys.stderr, flush=True)
        if evidence:
            command.extend(["--output", str(evidence)])
        result = subprocess.run(command, cwd=runner, capture_output=True, text=True)
        try:
            payload = json.loads(result.stdout)
        except (ValueError, TypeError):
            from .secrets import scrub_text
            diagnostic = scrub_text(result.stderr or "no stdout/stderr", cfg).strip()[:240]
            require(False, "Login helper did not produce JSON; check Node/browser installation",
                    {"exit_code": result.returncode, "diagnostic": diagnostic})
        require(result.returncode == 0 and payload.get("ok"), payload.get("error", "Login failed"),
                {"code": payload.get("code"), "choices": payload.get("choices", [])})
        return {k: v for k, v in payload.items() if k != "ok"}
    finally:
        Path(temp).unlink(missing_ok=True)


def invoke_snapshot(cfg, runner=None, area=None, manual=False, frame=None, scope=None, open_target=None, hover=None, clicks=None, goto=None, steps=None, entry_steps=None):
    runner = Path(runner or runtime_root()).resolve()
    require((runner / "node_modules/@playwright/test").is_dir(),
            "Install Node dependencies first: npm --prefix " + str(runner) + " ci")
    import tempfile
    private_dir = ROOT / ".auth"
    private_dir.mkdir(exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix="snapshot-", suffix=".json", dir=private_dir)
    os.close(fd)
    try:
        atomic_write(temp, cfg)
        command = ["node", str(runner / "scripts/session.mjs"), "--config", temp, "--snapshot"]
        if area:
            command.append(area)
        for flag, value in (("--frame", frame), ("--scope", scope), ("--open-target", open_target), ("--hover", hover), ("--goto", goto)):
            if value:
                command.extend([flag, value])
        if manual:
            command.append("--manual")
        if entry_steps is not None:
            command.extend(['--entry-steps', str(entry_steps)])
        for selector in clicks or []:
            command.extend(["--click", selector])
        for step in steps or []:
            command.extend(["--step", step])
        result = subprocess.run(command, cwd=runner, capture_output=True, text=True, timeout=180 + 10 * len(steps or []))
        try:
            payload = json.loads(result.stdout)
        except (ValueError, TypeError):
            require(False, "Snapshot helper did not produce redacted JSON")
        require(result.returncode == 0 and payload.get("ok"), payload.get("error", "Snapshot failed"),
                {"code": payload.get("code"), "choices": payload.get("choices", [])})
        return {k: v for k, v in payload.items() if k != "ok"}
    finally:
        Path(temp).unlink(missing_ok=True)


def agent_env(base, m):
    """Private config projection; return only variable names and safe paths."""
    from .common import digest
    directory = ROOT / '.auth/agent-env' / digest(str(base.resolve()))[:16]
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    atomic_write(directory / 'config.json', m['config'])
    atomic_write(directory / 'cases.json', {})
    env = {'UIA_CONFIG': str(directory / 'config.json'), 'UIA_CASES_FILE': str(directory / 'cases.json'),
           'UIA_STATE_DIR': str(directory / 'fixture-snapshots'),
           'UIA_KNOWLEDGE_FILE': str((base / 'state/knowledge/llms-txt.json').resolve()),
           'UIA_RESULTS_DIR': str(directory / 'results'), 'UIA_CONTAMINATION_DIR': str(directory / 'contaminated')}
    for file in ('config.json', 'cases.json'):
        (directory / file).chmod(0o600)
    return {'cwd': str(runtime_root()), 'env': env}
