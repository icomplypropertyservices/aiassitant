#!/usr/bin/env python3
"""Probe production team: trial, orchestrator, seed-starter-team, list, hierarchy.

Writes scripts/live_team_report.json.

Auth notes:
  - Login rotates the session API key (invalidates previous).
  - Many concurrent swarm scripts share scripts/.demo_login.json — avoid login spam.
  - Prefer a still-valid stored key; on 401 re-read file; login only as last resort.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LOGIN_PATH = ROOT / ".demo_login.json"
BASE = "https://www.aibusinessagent.xyz/api"
login: dict[str, Any] = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
token: str | None = None


def _reload_login() -> dict[str, Any]:
    global login
    login = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
    return login


def _save_login() -> None:
    LOGIN_PATH.write_text(json.dumps(login, indent=2) + "\n", encoding="utf-8")


def _http(
    method: str,
    path: str,
    body: dict | None = None,
    timeout: float = 180,
    auth: bool = True,
) -> tuple[int, Any, str]:
    url = BASE + path if path.startswith("/") else f"{BASE}/{path}"
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "live-team-report/1.1",
    }
    if auth and token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = raw
            return int(getattr(resp, "status", None) or resp.getcode()), parsed, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return int(e.code), parsed, raw
    except Exception as e:  # noqa: BLE001
        return 0, None, str(e)


def login_fresh(wait_on_429: bool = True) -> str:
    global token
    for attempt in range(8):
        code, body, raw = _http(
            "POST",
            "/auth/login",
            {"email": login["email"], "password": login["password"]},
            auth=False,
            timeout=60,
        )
        if code == 429 and wait_on_429:
            # detail like "Too many attempts. Try again in 254s."
            wait_s = 60
            if isinstance(body, dict) and isinstance(body.get("detail"), str):
                detail = body["detail"]
                import re

                m = re.search(r"(\d+)\s*s", detail)
                if m:
                    wait_s = min(int(m.group(1)) + 5, 320)
            print(f"AUTH rate-limited; sleeping {wait_s}s (attempt {attempt + 1})")
            time.sleep(wait_s)
            continue
        if code != 200 or not isinstance(body, dict):
            raise SystemExit(f"login failed http={code}: {raw[:400]}")
        new_token = body.get("api_key") or body.get("token")
        if not new_token:
            raise SystemExit(f"login ok but no token: {raw[:400]}")
        token = str(new_token)
        user = body.get("user") if isinstance(body.get("user"), dict) else {}
        login["api_key"] = token
        if user.get("id") is not None:
            login["user_id"] = user["id"]
        _save_login()
        print(
            f"AUTH login ok prefix={token[:16]} "
            f"user={user.get('id')} plan={user.get('plan')}"
        )
        return token
    raise SystemExit("login failed: still rate-limited after retries")


def ensure_valid_token() -> str:
    """Use stored key if valid; else re-read file; else login."""
    global token
    _reload_login()
    stored = (login.get("api_key") or "").strip()
    if stored:
        token = stored
        code, me, _ = _http("GET", "/auth/me", auth=True, timeout=60)
        if code == 200 and isinstance(me, dict):
            print("AUTH stored_key ok", me.get("email"), me.get("plan"))
            return token
        print("AUTH stored_key invalid status=", code)

    # Another process may have just rotated — re-read file once
    time.sleep(0.3)
    _reload_login()
    stored2 = (login.get("api_key") or "").strip()
    if stored2 and stored2 != stored:
        token = stored2
        code, me, _ = _http("GET", "/auth/me", auth=True, timeout=60)
        if code == 200 and isinstance(me, dict):
            print("AUTH file-refresh key ok", me.get("email"), me.get("plan"))
            return token
        print("AUTH file-refresh key invalid status=", code)

    return login_fresh(wait_on_429=True)


def req(
    method: str,
    path: str,
    body: dict | None = None,
    timeout: float = 180,
    retries: int = 2,
) -> tuple[int, Any, str]:
    """Authenticated request; recover from concurrent key rotation without login spam."""
    global token
    if not token:
        ensure_valid_token()
    code, parsed, raw = _http(method, path, body=body, timeout=timeout, auth=True)
    if code != 401 or retries <= 0:
        return code, parsed, raw

    print(f"  401 on {method} {path} — try file key / login")
    # Prefer re-read of shared demo login (other swarm agents may have refreshed it)
    _reload_login()
    file_key = (login.get("api_key") or "").strip()
    if file_key and file_key != token:
        token = file_key
        code2, parsed2, raw2 = _http(method, path, body=body, timeout=timeout, auth=True)
        if code2 != 401:
            return code2, parsed2, raw2

    ensure_valid_token()
    return req(method, path, body=body, timeout=timeout, retries=retries - 1)


def as_list(body: Any, *keys: str) -> list:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for k in keys:
            v = body.get(k)
            if isinstance(v, list):
                return v
    return []


def main() -> None:
    t0 = time.time()
    ensure_valid_token()

    me_code, me, me_raw = req("GET", "/auth/me")
    print("ME", me_code, me.get("plan") if isinstance(me, dict) else me_raw[:200])
    if me_code != 200 or not isinstance(me, dict):
        raise SystemExit(f"auth/me failed: {me_code} {me_raw[:300]}")

    trial_code, trial, trial_raw = req(
        "POST",
        "/billing/plan",
        {"plan": "trial", "company_name": "Live Demo Co"},
    )
    print(
        "TRIAL",
        trial_code,
        {
            k: trial.get(k)
            for k in ("plan", "subscription_active", "already_active")
        }
        if isinstance(trial, dict)
        else trial_raw[:200],
    )

    orch_code, orch, orch_raw = req(
        "POST", "/agents/ensure-orchestrator?bootstrap=true", timeout=180
    )
    if isinstance(orch, dict):
        print(
            "ORCH",
            orch_code,
            orch.get("id"),
            orch.get("name"),
            orch.get("hierarchy_role"),
        )
        if orch.get("bootstrap_error"):
            print("  bootstrap_error:", orch.get("bootstrap_error"))
    else:
        print("ORCH", orch_code, orch_raw[:300])

    seed_code, seed, seed_raw = req("POST", "/agents/seed-starter-team", timeout=180)
    if isinstance(seed, dict):
        print(
            "SEED",
            seed_code,
            {
                k: seed.get(k)
                for k in (
                    "ok",
                    "count",
                    "message",
                    "plan_limit",
                    "at_limit",
                    "detail",
                )
            },
        )
    else:
        print("SEED", seed_code, seed_raw[:400])

    agents_code, agents_body, _agents_raw = req("GET", "/agents/")
    agents = as_list(agents_body, "agents", "items", "data")
    print("AGENTS", agents_code, "count=", len(agents))
    for a in agents:
        if isinstance(a, dict):
            print(
                f"  id={a.get('id')} name={a.get('name')!r} "
                f"role={a.get('hierarchy_role')} parent={a.get('parent_id')} "
                f"lead={a.get('is_lead')} status={a.get('status')}"
            )

    hier_code, hier, hier_raw = req("GET", "/agents/hierarchy")
    print("HIER", hier_code, type(hier).__name__)

    slim_agents: list[dict] = []
    for a in agents:
        if not isinstance(a, dict):
            continue
        slim_agents.append(
            {
                "id": a.get("id"),
                "name": a.get("name"),
                "template_type": a.get("template_type"),
                "hierarchy_role": a.get("hierarchy_role"),
                "parent_id": a.get("parent_id"),
                "is_lead": a.get("is_lead"),
                "status": a.get("status"),
                "role": a.get("role"),
            }
        )

    seed_limit_note = None
    if seed_code == 400:
        seed_limit_note = (
            seed.get("detail") if isinstance(seed, dict) else str(seed)[:500]
        )
        print("SEED_LIMIT", seed_limit_note)

    meter = me.get("meter") or {}
    limits = meter.get("limits") or {}
    agents_limit = limits.get("agents") if isinstance(limits, dict) else None

    trial_active = bool(
        (me.get("plan") == "trial" and me.get("subscription_active"))
        or (
            isinstance(trial, dict)
            and (
                trial.get("already_active")
                or trial.get("plan") == "trial"
                or trial.get("subscription_active")
            )
        )
    )

    max_agents = int((limits or {}).get("agents") or 10)
    if seed_code == 400:
        seed_note = (
            f"plan_limits.agents={max_agents}; seed-starter-team needs free slots "
            "and tries to create many agents. Expect 400 when already at/near cap "
            f"(trial allows up to {max_agents} agents / "
            f"{int((limits or {}).get('companies') or 2)} companies)."
        )
    elif seed_code == 200:
        seed_note = "seed succeeded"
    else:
        seed_note = f"seed returned HTTP {seed_code}"

    report = {
        "ok": True,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_sec": round(time.time() - t0, 2),
        "base": BASE,
        "account": {
            "email": login.get("email"),
            "user_id": login.get("user_id") or me.get("id"),
            "plan": me.get("plan"),
            "subscription_active": me.get("subscription_active"),
            "subscription_expires_at": me.get("subscription_expires_at"),
            "plan_limits": limits,
            "tokens_remaining_included": meter.get("tokens_remaining_included"),
            "tokens_used_period": meter.get("tokens_used_period"),
        },
        "trial": {
            "status": trial_code,
            "active": trial_active,
            "result": {
                k: trial.get(k)
                for k in (
                    "plan",
                    "subscription_active",
                    "subscription_expires_at",
                    "already_active",
                )
            }
            if isinstance(trial, dict)
            else {"raw": trial_raw[:400]},
        },
        "orchestrator": {
            "status": orch_code,
            "id": orch.get("id") if isinstance(orch, dict) else None,
            "name": orch.get("name") if isinstance(orch, dict) else None,
            "hierarchy_role": orch.get("hierarchy_role")
            if isinstance(orch, dict)
            else None,
            "parent_id": orch.get("parent_id") if isinstance(orch, dict) else None,
            "bootstrap": orch.get("bootstrap") if isinstance(orch, dict) else None,
            "bootstrap_error": orch.get("bootstrap_error")
            if isinstance(orch, dict)
            else None,
            "error": None
            if isinstance(orch, dict)
            else (orch if orch is not None else orch_raw[:400]),
        },
        "seed_starter_team": {
            "status": seed_code,
            "ok": seed_code == 200,
            "body": seed
            if isinstance(seed, (dict, list, str, int, float, bool, type(None)))
            else str(seed)[:500],
            "plan_limit_blocked": seed_code == 400,
            "limit_detail": seed_limit_note,
            "note": seed_note,
        },
        "agent_count": len(slim_agents),
        "agents": slim_agents,
        "hierarchy": hier
        if isinstance(hier, (dict, list))
        else {"raw": (hier_raw or str(hier))[:800]},
        "goal": "more agents so hierarchy auto-chain has people to delegate to",
        "recommendation": (
            "Upgrade plan (starter/pro/business) for more agent slots, then re-run "
            "POST /api/agents/seed-starter-team so leads/specialists exist for "
            "hierarchy auto-chain delegation. "
            f"Current plan agents limit={agents_limit}, count={len(slim_agents)}."
        ),
        "steps": {
            "auth": "ok",
            "auth_me_status": me_code,
            "billing_trial_status": trial_code,
            "ensure_orchestrator_status": orch_code,
            "seed_starter_team_status": seed_code,
            "list_agents_status": agents_code,
            "hierarchy_status": hier_code,
        },
    }

    _save_login()
    out = ROOT / "live_team_report.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("WROTE", out)
    print(
        "summary:",
        f"plan={me.get('plan')} agents={len(slim_agents)}/{agents_limit} "
        f"seed={seed_code} orch_id="
        f"{orch.get('id') if isinstance(orch, dict) else None}",
    )


if __name__ == "__main__":
    main()
