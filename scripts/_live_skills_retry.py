#!/usr/bin/env python3
"""Login then immediately GET orchestrator skills; retry through key-rotation races."""
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
ORCH_ID_HINT = 27


def req(method: str, path: str, token: str | None = None, body: dict | None = None):
    url = BASE + path
    data = None
    headers = {"Accept": "application/json", "User-Agent": "skills-retry/1.1"}
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
            return int(e.code), json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return int(e.code), raw
    except (URLError, TimeoutError, OSError) as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def ids_of(x):
    out = []
    if isinstance(x, list):
        for it in x:
            if isinstance(it, str):
                out.append(it)
            elif isinstance(it, dict):
                out.append(it.get("id") or it.get("skill") or it.get("name") or it.get("key"))
    elif isinstance(x, dict):
        # catalog may be list of dicts OR id->meta map
        for k, v in x.items():
            if isinstance(v, dict) and (v.get("id") or "name" in v or "description" in v):
                out.append(v.get("id") or k)
            else:
                out.append(k)
    return [i for i in out if i]


def extract_list(body, keys):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for k in keys:
            if isinstance(body.get(k), list):
                return body[k]
    return []


def main() -> int:
    login = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
    report = None

    for attempt in range(1, 16):
        code, body = req(
            "POST",
            "/api/auth/login",
            body={"email": login["email"], "password": login["password"]},
        )
        if code == 429:
            print(f"attempt {attempt}: login 429 — sleep 20s")
            time.sleep(20)
            continue
        if code != 200 or not isinstance(body, dict):
            print(f"attempt {attempt}: login {code} {str(body)[:160]}")
            time.sleep(1)
            continue

        token = body.get("api_key") or body.get("token")
        if not token:
            print(f"attempt {attempt}: no token keys={list(body.keys())}")
            continue

        # skills first (minimize race window)
        code_s, skills = req("GET", f"/api/agents/{ORCH_ID_HINT}/skills", token=token)
        print(f"attempt {attempt}: skills={code_s}")
        if code_s != 200 or not isinstance(skills, dict):
            print(f"  detail={str(skills)[:200]}")
            time.sleep(0.25)
            continue

        (ROOT / "_live_skills_raw.json").write_text(
            json.dumps(skills, indent=2, ensure_ascii=False)[:500000],
            encoding="utf-8",
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
        if isinstance(skills.get("stats"), dict):
            total_catalog = total_catalog or skills["stats"].get("unique_catalog") or skills["stats"].get("total")
        if total_catalog is None:
            total_catalog = len(cat_ids) if cat_ids else None

        raw = json.dumps(skills)
        presence = {}
        for n in NEEDED:
            presence[n] = {
                "present": (n in en_ids) or (n in cat_ids) or (f'"{n}"' in raw),
                "enabled": n in en_ids,
                "in_catalog": n in cat_ids,
            }

        # secondary reads (best-effort; may 401 if key rotated)
        code_a, agents_body = req("GET", "/api/agents/", token=token)
        alist = extract_list(agents_body, ("agents", "items", "data", "results"))
        orch = None
        for a in alist:
            if not isinstance(a, dict):
                continue
            if a.get("id") == ORCH_ID_HINT or "orchestrator" in (a.get("name") or "").lower():
                orch = a
                break

        code_t, templates_body = req("GET", "/api/templates/", token=token)
        titems = extract_list(templates_body, ("templates", "items", "data", "results"))
        # If templates 401, re-login once just for templates count
        if code_t != 200:
            code2, body2 = req(
                "POST",
                "/api/auth/login",
                body={"email": login["email"], "password": login["password"]},
            )
            if code2 == 200 and isinstance(body2, dict):
                token2 = body2.get("api_key") or body2.get("token")
                code_t, templates_body = req("GET", "/api/templates/", token=token2)
                titems = extract_list(templates_body, ("templates", "items", "data", "results"))
                if token2:
                    token = token2

        template_names = []
        for it in titems:
            if isinstance(it, dict):
                template_names.append(
                    {
                        "id": it.get("id"),
                        "name": it.get("name") or it.get("title"),
                        "slug": it.get("slug"),
                    }
                )

        report = {
            "base": BASE,
            "attempt": attempt,
            "email": login.get("email"),
            "templates_http": code_t,
            "templates_count": len(titems),
            "template_names": template_names,
            "agents_http": code_a,
            "agents_count": len(alist),
            "orchestrator_id": (orch or {}).get("id") or ORCH_ID_HINT,
            "orchestrator": {
                "id": (orch or {}).get("id") or ORCH_ID_HINT,
                "name": (orch or {}).get("name"),
                "role": (orch or {}).get("role"),
                "status": (orch or {}).get("status"),
            },
            "skills": {
                "path": f"/api/agents/{ORCH_ID_HINT}/skills",
                "http": code_s,
                "enabled_count": enabled_count,
                "total_catalog": total_catalog,
                "presence": presence,
                "skills_keys": list(skills.keys()),
                "enabled_sample": en_ids[:60],
                "catalog_sample": cat_ids[:60],
                "stats": skills.get("stats"),
            },
        }
        login["api_key"] = token
        LOGIN_PATH.write_text(json.dumps(login, indent=2) + "\n", encoding="utf-8")
        (ROOT / ".demo_token").write_text(token, encoding="utf-8")
        out = ROOT / "_live_templates_skills_report.json"
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({
            "templates_count": report["templates_count"],
            "orchestrator_id": report["orchestrator_id"],
            "enabled_count": enabled_count,
            "total_catalog": total_catalog,
            "presence": {k: v["present"] for k, v in presence.items()},
            "presence_detail": presence,
            "skills_keys": list(skills.keys()),
            "stats": skills.get("stats"),
        }, indent=2))
        print("wrote", out)
        return 0

    print("FAIL: could not fetch skills after retries")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
