#!/usr/bin/env python3
"""Single-process: login once then hit agents + skills immediately (minimize key race)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LOGIN_PATH = ROOT / ".demo_login.json"
BASE = "https://www.aibusinessagent.xyz"
TIMEOUT = 90
NEEDED = ("create_task", "execute_goal", "message_agent", "status_update")


def req(method: str, path: str, token: str | None = None, body: dict | None = None):
    url = BASE + path
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "live-skills-only/1.0",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-API-Key"] = token
    request = Request(url, data=data, headers=headers, method=method)
    t0 = time.time()
    try:
        with urlopen(request, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = int(getattr(resp, "status", None) or resp.getcode())
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = raw
            return code, parsed, time.time() - t0
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return int(e.code), parsed, time.time() - t0
    except (URLError, TimeoutError, OSError) as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}, time.time() - t0


def ids_of(x):
    out = []
    if isinstance(x, list):
        for it in x:
            if isinstance(it, str):
                out.append(it)
            elif isinstance(it, dict):
                out.append(it.get("id") or it.get("skill") or it.get("name") or it.get("key"))
    elif isinstance(x, dict):
        out.extend(list(x.keys()))
    return [i for i in out if i]


def main() -> int:
    login = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
    print("login start", login["email"])
    code, body, dt = req(
        "POST",
        "/api/auth/login",
        body={"email": login["email"], "password": login["password"]},
    )
    print(f"login http={code} dt={dt:.2f}s")
    if code != 200 or not isinstance(body, dict):
        print("login body", str(body)[:400])
        return 1
    token = body.get("api_key") or body.get("token")
    if not token:
        print("no token", body.keys())
        return 1
    login["api_key"] = token
    if body.get("user") and isinstance(body["user"], dict):
        login["user_id"] = body["user"].get("id")
    LOGIN_PATH.write_text(json.dumps(login, indent=2) + "\n", encoding="utf-8")
    (ROOT / ".demo_token").write_text(token, encoding="utf-8")
    print("token", token[:22])

    # Immediate chain — no sleeps
    for path in (
        "/api/auth/me",
        "/api/templates/",
        "/api/agents/",
        "/api/agents",
        "/api/agents/27",
        "/api/agents/27/skills",
    ):
        code, body, dt = req("GET", path, token=token)
        if isinstance(body, list):
            print(f"{path} http={code} dt={dt:.2f}s list={len(body)}")
        elif isinstance(body, dict):
            detail = body.get("detail")
            keys = list(body.keys())[:15]
            print(f"{path} http={code} dt={dt:.2f}s keys={keys} detail={str(detail)[:120] if detail else ''}")
        else:
            print(f"{path} http={code} dt={dt:.2f}s type={type(body).__name__}")

    # agents list
    code_a, agents, _ = req("GET", "/api/agents/", token=token)
    alist = agents if isinstance(agents, list) else []
    if isinstance(agents, dict):
        alist = agents.get("agents") or agents.get("items") or []
    orch = None
    for a in alist:
        if not isinstance(a, dict):
            continue
        name = (a.get("name") or "").lower()
        if a.get("id") == 27 or "orchestrator" in name:
            orch = a
            if "orchestrator" in name:
                break
    orch_id = (orch or {}).get("id") or 27
    print("orchestrator", orch_id, (orch or {}).get("name"))

    code_s, skills, dt = req("GET", f"/api/agents/{orch_id}/skills", token=token)
    print(f"skills final http={code_s} dt={dt:.2f}s")
    report = {
        "base": BASE,
        "orchestrator_id": orch_id,
        "orchestrator": {k: (orch or {}).get(k) for k in ("id", "name", "role", "status")} if orch else None,
        "agents_http": code_a,
        "agents_count": len(alist) if isinstance(alist, list) else None,
        "skills_http": code_s,
    }
    if isinstance(skills, dict) and code_s == 200:
        (ROOT / "_live_skills_raw.json").write_text(
            json.dumps(skills, indent=2, ensure_ascii=False)[:500000], encoding="utf-8"
        )
        enabled = skills.get("enabled") or skills.get("enabled_skills") or skills.get("skills")
        catalog = (
            skills.get("catalog")
            or skills.get("skill_catalog")
            or skills.get("all")
            or skills.get("available")
        )
        en_ids = ids_of(enabled)
        cat_ids = ids_of(catalog)
        enabled_count = skills.get("enabled_count")
        if enabled_count is None:
            enabled_count = len(en_ids)
        total_catalog = (
            skills.get("total")
            or skills.get("catalog_count")
            or skills.get("total_catalog")
            or skills.get("total_count")
        )
        if total_catalog is None:
            total_catalog = len(cat_ids) if cat_ids else None
        raw = json.dumps(skills)
        presence = {}
        for n in NEEDED:
            presence[n] = {
                "present": n in en_ids or n in cat_ids or f'"{n}"' in raw,
                "enabled": n in en_ids,
                "in_catalog": n in cat_ids,
            }
        report.update(
            {
                "enabled_count": enabled_count,
                "total_catalog": total_catalog,
                "presence": presence,
                "skills_keys": list(skills.keys()),
                "enabled_sample": en_ids[:40],
                "catalog_sample": cat_ids[:40],
            }
        )
        print("enabled_count", enabled_count)
        print("total_catalog", total_catalog)
        print("presence", json.dumps(presence))
    else:
        report["skills_body"] = skills
        print("skills fail", str(skills)[:500])

    out = ROOT / "_live_skills_only_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", out)
    return 0 if code_s == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
