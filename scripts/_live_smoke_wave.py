#!/usr/bin/env python3
"""Live smoke wave: trial, orchestrator, templates, meetings, agents.

Uses scripts/.demo_login.json against https://www.aibusinessagent.xyz.
Writes scripts/live_smoke_wave.json.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LOGIN_PATH = ROOT / ".demo_login.json"
BASE = "https://www.aibusinessagent.xyz"
OUT = ROOT / "live_smoke_wave.json"
TIMEOUT = 90

login: dict[str, Any] = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
token: str | None = None
t0 = time.time()
checks: list[dict[str, Any]] = []


def record(
    name: str,
    method: str,
    path: str,
    code: int,
    ok: bool,
    detail: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": name,
        "method": method,
        "path": path,
        "status": code,
        "ok": bool(ok),
    }
    if detail is not None:
        row["detail"] = detail
    if extra:
        row.update(extra)
    checks.append(row)
    flag = "PASS" if ok else "FAIL"
    suffix = f" | {detail}" if detail else ""
    print(f"{flag:4} {method} {path} status={code} {name}{suffix}")
    return row


def _http(
    method: str,
    path: str,
    body: dict | None = None,
    auth: bool = True,
    timeout: float = TIMEOUT,
) -> tuple[int, Any]:
    url = BASE + path
    data = None
    headers = {"Accept": "application/json", "User-Agent": "live-smoke-wave/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if auth and token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = int(getattr(resp, "status", None) or resp.getcode())
            try:
                return code, (json.loads(raw) if raw else None)
            except json.JSONDecodeError:
                return code, raw
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            parsed: Any = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return int(e.code), parsed
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def login_fresh() -> bool:
    """Login and store rotated session key (login invalidates previous key)."""
    global token
    code, body = _http(
        "POST",
        "/api/auth/login",
        body={"email": login["email"], "password": login["password"]},
        auth=False,
        timeout=60,
    )
    new_token = None
    user: dict[str, Any] = {}
    if isinstance(body, dict):
        new_token = body.get("api_key") or body.get("token") or body.get("access_token")
        user = body.get("user") if isinstance(body.get("user"), dict) else {}
    if code != 200 or not new_token:
        print(f"  login_fresh failed http={code} body={snip(body)}")
        return False
    token = str(new_token)
    login["api_key"] = token
    if user.get("id") is not None:
        login["user_id"] = user["id"]
    print(
        f"  AUTH login ok prefix={token[:16]}… user={user.get('id')} plan={user.get('plan')}"
    )
    return True


def req(
    method: str,
    path: str,
    body: dict | None = None,
    auth: bool = True,
    timeout: float = TIMEOUT,
    retries: int = 2,
) -> tuple[int, Any]:
    """Authenticated request; re-login on 401 (session key rotation)."""
    global token
    if auth and not token:
        if not login_fresh():
            return 401, {"detail": "login_fresh failed"}
    code, parsed = _http(method, path, body=body, auth=auth, timeout=timeout)
    if auth and code == 401 and retries > 0:
        print(f"  401 on {method} {path} — re-login and retry")
        if login_fresh():
            return req(
                method, path, body=body, auth=auth, timeout=timeout, retries=retries - 1
            )
    return code, parsed

def as_list(body: Any, *keys: str) -> list:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for k in keys:
            v = body.get(k)
            if isinstance(v, list):
                return v
    return []


def snip(body: Any, n: int = 300) -> str:
    if isinstance(body, (dict, list)):
        return json.dumps(body, default=str)[:n]
    return str(body)[:n]


def main() -> int:
    global token

    # 1 health
    code, body = req("GET", "/api/health", auth=False)
    health_ok = code == 200 and isinstance(body, dict) and body.get("ok") is True
    detail = (
        json.dumps(
            {
                k: body.get(k)
                for k in (
                    "ok",
                    "version",
                    "environment",
                    "meetings",
                    "features",
                )
            },
            default=str,
        )
        if isinstance(body, dict)
        else snip(body)
    )
    record("health", "GET", "/api/health", code, health_ok, detail=detail)

    # 2 login (rotates session key)
    login_ok = login_fresh()
    record(
        "login",
        "POST",
        "/api/auth/login",
        200 if login_ok else 401,
        login_ok,
        detail=(
            f"email={login.get('email')} user_id={login.get('user_id')} token_prefix={str(token)[:12]}…"
            if login_ok
            else "login_fresh failed"
        ),
    )

    if not login_ok:
        report = {
            "ok": False,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_sec": round(time.time() - t0, 2),
            "base": BASE,
            "email": login.get("email"),
            "checks": checks,
            "summary": {"login": False},
            "error": "login failed — aborting wave",
        }
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print("WROTE", OUT)
        return 1
    # 3 me
    code, me = req("GET", "/api/auth/me")
    me_ok = code == 200 and isinstance(me, dict)
    plan = me.get("plan") if me_ok else None
    record(
        "auth_me",
        "GET",
        "/api/auth/me",
        code,
        me_ok,
        detail=f"plan={plan} active={me.get('subscription_active') if me_ok else None}",
        extra={
            "plan": plan,
            "subscription_active": me.get("subscription_active") if me_ok else None,
        },
    )

    # 4 trial
    code, trial = req(
        "POST",
        "/api/billing/plan",
        body={"plan": "trial", "company_name": "Live Demo Co"},
    )
    trial_ok = False
    trial_detail = snip(trial)
    if isinstance(trial, dict):
        if code == 200:
            trial_ok = True
        trial_detail = json.dumps(
            {
                k: trial.get(k)
                for k in (
                    "plan",
                    "subscription_active",
                    "already_active",
                    "subscription_expires_at",
                    "detail",
                )
                if k in trial or trial.get(k) is not None
            },
            default=str,
        )[:400]
    # Existing demo account already on trial counts as pass even if re-POST is 402
    if (
        not trial_ok
        and me_ok
        and plan == "trial"
        and me.get("subscription_active")
    ):
        trial_ok = True
        trial_detail = (
            f"already on active trial via /me; billing POST status={code} {trial_detail}"
        )
    record(
        "trial",
        "POST",
        "/api/billing/plan",
        code,
        trial_ok,
        detail=trial_detail,
        extra={
            "plan": trial.get("plan") if isinstance(trial, dict) else plan,
            "already_active": trial.get("already_active")
            if isinstance(trial, dict)
            else None,
            "subscription_active": (
                trial.get("subscription_active")
                if isinstance(trial, dict)
                else (me.get("subscription_active") if me_ok else None)
            ),
        },
    )

    # 5 orchestrator
    code, orch = req(
        "POST", "/api/agents/ensure-orchestrator?bootstrap=true", timeout=180
    )
    orch_id = orch.get("id") if isinstance(orch, dict) else None
    orch_ok = code == 200 and isinstance(orch, dict) and orch_id is not None
    if orch_ok:
        login["agent_id"] = orch_id
    record(
        "orchestrator",
        "POST",
        "/api/agents/ensure-orchestrator?bootstrap=true",
        code,
        orch_ok,
        detail=(
            f"id={orch_id} name={orch.get('name')!r} role={orch.get('hierarchy_role')} "
            f"bootstrap_error={orch.get('bootstrap_error')}"
            if isinstance(orch, dict)
            else snip(orch)
        ),
        extra={
            "agent_id": orch_id,
            "agent_name": orch.get("name") if isinstance(orch, dict) else None,
            "hierarchy_role": orch.get("hierarchy_role")
            if isinstance(orch, dict)
            else None,
            "bootstrap_error": orch.get("bootstrap_error")
            if isinstance(orch, dict)
            else None,
        },
    )

    # 6 templates
    code, templates_body = req("GET", "/api/templates/")
    templates = as_list(templates_body, "templates", "items", "data", "results")
    tpl_ok = code == 200 and len(templates) > 0
    sample_tpl = []
    for t in templates[:5]:
        if isinstance(t, dict):
            sample_tpl.append(
                {"id": t.get("id"), "name": t.get("name"), "type": t.get("type")}
            )
    record(
        "templates",
        "GET",
        "/api/templates/",
        code,
        tpl_ok,
        detail=f"count={len(templates)}",
        extra={"count": len(templates), "sample": sample_tpl},
    )

    # 7 agents list
    code, agents_body = req("GET", "/api/agents/")
    agents = as_list(agents_body, "agents", "items", "data")
    agents_ok = code == 200
    if orch_ok and len(agents) == 0:
        agents_ok = False
    slim = []
    for a in agents[:20]:
        if isinstance(a, dict):
            slim.append(
                {
                    "id": a.get("id"),
                    "name": a.get("name"),
                    "hierarchy_role": a.get("hierarchy_role"),
                    "template_type": a.get("template_type") or a.get("type"),
                    "parent_id": a.get("parent_id"),
                    "status": a.get("status"),
                }
            )
    record(
        "agents",
        "GET",
        "/api/agents/",
        code,
        agents_ok,
        detail=f"count={len(agents)}",
        extra={"count": len(agents), "agents": slim},
    )

    # 8 meetings list
    code, meetings_body = req("GET", "/api/meetings/")
    meetings = as_list(meetings_body, "meetings", "items", "data", "results")
    meetings_list_ok = code == 200
    record(
        "meetings_list",
        "GET",
        "/api/meetings/",
        code,
        meetings_list_ok,
        detail=f"count={len(meetings)}",
        extra={"count": len(meetings)},
    )

    # 9 meeting create
    code, meeting = req(
        "POST",
        "/api/meetings/",
        body={
            "title": "Live smoke wave meeting",
            "purpose": "live_smoke_wave",
        },
    )
    mid = None
    if isinstance(meeting, dict):
        mid = meeting.get("id") or (meeting.get("meeting") or {}).get("id")
    meeting_create_ok = code in (200, 201) and mid is not None
    record(
        "meetings_create",
        "POST",
        "/api/meetings/",
        code,
        meeting_create_ok,
        detail=f"id={mid}" if mid else snip(meeting),
        extra={"meeting_id": mid},
    )

    # 10 optional GET meeting
    if mid is not None:
        code, mget = req("GET", f"/api/meetings/{mid}")
        record(
            "meetings_get",
            "GET",
            f"/api/meetings/{mid}",
            code,
            code == 200,
            detail=(
                snip(mget)
                if code != 200
                else f"title={(mget.get('title') if isinstance(mget, dict) else None)}"
            ),
        )

    # Persist rotated key
    LOGIN_PATH.write_text(json.dumps(login, indent=2) + "\n", encoding="utf-8")

    areas = {
        "health": any(c["name"] == "health" and c["ok"] for c in checks),
        "login": any(c["name"] == "login" and c["ok"] for c in checks),
        "trial": any(c["name"] == "trial" and c["ok"] for c in checks),
        "orchestrator": any(c["name"] == "orchestrator" and c["ok"] for c in checks),
        "templates": any(c["name"] == "templates" and c["ok"] for c in checks),
        "agents": any(c["name"] == "agents" and c["ok"] for c in checks),
        "meetings": any(
            c["name"] in ("meetings_list", "meetings_create") and c["ok"]
            for c in checks
        ),
    }
    all_core = all(
        areas[k]
        for k in (
            "health",
            "login",
            "trial",
            "orchestrator",
            "templates",
            "agents",
            "meetings",
        )
    )
    failed = [c["name"] for c in checks if not c["ok"]]

    report = {
        "ok": all_core and not failed,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_sec": round(time.time() - t0, 2),
        "base": BASE,
        "login_path": str(LOGIN_PATH),
        "account": {
            "email": login.get("email"),
            "user_id": login.get("user_id"),
            "agent_id": login.get("agent_id"),
            "plan": plan
            if me_ok
            else (trial.get("plan") if isinstance(trial, dict) else None),
            "subscription_active": me.get("subscription_active") if me_ok else None,
            "subscription_expires_at": me.get("subscription_expires_at")
            if me_ok
            else None,
        },
        "areas": areas,
        "failed": failed,
        "checks": checks,
        "summary": {
            "total_checks": len(checks),
            "passed": sum(1 for c in checks if c["ok"]),
            "failed": len(failed),
            "templates_count": next(
                (c.get("count") for c in checks if c["name"] == "templates"), None
            ),
            "agents_count": next(
                (c.get("count") for c in checks if c["name"] == "agents"), None
            ),
            "meetings_count": next(
                (c.get("count") for c in checks if c["name"] == "meetings_list"), None
            ),
            "orchestrator_id": orch_id,
            "meeting_id": mid,
        },
    }
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print()
    print("=== WAVE SUMMARY ===")
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "areas": areas,
                "failed": failed,
                "elapsed_sec": report["elapsed_sec"],
                "summary": report["summary"],
            },
            indent=2,
        )
    )
    print("WROTE", OUT)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
