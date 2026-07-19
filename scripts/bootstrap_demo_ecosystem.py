#!/usr/bin/env python3
"""
Bootstrap a full demo ecosystem via the live API:

  1. Login / register (or reuse ABA_TOKEN)
  2. Ensure Main AI Orchestrator (+ 3-company bootstrap by default)
  3. Seed starter team when plan slots allow
  4. Create a few queued tasks on live agents
  5. Open a meeting with agent participants
  6. Post a kickoff message with explicit action items
  7. Extract tasks from the meeting (status=queued when agent-assigned)

Usage:
  # Fresh throwaway account on production
  python scripts/bootstrap_demo_ecosystem.py

  # Existing credentials
  set ABA_EMAIL=you@example.com
  set ABA_PASSWORD=YourPass1
  python scripts/bootstrap_demo_ecosystem.py

  # Already have a session key
  set ABA_TOKEN=aba_...
  python scripts/bootstrap_demo_ecosystem.py

  # Local / custom host
  set ABA_BASE=http://127.0.0.1:8000
  python scripts/bootstrap_demo_ecosystem.py --base http://127.0.0.1:8000

  # Skip LLM-burning auto-run on direct tasks (still status=queued via PATCH)
  python scripts/bootstrap_demo_ecosystem.py --no-run

Env:
  ABA_BASE / ABA_API / BASE_URL   API host (with or without /api)
  ABA_TOKEN                       Bearer session key (skip login)
  ABA_EMAIL / ABA_PASSWORD        Login credentials
  DEMO_PASSWORD / TEST_PASSWORD   Password for new register path
  ABA_TIMEOUT                     HTTP timeout seconds (default 90)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_HOST = "https://www.aibusinessagent.xyz"
DEFAULT_PASSWORD = "DemoAgent1"
TIMEOUT = float(os.environ.get("ABA_TIMEOUT", "90"))

# Explicit action-style lines so extract-tasks heuristic works without LLM.
KICKOFF_MESSAGE = """Demo kickoff — ecosystem bootstrap.

Purpose: get the starter team moving on the three guided companies.

Action items:
TODO: Draft Q3 outreach sequence for Fire Alarms Dublin service renewals
- Review open service certificates due this month
ACTION: Prepare Shopify catalogue SEO keyword batch for iComply Products
- Build ICP notes for iComply Property Services compliance pipeline
Please schedule a follow-up standup by end of week
Need to qualify new install leads for fire detection systems

