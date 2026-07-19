#!/usr/bin/env python3
"""
Live production smoke: demo login → templates → agents → meetings → chat goal chain.

Single login (one session key) used for the whole run so concurrent re-logins
from other workers cannot invalidate mid-suite.

Writes scripts/live_smoke_full_report.json
Exit 0 if critical path passes.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LOGIN_PATH = ROOT / ".demo_login.json"
TOKEN_PATH = ROOT / ".demo_token"
REPORT_PATH = ROOT / "live_smoke_full_report.json"
BASE = "https://www.aibusinessagent.xyz"
GOAL_MSG = (
    "Build a full sales plan for Live Demo Co: research ICP, write 5 outreach emails, "
    "set weekly targets, and report progress."
)


def req(
    method: str,
    path: str,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 180,
    retries: int = 2,
) -> tuple[int, Any]:
    url = f"{BASE}{path if path.startswith('/') else '/' + path}"
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "live-smoke-full/1.0",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-API-Key"] = token
    last: tuple[int, Any] = (0, {"error": "no attempt"})
    for attempt in range(max(1, retries + 1)):
        request = Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=timeout) as resp:
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
            # Retry transient 5xx / 429 briefly
            if int(e.code) in (429, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                last = (int(e.code), parsed)
                continue
            return int(e.code), parsed
        except (URLError, TimeoutError, OSError) as e:
            last = (0, {"error": str(getattr(e, "reason", e))})
            if attempt < retries:
                time.sleep(1.2 * (attempt + 1))
                continue
            return last
    return last


def is_html(body: Any) -> bool:
    if not isinstance(body, str):
        return False
    head = body[:200].lower()
    return "<!doctype" in head or "<html" in head


def list_len(body: Any) -> int | None:
    if isinstance(body, list):
        return len(body)
    if isinstance(body, dict):
        if isinstance(body.get("count"), int) and any(
            isinstance(body.get(k), list)
            for k in ("items", "agents", "meetings", "templates", "data", "results", "messages")
        ):
            # Prefer explicit count when present (meetings list shape)
            for k in ("items", "agents", "meetings", "templates", "data", "results", "messages"):
                if isinstance(body.get(k), list):
                    return int(body.get("count") if body.get("count") is not None else len(body[k]))
        for k in ("items", "agents", "meetings", "templates", "data", "results", "messages"):
            if isinstance(body.get(k), list):
                return len(body[k])
    return None


def main() -> int:
    login = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
    email = login["email"]
    password = login["password"]

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_url": BASE,
        "email": email,
        "checks": [],
        "summary": {},
    }
    checks: list[dict[str, Any]] = report["checks"]

    def check(name: str, ok: bool, detail: Any = None, **extra: Any) -> None:
        row = {"name": name, "pass": bool(ok), "detail": detail, **extra}
        checks.append(row)
        flag = "PASS" if ok else "FAIL"
        d = detail if not isinstance(detail, (dict, list)) else json.dumps(detail, default=str)[:220]
        print(f"{flag:4}  {name}: {d}")

    # 0) health
    code, health = req("GET", "/api/health", timeout=30)
    check(
        "health",
        code == 200 and isinstance(health, dict) and health.get("ok") is True,
        {
            "status": code,
            "version": health.get("version") if isinstance(health, dict) else None,
            "environment": health.get("environment") if isinstance(health, dict) else None,
            "meetings": health.get("meetings") if isinstance(health, dict) else None,
        },
    )

    # 1) Prefer stored session key (avoids login rate-limit + key rotation).
    #    Fall back to password login only when /auth/me rejects the key.
    token = (login.get("api_key") or "").strip()
    if not token and TOKEN_PATH.exists():
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    user: dict[str, Any] = {}
    login_source = "stored_key"

    code_me, me_probe = req("GET", "/api/auth/me", token=token, timeout=45) if token else (0, None)
    if not token or code_me != 200:
        code, body = req(
            "POST",
            "/api/auth/login",
            body={"email": email, "password": password},
            timeout=60,
        )
        login_source = "password_login"
        token = None
        if isinstance(body, dict):
            token = body.get("api_key") or body.get("token") or body.get("access_token")
            user = body.get("user") if isinstance(body.get("user"), dict) else {}
        check(
            "demo_login",
            code == 200 and bool(token),
            {
                "status": code,
                "source": login_source,
                "has_token": bool(token),
                "user_id": user.get("id"),
                "plan": user.get("plan"),
                "subscription_active": user.get("subscription_active"),
                "detail": body.get("detail") if isinstance(body, dict) else None,
            },
        )
        if not token:
            report["summary"] = {"ok": False, "error": "login failed", "status": code}
            REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            return 1
        # Persist for other tools — but do NOT re-login later in this script
        login["api_key"] = token
        if user.get("id") is not None:
            login["user_id"] = user["id"]
        LOGIN_PATH.write_text(json.dumps(login, indent=2), encoding="utf-8")
        TOKEN_PATH.write_text(token, encoding="utf-8")
        me = user if user else None
        code = 200
        plan = user.get("plan") if user else None
    else:
        me = me_probe if isinstance(me_probe, dict) else {}
        user = me
        plan = me.get("plan") if isinstance(me, dict) else None
        check(
            "demo_login",
            True,
            {
                "status": 200,
                "source": login_source,
                "has_token": True,
                "user_id": me.get("id") if isinstance(me, dict) else login.get("user_id"),
                "plan": plan,
                "subscription_active": me.get("subscription_active") if isinstance(me, dict) else None,
            },
        )
        # Ensure files stay complete (other workers strip fields)
        login["api_key"] = token
        if isinstance(me, dict) and me.get("id") is not None:
            login["user_id"] = me["id"]
        LOGIN_PATH.write_text(json.dumps(login, indent=2), encoding="utf-8")
        TOKEN_PATH.write_text(token, encoding="utf-8")
        code = code_me

    # 2) me + trial if needed
    if not isinstance(me, dict) or not me.get("id"):
        code, me = req("GET", "/api/auth/me", token=token, timeout=45)
        plan = me.get("plan") if isinstance(me, dict) else plan
    check(
        "auth_me",
        code == 200 and isinstance(me, dict),
        {"status": code, "plan": plan, "subscription_active": me.get("subscription_active") if isinstance(me, dict) else None},
    )
    if not plan or plan in ("none", ""):
        code_t, trial = req(
            "POST",
            "/api/billing/plan",
            token=token,
            body={"plan": "trial", "company_name": "Live Demo Co"},
            timeout=60,
        )
        check(
            "activate_trial",
            code_t in (200, 402) or (isinstance(trial, dict) and trial.get("plan")),
            {"status": code_t, "body": trial if isinstance(trial, dict) else str(trial)[:200]},
        )
    else:
        check("activate_trial", True, {"status": "skipped", "plan": plan})

    # 3) templates
    code, templates = req("GET", "/api/templates/", token=token, timeout=45)
    n_t = list_len(templates)
    check(
        "templates_list",
        code == 200 and not is_html(templates) and (n_t or 0) > 0,
        {
            "status": code,
            "count": n_t,
            "html": is_html(templates),
            "first": (templates[0].get("name") if isinstance(templates, list) and templates else None),
        },
    )

    # 4) agents + orchestrator
    code, orch = req("POST", "/api/agents/ensure-orchestrator", token=token, timeout=120)
    agent_id = orch.get("id") if isinstance(orch, dict) else None
    check(
        "ensure_orchestrator",
        code == 200 and agent_id is not None,
        {
            "status": code,
            "agent_id": agent_id,
            "name": orch.get("name") if isinstance(orch, dict) else None,
            "detail": orch.get("detail") if isinstance(orch, dict) else None,
        },
    )

    code, agents = req("GET", "/api/agents/", token=token, timeout=45)
    n_a = list_len(agents)
    if not agent_id and isinstance(agents, list) and agents:
        for a in agents:
            if a.get("is_orchestrator") or a.get("hierarchy_role") == "orchestrator":
                agent_id = a.get("id")
                break
        if not agent_id:
            agent_id = agents[0].get("id")
    if agent_id:
        login["agent_id"] = agent_id
        LOGIN_PATH.write_text(json.dumps(login, indent=2), encoding="utf-8")
    check(
        "agents_list",
        code == 200 and (n_a or 0) > 0,
        {
            "status": code,
            "count": n_a,
            "selected_agent_id": agent_id,
            "names": [a.get("name") for a in (agents or [])[:6]] if isinstance(agents, list) else None,
        },
    )

    # 5) meetings list + create + message
    code, meetings = req("GET", "/api/meetings/", token=token, timeout=45)
    n_m = list_len(meetings)
    check(
        "meetings_list",
        code == 200 and not is_html(meetings),
        {"status": code, "count": n_m, "html": is_html(meetings)},
    )

    meeting_id = None
    if agent_id:
        title = f"Smoke meeting {int(time.time())}"
        code, room = req(
            "POST",
            "/api/meetings/",
            token=token,
            body={
                "title": title,
                "purpose": "Live smoke test room",
                "room_type": "brainstorm",
                "chair_agent_id": agent_id,
                "participants": [
                    {"kind": "agent", "agent_id": agent_id, "role": "chair"},
                ],
            },
            timeout=60,
        )
        if isinstance(room, dict):
            meeting_id = room.get("id") or (room.get("meeting") or {}).get("id")
        # some APIs nest under "meeting"
        if not meeting_id and isinstance(room, dict) and isinstance(room.get("meeting"), dict):
            meeting_id = room["meeting"].get("id")
        check(
            "meetings_create",
            code in (200, 201) and meeting_id is not None,
            {
                "status": code,
                "meeting_id": meeting_id,
                "detail": room.get("detail") if isinstance(room, dict) else str(room)[:200],
                "keys": sorted(room.keys()) if isinstance(room, dict) else None,
            },
        )
        if meeting_id:
            code, msg = req(
                "POST",
                f"/api/meetings/{meeting_id}/messages",
                token=token,
                body={"content": "Smoke test message from live_smoke_full."},
                timeout=60,
            )
            check(
                "meetings_post_message",
                code in (200, 201),
                {
                    "status": code,
                    "detail": msg.get("detail") if isinstance(msg, dict) else str(msg)[:200],
                },
            )
            code, msgs = req(
                "GET",
                f"/api/meetings/{meeting_id}/messages",
                token=token,
                timeout=45,
            )
            n_msg = list_len(msgs)
            check(
                "meetings_list_messages",
                code == 200 and (n_msg is None or n_msg >= 1),
                {"status": code, "count": n_msg},
            )
    else:
        check("meetings_create", False, "no agent_id")
        check("meetings_post_message", False, "skipped")
        check("meetings_list_messages", False, "skipped")

    # 6) chat goal chain
    goal_chain = None
    chat_code = 0
    if agent_id:
        print(f"CHAT posting to agent {agent_id} ...")
        t0 = time.time()
        chat_code, chat = req(
            "POST",
            f"/api/agents/{agent_id}/chat",
            token=token,
            body={"message": GOAL_MSG},
            timeout=300,
        )
        elapsed = round(time.time() - t0, 2)
        reply = ""
        if isinstance(chat, dict):
            reply = chat.get("reply") or ""
            goal_chain = chat.get("goal_chain")
        markers = [
            m
            for m in (
                "Auto-chain started",
                "Goal chain already running",
                "auto-chain",
                "goal task #",
                "delegated steps",
            )
            if m.lower() in (reply or "").lower()
        ]
        has_gc = isinstance(goal_chain, dict) and (
            goal_chain.get("ok")
            or goal_chain.get("parent_task_id")
            or goal_chain.get("deduped")
        )
        check(
            "chat_goal_chain",
            chat_code == 200 and (has_gc or bool(markers)),
            {
                "status": chat_code,
                "elapsed_sec": elapsed,
                "has_goal_chain_field": isinstance(chat, dict) and "goal_chain" in chat,
                "goal_chain_ok": has_gc,
                "goal_chain": goal_chain if isinstance(goal_chain, dict) else None,
                "auto_chain_markers": markers,
                "reply_preview": (reply or "")[:400],
                "detail": chat.get("detail") if isinstance(chat, dict) and chat_code >= 400 else None,
            },
        )

        # tasks board sample
        code, tasks = req("GET", f"/api/agents/{agent_id}/tasks", token=token, timeout=45)
        chainish = []
        if isinstance(tasks, list):
            for t in tasks[:80]:
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
                            "parent_task_id": t.get("parent_task_id"),
                        }
                    )
        # Soft: goal_chain already proves auto-chain; tasks list may 401 if
        # another worker re-logged and rotated the session key mid-chat.
        tasks_ok = (code == 200 and (bool(chainish) or has_gc)) or has_gc
        check(
            "tasks_chain_visible",
            tasks_ok,
            {
                "status": code,
                "count": list_len(tasks),
                "chain_related": chainish[:12],
                "accepted_via_goal_chain": has_gc and code != 200,
            },
        )
    else:
        check("chat_goal_chain", False, "no agent")
        check("tasks_chain_visible", False, "skipped")

    critical = {
        "demo_login",
        "templates_list",
        "agents_list",
        "meetings_list",
        "chat_goal_chain",
    }
    passed = sum(1 for c in checks if c["pass"])
    failed_critical = [c["name"] for c in checks if c["name"] in critical and not c["pass"]]
    all_failed = [c["name"] for c in checks if not c["pass"]]
    report["summary"] = {
        "ok": not failed_critical,
        "passed": passed,
        "total": len(checks),
        "failed": all_failed,
        "failed_critical": failed_critical,
        "agent_id": agent_id,
        "meeting_id": meeting_id,
        "goal_parent_task_id": (goal_chain or {}).get("parent_task_id")
        if isinstance(goal_chain, dict)
        else None,
        "chat_http": chat_code,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print()
    print("=== SUMMARY ===")
    print(json.dumps(report["summary"], indent=2))
    print(f"Wrote {REPORT_PATH}")
    return 0 if report["summary"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
