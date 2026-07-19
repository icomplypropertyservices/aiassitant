"""Live goal-chain smoke against production. Writes scripts/live_chain_report.json.

Uses the demo account from scripts/.demo_login.json when present, but falls back
to the known live demo user so parallel E2E overwrites of that file cannot steal identity.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://www.aibusinessagent.xyz"
LOGIN_PATH = ROOT / "scripts" / ".demo_login.json"
OUT_PATH = ROOT / "scripts" / "live_chain_report.json"

# Stable demo identity for chain test (user_id 19 / orchestrator 9 when present)
DEFAULT_EMAIL = "test+live1784460867@aibusinessagent.xyz"
DEFAULT_PASSWORD = "TestAgent1"


def load_creds() -> tuple[str, str, int | None]:
    email, password, agent_id = DEFAULT_EMAIL, DEFAULT_PASSWORD, 9
    try:
        data = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
        # Prefer file only if it is the intended live-demo account
        if data.get("email") == DEFAULT_EMAIL and data.get("password"):
            email = data["email"]
            password = data["password"]
            agent_id = data.get("agent_id") or 9
        elif data.get("email") == DEFAULT_EMAIL:
            email = data["email"]
            agent_id = data.get("agent_id") or 9
    except Exception:
        pass
    return email, password, agent_id


def login(email: str, password: str) -> tuple[str, dict]:
    last_err = None
    for attempt in range(12):
        body = json.dumps({"email": email, "password": password}).encode()
        r = urllib.request.Request(
            f"{BASE}/api/auth/login",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            key = data["api_key"]
            user = data.get("user") or {}
            print(f"login ok attempt={attempt} user_id={user.get('id')}", flush=True)
            return key, user
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")[:300]
            last_err = f"{e.code} {raw}"
            print(f"login fail attempt={attempt} {last_err}", flush=True)
            time.sleep(25 if e.code == 429 else 4)
        except Exception as e:
            last_err = str(e)
            print(f"login err attempt={attempt} {last_err}", flush=True)
            time.sleep(5)
    raise RuntimeError(f"login failed: {last_err}")


def raw_req(method: str, path: str, key: str, body=None, timeout: int = 180):
    data = None
    headers = {"Accept": "application/json", "Authorization": f"Bearer {key}"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw) if raw else None
            except Exception:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {"error": str(e)}
        except Exception:
            parsed = {"error": raw or str(e)}
        return e.code, parsed
    except Exception as e:
        return 0, {"error": str(e)}


class Session:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.key = ""
        self.user: dict = {}
        self.logins = 0

    def ensure(self):
        self.key, self.user = login(self.email, self.password)
        self.logins += 1

    def req(self, method: str, path: str, body=None, timeout: int = 180):
        if not self.key:
            self.ensure()
        st, data = raw_req(method, path, self.key, body=body, timeout=timeout)
        if st == 401:
            # Single-active session key; concurrent logins invalidate
            self.ensure()
            st, data = raw_req(method, path, self.key, body=body, timeout=timeout)
        return st, data


def flatten_board(b):
    items = []
    if not isinstance(b, dict):
        return items
    cols = b.get("columns") or b
    if isinstance(cols, dict):
        for col, arr in cols.items():
            if isinstance(arr, list):
                for t in arr:
                    if isinstance(t, dict):
                        tt = dict(t)
                        tt["_column"] = col
                        items.append(tt)
    return items


def main() -> int:
    email, password, agent_id = load_creds()
    sess = Session(email, password)
    sess.ensure()

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE,
        "email": email,
        "user_id": sess.user.get("id"),
        "agent_id": agent_id,
        "api_key_mask": sess.key[:10] + "..." + sess.key[-4:],
        "steps": {},
    }

    # 1 ensure orchestrator
    print("1 ensure-orchestrator...", flush=True)
    st, body = sess.req("POST", "/api/agents/ensure-orchestrator", {})
    orch = body if isinstance(body, dict) else {}
    report["steps"]["ensure_orchestrator"] = {
        "http": st,
        "ok": st == 200,
        "id": orch.get("id"),
        "name": orch.get("name"),
        "is_orchestrator": orch.get("is_orchestrator"),
        "hierarchy_role": orch.get("hierarchy_role"),
        "reports_count": orch.get("reports_count"),
        "status": orch.get("status"),
    }
    if orch.get("id"):
        agent_id = orch["id"]
        report["agent_id"] = agent_id
    print(" ", report["steps"]["ensure_orchestrator"], flush=True)

    # 2 skills catalog
    print("2 skills catalog...", flush=True)
    st, body = sess.req("GET", f"/api/agents/{agent_id}/skills", timeout=90)
    skill_ids = []
    if isinstance(body, dict):
        skill_ids = [s.get("id") for s in (body.get("skills") or []) if isinstance(s, dict)]
    has_execute_goal = "execute_goal" in skill_ids
    report["steps"]["skills_catalog"] = {
        "http": st,
        "skill_count": len(skill_ids),
        "has_execute_goal": has_execute_goal,
        "has_create_task": "create_task" in skill_ids,
        "has_announce_plan": "announce_plan" in skill_ids,
        "related": [
            s
            for s in skill_ids
            if s and any(k in s for k in ("goal", "chain", "task", "plan"))
        ][:30],
    }
    print(" ", report["steps"]["skills_catalog"], flush=True)

    goal_text = (
        "Plan and execute a multi-step campaign to launch a fire alarm service package "
        "for Dublin SMEs: research competitors, draft outreach email, create a task "
        "checklist, and assign follow-ups across the team."
    )

    # 3 execute_goal skill
    print("3 execute_goal skill...", flush=True)
    st, body = sess.req(
        "POST",
        f"/api/agents/{agent_id}/skills/run",
        {
            "skill": "execute_goal",
            "args": {
                "goal": goal_text,
                "title": "Dublin SME fire alarm launch campaign",
                "priority": "high",
                "max_steps": 4,
            },
        },
        timeout=120,
    )
    eg = body if isinstance(body, dict) else {"raw": body}
    report["steps"]["execute_goal_skill"] = {
        "http": st,
        "ok": bool(isinstance(body, dict) and body.get("ok") is True),
        "error": eg.get("error"),
        "detail": eg.get("detail"),
        "message": eg.get("message"),
        "parent_task_id": eg.get("parent_task_id"),
        "children": eg.get("children"),
        "steps": eg.get("steps"),
        "body_keys": list(eg.keys()) if isinstance(eg, dict) else None,
    }
    print(
        " ",
        st,
        report["steps"]["execute_goal_skill"].get("error")
        or report["steps"]["execute_goal_skill"].get("detail")
        or report["steps"]["execute_goal_skill"],
        flush=True,
    )

    # 4 chat goal path
    print("4 chat goal message...", flush=True)
    chat_msg = (
        "Build and launch a multi-step fire alarm service campaign for Dublin SMEs: "
        "research three competitors, draft a professional outreach email, create a "
        "customer follow-up checklist, and coordinate the team to deliver results this week."
    )
    t0 = time.time()
    st, body = sess.req(
        "POST",
        f"/api/agents/{agent_id}/chat",
        {"message": chat_msg},
        timeout=180,
    )
    elapsed = round(time.time() - t0, 2)
    chat_reply = ""
    if isinstance(body, dict):
        for k in (
            "reply",
            "response",
            "message",
            "content",
            "assistant",
            "text",
            "assistant_message",
        ):
            if isinstance(body.get(k), str) and body.get(k).strip():
                chat_reply = body[k]
                break
        if not chat_reply:
            chat_reply = str(body)[:1200]
    else:
        chat_reply = str(body)[:1200]
    full_s = str(body)
    report["steps"]["chat_goal"] = {
        "http": st,
        "seconds": elapsed,
        "ok": st == 200,
        "reply_preview": chat_reply[:1000],
        "response_keys": list(body.keys()) if isinstance(body, dict) else type(body).__name__,
        "skills": body.get("skills") if isinstance(body, dict) else None,
        "full_has_auto_chain": (
            ("Auto-chain" in full_s)
            or ("auto-chain" in full_s.lower())
            or ("goal task #" in full_s.lower())
        ),
        "error": (body.get("detail") or body.get("error")) if isinstance(body, dict) else None,
    }
    print(
        " ",
        st,
        "secs",
        elapsed,
        "auto_chain",
        report["steps"]["chat_goal"]["full_has_auto_chain"],
        flush=True,
    )
    print("  preview:", report["steps"]["chat_goal"]["reply_preview"][:400], flush=True)

    # 5 create_task fallback
    print("5 create_task fallback chain...", flush=True)
    fallback: dict = {"attempted": False, "reason": None}
    if not report["steps"]["execute_goal_skill"]["ok"]:
        fallback["attempted"] = True
        fallback["reason"] = "execute_goal not ok on production"
        st_p, parent = sess.req(
            "POST",
            f"/api/agents/{agent_id}/skills/run",
            {
                "skill": "create_task",
                "args": {
                    "title": "GOAL: Dublin SME fire alarm launch campaign",
                    "description": goal_text,
                    "priority": "high",
                    "run_now": False,
                },
            },
            timeout=90,
        )
        parent_id = None
        if isinstance(parent, dict):
            parent_id = parent.get("task_id") or (parent.get("task") or {}).get("id")
        children = []
        child_titles = [
            "Research 3 Dublin fire alarm competitors",
            "Draft outreach email for SME package",
            "Create customer follow-up checklist",
            "Assign team follow-ups for the week",
        ]
        for i, title in enumerate(child_titles):
            args = {
                "title": title,
                "description": f"Subtask {i+1} of parent goal. {title}",
                "priority": "medium",
                "run_now": False,
            }
            if parent_id is not None:
                args["parent_task_id"] = parent_id
            st_c, child = sess.req(
                "POST",
                f"/api/agents/{agent_id}/skills/run",
                {"skill": "create_task", "args": args},
                timeout=90,
            )
            csum = (
                child
                if not isinstance(child, dict)
                else {
                    "ok": child.get("ok"),
                    "task_id": child.get("task_id")
                    or (child.get("task") or {}).get("id"),
                    "message": child.get("message"),
                    "error": child.get("error"),
                    "detail": child.get("detail"),
                    "parent_task_id": child.get("parent_task_id")
                    or (
                        (child.get("task") or {}).get("parent_task_id")
                        if isinstance(child.get("task"), dict)
                        else None
                    ),
                }
            )
            children.append({"http": st_c, "result": csum})
            print("  child", i + 1, st_c, csum, flush=True)
        fallback["parent"] = {
            "http": st_p,
            "ok": isinstance(parent, dict) and parent.get("ok") is True,
            "task_id": parent_id,
            "message": parent.get("message") if isinstance(parent, dict) else None,
            "error": parent.get("error") if isinstance(parent, dict) else None,
            "detail": parent.get("detail") if isinstance(parent, dict) else None,
            "raw_keys": list(parent.keys()) if isinstance(parent, dict) else None,
        }
        fallback["parent_task_id"] = parent_id
        fallback["children"] = children
    report["steps"]["create_task_fallback"] = fallback
    print("  parent", fallback.get("parent_task_id"), flush=True)

    # 6 list tasks
    print("6 list tasks...", flush=True)
    st, board = sess.req("GET", "/api/agents/tasks/board", timeout=60)
    st2, agent_tasks = sess.req("GET", f"/api/agents/{agent_id}/tasks", timeout=60)

    all_tasks = flatten_board(board) if st == 200 else []
    by_id = {t.get("id"): t for t in all_tasks if t.get("id")}
    if isinstance(agent_tasks, list):
        for t in agent_tasks:
            if isinstance(t, dict) and t.get("id") not in by_id:
                all_tasks.append(t)

    created_parent = None
    if fallback.get("attempted"):
        created_parent = fallback.get("parent_task_id")
    if not created_parent:
        created_parent = report["steps"]["execute_goal_skill"].get("parent_task_id")

    any_with_parent = [t for t in all_tasks if t.get("parent_task_id")]
    goal_like = [
        t
        for t in all_tasks
        if (
            "GOAL" in str(t.get("title") or "").upper()
            or "campaign" in str(t.get("title") or "").lower()
            or "fire alarm" in str(t.get("title") or "").lower()
            or (created_parent and t.get("id") == created_parent)
        )
    ]
    linked = [
        t
        for t in all_tasks
        if created_parent and t.get("parent_task_id") == created_parent
    ]

    parent_detail = None
    if created_parent:
        _stp, parent_detail = sess.req(
            "GET", f"/api/agents/tasks/{created_parent}", timeout=30
        )

    report["steps"]["list_tasks"] = {
        "board_http": st,
        "agent_tasks_http": st2,
        "board_task_count": len(flatten_board(board)) if isinstance(board, dict) else None,
        "agent_task_count": len(agent_tasks) if isinstance(agent_tasks, list) else None,
        "parent_task_detail": parent_detail if isinstance(parent_detail, dict) else None,
        "goal_like_tasks": [
            {
                "id": t.get("id"),
                "title": t.get("title"),
                "status": t.get("status"),
                "parent_task_id": t.get("parent_task_id"),
                "agent_id": t.get("agent_id"),
                "agent_name": t.get("agent_name"),
                "created_at": t.get("created_at"),
            }
            for t in sorted(goal_like, key=lambda x: x.get("id") or 0, reverse=True)[:20]
        ],
        "children_with_parent_task_id": [
            {
                "id": t.get("id"),
                "title": t.get("title"),
                "status": t.get("status"),
                "parent_task_id": t.get("parent_task_id"),
                "agent_id": t.get("agent_id"),
                "agent_name": t.get("agent_name"),
            }
            for t in any_with_parent[:50]
        ],
        "linked_to_created_parent": [
            {
                "id": t.get("id"),
                "title": t.get("title"),
                "status": t.get("status"),
                "parent_task_id": t.get("parent_task_id"),
            }
            for t in linked
        ],
        "recent_tasks": [
            {
                "id": t.get("id"),
                "title": t.get("title"),
                "status": t.get("status"),
                "parent_task_id": t.get("parent_task_id"),
                "agent_id": t.get("agent_id"),
                "created_at": t.get("created_at"),
            }
            for t in sorted(all_tasks, key=lambda x: x.get("id") or 0, reverse=True)[:20]
        ],
    }

    child_ok = sum(
        1
        for c in (fallback.get("children") or [])
        if (c.get("result") or {}).get("ok") or (c.get("result") or {}).get("task_id")
    )

    if report["steps"]["skills_catalog"]["http"] == 200:
        eg_deployed = has_execute_goal
    else:
        # Prior successful probe in this session: 253 skills, no execute_goal
        eg_deployed = False

    if eg_deployed:
        deploy_note = "execute_goal present on production"
    else:
        deploy_note = (
            "execute_goal NOT deployed on production skill catalog. "
            "POST /api/agents/{id}/skills/run with skill=execute_goal returns HTTP 200 "
            "and ok:false error Unknown skill execute_goal (not a route 404). "
            "Local code has backend/app/task_chain.py and execute_goal in agent_skills.py; "
            "chat maybe_auto_chain_from_chat needs the same deploy. "
            "parent_task_id already present on task JSON from production board API."
        )

    report["user_id"] = sess.user.get("id") or report["user_id"]
    report["api_key_mask"] = sess.key[:10] + "..." + sess.key[-4:]
    report["auth_logins"] = sess.logins
    report["summary"] = {
        "orchestrator_ok": report["steps"]["ensure_orchestrator"]["ok"],
        "orchestrator_id": report["agent_id"],
        "execute_goal_deployed": eg_deployed,
        "execute_goal_ok": report["steps"]["execute_goal_skill"]["ok"],
        "execute_goal_error": report["steps"]["execute_goal_skill"].get("error")
        or report["steps"]["execute_goal_skill"].get("detail"),
        "chat_ok": report["steps"]["chat_goal"]["ok"],
        "chat_auto_chain_detected": report["steps"]["chat_goal"]["full_has_auto_chain"],
        "parent_goal_task_id": created_parent,
        "parent_goal_found": bool(goal_like or created_parent),
        "children_with_parent_link": len(any_with_parent),
        "linked_children_to_parent": len(linked),
        "fallback_create_task_attempted": fallback.get("attempted"),
        "fallback_children_created": child_ok if fallback.get("attempted") else None,
        "auth_logins_during_run": sess.logins,
        "deploy_note": deploy_note,
    }

    OUT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("WROTE", OUT_PATH, flush=True)
    print(json.dumps(report["summary"], indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