Agents: claim one action, update status, and escalate blockers to the Main Orchestrator.
"""

QUEUED_TASK_SPECS = [
    {
        "title": "Triage service enquiries (demo)",
        "description": (
            "Demo queued task: triage open Fire Alarms Dublin service enquiries "
            "and list top 5 follow-ups."
        ),
        "priority": "high",
    },
    {
        "title": "Draft landlord renewal notices (demo)",
        "description": (
            "Demo queued task: draft landlord renewal notice templates for "
            "iComply Property Services compliance ops."
        ),
        "priority": "medium",
    },
    {
        "title": "Catalogue SEO keyword batch (demo)",
        "description": (
            "Demo queued task: plan next keyword batch for iComply Products "
            "manufacturer landings (Apollo, Hochiki, Advanced)."
        ),
        "priority": "medium",
    },
]


# ── HTTP helpers ──────────────────────────────────────────────────────────


def _resolve_base(override: str | None = None) -> str:
    """Return API root including /api, no trailing slash."""
    raw = (
        (override or "").strip()
        or os.environ.get("ABA_BASE")
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
    base: str | None = None,
) -> tuple[int, Any]:
    api_base = base or _resolve_base()
    path = path if path.startswith("/") else f"/{path}"
    url = f"{api_base}{path}"
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "bootstrap-demo-ecosystem/1.0",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
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
    except URLError as e:
        return 0, {"error": str(getattr(e, "reason", e))}


def _snip(payload: Any, n: int = 280) -> str:
    if payload is None:
        return ""
    if isinstance(payload, (dict, list)):
        return json.dumps(payload, default=str)[:n]
    return str(payload)[:n]


def _extract_token(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("api_key", "token", "access_token"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _extract_user_id(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return None
    user = payload.get("user")
    if isinstance(user, dict) and user.get("id") is not None:
        return user.get("id")
    return payload.get("user_id") or payload.get("id")


def _extract_id(payload: Any, *keys: str) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in keys or ("id",):
        val = payload.get(key)
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
    for nest in ("meeting", "room", "task", "agent"):
        inner = payload.get(nest)
        if isinstance(inner, dict):
            found = _extract_id(inner, "id")
            if found is not None:
                return found
    return None


def _as_list(payload: Any, *keys: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            val = payload.get(key)
            if isinstance(val, list):
                return val
    return []


def _ok(code: int) -> bool:
    return 200 <= code < 300


def _log(step: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL':4}  {step}  {detail}")


# ── Auth ──────────────────────────────────────────────────────────────────


def register_or_login(
    email: str,
    password: str,
    *,
    base: str,
) -> tuple[str, Any, str]:
    """Return (token, user_id, mode) where mode is register|login."""
    code, body = _request(
        "POST",
        "/auth/register",
        base=base,
        body={
            "email": email,
            "password": password,
            "name": "Demo Ecosystem",
            "company_name": "Demo Co",
        },
    )
    if _ok(code):
        token = _extract_token(body)
        if token:
            return token, _extract_user_id(body), "register"
        raise SystemExit(f"register ok but no token: {_snip(body)}")

    detail = ""
    if isinstance(body, dict):
        detail = str(body.get("detail") or body)
    already = code in (400, 409) and (
        "already" in detail.lower() or "exists" in detail.lower()
    )
    if not already and code not in (400, 409):
        raise SystemExit(f"register failed http={code}: {_snip(body)}")

    code, body = _request(
        "POST",
        "/auth/login",
        base=base,
        body={"email": email, "password": password},
    )
    if code != 200:
        raise SystemExit(f"login failed http={code}: {_snip(body)}")
    token = _extract_token(body)
    if not token:
        raise SystemExit(f"login ok but no token: {_snip(body)}")
    return token, _extract_user_id(body), "login"


def maybe_activate_trial(token: str, base: str) -> None:
    """Best-effort trial activation so seed-starter-team has a plan."""
    code, body = _request(
        "POST",
        "/billing/plan",
        token=token,
        base=base,
        body={"plan": "trial", "company_name": "Demo Co"},
    )
    already = isinstance(body, dict) and body.get("already_active")
    ok = _ok(code) or code == 402  # 402 = trial used / paid plan required
    _log(
        "billing/trial",
        ok,
        f"status={code} already_active={bool(already)} {_snip(body)}",
    )


# ── Steps ─────────────────────────────────────────────────────────────────


def ensure_orchestrator(token: str, base: str) -> dict[str, Any] | None:
    code, body = _request(
        "POST",
        "/agents/ensure-orchestrator?bootstrap=true",
        token=token,
        base=base,
    )
    ok = _ok(code) and isinstance(body, dict)
    aid = _extract_id(body) if isinstance(body, dict) else None
    _log(
        "ensure-orchestrator",
        ok,
        f"status={code} id={aid} name={(body or {}).get('name')!r} {_snip(body)}",
    )
    if isinstance(body, dict) and body.get("bootstrap_error"):
        print(f"      bootstrap_error={body.get('bootstrap_error')}")
    return body if ok else None


def seed_starter_team(token: str, base: str) -> dict[str, Any] | None:
    code, body = _request(
        "POST",
        "/agents/seed-starter-team",
        token=token,
        base=base,
    )
    # 400 = not enough slots / already full; 402 = no plan — non-fatal for demo
    soft_fail = code in (400, 402)
    ok = _ok(code) or soft_fail
    count = body.get("count") if isinstance(body, dict) else None
    _log(
        "seed-starter-team",
        ok,
        f"status={code} count={count} {_snip(body)}",
    )
    if soft_fail:
        print("      (soft) seed skipped or partial — continuing with existing agents")
    return body if _ok(code) and isinstance(body, dict) else None


def list_agents(token: str, base: str) -> list[dict[str, Any]]:
    code, body = _request("GET", "/agents/", token=token, base=base)
    agents = [a for a in _as_list(body, "agents", "items", "data") if isinstance(a, dict)]
    ok = _ok(code) and len(agents) >= 1
    _log("list-agents", ok, f"status={code} count={len(agents)}")
    return agents


def _prefer_agent_ids(agents: list[dict[str, Any]], n: int = 5) -> list[int]:
    """Pick orchestrator first, then leads, then others."""
    scored: list[tuple[int, int]] = []
    for a in agents:
        aid = a.get("id")
        if not isinstance(aid, int):
            continue
        name = (a.get("name") or "").lower()
        role = (a.get("hierarchy_role") or a.get("role") or "").lower()
        score = 0
        if "orchestrator" in name or role == "orchestrator":
            score = 100
        elif a.get("is_lead") or role == "lead" or "lead" in name:
            score = 50
        elif (a.get("status") or "").lower() == "active":
            score = 20
        else:
            score = 10
        scored.append((score, aid))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out: list[int] = []
    for _, aid in scored:
        if aid not in out:
            out.append(aid)
        if len(out) >= n:
            break
    return out


def create_queued_tasks(
    token: str,
    base: str,
    agents: list[dict[str, Any]],
    *,
    run_now: bool,
    specs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Create a few queued tasks after seed-starter-team."""
    task_specs = list(specs if specs is not None else QUEUED_TASK_SPECS)
    if not task_specs:
        _log("queued-tasks", True, "count=0 (none requested)")
        return []

    agent_ids = _prefer_agent_ids(agents, n=max(3, len(task_specs)))
    if not agent_ids:
        _log("queued-tasks", False, "no agents available")
        return []

    created: list[dict[str, Any]] = []
    for i, spec in enumerate(task_specs):
        agent_id = agent_ids[i % len(agent_ids)]
        body = {
            "title": spec["title"],
            "description": spec["description"],
            "priority": spec.get("priority") or "medium",
            "labels": "demo,bootstrap,queued",
            "run_now": bool(run_now),
        }
        code, resp = _request(
            "POST",
            f"/agents/{agent_id}/tasks",
            token=token,
            base=base,
            body=body,
        )
        task_id = _extract_id(resp) if isinstance(resp, dict) else None
        status = resp.get("status") if isinstance(resp, dict) else None

        # When --no-run, API stores todo; promote to queued without scheduling.
        if _ok(code) and not run_now and task_id is not None and status != "queued":
            pcode, patched = _request(
                "PATCH",
                f"/agents/tasks/{task_id}",
                token=token,
                base=base,
                body={"status": "queued"},
            )
            if _ok(pcode) and isinstance(patched, dict):
                resp = patched
                status = patched.get("status")
                code = pcode

        ok = _ok(code) and task_id is not None
        _log(
            f"queued-task[{i + 1}]",
            ok,
            f"status={code} task_id={task_id} agent_id={agent_id} "
            f"task_status={status} {_snip(resp)}",
        )
        if ok and isinstance(resp, dict):
            created.append(resp)
    return created


