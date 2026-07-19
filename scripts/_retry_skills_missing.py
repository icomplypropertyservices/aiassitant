#!/usr/bin/env python3
"""Enable skills on all demo agents; resilient to concurrent key rotation."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LOGIN_PATH = ROOT / ".demo_login.json"
REPORT_PATH = ROOT / "live_trial_team_fill_report.json"
BASE = "https://www.aibusinessagent.xyz/api"
login = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
# In-memory only — do not trust shared file after login (other swarm scripts rotate keys).
token_box: dict[str, str] = {"v": ""}


def http(
    method: str,
    path: str,
    body: dict | None = None,
    timeout: float = 120,
    *,
    use_token: str | None = None,
    auth: bool = True,
) -> tuple[int, Any]:
    url = BASE + path
    data = None
    headers = {"Accept": "application/json", "User-Agent": "retry-skills/2.0"}
    t = use_token if use_token is not None else token_box["v"]
    if auth and t:
        headers["Authorization"] = "Bearer " + t
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return int(resp.status), json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return int(resp.status), raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            return int(e.code), json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return int(e.code), raw


def login_fresh() -> str:
    for _ in range(12):
        code, body = http(
            "POST",
            "/auth/login",
            {"email": login["email"], "password": login["password"]},
            auth=False,
            timeout=60,
        )
        if code == 429:
            wait = 90
            if isinstance(body, dict) and isinstance(body.get("detail"), str):
                m = re.search(r"(\d+)\s*s", body["detail"])
                if m:
                    wait = min(int(m.group(1)) + 5, 320)
            print("rate-limit sleep", wait)
            time.sleep(wait)
            continue
        if code != 200 or not isinstance(body, dict):
            raise SystemExit(f"login fail {code} {body}")
        t = str(body.get("api_key") or body.get("token") or "")
        token_box["v"] = t
        login["api_key"] = t
        # Best-effort save (may be overwritten by peers)
        try:
            LOGIN_PATH.write_text(json.dumps(login, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
        print("login ok", t[:16])
        return t
    raise SystemExit("login exhausted")


def call(method: str, path: str, body: dict | None = None, timeout: float = 120) -> tuple[int, Any]:
    """Call API; on 401 re-login and retry (other swarm scripts rotate keys constantly)."""
    last: tuple[int, Any] = (0, None)
    for attempt in range(14):
        if not token_box["v"] or attempt > 0:
            # attempt 0 may reuse existing; subsequent always re-login after 401
            if attempt > 0 or not token_box["v"]:
                try:
                    login_fresh()
                except SystemExit as e:
                    if attempt >= 13:
                        raise
                    print("login retry after", e)
                    time.sleep(5)
                    continue
        # Fire request immediately after login to win the race vs concurrent logins
        code, parsed = http(method, path, body, timeout=timeout, use_token=token_box["v"])
        last = (code, parsed)
        if code != 401:
            return code, parsed
        print(f"  401 {method} {path} attempt={attempt+1} — re-login")
        token_box["v"] = ""  # force fresh login
        time.sleep(0.2 + min(attempt * 0.15, 1.5))
    return last


def enable_for(agent_id: int, hierarchy_role: str) -> dict[str, Any]:
    sc, skills = call("GET", f"/agents/{agent_id}/skills")
    if sc != 200 or not isinstance(skills, dict):
        return {"id": agent_id, "skills_http": sc, "enabled_count": None, "error": str(skills)[:200]}

    enabled = int(skills.get("enabled_count") or 0)
    catalog = skills.get("skills") or []
    role = (hierarchy_role or "").lower()
    want: list[str] = []
    for s in catalog:
        if not isinstance(s, dict) or not s.get("id"):
            continue
        sid = str(s["id"])
        is_prem = bool(s.get("premium"))
        if s.get("enabled") or (not is_prem) or (role in ("orchestrator", "lead") and is_prem):
            want.append(sid)
    seen: set[str] = set()
    want2: list[str] = []
    for x in want:
        if x not in seen:
            seen.add(x)
            want2.append(x)

    put_n = None
    if len(want2) > max(enabled, 0):
        pc, put = call("PUT", f"/agents/{agent_id}/skills", {"enabled": want2[:150]})
        if pc == 200 and isinstance(put, dict):
            put_n = len(put.get("enabled") or [])
        else:
            put_n = pc
        sc, skills = call("GET", f"/agents/{agent_id}/skills")
        if isinstance(skills, dict):
            enabled = int(skills.get("enabled_count") or 0)

    summary = skills.get("summary") if isinstance(skills, dict) else None
    return {
        "id": agent_id,
        "skills_http": sc,
        "enabled_count": enabled if sc == 200 else None,
        "summary": summary,
        "put_enabled_n": put_n,
    }


def main() -> None:
    login_fresh()
    # Verify immediately
    code, me = call("GET", "/auth/me")
    if code != 200:
        raise SystemExit(f"me fail {code} {me}")
    print("me", me.get("email"), me.get("plan"), "limits", ((me.get("meter") or {}).get("limits")))

    code, ab = call("GET", "/agents/")
    if code != 200:
        raise SystemExit(f"agents fail {code} {ab}")
    live = ab if isinstance(ab, list) else (ab or {}).get("agents") or (ab or {}).get("items") or []
    agents = [a for a in live if isinstance(a, dict) and a.get("id") is not None]
    print("agents", len(agents))

    # Scaffold once (expands default skills server-side)
    sc_code, scaffold = call("POST", "/ops/scaffold", timeout=180)
    print("scaffold", sc_code, scaffold if not isinstance(scaffold, dict) else {k: scaffold.get(k) for k in ("ok", "agents", "updated", "orchestrator_id")})

    updated: list[dict[str, Any]] = []
    for a in sorted(agents, key=lambda x: x["id"]):
        aid = int(a["id"])
        role = a.get("hierarchy_role") or "member"
        print(f"enable id={aid} {a.get('name')!r} role={role}")
        # retry loop per agent
        res: dict[str, Any] = {}
        for attempt in range(4):
            res = enable_for(aid, role)
            if (res.get("enabled_count") or 0) > 0:
                break
            print(f"  retry {attempt+1} http={res.get('skills_http')}")
            time.sleep(1.5)
            login_fresh()
        row = {
            "id": aid,
            "name": a.get("name"),
            "template_type": a.get("template_type"),
            "hierarchy_role": role,
            "parent_id": a.get("parent_id"),
            "is_lead": a.get("is_lead"),
            "status": a.get("status"),
            **res,
        }
        updated.append(row)
        print(f"  -> http={res.get('skills_http')} skills={res.get('enabled_count')} put={res.get('put_enabled_n')}")

    out = {
        "account": {
            "email": me.get("email") if isinstance(me, dict) else login.get("email"),
            "user_id": me.get("id") if isinstance(me, dict) else login.get("user_id"),
            "plan": me.get("plan") if isinstance(me, dict) else "trial",
            "subscription_active": me.get("subscription_active") if isinstance(me, dict) else True,
            "limits": ((me.get("meter") or {}).get("limits") if isinstance(me, dict) else {"agents": 10}),
        },
        "agent_count": len(updated),
        "max_agents": 10,
        "slots_filled": f"{len(updated)}/10",
        "scaffold_status": sc_code,
        "scaffold": scaffold if isinstance(scaffold, (dict, list, str, int, type(None))) else str(scaffold)[:400],
        "agents": updated,
        "template_types": sorted({r.get("template_type") for r in updated if r.get("template_type")}),
        "hierarchy_roles": sorted({r.get("hierarchy_role") for r in updated if r.get("hierarchy_role")}),
        "all_have_skills": all((r.get("enabled_count") or 0) > 0 for r in updated),
        "sum_enabled": sum((r.get("enabled_count") or 0) for r in updated),
    }
    REPORT_PATH.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print("WROTE", REPORT_PATH)
    print("all_have_skills", out["all_have_skills"], "sum_enabled", out["sum_enabled"])
    print("types", out["template_types"])
    print("roles", out["hierarchy_roles"])
    for r in updated:
        print(
            f"  id={r['id']} {r.get('name')!r} type={r.get('template_type')} "
            f"role={r.get('hierarchy_role')} parent={r.get('parent_id')} skills={r.get('enabled_count')}"
        )


if __name__ == "__main__":
    main()
