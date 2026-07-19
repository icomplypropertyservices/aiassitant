#!/usr/bin/env python3
"""Live: list templates + orchestrator GET /api/agents/{id}/skills summary."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LOGIN_PATH = ROOT / ".demo_login.json"
TOKEN_PATH = ROOT / ".demo_token"
BASE = "https://www.aibusinessagent.xyz"
TIMEOUT = 90
REPORT_PATH = ROOT / "_live_templates_skills_report.json"
SKILLS_RAW_PATH = ROOT / "_live_skills_raw.json"

NEEDED = ("create_task", "execute_goal", "message_agent", "status_update")


def load_login() -> dict:
    return json.loads(LOGIN_PATH.read_text(encoding="utf-8"))


def save_token(login: dict, token: str) -> None:
    login = dict(login)
    login["api_key"] = token
    LOGIN_PATH.write_text(json.dumps(login, indent=2) + "\n", encoding="utf-8")
    TOKEN_PATH.write_text(token, encoding="utf-8")


def req(method: str, path: str, token: str | None = None, body: dict | None = None):
    url = BASE + path
    data = None
    headers = {"Accept": "application/json", "User-Agent": "live-templates-skills/1.0"}
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


def extract_list(body, keys=("templates", "agents", "items", "data", "results", "skills")):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for k in keys:
            if isinstance(body.get(k), list):
                return body[k]
    return []


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
    login = load_login()
    token = login.get("api_key") or (
        TOKEN_PATH.read_text(encoding="utf-8").strip() if TOKEN_PATH.exists() else None
    )
    print(f"BASE={BASE}")
    print(f"email={login.get('email')}")
    print(f"token_prefix={(token or '')[:18]}")

    code_me, me = req("GET", "/api/auth/me", token=token)
    print(f"auth/me={code_me}")
    if code_me == 401:
        code_l, body_l = req(
            "POST",
            "/api/auth/login",
            body={"email": login["email"], "password": login["password"]},
        )
        print(f"login={code_l}")
        if isinstance(body_l, dict):
            token = body_l.get("api_key") or body_l.get("token") or body_l.get("access_token")
            if token:
                save_token(login, token)
                print(f"new_token_prefix={token[:18]}")
            else:
                print(f"login_body={str(body_l)[:300]}")
                return 1
        else:
            print(f"login_body={str(body_l)[:300]}")
            return 1
        code_me, me = req("GET", "/api/auth/me", token=token)
        print(f"auth/me_after={code_me}")

    # --- templates ---
    code_t, templates_body = req("GET", "/api/templates/", token=token)
    items = extract_list(templates_body, keys=("templates", "items", "data", "results"))
    names = []
    for it in items:
        if isinstance(it, dict):
            names.append(
                {
                    "id": it.get("id"),
                    "slug": it.get("slug"),
                    "name": it.get("name") or it.get("title"),
                    "category": it.get("category") or it.get("group") or it.get("type"),
                }
            )
        else:
            names.append({"raw": str(it)[:80]})
    print(f"templates status={code_t} count={len(items)}")
    for n in names:
        print(f"  - {n.get('id')} {n.get('slug') or ''} | {n.get('name')}")

    # --- agents / orchestrator ---
    code_a, agents_body = req("GET", "/api/agents/", token=token)
    agents = extract_list(agents_body, keys=("agents", "items", "data", "results"))
    print(f"agents status={code_a} count={len(agents)}")
    orch = None
    for a in agents:
        if not isinstance(a, dict):
            continue
        name = (a.get("name") or "").lower()
        role = (a.get("role") or "").lower()
        if a.get("id") == login.get("agent_id") or "orchestrator" in name or role == "orchestrator":
            orch = a
            if "orchestrator" in name or role == "orchestrator":
                break
    if not orch and agents:
        orch = next((a for a in agents if isinstance(a, dict)), None)
    orch_id = orch.get("id") if orch else login.get("agent_id") or 27
    print(
        f"orchestrator id={orch_id} name={orch.get('name') if orch else None} "
        f"role={orch.get('role') if orch else None}"
    )

    # --- skills ---
    code_s, skills = req("GET", f"/api/agents/{orch_id}/skills", token=token)
    print(f"skills status={code_s} type={type(skills).__name__}")
    if isinstance(skills, dict):
        SKILLS_RAW_PATH.write_text(
            json.dumps(skills, indent=2, ensure_ascii=False)[:500000],
            encoding="utf-8",
        )
        print(f"skills keys={list(skills.keys())}")
        enabled = (
            skills.get("enabled")
            or skills.get("enabled_skills")
            or skills.get("skills")
        )
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

        # If catalog is list of objects with more detail
        all_ids = set(en_ids) | set(cat_ids)
        raw = json.dumps(skills)
        presence = {}
        for n in NEEDED:
            in_enabled = n in en_ids
            in_catalog = n in cat_ids
            in_raw = f'"{n}"' in raw
            presence[n] = {
                "present": in_enabled or in_catalog or in_raw,
                "enabled": in_enabled,
                "in_catalog": in_catalog,
            }
        print(f"enabled_count={enabled_count}")
        print(f"total_catalog={total_catalog}")
        print(f"enabled_len={len(en_ids)} catalog_len={len(cat_ids)}")
        print(f"presence={json.dumps(presence)}")
        print(f"enabled_sample={en_ids[:40]}")
        print(f"catalog_sample={cat_ids[:40]}")
    elif isinstance(skills, list):
        en_ids = ids_of(skills)
        cat_ids = en_ids
        enabled_count = len(en_ids)
        total_catalog = len(en_ids)
        presence = {n: {"present": n in en_ids, "enabled": n in en_ids, "in_catalog": n in en_ids} for n in NEEDED}
        print(f"skills list len={len(skills)}")
        print(f"presence={json.dumps(presence)}")
    else:
        en_ids, cat_ids = [], []
        enabled_count = None
        total_catalog = None
        presence = {n: {"present": False, "enabled": False, "in_catalog": False} for n in NEEDED}
        print(f"skills body={str(skills)[:800]}")

    report = {
        "base": BASE,
        "email": login.get("email"),
        "templates": {
            "status": code_t,
            "count": len(items),
            "items": names,
        },
        "orchestrator": {
            "id": orch_id,
            "name": orch.get("name") if orch else None,
            "role": orch.get("role") if orch else None,
            "status": orch.get("status") if orch else None,
        },
        "skills": {
            "path": f"/api/agents/{orch_id}/skills",
            "http": code_s,
            "enabled_count": enabled_count,
            "total_catalog": total_catalog,
            "presence": presence,
            "enabled_ids_sample": (en_ids[:50] if en_ids else []),
            "catalog_ids_sample": (cat_ids[:50] if cat_ids else []),
            "top_keys": list(skills.keys()) if isinstance(skills, dict) else None,
        },
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {REPORT_PATH}")
    print(json.dumps({
        "templates_count": report["templates"]["count"],
        "orchestrator_id": orch_id,
        "enabled_count": enabled_count,
        "total_catalog": total_catalog,
        "presence_summary": {k: v["present"] for k, v in presence.items()},
    }, indent=2))
    return 0 if code_t == 200 and code_s == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