def create_meeting_with_agents(
    token: str,
    base: str,
    agents: list[dict[str, Any]],
) -> dict[str, Any] | None:
    agent_ids = _prefer_agent_ids(agents, n=5)
    chair_id = agent_ids[0] if agent_ids else None
    participants = [
        {"kind": "agent", "agent_id": aid, "role": "member"}
        for aid in agent_ids
        if aid != chair_id
    ]
    # Chair is also an agent participant when present
    if chair_id is not None:
        participants.insert(0, {"kind": "agent", "agent_id": chair_id, "role": "chair"})

    body = {
        "title": "Demo ecosystem kickoff",
        "purpose": (
            "Automated bootstrap: seed team, queue starter work, align agents "
            "across Fire Alarms Dublin / iComply companies."
        ),
        "room_type": "brainstorm",
        "chair_agent_id": chair_id,
        "participants": participants,
        "settings": {"source": "bootstrap_demo_ecosystem", "demo": True},
    }
    code, resp = _request("POST", "/meetings", token=token, base=base, body=body)
    meeting_id = _extract_id(resp, "id", "meeting_id", "room_id")
    ok = _ok(code) and meeting_id is not None
    _log(
        "create-meeting",
        ok,
        f"status={code} id={meeting_id} agents={agent_ids} {_snip(resp)}",
    )
    if not ok:
        return None
    if isinstance(resp, dict):
        resp.setdefault("id", meeting_id)
        return resp
    return {"id": meeting_id}


