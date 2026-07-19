#!/usr/bin/env python3
import json
import ssl
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://www.aibusinessagent.xyz"
login = json.loads(Path("scripts/.demo_login.json").read_text(encoding="utf-8"))
report_path = Path("scripts/live_chat_chain_report.json")


def call(method, path, token=None, body=None, timeout=60, retries=3):
    url = BASE + path
    last = (0, {"error": "no attempt"})
    for i in range(retries):
        data = None
        headers = {"Accept": "application/json", "User-Agent": "tasks-once/1.0"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=timeout) as resp:
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
            # don't retry hard auth failures
            if e.code in (401, 403):
                return int(e.code), parsed
            last = (int(e.code), parsed)
        except Exception as e:
            last = (0, {"error": repr(e)})
            print(f"  attempt {i+1} failed: {e!r}")
            time.sleep(1.5 * (i + 1))
    return last


print("login...")
code, body = call(
    "POST",
    "/api/auth/login",
    body={"email": login["email"], "password": login["password"]},
    timeout=90,
    retries=4,
)
print("LOGIN", code, type(body).__name__)
if isinstance(body, dict):
    print(" keys", sorted(body.keys()))
    for k in ("api_key", "access_token", "token"):
        if body.get(k):
            print(f" {k}_prefix", str(body[k])[:18], "len", len(str(body[k])))

token = None
if isinstance(body, dict):
    token = body.get("api_key") or body.get("access_token") or body.get("token")
if not token:
    token = login.get("api_key")
    print("using stored api_key")

if not token:
    print("NO TOKEN")
    raise SystemExit(1)

# health with auth optional
c, h = call("GET", "/api/health", timeout=30, retries=2)
print("HEALTH", c)

c, me = call("GET", "/api/auth/me", token=token, timeout=45, retries=3)
print("ME", c, me.get("plan") if isinstance(me, dict) else me)

results = {}
for path in [
    "/api/agents/",
    "/api/agents/9/tasks",
    "/api/agents/tasks/76",
    "/api/org/tasks",
    "/api/agents/tasks/board",
]:
    c, b = call("GET", path, token=token, timeout=60, retries=2)
    print("GET", path, c)
    entry = {"status": c}
    if isinstance(b, list):
        entry["count"] = len(b)
        chain = []
        for t in b:
            if not isinstance(t, dict):
                continue
            labels = str(t.get("labels") or "")
            tid = t.get("id")
            if (
                "auto-chain" in labels
                or "goal" in labels
                or (isinstance(tid, int) and 76 <= tid <= 90)
                or t.get("parent_task_id") == 76
            ):
                chain.append(
                    {
                        "id": tid,
                        "title": t.get("title"),
                        "status": t.get("status"),
                        "labels": t.get("labels"),
                        "parent_task_id": t.get("parent_task_id"),
                        "agent_id": t.get("agent_id"),
                    }
                )
        entry["chain_related"] = chain
        entry["sample"] = [
            {
                "id": t.get("id"),
                "title": t.get("title"),
                "status": t.get("status"),
                "labels": t.get("labels"),
                "parent_task_id": t.get("parent_task_id"),
            }
            for t in b[:15]
            if isinstance(t, dict)
        ]
        for row in chain[:12]:
            print("  ", row)
    elif isinstance(b, dict):
        entry["keys"] = sorted(b.keys())[:20]
        if b.get("detail"):
            entry["detail"] = b.get("detail")
            print("  detail", b.get("detail"))
        if b.get("id") is not None:
            entry["task"] = {
                "id": b.get("id"),
                "title": b.get("title"),
                "status": b.get("status"),
                "labels": b.get("labels"),
                "parent_task_id": b.get("parent_task_id"),
            }
            print("  task", entry["task"])
        # board
        all_tasks = []
        if isinstance(b.get("tasks"), list):
            all_tasks = b["tasks"]
        if isinstance(b.get("columns"), list):
            for col in b["columns"]:
                if isinstance(col, dict):
                    all_tasks.extend(col.get("tasks") or [])
        if all_tasks:
            entry["flattened_count"] = len(all_tasks)
            chain = []
            for t in all_tasks:
                if not isinstance(t, dict):
                    continue
                labels = str(t.get("labels") or "")
                tid = t.get("id")
                if (
                    "auto-chain" in labels
                    or "goal" in labels
                    or (isinstance(tid, int) and 76 <= tid <= 90)
                    or t.get("parent_task_id") == 76
                ):
                    chain.append(
                        {
                            "id": tid,
                            "title": t.get("title"),
                            "status": t.get("status"),
                            "labels": t.get("labels"),
                            "parent_task_id": t.get("parent_task_id"),
                        }
                    )
            entry["chain_related"] = chain
            for row in chain[:12]:
                print("  ", row)
        if c >= 400 and not entry.get("detail"):
            entry["body_preview"] = json.dumps(b)[:400]
    else:
        entry["body"] = str(b)[:300]
        print("  body", str(b)[:200])
    results[path] = entry

# update report
rep = json.loads(report_path.read_text(encoding="utf-8"))
rep["steps"]["tasks"] = results
rep["steps"]["tasks_refresh"] = {
    "login_status": code,
    "me_status": c if "me" in dir() else None,
    "note": "tasks_once re-fetch with retries",
}
report_path.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
print("WROTE", report_path)
