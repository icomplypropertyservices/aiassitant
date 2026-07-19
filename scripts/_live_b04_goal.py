#!/usr/bin/env python3
"""Live B04: demo login + orchestrator chat multi-step weekly sales plan goal.

Message:
  Build a weekly sales plan: research ICP, write 3 outreach lines, set targets,
  report to human owner.

Writes scripts/live_b04_goal_report.json with parent_task_id + children count.
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

BASE = "https://www.aibusinessagent.xyz"
ROOT = Path(__file__).resolve().parent
LOGIN_PATH = ROOT / ".demo_login.json"
REPORT_PATH = ROOT / "live_b04_goal_report.json"
MSG = (
    "Build a weekly sales plan: research ICP, write 3 outreach lines, "
    "set targets, report to human owner."
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
    headers = {"Accept": "application/json", "User-Agent": "live-b04-goal/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-API-Key"] = token
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


class Session:
    """Single-active session key; concurrent demo logins invalidate — re-login on 401."""

    def __init__(self, email: str, password: str, api_key: str | None = None):
        self.email = email
        self.password = password
        self.key = api_key or ""
        self.user: dict = {}
        self.logins = 0

    def login(self) -> bool:
        for attempt in range(8):
            code, body = req(
                "POST",
                "/api/auth/login",
                body={"email": self.email, "password": self.password},
                timeout=60,
            )
            print("LOGIN", attempt, code, flush=True)
            if isinstance(body, dict):
                key = (
                    body.get("api_key")
                    or body.get("access_token")
                    or body.get("token")
                )
                if key and code == 200:
                    self.key = key
                    self.user = (
                        body.get("user")
                        if isinstance(body.get("user"), dict)
                        else body
                    )
                    self.logins += 1
                    return True
            if code == 429:
                time.sleep(22)
            else:
                time.sleep(3)
        return False

    def ensure(self) -> bool:
        if self.key:
            code, me = req("GET", "/api/auth/me", token=self.key, timeout=45)
            print("ME", code, me.get("id") if isinstance(me, dict) else me, flush=True)
            if code == 200 and isinstance(me, dict):
                self.user = me
                return True
        return self.login()

    def call(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        timeout: float = 180,
    ) -> tuple[int, Any]:
        if not self.key and not self.ensure():
            return 0, {"error": "no token"}
        code, data = req(method, path, token=self.key, body=body, timeout=timeout)
        if code == 401:
            print(f"401 on {method} {path} — re-login", flush=True)
            if not self.login():
                return 401, data
            code, data = req(method, path, token=self.key, body=body, timeout=timeout)
        return code, data


def main() -> int:
    login = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
    email = login["email"]
    password = login["password"]
    api_key = login.get("api_key")
    agent_id_hint = login.get("agent_id")

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_url": BASE,
        "email": email,
        "message": MSG,
        "steps": {},
    }

    sess = Session(email, password, api_key)
    if not sess.ensure():
        report["summary"] = {"ok": False, "error": "no token"}
        REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("NO TOKEN")
        return 1

    report["steps"]["login"] = {
        "status": "ok",
        "user_id": sess.user.get("id"),
        "plan": sess.user.get("plan"),
        "subscription_active": sess.user.get("subscription_active"),
        "logins": sess.logins,
    }
    # Persist key for screenshot step (best-effort; swarm may rotate)
    login["api_key"] = sess.key
    if sess.user.get("id") is not None:
        login["user_id"] = sess.user["id"]
    LOGIN_PATH.write_text(json.dumps(login, indent=2), encoding="utf-8")

    code, orch = sess.call(
        "POST", "/api/agents/ensure-orchestrator", body={}, timeout=120
    )
    print("ENSURE_ORCH", code, orch.get("id") if isinstance(orch, dict) else orch)
    agent_id = orch.get("id") if isinstance(orch, dict) else None
    if not agent_id:
        agent_id = agent_id_hint
    report["steps"]["ensure_orchestrator"] = {
        "status": code,
        "agent_id": agent_id,
        "name": orch.get("name") if isinstance(orch, dict) else None,
        "is_orchestrator": orch.get("is_orchestrator") if isinstance(orch, dict) else None,
        "hierarchy_role": orch.get("hierarchy_role") if isinstance(orch, dict) else None,
    }
    if agent_id:
        login["agent_id"] = agent_id
        login["api_key"] = sess.key
        LOGIN_PATH.write_text(json.dumps(login, indent=2), encoding="utf-8")

    if not agent_id:
        report["summary"] = {"ok": False, "error": "no agent"}
        REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("NO AGENT")
        return 1

    # Fresh login immediately before long chat so swarm workers less likely mid-flight
    sess.login()
    login["api_key"] = sess.key
    LOGIN_PATH.write_text(json.dumps(login, indent=2), encoding="utf-8")

    print("CHAT posting to agent", agent_id, "...")
    t0 = time.time()
    code, chat = sess.call(
        "POST",
        f"/api/agents/{agent_id}/chat",
        body={"message": MSG},
        timeout=300,
    )
    elapsed = round(time.time() - t0, 2)
    print("CHAT", code, "elapsed", elapsed)
    # Keep latest key after chat
    login["api_key"] = sess.key
    LOGIN_PATH.write_text(json.dumps(login, indent=2), encoding="utf-8")

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
            "reply_preview": (reply or "")[:900],
            "reply_len": len(reply or ""),
            "response_keys": sorted(list(chat.keys())),
            "detail": chat.get("detail") if code >= 400 else None,
        }
    else:
        report["steps"]["chat"] = {
            "status": code,
            "elapsed_sec": elapsed,
            "body": str(chat)[:1000],
        }

    auto_markers = [
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
    report["auto_chain_text_present"] = bool(auto_markers)
    report["auto_chain_markers_found"] = auto_markers
    report["goal_chain"] = goal_chain

    c, tasks = sess.call("GET", f"/api/agents/{agent_id}/tasks", timeout=60)
    print("TASKS agent", c, len(tasks) if isinstance(tasks, list) else tasks)
    login["api_key"] = sess.key
    LOGIN_PATH.write_text(json.dumps(login, indent=2), encoding="utf-8")
    chain_related = []
    if isinstance(tasks, list):
        for t in tasks:
            if not isinstance(t, dict):
                continue
            labels = str(t.get("labels") or "")
            title = str(t.get("title") or "")
            if (
                "auto-chain" in labels
                or "goal" in labels
                or "weekly sales" in title.lower()
                or "outreach" in title.lower()
                or "icp" in title.lower()
                or "sales plan" in title.lower()
            ):
                chain_related.append(
                    {
                        "id": t.get("id"),
                        "title": t.get("title"),
                        "status": t.get("status"),
                        "labels": t.get("labels"),
                        "parent_task_id": t.get("parent_task_id"),
                        "agent_id": t.get("agent_id"),
                    }
                )
    report["steps"]["tasks"] = {
        "status": c,
        "count": len(tasks) if isinstance(tasks, list) else None,
        "chain_related": chain_related[:50],
    }

    parent_task_id = None
    children_count = None
    children: list = []
    if isinstance(goal_chain, dict):
        parent_task_id = goal_chain.get("parent_task_id")
        children = goal_chain.get("children") or []
        if goal_chain.get("steps") is not None:
            children_count = goal_chain.get("steps")
        else:
            children_count = len(children) if isinstance(children, list) else None

    if parent_task_id and isinstance(tasks, list):
        linked = [
            t
            for t in tasks
            if isinstance(t, dict) and t.get("parent_task_id") == parent_task_id
        ]
        report["children_from_tasks_list"] = [
            {
                "id": t.get("id"),
                "title": t.get("title"),
                "status": t.get("status"),
                "labels": t.get("labels"),
                "agent_id": t.get("agent_id"),
            }
            for t in linked
        ]
        if not children and linked:
            children = linked
            children_count = len(linked)
        elif children_count is None:
            children_count = len(linked)

    has_goal_chain_ok = isinstance(goal_chain, dict) and (
        goal_chain.get("ok")
        or goal_chain.get("parent_task_id")
        or goal_chain.get("deduped")
    )
    report["summary"] = {
        "ok": code == 200 and (has_goal_chain_ok or bool(auto_markers)),
        "status": "auto_chain_live"
        if (has_goal_chain_ok or auto_markers)
        else "not_detected",
        "agent_id": agent_id,
        "chat_http": code,
        "has_goal_chain_field": isinstance(chat, dict) and "goal_chain" in chat,
        "goal_chain_ok": has_goal_chain_ok,
        "auto_chain_text_present": bool(auto_markers),
        "parent_task_id": parent_task_id,
        "children_count": children_count,
        "children": children if isinstance(children, list) else None,
        "goal_chain_message": goal_chain.get("message")
        if isinstance(goal_chain, dict)
        else None,
        "deduped": goal_chain.get("deduped") if isinstance(goal_chain, dict) else None,
    }

    REPORT_PATH.write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    print("WROTE", REPORT_PATH)
    print("SUMMARY", json.dumps(report["summary"], indent=2, default=str))
    return 0 if report["summary"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