def post_kickoff(token: str, base: str, meeting_id: int) -> bool:
    code, resp = _request(
        "POST",
        f"/meetings/{meeting_id}/messages",
        token=token,
        base=base,
        body={
            "content": KICKOFF_MESSAGE,
            "msg_type": "chat",
            "meta": {"event": "demo_kickoff", "source": "bootstrap_demo_ecosystem"},
        },
    )
    ok = _ok(code)
    _log("post-kickoff", ok, f"status={code} {_snip(resp)}")
    return ok


def extract_tasks(token: str, base: str, meeting_id: int) -> list[dict[str, Any]]:
    code, resp = _request(
        "POST",
        f"/meetings/{meeting_id}/extract-tasks",
        token=token,
        base=base,
        body={"model": "fast", "create": True, "assign_to_chair": True},
    )
    tasks = _as_list(resp, "tasks", "created") if isinstance(resp, dict) else []
    tasks = [t for t in tasks if isinstance(t, dict)]
    count = resp.get("count") if isinstance(resp, dict) else len(tasks)
    source = resp.get("source") if isinstance(resp, dict) else None
    ok = _ok(code) and (count or 0) >= 1
    _log(
        "extract-tasks",
        ok,
        f"status={code} count={count} source={source} {_snip(resp)}",
    )
    return tasks


