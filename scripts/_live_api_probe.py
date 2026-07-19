#!/usr/bin/env python3
"""Hit live health/agents/meetings/templates using scripts/.demo_login.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LOGIN_PATH = ROOT / ".demo_login.json"
TOKEN_PATH = ROOT / ".demo_token"
BASE = "https://www.aibusinessagent.xyz"
TIMEOUT = 60
REPORT_PATH = ROOT / "live_api_probe_report.json"


def load_login() -> dict:
    return json.loads(LOGIN_PATH.read_text(encoding="utf-8"))


def save_login(login: dict, token: str) -> None:
    login = dict(login)
    login["api_key"] = token
    LOGIN_PATH.write_text(json.dumps(login, indent=2) + "\n", encoding="utf-8")
    TOKEN_PATH.write_text(token, encoding="utf-8")


def req(method: str, path: str, token: str | None = None, body: dict | None = None):
    url = BASE + path
    data = None
    headers = {"Accept": "application/json", "User-Agent": "demo-live-probe/1.6"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-API-Key"] = token
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = int(getattr(resp, "status", None) or resp.getcode())
            try:
                return code, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return code, raw
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return int(e.code), parsed
    except (URLError, TimeoutError, OSError) as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def extract_items(body):
    if isinstance(body, list):
        return body, None
    if isinstance(body, dict):
        for key in ("meetings", "agents", "templates", "items", "data", "results"):
            if isinstance(body.get(key), list):
                return body[key], key
    return None, None


def summarize_list(items, limit=8):
    sample = []
    for it in (items or [])[:limit]:
        if not isinstance(it, dict):
            continue
        sample.append(
            {
                "id": it.get("id"),
                "name": it.get("name") or it.get("title") or it.get("slug"),
                "role": it.get("role"),
                "status": it.get("status"),
            }
        )
    return sample


def probe_collection(path: str, token: str | None) -> dict:
    code, body = req("GET", path, token=token)
    items, wrapper = extract_items(body)
    if code == 200 and items is not None:
        return {
            "path": path,
            "status": code,
            "ok": True,
            "count": len(items),
            "wrapper_key": wrapper,
            "sample": summarize_list(items),
        }
    detail = body
    if isinstance(body, dict):
        detail = body.get("detail", body)
    elif isinstance(body, str) and ("<!DOCTYPE" in body or "<html" in body[:200].lower()):
        detail = "HTML SPA fallback"
    return {
        "path": path,
        "status": code,
        "ok": False,
        "detail": detail if not isinstance(detail, (dict, list)) else json.dumps(detail)[:300],
    }


def main() -> int:
    login = load_login()
    file_key = (login.get("api_key") or "").strip()
    email = login.get("email")
    password = login.get("password")

    print("CREDS")
    print(f"  path={LOGIN_PATH}")
    print(f"  email={email}")
    print(f"  user_id={login.get('user_id')}")
    print(f"  agent_id={login.get('agent_id')}")
    print(f"  api_key={(file_key[:16] + '...') if file_key else '(empty)'}")
    print(f"  BASE={BASE}")
    print()

    report: dict = {
        "base": BASE,
        "email": email,
        "user_id": login.get("user_id"),
        "agent_id": login.get("agent_id"),
        "api_key_prefix": file_key[:16] if file_key else "",
        "auth_source": None,
        "endpoints": {},
    }

    # 1) health
    code, health = req("GET", "/api/health")
    health_ok = code == 200 and isinstance(health, dict) and health.get("ok") is True
    health_summary = health if isinstance(health, dict) else {"raw": str(health)[:300]}
    report["endpoints"]["health"] = {
        "path": "/api/health",
        "status": code,
        "ok": health_ok,
        "body": health_summary,
    }
    label = "PASS" if health_ok else "FAIL"
    print(f"{label:4}  GET /api/health  status={code}")
    if isinstance(health, dict):
        print(
            f"      ok={health.get('ok')} env={health.get('environment')} "
            f"version={health.get('version')} meetings={health.get('meetings')} "
            f"features={health.get('features')}"
        )
    else:
        print(f"      {health}")
    print()

    # 2) try file api_key first (avoid login spam / key rotation races)
    token = file_key or None
    auth_source = "file_api_key" if token else None
    agents = probe_collection("/api/agents/", token) if token else {
        "path": "/api/agents/",
        "status": 0,
        "ok": False,
        "detail": "no api_key in .demo_login.json",
    }

    if not agents.get("ok"):
        print(
            f"WARN  file api_key failed for agents: "
            f"status={agents.get('status')} detail={agents.get('detail')}"
        )
        print("      refreshing via POST /api/auth/login ...")
        code, body = req(
            "POST",
            "/api/auth/login",
            body={"email": email, "password": password},
        )
        new_tok = None
        if isinstance(body, dict):
            new_tok = body.get("token") or body.get("api_key")
        report["login_refresh"] = {
            "status": code,
            "ok": bool(new_tok),
            "user": body.get("user") if isinstance(body, dict) else None,
            "detail": None if new_tok else (body if not isinstance(body, dict) else body.get("detail", body)),
        }
        if new_tok:
            token = new_tok
            auth_source = "login_refresh"
            save_login(login, new_tok)
            if isinstance(body, dict) and isinstance(body.get("user"), dict):
                report["user_id"] = body["user"].get("id", report.get("user_id"))
            print(f"PASS  POST /api/auth/login  status={code} token_prefix={new_tok[:16]}")
            print("      refreshed .demo_login.json + .demo_token")
        else:
            print(f"FAIL  POST /api/auth/login  status={code} detail={report['login_refresh'].get('detail')}")
            token = None
        print()

    report["auth_source"] = auth_source
    report["api_key_prefix"] = (token or "")[:16]

    # 3) authenticated endpoints
    for key, path in (
        ("agents", "/api/agents/"),
        ("meetings", "/api/meetings/"),
        ("templates", "/api/templates/"),
    ):
        result = probe_collection(path, token)
        # if we already probed agents with file key and it passed, reuse
        if key == "agents" and agents.get("ok") and auth_source == "file_api_key":
            result = agents
        report["endpoints"][key] = result
        label = "PASS" if result.get("ok") else "FAIL"
        extra = f"count={result['count']}" if "count" in result else f"detail={result.get('detail')}"
        print(f"{label:4}  GET {path}  status={result.get('status')}  {extra}")
        for row in result.get("sample") or []:
            print(
                f"        - id={row.get('id')} name={row.get('name')} "
                f"role={row.get('role') or ''} status={row.get('status') or ''}".rstrip()
            )
        print()

    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("=== CANONICAL SUMMARY ===")
    failed = 0
    for key in ("health", "agents", "meetings", "templates"):
        ep = report["endpoints"][key]
        ok = bool(ep.get("ok"))
        if not ok:
            failed += 1
        label = "PASS" if ok else "FAIL"
        if "count" in ep:
            print(f"{label:4} {key:10} status={ep.get('status')} count={ep.get('count')}")
        else:
            detail = ""
            if key == "health" and isinstance(ep.get("body"), dict):
                detail = f" ok={ep['body'].get('ok')} env={ep['body'].get('environment')}"
            else:
                detail = f" {ep.get('detail') or ''}"
            print(f"{label:4} {key:10} status={ep.get('status')}{detail}")
    print()
    print(f"auth_source={auth_source}")
    print(f"Wrote {REPORT_PATH}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
