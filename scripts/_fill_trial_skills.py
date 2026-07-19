#!/usr/bin/env python3
"""Ensure demo trial has ~10 agents with skills enabled; write live_trial_team_fill_report.json."""
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
BASE = "https://www.aibusinessagent.xyz/api"
login: dict[str, Any] = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
token: dict[str, str] = {"v": (login.get("api_key") or "").strip()}


def _save_login() -> None:
    LOGIN_PATH.write_text(json.dumps(login, indent=2) + "\n", encoding="utf-8")


def http(
    method: str,
    path: str,
    body: dict | None = None,
    timeout: float = 180,
    auth: bool = True,
) -> tuple[int, Any]:
    url = BASE + path if path.startswith("/") else f"{BASE}/{path}"
    data = None
    headers = {"Accept": "application/json", "User-Agent": "fill-trial-skills/1.0"}
    if auth and token["v"]:
        headers["Authorization"] = "Bearer " + token["v"]
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return int(getattr(resp, "status", None) or resp.getcode()), (
                    json.loads(raw) if raw else None
                )
            except json.JSONDecodeError:
                return int(getattr(resp, "status", None) or resp.getcode()), raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            return int(e.code), json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return int(e.code), raw


def login_fresh() -> None:
    for _attempt in range(8):
        code, body = http(
            "POST",
            "/auth/login",
            {"email": login["email"], "password": login["password"]},
            auth=False,
            timeout=60,
        )
        if code == 429:
            wait = 70
            if isinstance(body, dict) and isinstance(body.get("detail"), str):
                m = re.search(r"(\d+)\s*s", body["detail"])
                if m:
                    wait = min(int(m.group(1)) + 5, 320)
            print("rate limit sleep", wait)
            time.sleep(wait)
            continue
        if code != 200 or not isinstance(body, dict):
            raise SystemExit(f"login fail {code} {body}")
        token["v"] = str(body.get("api_key") or body.get("token") or "")
        login["api_key"] = token["v"]
        user = body.get("user") if isinstance(body.get("user"), dict) else {}
        if user.get("id") is not None:
            login["user_id"] = user["id"]
        _save_login()
        print("login ok", token["v"][:16], "plan=", user.get("plan"))
        return
    raise SystemExit("login exhausted")


def ensure_me() -> dict[str, Any]:
    global login
    login = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
    token["v"] = (login.get("api_key") or "").strip()
    code, me = http("GET", "/auth/me")
    if code == 200 and isinstance(me, dict):
        print("auth ok", me.get("email"), me.get("plan"))
        return me
    print("stored invalid", code)
    login_fresh()
    code, me = http("GET", "/auth/me")
    if code != 200 or not isinstance(me, dict):
        raise SystemExit(f"me after login {code} {me}")
    print("auth ok", me.get("email"), me.get("plan"))
    return me


