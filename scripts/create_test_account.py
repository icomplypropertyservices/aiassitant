#!/usr/bin/env python3
"""
Create (or login) a throwaway test account on production, activate free trial,
bootstrap orchestrator, optionally smoke execute_goal via agent chat, and
cache the session token for other demo scripts.

Usage:
  python scripts/create_test_account.py
  BASE_URL=https://www.aibusinessagent.xyz python scripts/create_test_account.py

Writes Bearer token to scripts/.demo_token (gitignored).
Final summary reports email only (no password / full api_key).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# www is the host that accepts API POSTs without 308 (apex may redirect)
DEFAULT_BASE = "https://www.aibusinessagent.xyz"
# Fixed test password (meets min 8 + letter + digit). Not a production secret.
TEST_PASSWORD = "TestAgent1"
TIMEOUT = float(os.environ.get("TIMEOUT", "90"))
# Chat / goal chain may wait on LLM; keep a higher ceiling.
CHAT_TIMEOUT = float(os.environ.get("CHAT_TIMEOUT", "180"))
TOKEN_PATH = Path(__file__).resolve().parent / ".demo_token"

# Goal-like prompt so maybe_auto_chain_from_chat → execute_goal chain fires.
SMOKE_GOAL_MESSAGE = (
    "Plan and execute a short smoke test: organize our trial workspace, "
    "list the next steps, and delegate one research task to the team."
)


def base_url() -> str:
    return (os.environ.get("BASE_URL") or DEFAULT_BASE).strip().rstrip("/")


def request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> tuple[int, Any]:
    url = f"{base_url()}{path if path.startswith('/') else '/' + path}"
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "create-test-account/1.2",
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


def _extract_key(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    key = payload.get("api_key") or payload.get("token") or payload.get("access_token")
    if key and isinstance(key, str):
        return key
    return None


def _extract_user_id(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return None
    user = payload.get("user")
    if isinstance(user, dict) and user.get("id") is not None:
        return user.get("id")
    return payload.get("user_id") or payload.get("id")


def _mask_token(token: str) -> str:
    t = (token or "").strip()
    if len(t) <= 10:
        return "***"
    return f"{t[:8]}..."


def save_demo_token(token: str) -> Path:
    """Persist session key for other demo/smoke scripts (gitignored)."""
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(token.strip() + "\n", encoding="utf-8")
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass  # Windows may ignore chmod
    return TOKEN_PATH


def register_or_login(email: str, password: str) -> tuple[str, Any, str, dict[str, Any]]:
    """Return (api_key, user_id, mode, register_body)."""
    code, body = request(
        "POST",
        "/api/auth/register",
        body={
            "email": email,
            "password": password,
            "name": "Test Agent",
            "company_name": "Test Co",
        },
    )
    if code == 0:
        raise SystemExit(f"register unreachable: {body!r}")
    if code == 308 and isinstance(body, dict) and body.get("redirect"):
        raise SystemExit(
            f"register got HTTP 308 redirect to {body.get('redirect')!r}. "
            "Use BASE_URL=https://www.aibusinessagent.xyz (apex may redirect POSTs)."
        )
    if code in (200, 201):
        key = _extract_key(body)
        if key:
            return key, _extract_user_id(body), "register", body if isinstance(body, dict) else {}
        raise SystemExit(f"register ok but no api_key in response: {body!r}")

    # Account may already exist — fall back to login
    detail = ""
    if isinstance(body, dict):
        detail = str(body.get("detail") or body)
    already = code in (400, 409) and (
        "already" in detail.lower() or "exists" in detail.lower()
    )
    if not already and code not in (400, 409):
        raise SystemExit(f"register failed http={code}: {body!r}")

    code, body = request(
        "POST",
        "/api/auth/login",
        body={"email": email, "password": password},
    )
    if code != 200:
        raise SystemExit(f"login failed http={code}: {body!r}")
    key = _extract_key(body)
    if not key:
        raise SystemExit(f"login ok but no api_key in response: {body!r}")
    return key, _extract_user_id(body), "login", body if isinstance(body, dict) else {}


def ensure_trial(token: str, register_body: dict[str, Any]) -> dict[str, Any]:
    """If register left plan=none, activate free trial via billing. Returns result info."""
    info: dict[str, Any] = {"skipped": False, "http": None, "plan": None}
    user = register_body.get("user") if isinstance(register_body.get("user"), dict) else {}
    plan = user.get("plan")
    if plan and plan not in ("none", ""):
        print(f"plan: already {plan} (subscription_active={user.get('subscription_active')})")
        info["skipped"] = True
        info["plan"] = plan
        return info

    code, me = request("GET", "/api/auth/me", token=token)
    if code == 200 and isinstance(me, dict):
        plan = me.get("plan")
        if plan and plan not in ("none", ""):
            print(f"plan: me says {plan}")
            info["skipped"] = True
            info["plan"] = plan
            info["http"] = code
            return info

    code, body = request(
        "POST",
        "/api/billing/plan",
        token=token,
        body={"plan": "trial"},
    )
    info["http"] = code
    print(f"billing/plan trial: http={code}")
    if isinstance(body, dict):
        info["plan"] = body.get("plan")
        info["already_active"] = body.get("already_active")
        info["subscription_active"] = body.get("subscription_active")
        print(
            f"  plan={body.get('plan')} active={body.get('subscription_active')} "
            f"expires={body.get('subscription_expires_at')}"
        )
    elif code >= 400:
        print(f"  body={str(body)[:300]}")
    return info


def templates_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for k in ("templates", "items", "data", "results"):
            v = payload.get(k)
            if isinstance(v, list):
                return len(v)
        if "count" in payload and isinstance(payload["count"], int):
            return payload["count"]
    return 0


def maybe_create_meeting(token: str) -> None:
    """If /api/meetings exists, create a minimal test meeting; otherwise skip."""
    for path in ("/api/meetings", "/api/meetings/"):
        code, body = request("GET", path, token=token)
        if code == 404:
            continue
        if code == 0:
            print(f"meetings: unreachable ({body})")
            return
        if code in (401, 403):
            print(f"meetings: auth error http={code}")
            return
        if code >= 500:
            print(f"meetings: server error http={code}")
            return
        print(f"meetings: GET {path} -> http={code}")
        create_code, create_body = request(
            "POST",
            "/api/meetings" if not path.endswith("/") else "/api/meetings/",
            token=token,
            body={
                "title": "Test meeting",
                "purpose": "Created by create_test_account.py",
            },
        )
        print(f"meetings: POST create -> http={create_code}")
        if isinstance(create_body, dict):
            mid = create_body.get("id") or (create_body.get("meeting") or {}).get("id")
            if mid is not None:
                print(f"meetings: created id={mid}")
            else:
                print(f"meetings: response={json.dumps(create_body)[:300]}")
        else:
            print(f"meetings: response={str(create_body)[:300]}")
        return

    print("meetings: /api/meetings not available — skipped")


def smoke_execute_goal_via_chat(token: str, agent_id: Any) -> dict[str, Any]:
    """
    Optional smoke: POST agent chat with a goal-like message so auto-chain /
    execute_goal path runs. Best-effort — does not fail the whole script.
    Falls back to skills/run execute_goal if chat is unavailable.
    """
    result: dict[str, Any] = {
        "attempted": False,
        "via": None,
        "http": None,
        "ok": False,
        "detail": "",
    }
    if agent_id is None:
        print("execute_goal smoke: no orchestrator id — skipped")
        result["detail"] = "no_agent_id"
        return result

    result["attempted"] = True
    path = f"/api/agents/{agent_id}/chat"
    print(f"execute_goal smoke: POST {path} (goal-like chat)...")
    code, body = request(
        "POST",
        path,
        token=token,
        body={"message": SMOKE_GOAL_MESSAGE},
        timeout=CHAT_TIMEOUT,
    )
    result["http"] = code
    result["via"] = "chat"

    if code == 200 and isinstance(body, dict):
        chain = body.get("goal_chain")
        skills = body.get("skills") or []
        reply_snip = str(body.get("reply") or "")[:160].replace("\n", " ")
        print(f"  chat: http={code} ok={body.get('ok')} tokens={body.get('tokens')}")
        if reply_snip:
            print(f"  reply: {reply_snip!r}")
        if isinstance(chain, dict):
            result["ok"] = bool(chain.get("ok") or chain.get("parent_task_id"))
            result["parent_task_id"] = chain.get("parent_task_id")
            result["steps"] = chain.get("steps") or len(chain.get("children") or [])
            result["deduped"] = chain.get("deduped")
            print(
                f"  goal_chain: ok={chain.get('ok')} parent={chain.get('parent_task_id')} "
                f"steps={result.get('steps')} deduped={chain.get('deduped')}"
            )
        elif skills:
            # Model emitted skill blocks (possibly execute_goal)
            skill_ids = [
                s.get("skill") for s in skills if isinstance(s, dict)
            ]
            result["skills"] = skill_ids
            result["ok"] = any(
                (s.get("skill") == "execute_goal" and s.get("ok") is not False)
                for s in skills
                if isinstance(s, dict)
            ) or body.get("ok") is True
            print(f"  skills: {skill_ids}")
        else:
            # Chat answered but no chain — still a successful chat smoke
            result["ok"] = body.get("ok") is True or bool(body.get("reply"))
            result["detail"] = "chat_ok_no_goal_chain"
            print("  goal_chain: none (chat replied without auto-chain)")
        return result

    print(f"  chat: http={code} body={str(body)[:280]}")

    # Fallback: direct skill if chat timed out / 5xx / missing route
    if code in (0, 404, 405, 408, 500, 502, 503, 504) or code >= 500:
        skill_path = f"/api/agents/{agent_id}/skills/run"
        print(f"execute_goal smoke: fallback POST {skill_path} ...")
        scode, sbody = request(
            "POST",
            skill_path,
            token=token,
            body={
                "skill": "execute_goal",
                "args": {
                    "goal": SMOKE_GOAL_MESSAGE,
                    "title": "Smoke execute_goal",
                    "max_steps": 3,
                    "priority": "medium",
                },
            },
            timeout=CHAT_TIMEOUT,
        )
        result["via"] = "skills/run"
        result["http"] = scode
        if scode == 200 and isinstance(sbody, dict):
            result["ok"] = bool(sbody.get("ok") or sbody.get("parent_task_id"))
            result["parent_task_id"] = sbody.get("parent_task_id")
            result["steps"] = sbody.get("steps") or len(sbody.get("children") or [])
            print(
                f"  skills/run: http={scode} ok={sbody.get('ok')} "
                f"parent={sbody.get('parent_task_id')} {_snip_dict(sbody)}"
            )
        else:
            result["detail"] = str(sbody)[:200]
            print(f"  skills/run: http={scode} body={str(sbody)[:280]}")
        return result

    result["detail"] = str(body)[:200]
    return result


def _snip_dict(d: dict[str, Any]) -> str:
    try:
        return json.dumps({k: d.get(k) for k in ("ok", "message", "parent_task_id", "steps") if k in d})[:200]
    except Exception:
        return ""


def main() -> int:
    ts = int(time.time())
    email = f"test+{ts}@aibusinessagent.xyz"
    password = os.environ.get("TEST_PASSWORD") or TEST_PASSWORD

    print(f"BASE_URL={base_url()}")
    print(f"email={email}")

    api_key, user_id, mode, reg_body = register_or_login(email, password)
    print(f"auth_mode={mode}")
    print(f"user_id={user_id}")
    print(f"token_mask={_mask_token(api_key)}")
    if mode == "register" and isinstance(reg_body, dict):
        print(f"trial_started={reg_body.get('trial_started')}")

    token_path = save_demo_token(api_key)
    print(f"token_saved={token_path}")

    trial_info = ensure_trial(api_key, reg_body if mode == "register" else {})

    # Ensure main orchestrator
    orch_id = None
    code, orch = request(
        "POST",
        "/api/agents/ensure-orchestrator",
        token=api_key,
        timeout=max(TIMEOUT, 120),
    )
    print(f"ensure-orchestrator: http={code}")
    if isinstance(orch, dict):
        orch_id = orch.get("id")
        print(
            f"  agent_id={orch_id} name={orch.get('name')!r} "
            f"type={orch.get('type') or orch.get('role') or orch.get('template_type')}"
        )
        if orch.get("bootstrap_error"):
            print(f"  bootstrap_error={orch.get('bootstrap_error')}")
    elif code >= 400 or code == 0:
        print(f"  body={str(orch)[:300]}")

    # Optional execute_goal smoke via chat (best-effort)
    goal_smoke: dict[str, Any] = {"attempted": False, "ok": False}
    skip_chat = os.environ.get("SKIP_CHAT_SMOKE", "").strip().lower() in ("1", "true", "yes")
    if skip_chat:
        print("execute_goal smoke: SKIP_CHAT_SMOKE set — skipped")
        goal_smoke["detail"] = "skipped_env"
    else:
        goal_smoke = smoke_execute_goal_via_chat(api_key, orch_id)

    # Templates count
    code_t, templates = request("GET", "/api/templates/", token=api_key)
    count = templates_count(templates) if code_t == 200 else 0
    print(f"templates: http={code_t} count={count}")
    if code_t != 200:
        print(f"  body={str(templates)[:300]}")

    # Optional meeting
    maybe_create_meeting(api_key)

    # Final report — credentials: email only
    print("-" * 40)
    print("DONE")
    print(f"email={email}")
    print(f"user_id={user_id}")
    print(f"auth_mode={mode}")
    print(f"trial_plan={trial_info.get('plan')} trial_http={trial_info.get('http')} trial_skipped={trial_info.get('skipped')}")
    print(f"ensure-orchestrator_http={code} agent_id={orch_id}")
    print(
        f"execute_goal_smoke via={goal_smoke.get('via')} http={goal_smoke.get('http')} "
        f"ok={goal_smoke.get('ok')} parent_task_id={goal_smoke.get('parent_task_id')} "
        f"detail={goal_smoke.get('detail') or ''}"
    )
    print(f"templates_count={count}")
    print(f"token_file={token_path} mask={_mask_token(api_key)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        sys.exit(130)
