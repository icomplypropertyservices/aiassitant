#!/usr/bin/env python3
"""Fill current scripts/.demo_login.json trial account to plan agent cap with skills."""
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


def http(method: str, path: str, body: dict | None = None, token: str | None = None, timeout: float = 180):
    url = BASE + path
    data = None
    headers = {"Accept": "application/json", "User-Agent": "fill-current-demo/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
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
    for _ in range(16):
        # re-read file — peers may have updated email/password
        try:
            data = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
            login.update(data)
        except Exception:
            pass
        code, body = http(
            "POST",
            "/auth/login",
            {"email": login["email"], "password": login["password"]},
            token=None,
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
            print("login fail", code, str(body)[:200])
            time.sleep(2)
            continue
        t = str(body.get("api_key") or body.get("token") or "")
        login["api_key"] = t
        user = body.get("user") if isinstance(body.get("user"), dict) else {}
        if user.get("id") is not None:
            login["user_id"] = user["id"]
        LOGIN_PATH.write_text(json.dumps(login, indent=2) + "\n", encoding="utf-8")
        print("login ok", t[:16], "user", user.get("id"), user.get("email"), user.get("plan"))
        return t
    raise SystemExit("login exhausted")


def call(token: str, method: str, path: str, body: dict | None = None, timeout: float = 180):
    t = token
    code, parsed = 0, None
    for attempt in range(14):
        code, parsed = http(method, path, body, token=t, timeout=timeout)
        if code != 401:
            return code, parsed, t
        print(f"401 {method} {path} #{attempt+1}")
        t = login_fresh()
        time.sleep(0.1)
    return code, parsed, t


def as_list(body: Any) -> list:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for k in ("agents", "items", "data", "results"):
            if isinstance(body.get(k), list):
                return body[k]
    return []


def main() -> None:
    token = login_fresh()

    code, me, token = call(token, "GET", "/auth/me")
    if code != 200 or not isinstance(me, dict):
        raise SystemExit(f"me {code} {me}")
    limits = ((me.get("meter") or {}).get("limits") or {})
    max_agents = int(limits.get("agents") or 10)
    print("me", me.get("email"), me.get("plan"), "limits", limits)

    # Ensure trial
    tcode, trial, token = call(
        token, "POST", "/billing/plan", {"plan": "trial", "company_name": "Live Demo Co"}
    )
    print("trial", tcode, (trial or {}).get("plan") if isinstance(trial, dict) else trial)

    # Orchestrator bootstrap
    ocode, orch, token = call(token, "POST", "/agents/ensure-orchestrator?bootstrap=true", timeout=180)
    print(
        "orch",
        ocode,
        orch.get("id") if isinstance(orch, dict) else orch,
        orch.get("name") if isinstance(orch, dict) else "",
    )

    code, ab, token = call(token, "GET", "/agents/")
    agents = [a for a in as_list(ab) if isinstance(a, dict)]
    print("agents_before", len(agents))

    remaining = max_agents - len(agents)
    seed_result: Any = None
    seed_status = None
    if remaining >= 3:
        seed_status, seed_result, token = call(token, "POST", "/agents/seed-starter-team", timeout=180)
        print(
            "seed",
            seed_status,
            seed_result.get("detail")
            if isinstance(seed_result, dict) and seed_result.get("detail")
            else (
                {
                    k: seed_result.get(k)
                    for k in ("ok", "count", "message", "created", "at_limit", "agents")
                    if isinstance(seed_result, dict) and k in seed_result
                }
                if isinstance(seed_result, dict)
                else seed_result
            ),
        )
        if isinstance(seed_result, dict):
            print("seed_snip", json.dumps(seed_result, default=str)[:900])
    elif remaining > 0:
        # Spawn a few diverse specialists under orchestrator
        orch_a = next(
            (
                a
                for a in agents
                if a.get("hierarchy_role") == "orchestrator"
                or a.get("template_type") == "orchestrator"
            ),
            agents[0] if agents else None,
        )
        orch_id = orch_a["id"] if orch_a else None
        specs = [
            {"name": "Sales Lead Agent", "template_type": "lead", "hierarchy_role": "lead"},
            {"name": "Sales Outreach Agent", "template_type": "sales", "hierarchy_role": "member"},
            {"name": "Customer Support Agent", "template_type": "support", "hierarchy_role": "member"},
            {"name": "Content Writer Agent", "template_type": "content", "hierarchy_role": "member"},
            {"name": "Full-Stack Developer", "template_type": "engineering", "hierarchy_role": "member"},
            {"name": "Master Designer", "template_type": "designer", "hierarchy_role": "specialist"},
            {"name": "Lead Qualifier", "template_type": "sales", "hierarchy_role": "member"},
            {"name": "Appointment Booker", "template_type": "booking", "hierarchy_role": "member"},
        ]
        names = {a.get("name") for a in agents}
        for spec in specs:
            code, ab, token = call(token, "GET", "/agents/")
            agents = [a for a in as_list(ab) if isinstance(a, dict)]
            if len(agents) >= max_agents:
                break
            if spec["name"] in names or not orch_id:
                continue
            sc, body, token = call(token, "POST", f"/agents/{orch_id}/spawn", spec, timeout=120)
            print("spawn", sc, spec["name"], body if not isinstance(body, dict) else body.get("detail") or body.get("agent_id") or list(body.keys())[:8])
            names.add(spec["name"])
    else:
        seed_status, seed_result, token = call(token, "POST", "/agents/seed-starter-team", timeout=60)
        print("seed_at_cap", seed_status, (seed_result or {}).get("detail") if isinstance(seed_result, dict) else seed_result)

    # Re-list after seed
    code, ab, token = call(token, "GET", "/agents/")
    agents = [a for a in as_list(ab) if isinstance(a, dict)]
    print("agents_after_seed", len(agents))

    # If still short, try seed again or spawn more
    if len(agents) < max_agents and (max_agents - len(agents)) >= 3:
        seed_status, seed_result, token = call(token, "POST", "/agents/seed-starter-team", timeout=180)
        print("seed_retry", seed_status, str(seed_result)[:300])
        code, ab, token = call(token, "GET", "/agents/")
        agents = [a for a in as_list(ab) if isinstance(a, dict)]
        print("agents_after_seed2", len(agents))

    # Scaffold + bulk skills
    sc_code, scaffold, token = call(token, "POST", "/ops/scaffold", timeout=180)
    print("scaffold", sc_code, scaffold if not isinstance(scaffold, dict) else {k: scaffold.get(k) for k in ("ok", "agents", "updated", "orchestrator_id")})

    ids = [int(a["id"]) for a in agents if a.get("id") is not None]
    orch_a = next(
        (
            a
            for a in agents
            if a.get("hierarchy_role") == "orchestrator" or a.get("template_type") == "orchestrator"
        ),
        agents[0] if agents else None,
    )
    orch_id = int(orch_a["id"]) if orch_a else None
    bulk = None
    bulk_status = None
    if orch_id and ids:
        bulk_status, bulk, token = call(
            token,
            "POST",
            f"/agents/{orch_id}/skills/run",
            {"skill": "bulk_enable_skills", "args": {"agent_ids": ids, "preset": "full"}},
            timeout=180,
        )
        print("bulk", bulk_status, json.dumps(bulk, default=str)[:500] if bulk is not None else None)

    rows = []
    for a in sorted(agents, key=lambda x: x.get("id") or 0):
        aid = int(a["id"])
        role = a.get("hierarchy_role") or "member"
        sc, skills, token = call(token, "GET", f"/agents/{aid}/skills")
        enabled = skills.get("enabled_count") if isinstance(skills, dict) else None
        summary = skills.get("summary") if isinstance(skills, dict) else None
        if sc == 200 and isinstance(skills, dict) and (enabled or 0) < 8:
            catalog = skills.get("skills") or []
            want = []
            for s in catalog:
                if not isinstance(s, dict) or not s.get("id"):
                    continue
                if s.get("enabled") or not s.get("premium") or role in ("orchestrator", "lead"):
                    want.append(str(s["id"]))
            want = list(dict.fromkeys(want))[:150]
            if want:
                pc, put, token = call(token, "PUT", f"/agents/{aid}/skills", {"enabled": want})
                print(f"  put {aid} {pc} n={len((put or {}).get('enabled') or []) if isinstance(put, dict) else put}")
                sc, skills, token = call(token, "GET", f"/agents/{aid}/skills")
                enabled = skills.get("enabled_count") if isinstance(skills, dict) else enabled
                summary = skills.get("summary") if isinstance(skills, dict) else summary
        row = {
            "id": aid,
            "name": a.get("name"),
            "template_type": a.get("template_type"),
            "hierarchy_role": role,
            "parent_id": a.get("parent_id"),
            "is_lead": a.get("is_lead"),
            "status": a.get("status"),
            "skills_http": sc,
            "enabled_count": enabled,
            "summary": summary,
        }
        rows.append(row)
        print(
            f"id={aid} {a.get('name')!r} type={a.get('template_type')} "
            f"role={role} parent={a.get('parent_id')} skills={enabled}"
        )

    out = {
        "account": {
            "email": me.get("email"),
            "user_id": me.get("id"),
            "plan": me.get("plan"),
            "subscription_active": me.get("subscription_active"),
            "limits": limits,
        },
        "agent_count": len(rows),
        "max_agents": max_agents,
        "slots_filled": f"{len(rows)}/{max_agents}",
        "seed_status": seed_status,
        "seed": seed_result
        if isinstance(seed_result, (dict, list, str, int, type(None)))
        else str(seed_result)[:500],
        "scaffold_status": sc_code,
        "scaffold": scaffold
        if isinstance(scaffold, (dict, list, str, int, type(None)))
        else str(scaffold)[:400],
        "bulk_enable_status": bulk_status,
        "bulk_enable": bulk
        if isinstance(bulk, (dict, list, str, int, type(None)))
        else str(bulk)[:400],
        "agents": rows,
        "template_types": sorted({r.get("template_type") for r in rows if r.get("template_type")}),
        "hierarchy_roles": sorted({r.get("hierarchy_role") for r in rows if r.get("hierarchy_role")}),
        "all_have_skills": all((r.get("enabled_count") or 0) > 0 for r in rows) and len(rows) > 0,
        "sum_enabled": sum((r.get("enabled_count") or 0) for r in rows),
    }
    REPORT_PATH.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print("WROTE", REPORT_PATH)
    print(
        "RESULT",
        out["slots_filled"],
        "types",
        out["template_types"],
        "roles",
        out["hierarchy_roles"],
        "skills_ok",
        out["all_have_skills"],
        "sum",
        out["sum_enabled"],
    )


if __name__ == "__main__":
    main()
