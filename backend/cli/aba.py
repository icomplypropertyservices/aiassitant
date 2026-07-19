#!/usr/bin/env python3
"""
ABA Agent CLI — talk to AI Business Assistant API.

  set ABA_BASE=https://www.aibusinessagent.xyz
  set ABA_TOKEN=aba_...   (from login)
  python -m cli.aba login --email you@x.com --password ...
  python -m cli.aba status
  python -m cli.aba bootstrap
  python -m cli.aba agents
  python -m cli.aba wallets
  python -m cli.aba git list
  python -m cli.aba git connect owner/repo --token ghp_...
  python -m cli.aba git local my-app --path C:\\Users\\...\\repo
  python -m cli.aba machine register
  python -m cli.aba machine list
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Allow `python backend/cli/aba.py` and `python -m cli.aba` from backend/
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_BASE = os.environ.get("ABA_BASE", "https://www.aibusinessagent.xyz").rstrip("/")
CONFIG_DIR = Path.home() / ".aba"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def base_url() -> str:
    cfg = load_config()
    return (os.environ.get("ABA_BASE") or cfg.get("base") or DEFAULT_BASE).rstrip("/")


def token() -> str:
    return (os.environ.get("ABA_TOKEN") or load_config().get("token") or "").strip()


def api(method: str, path: str, body: dict | None = None, auth: bool = True) -> tuple[int, object]:
    url = f"{base_url()}{path if path.startswith('/') else '/api' + path}"
    if not path.startswith("/api") and not path.startswith("http"):
        url = f"{base_url()}/api{path if path.startswith('/') else '/' + path}"
    data = None
    headers = {"Accept": "application/json", "User-Agent": "aba-cli/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if auth:
        t = token()
        if not t:
            print("Not logged in. Run: aba login --email ... --password ...", file=sys.stderr)
            sys.exit(2)
        headers["Authorization"] = f"Bearer {t}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw) if raw else {"error": str(e)}
        except json.JSONDecodeError:
            return e.code, {"error": raw or str(e)}


def pprint(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_login(args):
    code, body = api(
        "POST",
        "/api/auth/login",
        {"email": args.email, "password": args.password},
        auth=False,
    )
    if code >= 400:
        print("Login failed:", body, file=sys.stderr)
        sys.exit(1)
    tok = None
    if isinstance(body, dict):
        tok = body.get("api_key") or body.get("token") or body.get("access_token")
    if not tok:
        print("No API key in response:", body, file=sys.stderr)
        sys.exit(1)
    cfg = load_config()
    cfg["token"] = tok
    cfg["base"] = base_url()
    cfg["email"] = args.email
    save_config(cfg)
    print("Logged in. Token saved to", CONFIG_FILE)
    if isinstance(body, dict) and body.get("user"):
        pprint(body.get("user"))


def cmd_status(_args):
    code, body = api("GET", "/api/cli/status")
    if code >= 400:
        print("Error:", body, file=sys.stderr)
        sys.exit(1)
    pprint(body)


def cmd_bootstrap(_args):
    code, body = api("POST", "/api/cli/bootstrap")
    if code >= 400:
        print("Error:", body, file=sys.stderr)
        sys.exit(1)
    pprint(body)


def cmd_agents(_args):
    code, body = api("GET", "/api/cli/agents")
    if code >= 400:
        print("Error:", body, file=sys.stderr)
        sys.exit(1)
    if isinstance(body, list):
        for a in body:
            print(
                f"{a.get('id'):>4}  {(a.get('hierarchy_role') or ''):12}  "
                f"{(a.get('name') or '')[:40]:40}  co={a.get('company_id')}"
            )
    else:
        pprint(body)


def cmd_wallets(args):
    if args.ensure:
        code, body = api("POST", f"/api/cli/wallets/ensure/{args.ensure}")
    else:
        code, body = api("GET", "/api/cli/wallets")
    if code >= 400:
        print("Error:", body, file=sys.stderr)
        sys.exit(1)
    pprint(body)


def cmd_git(args):
    if args.git_cmd == "list":
        code, body = api("GET", "/api/cli/git/repos")
    elif args.git_cmd == "connect":
        code, body = api(
            "POST",
            "/api/cli/git/connect/github",
            {
                "full_name": args.repo,
                "token": args.token or os.environ.get("GITHUB_TOKEN", ""),
                "local_path": args.path or "",
                "company_id": args.company_id,
                "agent_id": args.agent_id,
            },
        )
    elif args.git_cmd == "local":
        code, body = api(
            "POST",
            "/api/cli/git/connect/local",
            {
                "name": args.name,
                "local_path": args.path,
                "machine_id": args.machine_id,
                "company_id": args.company_id,
                "default_branch": args.branch or "main",
            },
        )
    elif args.git_cmd == "github-list":
        code, body = api(
            "POST",
            "/api/cli/git/github/list",
            {"token": args.token or os.environ.get("GITHUB_TOKEN", ""), "limit": 30},
        )
    else:
        print("Unknown git subcommand", file=sys.stderr)
        sys.exit(2)
    if code >= 400:
        print("Error:", body, file=sys.stderr)
        sys.exit(1)
    pprint(body)


def cmd_machine(args):
    if args.machine_cmd == "list":
        code, body = api("GET", "/api/cli/machines")
    elif args.machine_cmd == "register":
        # Collect local snapshot on this machine
        try:
            from app.local_machine import collect_local_snapshot
            snap = collect_local_snapshot()
        except Exception:
            import platform, socket, os as _os
            snap = {
                "hostname": socket.gethostname(),
                "os": platform.platform(),
                "arch": platform.machine(),
                "cwd": _os.getcwd(),
                "home": _os.path.expanduser("~"),
            }
        code, body = api(
            "POST",
            "/api/cli/machines/register",
            {
                "name": args.name or snap.get("hostname"),
                "kind": args.kind or "local",
                "labels": args.labels or "",
                "snapshot": snap,
                "agent_version": "cli-1.0",
            },
        )
    elif args.machine_cmd == "snapshot":
        try:
            from app.local_machine import collect_local_snapshot
            pprint(collect_local_snapshot())
            return
        except Exception as e:
            print("snapshot error:", e, file=sys.stderr)
            sys.exit(1)
    else:
        print("Unknown machine subcommand", file=sys.stderr)
        sys.exit(2)
    if code >= 400:
        print("Error:", body, file=sys.stderr)
        sys.exit(1)
    pprint(body)


def main(argv=None):
    p = argparse.ArgumentParser(prog="aba", description="AI Business Assistant agent CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    login = sub.add_parser("login", help="Login and store API key")
    login.add_argument("--email", required=True)
    login.add_argument("--password", required=True)
    login.set_defaults(func=cmd_login)

    st = sub.add_parser("status", help="Workspace status")
    st.set_defaults(func=cmd_status)

    boot = sub.add_parser("bootstrap", help="Orchestrator setup 3 companies + wallets")
    boot.set_defaults(func=cmd_bootstrap)

    ag = sub.add_parser("agents", help="List agents")
    ag.set_defaults(func=cmd_agents)

    w = sub.add_parser("wallets", help="List / ensure agent crypto wallets")
    w.add_argument("--ensure", type=int, help="Agent id to ensure wallet")
    w.set_defaults(func=cmd_wallets)

    g = sub.add_parser("git", help="Git repos")
    g.add_argument("git_cmd", choices=["list", "connect", "local", "github-list"])
    g.add_argument("repo", nargs="?", help="owner/repo for connect")
    g.add_argument("name", nargs="?", help="name for local")
    g.add_argument("--token", default="")
    g.add_argument("--path", default="")
    g.add_argument("--branch", default="main")
    g.add_argument("--company-id", type=int, default=None)
    g.add_argument("--agent-id", type=int, default=None)
    g.add_argument("--machine-id", type=int, default=None)
    g.set_defaults(func=cmd_git)

    m = sub.add_parser("machine", help="Local / remote machines")
    m.add_argument("machine_cmd", choices=["list", "register", "snapshot"])
    m.add_argument("--name", default="")
    m.add_argument("--kind", default="local")
    m.add_argument("--labels", default="")
    m.set_defaults(func=cmd_machine)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
