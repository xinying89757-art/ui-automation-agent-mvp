"""Private operator profiles; public presets and PAC are shipped with the runner."""
from __future__ import annotations

import copy
import getpass
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .common import ROOT, atomic_write, read_json, require, safe_id


def runtime_root():
    return ROOT / "assets/playwright-runner"


def presets():
    return read_json(runtime_root() / "environments.json")


def site_url(value, scheme="https"):
    value = value.strip()
    parsed = urlsplit(value if "://" in value else scheme + "://" + value)
    require(parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password,
            "Provide an HTTP(S) website domain without credentials")
    require(parsed.path in {"", "/"} and not parsed.query and not parsed.fragment, "Provide the website domain without a page path")
    return parsed.scheme + "://" + parsed.netloc.lower().rstrip(".")


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
    runner = Path(runner or runtime_root())
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
            require(False, "Login helper did not produce JSON; check Node/browser installation")
        require(result.returncode == 0 and payload.get("ok"), payload.get("error", "Login failed"),
                {"code": payload.get("code"), "choices": payload.get("choices", [])})
        return {k: v for k, v in payload.items() if k != "ok"}
    finally:
        Path(temp).unlink(missing_ok=True)
