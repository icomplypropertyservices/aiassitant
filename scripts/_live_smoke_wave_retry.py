#!/usr/bin/env python3
"""Finish meetings_create after login rate-limit cooldown; patch live_smoke_wave.json."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LOGIN_PATH = ROOT / ".demo_login.json"
OUT = ROOT / "live_smoke_wave.json"
BASE = "https://www.aibusinessagent.xyz"
WAIT = 240

login = json.loads(LOGIN_PATH.read_text(encoding="utf-8"))
report = json.loads(OUT.read_text(encoding="utf-8"))


def http(
    method: str,
    path: str,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 90,
) -> tuple[int, Any]:
    headers = {"Accept": "application/json", "User-Agent": "live-smoke-wave/1.1"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = raw
            return int(getattr(r, "status", None) or r.getcode()), parsed
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return int(e.code), parsed
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def main() -> int:
    print(f"Waiting {WAIT}s for login rate limit...")
    time.sleep(WAIT)

    token: str | None = None
    for _ in range(5):
        code, body = http(
            "POST",
            "/api/auth/login",
            body={"email": login["email"], "password": login["password"]},
        )
        print("LOGIN", code, str(body)[:220])
        if code == 429:
            print("still rate limited, sleep 60")
            time.sleep(60)
            continue
        if code == 200 and isinstance(body, dict):
            token = body.get("api_key") or body.get("token")
            if token:
                login["api_key"] = token
                user = body.get("user") if isinstance(body.get("user"), dict) else {}
                if user.get("id") is not None:
                    login["user_id"] = user["id"]
                break
        time.sleep(5)

    if not token:
        print("Could not login after cooldown")
        return 1

    # Verify token, then create meeting in one go
    code, me = http("GET", "/api/auth/me", token=token)
    print("ME", code, str(me)[:200] if not isinstance(me, dict) else f"plan={me.get('plan')}")
    if code == 401:
        code, body = http(
            "POST",
            "/api/auth/login",
            body={"email": login["email"], "password": login["password"]},
        )
        if code == 200 and isinstance(body, dict):
            token = body.get("api_key") or body.get("token")
            login["api_key"] = token

    code, meetings = http("GET", "/api/meetings/", token=token)
    print("MEETINGS LIST", code, type(meetings).__name__)

    code, meeting = http(
        "POST",
        "/api/meetings/",
        token=token,
        body={"title": "Live smoke wave meeting", "purpose": "live_smoke_wave"},
    )
    print("MEETINGS CREATE", code, str(meeting)[:300])
    mid = None
    if isinstance(meeting, dict):
        mid = meeting.get("id") or (meeting.get("meeting") or {}).get("id")
    ok = code in (200, 201) and mid is not None

    if code == 401:
        # one more login+retry
        c2, b2 = http(
            "POST",
            "/api/auth/login",
            body={"email": login["email"], "password": login["password"]},
        )
        print("RELOGIN", c2)
        if c2 == 200 and isinstance(b2, dict):
            token = b2.get("api_key") or b2.get("token")
            login["api_key"] = token
            code, meeting = http(
                "POST",
                "/api/meetings/",
                token=token,
                body={
                    "title": "Live smoke wave meeting",
                    "purpose": "live_smoke_wave",
                },
            )
            print("RETRY CREATE", code, str(meeting)[:300])
            if isinstance(meeting, dict):
                mid = meeting.get("id") or (meeting.get("meeting") or {}).get("id")
            ok = code in (200, 201) and mid is not None

    checks = report.get("checks") or []
    found = False
    for c in checks:
        if c.get("name") == "meetings_create":
            c.update(
                {
                    "status": code,
                    "ok": ok,
                    "detail": f"id={mid}" if mid else str(meeting)[:300],
                    "meeting_id": mid,
                    "retry": True,
                }
            )
            found = True
    if not found:
        checks.append(
            {
                "name": "meetings_create",
                "method": "POST",
                "path": "/api/meetings/",
                "status": code,
                "ok": ok,
                "detail": f"id={mid}" if mid else str(meeting)[:300],
                "meeting_id": mid,
                "retry": True,
            }
        )

    if mid is not None:
        gc, gresp = http("GET", f"/api/meetings/{mid}", token=token)
        title = gresp.get("title") if isinstance(gresp, dict) else None
        print("MEETINGS GET", gc, title)
        gok = gc == 200
        gfound = False
        for c in checks:
            if c.get("name") == "meetings_get":
                c.update(
                    {
                        "status": gc,
                        "ok": gok,
                        "path": f"/api/meetings/{mid}",
                        "detail": f"title={title}",
                        "retry": True,
                    }
                )
                gfound = True
        if not gfound:
            checks.append(
                {
                    "name": "meetings_get",
                    "method": "GET",
                    "path": f"/api/meetings/{mid}",
                    "status": gc,
                    "ok": gok,
                    "detail": f"title={title}",
                    "retry": True,
                }
            )

    report["checks"] = checks
    failed = [c["name"] for c in checks if not c.get("ok")]
    report["failed"] = failed
    report["summary"]["failed"] = len(failed)
    report["summary"]["passed"] = sum(1 for c in checks if c.get("ok"))
    report["summary"]["total_checks"] = len(checks)
    report["summary"]["meeting_id"] = mid
    report["areas"]["meetings"] = any(
        c.get("name") in ("meetings_list", "meetings_create") and c.get("ok")
        for c in checks
    )
    core = ("health", "login", "trial", "orchestrator", "templates", "agents", "meetings")
    report["ok"] = (not failed) and all(report["areas"].get(k) for k in core)
    report["retry_note"] = (
        "meetings_create re-run after login rate-limit cooldown; "
        "concurrent session-key rotation caused mid-wave 401s on shared demo account"
    )
    report["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    LOGIN_PATH.write_text(json.dumps(login, indent=2) + "\n", encoding="utf-8")
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("FINAL ok=", report["ok"], "failed=", failed, "meeting_id=", mid)
    print("WROTE", OUT)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
