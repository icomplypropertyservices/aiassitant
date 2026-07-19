#!/usr/bin/env python3
"""Create a queued task on the orchestrator, optionally POST /run, report id+status."""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LOGIN_PATH = ROOT / ".demo_login.json"
OUT_PATH = ROOT / "live_queued_task_report.json"
BASE = "https://www.aibusinessagent.xyz"


def call(method: str, path: str, token: str | None = None, body=None, timeout: int = 90):
    data = None
    h = {"Accept": "application/json", "User-Agent": "live-create-queued/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = f"Bearer {token}"
        h["X-API-Key"] = token
    req = Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            code = int(getattr(r, "status", None) or r.getcode())
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
    except Exception as e:
        return 0, {"error": repr(e)}


def main() -> int:
    login = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
    orch_id = int(login.get("agent_id") or 27)
    title = f"Live test queued task {int(time.time())}"
    best = None

    for attempt in range(8):
        c, body = call(
            "POST",
            "/api/auth/login",
            body={"email": login["email"], "password": login["password"]},
            timeout=60,
        )
        if c != 200 or not isinstance(body, dict):
            print(f"attempt {attempt}: login {c} {str(body)[:160]}")
            time.sleep(1.5)
            continue
        tok = body.get("api_key") or body.get("token")
        if not tok:
            print(f"attempt {attempt}: no token keys={list(body.keys())}")
            time.sleep(1)
            continue

        # Persist for browser step
        login["api_key"] = tok
        if isinstance(body.get("user"), dict) and body["user"].get("id") is not None:
            login["user_id"] = body["user"]["id"]
        LOGIN_PATH.write_text(json.dumps(login, indent=2), encoding="utf-8")
        (ROOT / ".demo_token").write_text(tok, encoding="utf-8")

        # Immediate create — no other calls first (avoids concurrent key rotation window)
        create_body = {
            "title": title,
            "description": (
                "Live API test: confirm task appears on /agents/tasks "
                "with non-empty status."
            ),
            "priority": "high",
            "labels": "live-test,queued,demo",
            "run_now": False,
        }
        c1, task = call(
            "POST",
            f"/api/agents/{orch_id}/tasks",
            token=tok,
            body=create_body,
            timeout=60,
        )
        print(f"attempt {attempt}: create={c1}")
        if c1 == 401:
            time.sleep(0.6)
            continue
        if c1 != 200 or not isinstance(task, dict) or not task.get("id"):
            print("  body", str(task)[:280])
            # Try ensure-orchestrator then create again with same tok
            c0, orch = call("POST", "/api/agents/ensure-orchestrator", token=tok)
            print(f"  ensure-orch={c0}", str(orch)[:120] if not isinstance(orch, dict) else orch.get("id"))
            if c0 == 200 and isinstance(orch, dict) and orch.get("id"):
                orch_id = int(orch["id"])
                login["agent_id"] = orch_id
                LOGIN_PATH.write_text(json.dumps(login, indent=2), encoding="utf-8")
                c1, task = call(
                    "POST",
                    f"/api/agents/{orch_id}/tasks",
                    token=tok,
                    body=create_body,
                    timeout=60,
                )
                print(f"  create retry={c1}")
            if c1 != 200 or not isinstance(task, dict) or not task.get("id"):
                time.sleep(1)
                continue

        task_id = int(task["id"])
        status = task.get("status")
        print(f"  created id={task_id} status={status}")

        # Promote to queued if API left it as todo (run_now=false)
        if status != "queued":
            c2, patched = call(
                "PATCH",
                f"/api/agents/tasks/{task_id}",
                token=tok,
                body={"status": "queued"},
            )
            print(f"  patch queued={c2}", patched.get("status") if isinstance(patched, dict) else str(patched)[:120])
            if c2 == 401:
                c, body = call(
                    "POST",
                    "/api/auth/login",
                    body={"email": login["email"], "password": login["password"]},
                )
                tok = (body or {}).get("api_key") if isinstance(body, dict) else None
                if tok:
                    login["api_key"] = tok
                    LOGIN_PATH.write_text(json.dumps(login, indent=2), encoding="utf-8")
                    c2, patched = call(
                        "PATCH",
                        f"/api/agents/tasks/{task_id}",
                        token=tok,
                        body={"status": "queued"},
                    )
                    print(f"  patch retry={c2}")
            if isinstance(patched, dict) and patched.get("status"):
                status = patched.get("status")
                task = patched

        # POST run endpoint
        c3, runb = call("POST", f"/api/agents/tasks/{task_id}/run", token=tok, body={})
        print(f"  run={c3}", runb.get("status") if isinstance(runb, dict) else str(runb)[:160])
        if c3 == 401:
            c, body = call(
                "POST",
                "/api/auth/login",
                body={"email": login["email"], "password": login["password"]},
            )
            tok = (body or {}).get("api_key") if isinstance(body, dict) else None
            if tok:
                login["api_key"] = tok
                LOGIN_PATH.write_text(json.dumps(login, indent=2), encoding="utf-8")
                c3, runb = call("POST", f"/api/agents/tasks/{task_id}/run", token=tok, body={})
                print(f"  run retry={c3}", runb.get("status") if isinstance(runb, dict) else str(runb)[:160])
        if isinstance(runb, dict) and runb.get("id"):
            status = runb.get("status") or status
            task = runb

        # Confirm via GET
        c4, got = call("GET", f"/api/agents/tasks/{task_id}", token=tok)
        if c4 == 401:
            c, body = call(
                "POST",
                "/api/auth/login",
                body={"email": login["email"], "password": login["password"]},
            )
            tok = (body or {}).get("api_key") if isinstance(body, dict) else None
            if tok:
                login["api_key"] = tok
                LOGIN_PATH.write_text(json.dumps(login, indent=2), encoding="utf-8")
                c4, got = call("GET", f"/api/agents/tasks/{task_id}", token=tok)
        print(f"  get={c4}", {k: got.get(k) for k in ("id", "title", "status", "agent_id")} if isinstance(got, dict) else got)
        if isinstance(got, dict) and got.get("id"):
            status = got.get("status") or status
            task = got

        # List on agent for visibility
        c5, alist = call("GET", f"/api/agents/{orch_id}/tasks", token=tok)
        match = []
        if isinstance(alist, list):
            match = [t for t in alist if t.get("id") == task_id]
            print(f"  list={c5} count={len(alist)} match={[t.get('status') for t in match]}")
        else:
            print(f"  list={c5}", str(alist)[:160])

        best = {
            "task_id": task_id,
            "status": status,
            "agent_id": orch_id,
            "title": title,
            "create_http": c1,
            "run_http": c3,
            "get_http": c4,
            "list_http": c5,
            "task": (
                {
                    k: task.get(k)
                    for k in (
                        "id",
                        "title",
                        "status",
                        "agent_id",
                        "labels",
                        "priority",
                        "description",
                    )
                }
                if isinstance(task, dict)
                else task
            ),
            "list_match": [
                {k: t.get(k) for k in ("id", "title", "status", "agent_id")} for t in match
            ],
            "token_prefix": (tok or "")[:18],
        }
        break

    if not best:
        OUT_PATH.write_text(json.dumps({"ok": False, "error": "all attempts failed"}, indent=2), encoding="utf-8")
        print("FAILED")
        return 2

    OUT_PATH.write_text(json.dumps({"ok": True, **best}, indent=2, default=str), encoding="utf-8")
    print("OK", json.dumps({"task_id": best["task_id"], "status": best["status"], "agent_id": best["agent_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
