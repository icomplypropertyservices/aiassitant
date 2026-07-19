#!/usr/bin/env python3
"""Probe production for chat auto-chain (goal_chain). Writes live_chat_chain_report.json."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://www.aibusinessagent.xyz"
ROOT = Path(__file__).resolve().parent
LOGIN_PATH = ROOT / ".demo_login.json"
REPORT_PATH = ROOT / "live_chat_chain_report.json"
MSG = (
    "Build a full sales plan for Live Demo Co: research ICP, write 5 outreach emails, "
    "set weekly targets, and report progress."
)


def req(
    method: str,
    path: str,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 180,
) -> tuple[int, Any]:
    url = f"{BASE}{path if path.startswith('/') else '/' + path}"
    data = None
    headers = {"Accept": "application/json", "User-Agent": "live-chat-chain/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = int(getattr(resp, "status", None) or resp.getcode())
            try:
                return code, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return code, raw
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            parsed: Any = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return int(e.code), parsed
    except (URLError, TimeoutError, OSError) as e:
        return 0, {"error": str(getattr(e, "reason", e))}


def main() -> int:
    login = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
    email = login["email"]
    password = login["password"]
    api_key = login.get("api_key")
    agent_id_hint = login.get("agent_id")
    user_id_hint = login.get("user_id")

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_url": BASE,
        "email": email,
        "user_id_hint": user_id_hint,
        "agent_id_hint": agent_id_hint,
        "message": MSG,
        "steps": {},
        "goal_chain": None,
        "auto_chain_text_present": False,
        "deploy_required": None,
        "summary": {},
    }

    # 0) health
    code, health = req("GET", "/api/health", timeout=30)
    report["steps"]["health"] = {
        "status": code,
        "body": health if isinstance(health, dict) else str(health)[:500],
    }
    print(
        "HEALTH",
        code,
        health.get("version") if isinstance(health, dict) else health,
        health.get("environment") if isinstance(health, dict) else "",
    )

    # 1) login
    code, login_body = req(
        "POST",
        "/api/auth/login",
        body={"email": email, "password": password},
        timeout=60,
    )
    print("LOGIN", code)
    token = None
    if isinstance(login_body, dict):
        token = (
            login_body.get("api_key")
            or login_body.get("access_token")
            or login_body.get("token")
        )
    if not token:
        token = api_key
        print("FALLBACK to stored api_key")

    plan = None
    sub_active = None
    uid = None
    if isinstance(login_body, dict):
        u = login_body.get("user") if isinstance(login_body.get("user"), dict) else login_body
        if isinstance(u, dict):
            plan = u.get("plan")
            sub_active = u.get("subscription_active")
            uid = u.get("id") or login_body.get("user_id")
    report["steps"]["login"] = {
        "status": code,
        "has_token": bool(token),
        "user_id": uid,
        "plan": plan,
        "subscription_active": sub_active,
    }

    if not token:
        report["summary"] = {"ok": False, "error": "no token"}
        REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("NO TOKEN")
        return 1

    # 2) me + trial
    code, me = req("GET", "/api/auth/me", token=token, timeout=60)
    print("ME", code, me.get("plan") if isinstance(me, dict) else me)
    report["steps"]["me_before"] = {
        "status": code,
        "plan": me.get("plan") if isinstance(me, dict) else None,
        "subscription_active": me.get("subscription_active") if isinstance(me, dict) else None,
        "user_id": me.get("id") if isinstance(me, dict) else None,
    }

    plan = me.get("plan") if isinstance(me, dict) else plan
    if not plan or plan in ("none", ""):
        code, trial = req(
            "POST",
            "/api/billing/plan",
            token=token,
            body={"plan": "trial"},
            timeout=60,
        )
        print(
            "TRIAL",
            code,
            (trial.get("plan"), trial.get("subscription_active"))
            if isinstance(trial, dict)
            else trial,
        )
        report["steps"]["activate_trial"] = {
            "status": code,
            "body": trial if isinstance(trial, dict) else str(trial)[:500],
        }
    else:
        report["steps"]["activate_trial"] = {"status": "skipped", "plan": plan}
        print("TRIAL skipped, plan=", plan)

    # 3) ensure orchestrator
    code, orch = req("POST", "/api/agents/ensure-orchestrator", token=token, timeout=120)
    print("ENSURE_ORCH", code, orch.get("id") if isinstance(orch, dict) else orch)
    agent_id = None
    if isinstance(orch, dict) and orch.get("id") is not None:
        agent_id = orch.get("id")
    report["steps"]["ensure_orchestrator"] = {
        "status": code,
        "agent_id": agent_id,
        "name": orch.get("name") if isinstance(orch, dict) else None,
        "is_orchestrator": orch.get("is_orchestrator") if isinstance(orch, dict) else None,
        "hierarchy_role": orch.get("hierarchy_role") if isinstance(orch, dict) else None,
        "detail": orch.get("detail") if isinstance(orch, dict) and code >= 400 else None,
    }

    code_a, agents = req("GET", "/api/agents/", token=token, timeout=60)
    print("AGENTS", code_a, len(agents) if isinstance(agents, list) else agents)
    if not agent_id and isinstance(agents, list):
        for a in agents:
            if a.get("is_orchestrator") or a.get("hierarchy_role") == "orchestrator":
                agent_id = a.get("id")
                break
        if not agent_id and agent_id_hint:
            agent_id = agent_id_hint
        if not agent_id and agents:
            agent_id = agents[0].get("id")
    report["steps"]["agents_list"] = {
        "status": code_a,
        "count": len(agents) if isinstance(agents, list) else None,
        "ids": [
            {
                "id": a.get("id"),
                "name": a.get("name"),
                "is_orchestrator": a.get("is_orchestrator"),
                "hierarchy_role": a.get("hierarchy_role"),
            }
            for a in (agents or [])
        ]
        if isinstance(agents, list)
        else None,
        "selected_agent_id": agent_id,
    }

    if not agent_id:
        report["summary"] = {"ok": False, "error": "no agent"}
        report["deploy_required"] = "unknown - no agent to chat"
        REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("NO AGENT")
        return 1

    # 4) POST chat
    print("CHAT posting to agent", agent_id, "...")
    t0 = time.time()
    code, chat = req(
        "POST",
        f"/api/agents/{agent_id}/chat",
        token=token,
        body={"message": MSG},
        timeout=300,
    )
    elapsed = round(time.time() - t0, 2)
    print("CHAT", code, "elapsed", elapsed)

    reply = ""
    goal_chain = None
    if isinstance(chat, dict):
        reply = chat.get("reply") or ""
        goal_chain = chat.get("goal_chain")
        report["steps"]["chat"] = {
            "status": code,
            "elapsed_sec": elapsed,
            "ok": chat.get("ok"),
            "conversation_id": chat.get("conversation_id"),
            "tokens": chat.get("tokens"),
            "cost": chat.get("cost"),
            "has_goal_chain_field": "goal_chain" in chat,
            "goal_chain": goal_chain,
            "skills_count": len(chat.get("skills") or [])
            if isinstance(chat.get("skills"), list)
            else None,
            "reply_preview": (reply or "")[:800],
            "reply_len": len(reply or ""),
            "detail": chat.get("detail") if code >= 400 else None,
            "response_keys": sorted(list(chat.keys())),
        }
    else:
        report["steps"]["chat"] = {
            "status": code,
            "elapsed_sec": elapsed,
            "body": str(chat)[:1000],
        }

    auto_text_markers = [
        "Auto-chain started",
        "Goal chain already running",
        "auto-chain",
        "goal task #",
        "delegated steps",
    ]
    reply_l = (reply or "").lower()
    markers_found = [m for m in auto_text_markers if m.lower() in reply_l]
    report["auto_chain_text_present"] = bool(markers_found)
    report["auto_chain_markers_found"] = markers_found
    report["goal_chain"] = goal_chain

    # 5) tasks
    tasks_results: dict[str, Any] = {}
    for path in [
        f"/api/agents/{agent_id}/tasks",
        "/api/agents/tasks/board",
        "/api/org/tasks",
    ]:
        c, body = req("GET", path, token=token, timeout=60)
        summary: dict[str, Any] = {"status": c}
        if isinstance(body, list):
            summary["type"] = "list"
            summary["count"] = len(body)
            chainish = []
            for t in body[:50]:
                if not isinstance(t, dict):
                    continue
                labels = str(t.get("labels") or "")
                title = str(t.get("title") or "")
                if (
                    "auto-chain" in labels
                    or "goal" in labels
                    or "sales" in title.lower()
                    or "icp" in title.lower()
                    or "outreach" in title.lower()
                ):
                    chainish.append(
                        {
                            "id": t.get("id"),
                            "title": t.get("title"),
                            "status": t.get("status"),
                            "labels": t.get("labels"),
                            "parent_task_id": t.get("parent_task_id"),
                            "agent_id": t.get("agent_id"),
                        }
                    )
            summary["chain_related"] = chainish
            summary["sample"] = [
                {
                    "id": t.get("id"),
                    "title": t.get("title"),
                    "status": t.get("status"),
                    "labels": t.get("labels"),
                    "parent_task_id": t.get("parent_task_id"),
                }
                for t in body[:15]
                if isinstance(t, dict)
            ]
        elif isinstance(body, dict):
            summary["type"] = "dict"
            summary["keys"] = sorted(list(body.keys()))[:30]
            if body.get("detail"):
                summary["detail"] = body.get("detail")
            for k in ("tasks", "items", "columns", "todo", "in_progress", "done"):
                if k in body:
                    v = body[k]
                    if isinstance(v, list):
                        summary[f"{k}_count"] = len(v)
                    else:
                        summary[f"{k}_type"] = type(v).__name__
            all_tasks: list = []
            if isinstance(body.get("tasks"), list):
                all_tasks = body["tasks"]
            elif isinstance(body.get("columns"), list):
                for col in body["columns"]:
                    if isinstance(col, dict) and isinstance(col.get("tasks"), list):
                        all_tasks.extend(col["tasks"])
            if all_tasks:
                summary["flattened_count"] = len(all_tasks)
                summary["sample"] = [
                    {
                        "id": t.get("id"),
                        "title": t.get("title"),
                        "status": t.get("status"),
                        "labels": t.get("labels"),
                    }
                    for t in all_tasks[:15]
                    if isinstance(t, dict)
                ]
                chainish = []
                for t in all_tasks[:80]:
                    if not isinstance(t, dict):
                        continue
                    labels = str(t.get("labels") or "")
                    title = str(t.get("title") or "")
                    if "auto-chain" in labels or "goal" in labels or "sales" in title.lower():
                        chainish.append(
                            {
                                "id": t.get("id"),
                                "title": t.get("title"),
                                "status": t.get("status"),
                                "labels": t.get("labels"),
                            }
                        )
                summary["chain_related"] = chainish
            else:
                summary["body_preview"] = json.dumps(body)[:600]
        else:
            summary["body"] = str(body)[:400]
        tasks_results[path] = summary
        print(
            "TASKS",
            path,
            c,
            summary.get("count")
            or summary.get("flattened_count")
            or summary.get("detail")
            or summary.get("keys"),
        )

    report["steps"]["tasks"] = tasks_results

    has_goal_chain_ok = isinstance(goal_chain, dict) and (
        goal_chain.get("ok")
        or goal_chain.get("parent_task_id")
        or goal_chain.get("deduped")
    )
    has_goal_chain_field = isinstance(chat, dict) and "goal_chain" in chat
    auto_text = report["auto_chain_text_present"]

    if code == 200 and (has_goal_chain_ok or auto_text):
        deploy_required = False
        status = "auto_chain_live"
    elif code == 200 and has_goal_chain_field and goal_chain is None:
        deploy_required = False
        status = "goal_chain_field_null"
    elif code == 200 and not has_goal_chain_field:
        deploy_required = True
        status = "auto_chain_not_on_prod_yet"
    elif code != 200:
        deploy_required = "unknown"
        status = f"chat_failed_{code}"
    else:
        deploy_required = True
        status = "auto_chain_not_detected"

    report["deploy_required"] = deploy_required
    report["summary"] = {
        "ok": code == 200,
        "status": status,
        "agent_id": agent_id,
        "chat_http": code,
        "has_goal_chain_field": has_goal_chain_field,
        "goal_chain_ok": has_goal_chain_ok,
        "auto_chain_text_present": auto_text,
        "deploy_required": deploy_required,
        "parent_task_id": (goal_chain or {}).get("parent_task_id")
        if isinstance(goal_chain, dict)
        else None,
        "steps_count": (goal_chain or {}).get("steps")
        if isinstance(goal_chain, dict)
        else None,
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("WROTE", REPORT_PATH)
    print("SUMMARY", json.dumps(report["summary"], indent=2))
    return 0 if code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
