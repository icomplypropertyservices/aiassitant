#!/usr/bin/env python3
"""
Billing / auth smoke audit against a live API base URL.

Checks (P0 soft-launch gate):
  1. GET  /health
  2. POST /auth/register  (unique email)
  3. POST /billing/plan   pay_as_you_go  — expect 402 in production
  4. POST /billing/plan   trial          — expect 200 (first activation)
  5. POST /billing/plan   trial again    — expect already_active or 402

Usage:
  python scripts/audit_smoke.py
  BASE_URL=https://aiassitant-nu.vercel.app/api python scripts/audit_smoke.py
  BASE_URL=http://127.0.0.1:8000 python scripts/audit_smoke.py

Exit code 1 if any check fails.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Prefer production Vercel API when BASE_URL unset; local override via env.
DEFAULT_PROD = "https://aiassitant-nu.vercel.app/api"
DEFAULT_LOCAL = "http://127.0.0.1:8000"


def _default_base() -> str:
    env = (os.environ.get("BASE_URL") or "").strip().rstrip("/")
    if env:
        return env
    # Explicit LOCAL=1 forces local default
    if os.environ.get("LOCAL", "").strip() in ("1", "true", "yes"):
        return DEFAULT_LOCAL
    return DEFAULT_PROD


BASE_URL = _default_base()
TIMEOUT = float(os.environ.get("AUDIT_TIMEOUT", "45"))

rows: list[tuple[str, str, str]] = []  # name, PASS|FAIL, detail


def _record(name: str, ok: bool, detail: str) -> None:
    status = "PASS" if ok else "FAIL"
    rows.append((name, status, detail[:300]))
    print(f"{status:4}  {name}: {detail[:300]}")


def _request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    url = f"{BASE_URL}{path if path.startswith('/') else '/' + path}"
    data = None
    headers = {"Accept": "application/json", "User-Agent": "audit-smoke/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = getattr(resp, "status", None) or resp.getcode()
            try:
                return int(code), json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return int(code), raw
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            parsed: Any = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return int(e.code), parsed
    except URLError as e:
        return 0, {"error": str(e.reason if hasattr(e, "reason") else e)}


def _detail_snippet(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, dict):
        # FastAPI often returns {"detail": "..."}
        d = payload.get("detail", payload)
        if isinstance(d, (dict, list)):
            return json.dumps(d)[:200]
        return str(d)[:200]
    return str(payload)[:200]


def main() -> int:
    print(f"audit_smoke BASE_URL={BASE_URL}")
    print("-" * 60)

    # ── 1. Health ──────────────────────────────────────────────────────────
    code, health = _request("GET", "/health")
    health_ok = code == 200 and isinstance(health, dict) and health.get("ok") is True
    env_name = ""
    is_production = False
    if isinstance(health, dict):
        env_name = str(health.get("environment") or "")
        is_production = env_name.lower() in ("production", "prod") or (
            health.get("billing_free_grants") is False
            and "vercel" in BASE_URL.lower()
        )
        # Prefer explicit environment flag
        if env_name.lower() in ("production", "prod"):
            is_production = True
        elif env_name.lower() in ("development", "dev", "local", "test"):
            is_production = False
    _record(
        "health",
        health_ok,
        f"status={code} env={env_name or '?'} prod={is_production} {_detail_snippet(health)}",
    )

    # ── 2. Register unique user ────────────────────────────────────────────
    suffix = uuid.uuid4().hex[:12]
    email = f"audit.smoke.{suffix}@example.com"
    password = f"Audit1{suffix[:6]}x"  # letter + digit, len >= 8
    code, reg = _request(
        "POST",
        "/auth/register",
        body={
            "email": email,
            "password": password,
            "name": "Audit Smoke",
            "company_name": "Audit Co",
        },
    )
    token = None
    if code in (200, 201) and isinstance(reg, dict):
        token = reg.get("token")
    reg_ok = bool(token)
    _record(
        "register",
        reg_ok,
        f"status={code} email={email} token={'yes' if token else 'no'} {_detail_snippet(reg)}",
    )

    if not token:
        # Cannot continue billing checks without auth
        _record("pay_as_you_go", False, "skipped — no token")
        _record("trial_activate", False, "skipped — no token")
        _record("trial_reactivate", False, "skipped — no token")
        return _finish()

    # ── 3. pay_as_you_go ───────────────────────────────────────────────────
    code, payg = _request(
        "POST",
        "/billing/plan",
        token=token,
        body={"plan": "pay_as_you_go", "company_name": "Audit Co"},
    )
    if is_production:
        payg_ok = code == 402
        expect = "402"
    else:
        # Non-prod may free-activate (200) or still require payment
        payg_ok = code in (200, 402)
        expect = "200 or 402"
    _record(
        "pay_as_you_go",
        payg_ok,
        f"status={code} expect={expect} (prod={is_production}) {_detail_snippet(payg)}",
    )

    # ── 4. Activate trial once ─────────────────────────────────────────────
    code, trial1 = _request(
        "POST",
        "/billing/plan",
        token=token,
        body={"plan": "trial", "company_name": "Audit Co"},
    )
    trial1_ok = code == 200 and isinstance(trial1, dict) and (
        trial1.get("plan") == "trial" or trial1.get("subscription_active") is True
    )
    # If somehow already_active on first call, still count as activated state
    if code == 200 and isinstance(trial1, dict) and trial1.get("already_active"):
        trial1_ok = True
    _record(
        "trial_activate",
        trial1_ok,
        f"status={code} already_active={isinstance(trial1, dict) and trial1.get('already_active')} "
        f"{_detail_snippet(trial1)}",
    )

    # Small pause (serverless cold / commit race)
    time.sleep(0.3)

    # ── 5. Re-activate trial ───────────────────────────────────────────────
    code, trial2 = _request(
        "POST",
        "/billing/plan",
        token=token,
        body={"plan": "trial", "company_name": "Audit Co"},
    )
    already = isinstance(trial2, dict) and trial2.get("already_active") is True
    # Active trial → 200 + already_active; used/expired → 402
    trial2_ok = (code == 200 and already) or code == 402
    _record(
        "trial_reactivate",
        trial2_ok,
        f"status={code} already_active={already} {_detail_snippet(trial2)}",
    )

    return _finish()


def _finish() -> int:
    print("-" * 60)
    # Table
    name_w = max((len(r[0]) for r in rows), default=8)
    print(f"{'CHECK':<{name_w}}  {'RESULT':6}  DETAIL")
    for name, status, detail in rows:
        print(f"{name:<{name_w}}  {status:6}  {detail}")
    failed = sum(1 for _, s, _ in rows if s == "FAIL")
    passed = sum(1 for _, s, _ in rows if s == "PASS")
    print("-" * 60)
    print(f"Summary: {passed} PASS, {failed} FAIL  (BASE_URL={BASE_URL})")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
