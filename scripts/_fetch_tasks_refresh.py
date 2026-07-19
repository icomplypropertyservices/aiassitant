#!/usr/bin/env python3
"""Refresh tasks section of live_chat_chain_report.json after re-login."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://www.aibusinessagent.xyz"
ROOT = Path(__file__).resolve().parent
LOGIN_PATH = ROOT / ".demo_login.json"
REPORT_PATH = ROOT / "live_chat_chain_report.json"


def req(
    method: str,
    path: str,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 30,
):
    url = f"{BASE}{path}"
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


def is_chain(t: dict) -> bool:
    labels = str(t.get("labels") or "")
    title = str(t.get("title") or "")
    tid = t.get("id")
    return (
        "auto-chain" in labels
        or "goal" in labels
        or "sales" in title.lower()
        or (isinstance(tid, int) and 76 <= tid <= 82)
        or t.get("parent_task_id") == 76
    )


def row(t: dict) -> dict:
    return {
        "id": t.get("id"),
        "title": t.get("title"),
        "status": t.get("status"),
        "labels": t.get("labels"),
        "parent_task_id": t.get("parent_task_id"),
        "agent_id": t.get("agent_id"),
    }


def summarize(body: Any, status: int) -> dict:
    out: dict[str, Any] = {"status": status}
    if isinstance(body, list):
        out["type"] = "list"
        out["count"] = len(body)
        out["chain_related"] = [row(t) for t in body if isinstance(t, dict) and is_chain(t)]
        out["sample"] = [row(t) for t in body[:20] if isinstance(t, dict)]
        return out
    if isinstance(body, dict):
        out["type"] = "dict"
        out["keys"] = sorted(body.keys())[:30]
        if body.get("detail"):
            out["detail"] = body.get("detail")
        # single task
        if body.get("id") is not None and body.get("title") is not None:
            out["task"] = row(body)
            return out
        all_tasks: list = []
        if isinstance(body.get("tasks"), list):
            all_tasks = body["tasks"]
        elif isinstance(body.get("items"), list):
            all_tasks = body["items"]
        elif isinstance(body.get("columns"), list):
            for col in body["columns"]:
                if isinstance(col, dict) and isinstance(col.get("tasks"), list):
                    all_tasks.extend(col["tasks"])
        out["flattened_count"] = len(all_tasks)
        out["chain_related"] = [row(t) for t in all_tasks if isinstance(t, dict) and is_chain(t)]
        out["sample"] = [row(t) for t in all_tasks[:20] if isinstance(t, dict)]
        if not all_tasks and not out.get("detail"):
            out["body_preview"] = json.dumps(body)[:500]
        return out
    out["body"] = str(body)[:400]
    return out


def main() -> int:
    login = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
    code, body = req(
        "POST",
        "/api/auth/login",
        body={"email": login["email"], "password": login["password"]},
        timeout=45,
    )
    print("LOGIN", code, flush=True)
    if not isinstance(body, dict):
        print("login fail", body, flush=True)
        return 1
    token = body.get("api_key") or body.get("access_token") or body.get("token")
    print("token_len", len(token or ""), flush=True)

    # Prefer stored api_key if login token fails on tasks
    tokens_to_try = []
    if token:
        tokens_to_try.append(("login", token))
    stored = login.get("api_key")
    if stored and stored != token:
        tokens_to_try.append(("stored_demo_login", stored))

    tasks_results: dict[str, Any] = {}
    paths = [
        "/api/agents/9/tasks",
        "/api/agents/tasks/76",
        "/api/agents/tasks/77",
        "/api/org/tasks",
    ]

    working_token = None
    working_label = None
    for label, tok in tokens_to_try:
        c, b = req("GET", "/api/agents/9/tasks", token=tok, timeout=45)
        print(f"PROBE token={label} /api/agents/9/tasks -> {c}", flush=True)
        if c == 200:
            working_token = tok
            working_label = label
            tasks_results["/api/agents/9/tasks"] = summarize(b, c)
            break
        tasks_results[f"/api/agents/9/tasks ({label})"] = summarize(b, c)

    if working_token is None and tokens_to_try:
        working_token = tokens_to_try[0][1]
        working_label = tokens_to_try[0][0]

    for path in paths:
        if path in tasks_results:
            continue
        c, b = req("GET", path, token=working_token, timeout=45)
        print(f"GET {path} -> {c}", flush=True)
        tasks_results[path] = summarize(b, c)
        s = tasks_results[path]
        if s.get("chain_related"):
            print(f"  chain_related={len(s['chain_related'])}", flush=True)
            for r in s["chain_related"][:12]:
                print("   ", r, flush=True)
        elif s.get("task"):
            print("  task", s["task"], flush=True)
        elif s.get("detail"):
            print("  detail", s["detail"], flush=True)

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    report["steps"]["tasks"] = tasks_results
    report["steps"]["tasks_refresh"] = {
        "token_source": working_label,
        "note": "Re-fetched after probe; first pass saw 401 on tasks endpoints",
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("UPDATED", REPORT_PATH, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