def req(
    method: str, path: str, body: dict | None = None, timeout: float = 180
) -> tuple[int, Any]:
    global login
    code, parsed = http(method, path, body, timeout=timeout)
    if code != 401:
        return code, parsed
    login = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
    file_key = (login.get("api_key") or "").strip()
    if file_key and file_key != token["v"]:
        token["v"] = file_key
        code2, p2 = http(method, path, body, timeout=timeout)
        if code2 != 401:
            return code2, p2
    login_fresh()
    return http(method, path, body, timeout=timeout)


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
    me = ensure_me()
    limits = ((me.get("meter") or {}).get("limits") or {})
    max_agents = int(limits.get("agents") or 10)
    print("limits", limits)

    # Ensure trial active (idempotent)
    tcode, trial = req("POST", "/billing/plan", {"plan": "trial", "company_name": "Live Demo Co"})
    print("trial", tcode, (trial or {}).get("already_active") if isinstance(trial, dict) else trial)

    # Orchestrator
    ocode, orch = req("POST", "/agents/ensure-orchestrator?bootstrap=true", timeout=180)
    print(
        "orch",
        ocode,
        orch.get("id") if isinstance(orch, dict) else orch,
        orch.get("name") if isinstance(orch, dict) else "",
    )

    code, ab = req("GET", "/agents/")
    agents = [a for a in as_list(ab, "agents", "items", "data") if isinstance(a, dict)]
    print("agents_before", len(agents))

    remaining = max_agents - len(agents)
    seed_result: Any = None
    if remaining >= 3:
        scode, seed_result = req("POST", "/agents/seed-starter-team", timeout=180)
        print(
            "seed",
            scode,
            seed_result.get("detail")
            if isinstance(seed_result, dict) and seed_result.get("detail")
            else (
                {
                    k: seed_result.get(k)
                    for k in ("ok", "count", "message", "at_limit")
                    if isinstance(seed_result, dict)
                }
            ),
        )
        code, ab = req("GET", "/agents/")
        agents = [a for a in as_list(ab, "agents", "items", "data") if isinstance(a, dict)]
    elif remaining > 0:
        specs = [
            {"name": "Content Writer Agent", "template_type": "content", "hierarchy_role": "member"},
            {
                "name": "Full-Stack Developer",
                "template_type": "engineering",
                "hierarchy_role": "member",
            },
            {
                "name": "Social Media Manager",
                "template_type": "marketing",
                "hierarchy_role": "member",
            },
            {"name": "Code Reviewer", "template_type": "engineering", "hierarchy_role": "member"},
            {
                "name": "Email Newsletter Writer",
                "template_type": "content",
                "hierarchy_role": "member",
            },
        ]
        orch_agent = next(
            (
                a
                for a in agents
                if a.get("hierarchy_role") == "orchestrator"
                or a.get("template_type") == "orchestrator"
            ),
            None,
        )
        orch_id = orch_agent["id"] if orch_agent else (agents[0]["id"] if agents else None)
        names = {a.get("name") for a in agents}
        for spec in specs:
            code, ab = req("GET", "/agents/")
            agents = [a for a in as_list(ab, "agents", "items", "data") if isinstance(a, dict)]
            if len(agents) >= max_agents:
                break
            if spec["name"] in names or not orch_id:
                continue
            sc, body = req("POST", f"/agents/{orch_id}/spawn", spec, timeout=120)
            print("spawn", sc, spec["name"], body if not isinstance(body, dict) else body.get("detail") or body.get("agent_id") or list(body.keys())[:8])
            names.add(spec["name"])
        code, ab = req("GET", "/agents/")
        agents = [a for a in as_list(ab, "agents", "items", "data") if isinstance(a, dict)]
    else:
        scode, seed_result = req("POST", "/agents/seed-starter-team", timeout=60)
        print(
            "seed_at_cap",
            scode,
            (seed_result or {}).get("detail") if isinstance(seed_result, dict) else seed_result,
        )

    # Expand skills for whole workspace
    sc_code, scaffold = req("POST", "/ops/scaffold", timeout=180)
    print("scaffold", sc_code, list(scaffold.keys()) if isinstance(scaffold, dict) else type(scaffold))
    if isinstance(scaffold, dict):
        print("scaffold_snip", json.dumps(scaffold, default=str)[:700])

    code, ab = req("GET", "/agents/")
    agents = [a for a in as_list(ab, "agents", "items", "data") if isinstance(a, dict)]
    print("agents_after", len(agents))

    report: list[dict[str, Any]] = []
    for a in sorted(agents, key=lambda x: x.get("id") or 0):
        aid = a["id"]
        sc, skills = req("GET", f"/agents/{aid}/skills")
        enabled = skills.get("enabled_count") if isinstance(skills, dict) else None
        summary = skills.get("summary") if isinstance(skills, dict) else None
        put_n = None
        if isinstance(skills, dict):
            catalog = skills.get("skills") or []
            role = (a.get("hierarchy_role") or "").lower()
            want: list[str] = []
            for s in catalog:
                if not isinstance(s, dict) or not s.get("id"):
                    continue
                sid = str(s["id"])
                is_prem = bool(s.get("premium"))
                if s.get("enabled") or (not is_prem) or (
                    role in ("orchestrator", "lead") and is_prem
                ):
                    want.append(sid)
            # de-dupe
            seen: set[str] = set()
            want2: list[str] = []
            for x in want:
                if x not in seen:
                    seen.add(x)
                    want2.append(x)
            if len(want2) > (enabled or 0):
                pc, put = req("PUT", f"/agents/{aid}/skills", {"enabled": want2[:150]})
                put_n = (
                    len((put or {}).get("enabled") or [])
                    if isinstance(put, dict)
                    else pc
                )
                sc, skills = req("GET", f"/agents/{aid}/skills")
                enabled = skills.get("enabled_count") if isinstance(skills, dict) else enabled
                summary = skills.get("summary") if isinstance(skills, dict) else summary
        row = {
            "id": aid,
            "name": a.get("name"),
            "template_type": a.get("template_type"),
            "hierarchy_role": a.get("hierarchy_role"),
            "parent_id": a.get("parent_id"),
            "is_lead": a.get("is_lead"),
            "status": a.get("status"),
            "skills_http": sc,
            "enabled_count": enabled,
            "summary": summary,
            "put_enabled_n": put_n,
        }
        report.append(row)
        print(
            f"id={aid} {a.get('name')!r} type={a.get('template_type')} "
            f"role={a.get('hierarchy_role')} parent={a.get('parent_id')} "
            f"skills={enabled} put={put_n}"
        )

    out = {
        "account": {
            "email": me.get("email"),
            "user_id": me.get("id"),
            "plan": me.get("plan"),
            "subscription_active": me.get("subscription_active"),
            "limits": limits,
            "tokens_remaining": (me.get("meter") or {}).get("tokens_remaining_included"),
        },
        "agent_count": len(agents),
        "max_agents": max_agents,
        "scaffold_status": sc_code,
        "scaffold": scaffold
        if isinstance(scaffold, (dict, list, str, int, type(None)))
        else str(scaffold)[:500],
        "seed": seed_result
        if isinstance(seed_result, (dict, list, str, int, type(None)))
        else str(seed_result)[:500],
        "agents": report,
        "template_types": sorted(
            {r.get("template_type") for r in report if r.get("template_type")}
        ),
        "hierarchy_roles": sorted(
            {r.get("hierarchy_role") for r in report if r.get("hierarchy_role")}
        ),
        "slots_filled": f"{len(agents)}/{max_agents}",
        "all_have_skills": all((r.get("enabled_count") or 0) > 0 for r in report),
    }
    out_path = ROOT / "live_trial_team_fill_report.json"
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print("WROTE", out_path)
    print("types", out["template_types"])
    print("roles", out["hierarchy_roles"])
    print("sum_enabled", sum(r.get("enabled_count") or 0 for r in report))
    print("all_have_skills", out["all_have_skills"])


if __name__ == "__main__":
    main()