# ── Main ──────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bootstrap demo ecosystem: auth → orchestrator → seed → "
        "queued tasks → meeting → kickoff → extract",
    )
    p.add_argument(
        "--base",
        default=None,
        help="API host or host/api (overrides ABA_BASE / BASE_URL)",
    )
    p.add_argument(
        "--token",
        default=None,
        help="Bearer session key (overrides ABA_TOKEN)",
    )
    p.add_argument(
        "--email",
        default=None,
        help="Login/register email (default: ABA_EMAIL or demo+<ts>@…)",
    )
    p.add_argument(
        "--password",
        default=None,
        help="Password (default: ABA_PASSWORD / DEMO_PASSWORD / DemoAgent1)",
    )
    p.add_argument(
        "--no-seed",
        action="store_true",
        help="Skip POST /agents/seed-starter-team",
    )
    p.add_argument(
        "--no-trial",
        action="store_true",
        help="Skip best-effort trial activation",
    )
    p.add_argument(
        "--no-run",
        action="store_true",
        help="Create direct tasks as queued without scheduling agent runs",
    )
    p.add_argument(
        "--skip-meeting",
        action="store_true",
        help="Only seed + queue tasks (no meeting / kickoff / extract)",
    )
    p.add_argument(
        "--task-count",
        type=int,
        default=len(QUEUED_TASK_SPECS),
        help=f"How many direct queued tasks to create (default {len(QUEUED_TASK_SPECS)})",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    base = _resolve_base(args.base)
    print(f"bootstrap_demo_ecosystem base={base}")
    print("-" * 64)

    failed = 0
    summary: dict[str, Any] = {"base": base}

    # ── Auth ──────────────────────────────────────────────────────────────
    token = (args.token or os.environ.get("ABA_TOKEN") or "").strip() or None
    user_id: Any = None
    auth_mode = "token"

    if token:
        code, me = _request("GET", "/auth/me", token=token, base=base)
        if not _ok(code):
            # Some deploys use /auth/profile
            code2, me2 = _request("GET", "/auth/profile", token=token, base=base)
            if _ok(code2):
                code, me = code2, me2
        if _ok(code):
            user_id = _extract_user_id(me)
            _log("auth", True, f"mode=token user_id={user_id}")
        else:
            _log("auth", False, f"token rejected status={code} {_snip(me)}")
            return 1
    else:
        email = (
            (args.email or os.environ.get("ABA_EMAIL") or "").strip()
            or f"demo+{int(time.time())}@aibusinessagent.xyz"
        )
        password = (
            (args.password or "").strip()
            or (os.environ.get("ABA_PASSWORD") or "").strip()
            or (os.environ.get("DEMO_PASSWORD") or "").strip()
            or (os.environ.get("TEST_PASSWORD") or "").strip()
            or DEFAULT_PASSWORD
        )
        print(f"auth email={email}")
        try:
            token, user_id, auth_mode = register_or_login(email, password, base=base)
        except SystemExit as e:
            _log("auth", False, str(e))
            return 1
        _log("auth", True, f"mode={auth_mode} user_id={user_id}")
        summary["email"] = email

    summary["auth_mode"] = auth_mode
    summary["user_id"] = user_id
    summary["token_prefix"] = (token or "")[:12] + "…"

    if not args.no_trial:
        maybe_activate_trial(token, base)

    # ── Orchestrator ──────────────────────────────────────────────────────
    orch = ensure_orchestrator(token, base)
    if not orch:
        failed += 1
    else:
        summary["orchestrator_id"] = orch.get("id")

    # ── Seed starter team ─────────────────────────────────────────────────
    if not args.no_seed:
        seed = seed_starter_team(token, base)
        if seed:
            summary["seed_count"] = seed.get("count")
            summary["seed_at_limit"] = seed.get("at_limit")
    else:
        print("SKIP  seed-starter-team (--no-seed)")

    # ── Agents ────────────────────────────────────────────────────────────
    agents = list_agents(token, base)
    if not agents:
        failed += 1
        print("-" * 64)
        print("No agents available — cannot queue tasks or open meeting.")
        print(f"Done: {failed} FAIL")
        return 1
    summary["agent_count"] = len(agents)
    summary["agent_ids"] = [a.get("id") for a in agents[:12]]

    # ── Queued tasks (after seed) ─────────────────────────────────────────
    specs = QUEUED_TASK_SPECS[: max(0, int(args.task_count))]
    queued = create_queued_tasks(
        token,
        base,
        agents,
        run_now=not args.no_run,
        specs=specs,
    )

    if len(queued) < 1 and specs:
        failed += 1
    summary["queued_tasks"] = [
        {"id": t.get("id"), "status": t.get("status"), "title": t.get("title"), "agent_id": t.get("agent_id")}
        for t in queued
    ]

    # ── Meeting + kickoff + extract ───────────────────────────────────────
    meeting_id: int | None = None
    extracted: list[dict[str, Any]] = []
    if args.skip_meeting:
        print("SKIP  meeting/kickoff/extract (--skip-meeting)")
    else:
        meeting = create_meeting_with_agents(token, base, agents)
        if not meeting:
            failed += 1
        else:
            meeting_id = int(meeting["id"])
            summary["meeting_id"] = meeting_id
            if not post_kickoff(token, base, meeting_id):
                failed += 1
            else:
                extracted = extract_tasks(token, base, meeting_id)
                if not extracted:
                    failed += 1
                summary["extracted_tasks"] = [
                    {
                        "id": t.get("id"),
                        "status": t.get("status"),
                        "title": t.get("title"),
                        "agent_id": t.get("agent_id"),
                    }
                    for t in extracted
                ]

    # ── Summary ───────────────────────────────────────────────────────────
    print("-" * 64)
    print("SUMMARY")
    print(json.dumps(summary, indent=2, default=str))
    print("-" * 64)
    # Re-print token only when we created/logged-in this run (not when token was input)
    if auth_mode in ("register", "login"):
        print(f"api_key={token}")
        print(f"user_id={user_id}")
    print(
        f"Done: {'OK' if failed == 0 else f'{failed} FAIL'}  "
        f"agents={len(agents)} queued={len(queued)} "
        f"meeting={meeting_id} extracted={len(extracted)}"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
