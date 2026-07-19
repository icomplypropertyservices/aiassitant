#!/usr/bin/env python3
"""Login once, list agents, bulk-enable skills via orchestrator, report."""
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
    headers = {"Accept": "application/json", "User-Agent": "bulk-enable-demo/1.0"}
    if token:
        headers["Authorization"] = "Bearer " + token
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
    for _ in range(15):
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
            print("rate-limit", wait)
            time.sleep(wait)
            continue
        if code != 200 or not isinstance(body, dict):
            print("login fail", code, body)
            time.sleep(3)
            continue
        t = str(body.get("api_key") or body.get("token") or "")
        login["api_key"] = t
        LOGIN_PATH.write_text(json.dumps(login, indent=2) + "\n", encoding="utf-8")
        print("login", t[:18])
        return t
    raise SystemExit("login exhausted")


def call(token: str, method: str, path: str, body: dict | None = None, timeout: float = 180):
    """Use token; on 401 re-login and retry a few times. Returns (code, body, token)."""
    t = token
    code, parsed = 0, None
    for attempt in range(12):
        code, parsed = http(method, path, body, token=t, timeout=timeout)
        if code != 401:
            return code, parsed, t
        print(f"401 on {method} {path} attempt {attempt+1}")
        t = login_fresh()
        time.sleep(0.15)
    return code, parsed, t


def main() -> None:
    token = login_fresh()

    code, me, token = call(token, "GET", "/auth/me")
    if code != 200:
        raise SystemExit(f"me {code} {me}")
    print("me", me.get("email"), me.get("plan"), ((me.get("meter") or {}).get("limits")))

    code, ab, token = call(token, "GET", "/agents/")
    if code != 200:
        raise SystemExit(f"agents {code} {ab}")
    agents = ab if isinstance(ab, list) else (ab or {}).get("agents") or (ab or {}).get("items") or []
    agents = [a for a in agents if isinstance(a, dict)]
    print("agents", len(agents))
    for a in sorted(agents, key=lambda x: x.get("id") or 0):
        print(
            f"  id={a.get('id')} {a.get('name')!r} type={a.get('template_type')} "
            f"role={a.get('hierarchy_role')} parent={a.get('parent_id')}"
        )

    ids = [int(a["id"]) for a in agents if a.get("id") is not None]
    orch = next(
        (
            a
            for a in agents
            if a.get("hierarchy_role") == "orchestrator" or a.get("template_type") == "orchestrator"
        ),
        agents[0] if agents else None,
    )
    if not orch:
        raise SystemExit("no agents")
    orch_id = int(orch["id"])

    # 2) scaffold
    code, scaffold, token = call(token, "POST", "/ops/scaffold")
    print(
        "scaffold",
        code,
        scaffold
        if not isinstance(scaffold, dict)
        else {k: scaffold.get(k) for k in ("ok", "agents", "updated", "orchestrator_id")},
    )

    # 3) bulk enable via orchestrator skill (one server-side write for all)
    code, bulk, token = call(
        token,
        "POST",
        f"/agents/{orch_id}/skills/run",
        {"skill": "bulk_enable_skills", "args": {"agent_ids": ids, "preset": "full"}},
        timeout=180,
    )
    print("bulk_enable", code)
    print(json.dumps(bulk, default=str)[:900] if bulk is not None else None)
    bulk_status = code

    # 4) per-agent skill counts (reuse token; re-login only on 401)
    rows = []
    for a in sorted(agents, key=lambda x: x.get("id") or 0):
        aid = int(a["id"])
        role = a.get("hierarchy_role") or "member"
        sc, skills, token = call(token, "GET", f"/agents/{aid}/skills")
        enabled = skills.get("enabled_count") if isinstance(skills, dict) else None
        summary = skills.get("summary") if isinstance(skills, dict) else None
        if sc == 200 and isinstance(skills, dict) and (enabled or 0) < 5:
            catalog = skills.get("skills") or []
            want = []
            for s in catalog:
                if not isinstance(s, dict) or not s.get("id"):
                    continue
                if s.get("enabled") or not s.get("premium") or role in ("orchestrator", "lead"):
                    want.append(s["id"])
            want = list(dict.fromkeys(want))[:150]
            pc, put, token = call(token, "PUT", f"/agents/{aid}/skills", {"enabled": want})
            print(
                f"  put {aid} {pc} n={len((put or {}).get('enabled') or []) if isinstance(put, dict) else put}"
            )
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
        print(f"  skills id={aid} http={sc} enabled={enabled}")

    out = {
        "account": {
            "email": me.get("email"),
            "user_id": me.get("id"),
            "plan": me.get("plan"),
            "subscription_active": me.get("subscription_active"),
            "limits": ((me.get("meter") or {}).get("limits")),
        },
        "agent_count": len(rows),
        "max_agents": 10,
        "slots_filled": f"{len(rows)}/10",
        "scaffold_status": 200 if isinstance(scaffold, dict) and scaffold.get("ok") else None,
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
        "all_have_skills": all((r.get("enabled_count") or 0) > 0 for r in rows),
        "sum_enabled": sum((r.get("enabled_count") or 0) for r in rows),
    }
    REPORT_PATH.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print("WROTE", REPORT_PATH)
    print(
        "RESULT slots",
        out["slots_filled"],
        "all_have_skills",
        out["all_have_skills"],
        "sum",
        out["sum_enabled"],
    )
    print("types", out["template_types"])
    print("roles", out["hierarchy_roles"])


if __name__ == "__main__":
    main()
