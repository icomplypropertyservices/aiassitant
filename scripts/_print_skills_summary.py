#!/usr/bin/env python3
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent
BASE = "https://www.aibusinessagent.xyz"
login = json.loads((ROOT / ".demo_login.json").read_text(encoding="utf-8"))
report = json.loads((ROOT / "_live_templates_skills_report.json").read_text(encoding="utf-8"))

print("=== FROM REPORT ===")
print("templates_count", report.get("templates_count"))
for i, t in enumerate(report.get("template_names") or [], 1):
    print(f"  {i:02d}. id={t.get('id')} {t.get('name')}")
print("orchestrator", report.get("orchestrator"))
sk = report.get("skills") or {}
print("enabled_count", sk.get("enabled_count"))
print("total_catalog", sk.get("total_catalog"))
print("presence", json.dumps(sk.get("presence"), indent=2))
print("enabled_sample", sk.get("enabled_sample", [])[:30])


def req(method, path, token=None, body=None):
    data = None
    h = {"Accept": "application/json", "User-Agent": "summary/1"}
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = f"Bearer {token}"
        h["X-API-Key"] = token
    r = Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urlopen(r, timeout=90) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return int(getattr(resp, "status", None) or resp.getcode()), json.loads(raw) if raw else None
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            return int(e.code), json.loads(raw) if raw else None
        except Exception:
            return int(e.code), raw


# re-fetch summary only
code, body = req(
    "POST",
    "/api/auth/login",
    body={"email": login["email"], "password": login["password"]},
)
print("login", code)
if code == 200 and isinstance(body, dict):
    token = body.get("api_key") or body.get("token")
    code_s, skills = req("GET", "/api/agents/27/skills", token=token)
    print("skills", code_s)
    if code_s == 200 and isinstance(skills, dict):
        print("agent_id", skills.get("agent_id"))
        print("role", skills.get("role"))
        print("enabled_count", skills.get("enabled_count"))
        print("summary", json.dumps(skills.get("summary"), indent=2))
        cat = skills.get("catalog") or []
        print("catalog_len", len(cat) if isinstance(cat, list) else type(cat).__name__)
        sl = skills.get("skills") or []
        print("skills_list_len", len(sl))
        # check needed in catalog ids
        cat_ids = []
        for it in cat if isinstance(cat, list) else []:
            if isinstance(it, dict):
                cat_ids.append(it.get("id"))
            elif isinstance(it, str):
                cat_ids.append(it)
        # catalog might be list of skill objects
        for n in ("create_task", "execute_goal", "message_agent", "status_update"):
            in_cat = n in cat_ids or any(
                isinstance(it, dict) and it.get("id") == n for it in (cat if isinstance(cat, list) else [])
            )
            in_skills = any(isinstance(it, dict) and it.get("id") == n for it in sl)
            en = any(isinstance(it, dict) and it.get("id") == n and it.get("enabled") for it in sl)
            print(f"  {n}: in_catalog={in_cat} in_skills={in_skills} enabled_flag={en}")
        # save slim summary
        slim = {
            "agent_id": skills.get("agent_id"),
            "role": skills.get("role"),
            "enabled_count": skills.get("enabled_count"),
            "summary": skills.get("summary"),
            "catalog_len": len(cat) if isinstance(cat, list) else None,
            "skills_list_len": len(sl),
            "needed": {
                n: {
                    "in_catalog": n in cat_ids
                    or any(isinstance(it, dict) and it.get("id") == n for it in (cat if isinstance(cat, list) else [])),
                    "in_skills": any(isinstance(it, dict) and it.get("id") == n for it in sl),
                    "enabled": any(
                        isinstance(it, dict) and it.get("id") == n and it.get("enabled") for it in sl
                    ),
                }
                for n in ("create_task", "execute_goal", "message_agent", "status_update")
            },
        }
        (ROOT / "_live_skills_summary.json").write_text(json.dumps(slim, indent=2) + "\n", encoding="utf-8")
        print("wrote _live_skills_summary.json")
    else:
        print("skills body", str(skills)[:300])
else:
    print("login body", str(body)[:300])
