#!/usr/bin/env python3
"""
Full live smoke for meeting rooms API.

Checks:
  1. GET  /api/health
  2. GET  /api/auth/me                 (when token)
  3. GET  /api/meetings                — 200 (auth) or 401 (no/invalid token)
  4. Agents: ensure-orchestrator (+ designer), list
  5. POST /api/meetings                — create room with agent participants
  6. POST /api/meetings/{id}/messages  — post a message
  7. GET  /api/meetings/{id}/messages  — list messages
  8. POST /api/meetings/{id}/round     — agent round (soft-fail 503)
  9. POST /api/meetings/{id}/extract-tasks
 10. GET  /api/meetings                — list includes new room

Usage:
  # Unauthenticated (list should be 401; health still 200)
  python scripts/smoke_meetings.py

  # With bearer token from env
  set ABA_TOKEN=aba_...
  python scripts/smoke_meetings.py

  # Token as arg
  python scripts/smoke_meetings.py aba_...
  python scripts/smoke_meetings.py --token aba_...

  # Point at another host (no trailing /api)
  set ABA_BASE=http://127.0.0.1:8000
  python scripts/smoke_meetings.py --token aba_...

  # Or BASE_URL already including /api
  set BASE_URL=https://www.aibusinessagent.xyz/api
  python scripts/smoke_meetings.py

Exit code 1 if health fails or meetings list is neither 200 nor 401,
or (when token provided) if create / post-message / list-messages / extract fails.
Round is soft: 503 (runner unavailable) is reported but does not fail the smoke.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# www serves API POSTs reliably (apex may 308 redirect and break urllib POST)
DEFAULT_HOST = "https://www.aibusinessagent.xyz"
TIMEOUT = float(os.environ.get("ABA_TIMEOUT", "90"))
ROUND_TIMEOUT = float(os.environ.get("ABA_ROUND_TIMEOUT", "300"))


def _resolve_base() -> str:
    """Return API root including /api, no trailing slash.

    Accepts:
      ABA_BASE / ABA_API   host or host/api
      BASE_URL             often already ends with /api (see audit_smoke)
    """
    raw = (
        os.environ.get("ABA_BASE")
        or os.environ.get("ABA_API")
        or os.environ.get("BASE_URL")
        or DEFAULT_HOST
    ).strip().rstrip("/")
    if raw.endswith("/api"):
        return raw
    return f"{raw}/api"


def _request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> tuple[int, Any]:
    base = _resolve_base()
    path = path if path.startswith("/") else f"/{path}"
    url = f"{base}{path}"
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "smoke-meetings/1.1",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers, method=method.upper())
    t = TIMEOUT if timeout is None else timeout
    try:
        with urlopen(req, timeout=t) as resp:
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


def _snip(payload: Any, n: int = 240) -> str:
    if payload is None:
        return ""
    if isinstance(payload, (dict, list)):
        return json.dumps(payload, default=str)[:n]
    return str(payload)[:n]


def _extract_id(payload: Any) -> int | None:
    """Pull a meeting/room id from common response shapes."""
    if not isinstance(payload, dict):
        return None
    for key in ("id", "meeting_id", "room_id"):
        val = payload.get(key)
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
    meeting = payload.get("meeting") or payload.get("room")
    if isinstance(meeting, dict):
        return _extract_id(meeting)
    return None


def _agent_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [a for a in payload if isinstance(a, dict)]
    if isinstance(payload, dict):
        for k in ("agents", "items", "data", "results"):
            v = payload.get(k)
            if isinstance(v, list):
                return [a for a in v if isinstance(a, dict)]
    return []


def _msg_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        inner = payload.get("messages") or payload.get("items") or []
        if isinstance(inner, list):
            return inner
    return []


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smoke test meeting rooms API")
    p.add_argument(
        "token_pos",
        nargs="?",
        default=None,
        help="Bearer JWT / API key (optional; else ABA_TOKEN env)",
    )
    p.add_argument(
        "--token",
        dest="token_flag",
        default=None,
        help="Bearer token (overrides positional and env if set)",
    )
    p.add_argument(
        "--base",
        default=None,
        help="API host or host/api (overrides ABA_BASE / BASE_URL)",
    )
    p.add_argument(
        "--skip-round",
        action="store_true",
        help="Skip multi-agent discussion round (saves LLM time)",
    )
    p.add_argument(
        "--skip-extract",
        action="store_true",
        help="Skip extract-tasks step",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.base:
        os.environ["ABA_BASE"] = args.base.strip().rstrip("/")

    token = (
        (args.token_flag or "").strip()
        or (args.token_pos or "").strip()
        or (os.environ.get("ABA_TOKEN") or "").strip()
        or None
    )

    base = _resolve_base()
    print(f"smoke_meetings base={base} token={'yes' if token else 'no'}")
    print("-" * 60)

    failed = 0

    # ── 1. Health ──────────────────────────────────────────────────────────
    code, health = _request("GET", "/health")
    health_ok = code == 200 and isinstance(health, dict) and health.get("ok") is True
    features = []
    if isinstance(health, dict):
        features = health.get("features") or []
    print(
        f"{'PASS' if health_ok else 'FAIL':4}  GET /health  "
        f"status={code} features={features} {_snip(health)}"
    )
    if not health_ok:
        failed += 1

    # ── 2. Auth me (when token) ────────────────────────────────────────────
    if token:
        code, me = _request("GET", "/auth/me", token=token)
        me_ok = code == 200 and isinstance(me, dict) and me.get("id") is not None
        plan = me.get("plan") if isinstance(me, dict) else None
        print(
            f"{'PASS' if me_ok else 'FAIL':4}  GET /auth/me  "
            f"status={code} plan={plan} {_snip(me)}"
        )
        if not me_ok:
            failed += 1
        # If plan is none, try free trial so agents/round/extract can run
        if me_ok and plan in (None, "", "none"):
            code, plan_body = _request(
                "POST", "/billing/plan", token=token, body={"plan": "trial"}
            )
            plan_ok = code == 200 and isinstance(plan_body, dict)
            print(
                f"{'PASS' if plan_ok else 'FAIL':4}  POST /billing/plan trial  "
                f"status={code} {_snip(plan_body)}"
            )
            if not plan_ok:
                failed += 1

    # ── 3. List meetings (200 with auth, 401 without / bad token) ──────────
    code, meetings = _request("GET", "/meetings", token=token)
    list_ok = code in (200, 401)
    if token and code == 401:
        list_ok = False
        print(f"FAIL  GET /meetings  status={code} (token rejected) {_snip(meetings)}")
        failed += 1
    elif list_ok:
        print(f"PASS  GET /meetings  status={code} {_snip(meetings)}")
    else:
        print(f"FAIL  GET /meetings  status={code} (want 200 or 401) {_snip(meetings)}")
        failed += 1

    if not token:
        print("SKIP  create/message/round/extract flow (no ABA_TOKEN / --token)")
        print("-" * 60)
        print(f"Done: {'OK' if failed == 0 else f'{failed} FAIL'}")
        return 0 if failed == 0 else 1

    # ── 4. Agents ──────────────────────────────────────────────────────────
    code, orch = _request("POST", "/agents/ensure-orchestrator", token=token)
    orch_id = _extract_id(orch) if code in (200, 201) else None
    orch_ok = code in (200, 201) and orch_id is not None
    print(
        f"{'PASS' if orch_ok else 'FAIL':4}  POST /agents/ensure-orchestrator  "
        f"status={code} id={orch_id} {_snip(orch)}"
    )
    if not orch_ok:
        failed += 1

    code, designer = _request("POST", "/agents/ensure-designer", token=token)
    designer_id = _extract_id(designer) if code in (200, 201) else None
    # Designer is nice-to-have for multi-agent room
    print(
        f"{'PASS' if designer_id else 'WARN':4}  POST /agents/ensure-designer  "
        f"status={code} id={designer_id} {_snip(designer)}"
    )

    code, agents_payload = _request("GET", "/agents/", token=token)
    agents = _agent_list(agents_payload)
    agent_ids = [a["id"] for a in agents if a.get("id") is not None]
    if orch_id and orch_id not in agent_ids:
        agent_ids.insert(0, orch_id)
    if designer_id and designer_id not in agent_ids:
        agent_ids.append(designer_id)
    agents_ok = code == 200 and len(agent_ids) >= 1
    print(
        f"{'PASS' if agents_ok else 'FAIL':4}  GET /agents/  "
        f"status={code} count={len(agent_ids)} ids={agent_ids[:5]}"
    )
    if not agents_ok:
        failed += 1

    chair = agent_ids[0] if agent_ids else None
    participants = [
        {"kind": "agent", "agent_id": aid, "role": "member"}
        for aid in agent_ids[:3]
        if aid != chair
    ]
    if chair:
        # chair is added via chair_agent_id; others as members
        pass

    # ── 5. Create meeting with agents ──────────────────────────────────────
    create_body: dict[str, Any] = {
        "title": "Smoke meeting",
        "purpose": "scripts/smoke_meetings.py automated full check",
        "room_type": "brainstorm",
    }
    if chair is not None:
        create_body["chair_agent_id"] = chair
    if participants:
        create_body["participants"] = participants

    code, created = _request("POST", "/meetings", token=token, body=create_body)
    meeting_id = _extract_id(created) if code in (200, 201) else None
    parts = []
    if isinstance(created, dict):
        parts = created.get("participants") or []
    has_agent = any(
        isinstance(p, dict) and p.get("kind") == "agent" for p in parts
    )
    # Without agents we still accept create; with agents require agent participant
    create_ok = code in (200, 201) and meeting_id is not None
    if agent_ids and create_ok and not has_agent:
        create_ok = False
    print(
        f"{'PASS' if create_ok else 'FAIL':4}  POST /meetings  "
        f"status={code} id={meeting_id} agents_in_room={has_agent} {_snip(created)}"
    )
    if not create_ok:
        failed += 1
        print("-" * 60)
        print(f"Done: {failed} FAIL (stopped before message steps)")
        return 1

    # ── 6. Post message ────────────────────────────────────────────────────
    msg_body = {
        "content": (
            "Hello from smoke_meetings — action items: "
            "1) Draft Q3 launch outline. "
            "2) Review pricing page. "
            "3) Schedule customer interviews."
        ),
        "msg_type": "chat",
    }
    code, posted = _request(
        "POST",
        f"/meetings/{meeting_id}/messages",
        token=token,
        body=msg_body,
    )
    post_ok = code in (200, 201)
    print(
        f"{'PASS' if post_ok else 'FAIL':4}  POST /meetings/{meeting_id}/messages  "
        f"status={code} {_snip(posted)}"
    )
    if not post_ok:
        failed += 1

    # ── 7. List messages ───────────────────────────────────────────────────
    code, msgs = _request(
        "GET",
        f"/meetings/{meeting_id}/messages",
        token=token,
    )
    msg_list = _msg_list(msgs)
    list_msgs_ok = code == 200 and len(msg_list) >= 1
    print(
        f"{'PASS' if list_msgs_ok else 'FAIL':4}  GET /meetings/{meeting_id}/messages  "
        f"status={code} count={len(msg_list)} {_snip(msgs)}"
    )
    if not list_msgs_ok:
        failed += 1

    # ── 8. Round (soft on 503) ─────────────────────────────────────────────
    if args.skip_round:
        print("SKIP  POST /meetings/{id}/round (--skip-round)")
    else:
        code, rnd = _request(
            "POST",
            f"/meetings/{meeting_id}/round",
            token=token,
            body={
                "prompt": "Each agent: pick one action item and outline first steps.",
                "max_turns": 1,
            },
            timeout=ROUND_TIMEOUT,
        )
        # 200/201 success; 503 runner unavailable is soft; 402 credits is hard fail
        if code in (200, 201):
            print(
                f"PASS  POST /meetings/{meeting_id}/round  "
                f"status={code} count={(rnd or {}).get('count') if isinstance(rnd, dict) else '?'} "
                f"{_snip(rnd)}"
            )
        elif code == 503:
            print(
                f"WARN  POST /meetings/{meeting_id}/round  "
                f"status=503 (runner unavailable — soft) {_snip(rnd)}"
            )
        else:
            print(
                f"FAIL  POST /meetings/{meeting_id}/round  "
                f"status={code} {_snip(rnd)}"
            )
            failed += 1

    # ── 9. Extract tasks ───────────────────────────────────────────────────
    if args.skip_extract:
        print("SKIP  POST /meetings/{id}/extract-tasks (--skip-extract)")
    else:
        code, extracted = _request(
            "POST",
            f"/meetings/{meeting_id}/extract-tasks",
            token=token,
            body={"create": True, "assign_to_chair": True},
            timeout=ROUND_TIMEOUT,
        )
        tasks = []
        if isinstance(extracted, dict):
            tasks = extracted.get("tasks") or extracted.get("created_tasks") or []
            if not isinstance(tasks, list):
                tasks = []
        extract_ok = code in (200, 201) and isinstance(extracted, dict) and (
            extracted.get("ok") is True or len(tasks) >= 0
        )
        # Require success status; empty tasks still ok if heuristic found nothing
        if code not in (200, 201):
            extract_ok = False
        print(
            f"{'PASS' if extract_ok else 'FAIL':4}  POST /meetings/{meeting_id}/extract-tasks  "
            f"status={code} tasks={len(tasks)} {_snip(extracted)}"
        )
        if not extract_ok:
            failed += 1

    # ── 10. List meetings includes room ────────────────────────────────────
    code, meetings = _request("GET", "/meetings", token=token)
    meet_list: list[Any] = []
    if isinstance(meetings, list):
        meet_list = meetings
    elif isinstance(meetings, dict):
        meet_list = meetings.get("meetings") or meetings.get("rooms") or meetings.get("items") or []
        if not isinstance(meet_list, list):
            meet_list = []
    has_mid = any(
        isinstance(m, dict) and m.get("id") == meeting_id for m in meet_list
    )
    list_final_ok = code == 200 and has_mid
    print(
        f"{'PASS' if list_final_ok else 'FAIL':4}  GET /meetings (has id={meeting_id})  "
        f"status={code} count={len(meet_list)} has_mid={has_mid}"
    )
    if not list_final_ok:
        failed += 1

    print("-" * 60)
    print(
        f"Done: {'OK' if failed == 0 else f'{failed} FAIL'}  meeting_id={meeting_id}"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
