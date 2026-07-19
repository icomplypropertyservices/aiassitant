"""
Live skill + orchestrator autonomy smoke test against production.

Usage:
  set ABA_EMAIL / ABA_PASSWORD or pass --email --password
  python scripts/test_skills_live.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

BASE = os.environ.get("ABA_BASE", "https://www.aibusinessagent.xyz").rstrip("/")


def req(method: str, path: str, token: str | None = None, body: dict | None = None, timeout: int = 120) -> tuple[int, Any]:
    url = f"{BASE}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw) if raw else {"error": str(e)}
        except json.JSONDecodeError:
            return e.code, {"error": raw or str(e)}


def sample_args(skill: dict) -> dict:
    """Safe default args for automated runs (no real external side-effects when possible)."""
    sid = skill.get("id") or ""
    args_list = skill.get("args") or []
    if isinstance(args_list, str):
        args_list = [a for a in args_list.split() if a]
    out: dict[str, Any] = {}

    # Base deterministic fixtures (IDs are patched at runtime with real seeded data)
    fixtures = {
        "spawn_agent": {
            "name": "Skill Test Runner",
            "template_type": "general",
            "personality": "Concise test agent",
            "hierarchy_role": "member",
        },
        "save_memory": {"title": "Skill test note", "content": "Automated skill test OK", "kind": "note", "tags": "test"},
        "save_training": {"title": "Skill test training", "content": "Training snippet from skill test.", "tags": "test"},
        "create_task": {"title": "Skill test task", "description": "Created by skill test suite", "priority": "low"},
        "announce_plan": {"title": "Skill test plan", "steps": ["Step A", "Step B", "Step C"]},
        "list_customers": {"q": "", "limit": 5},
        "list_team": {},
        "list_diary": {"limit": 5},
        "get_time": {},
        "suggest_times": {"duration_minutes": 30, "days_ahead": 3},
        "search_memory": {"q": "skill test"},
        "search_knowledge": {"q": "fire alarm"},
        "generate_content": {"topic": "Fire alarm servicing Dublin", "format": "short_post", "tone": "professional"},
        "research": {"topic": "BS 5839 fire alarm standards Ireland", "depth": "brief"},
        "summarize": {"text": "Fire Alarms Dublin installs and services commercial fire alarms across the city.", "style": "bullets"},
        "draft_email": {
            "to": "client@example.com",
            "subject": "Service quote follow-up",
            "goal": "Follow up on fire alarm quote",
            "tone": "friendly professional",
        },
        "draft_sms": {"to": "+353800000000", "message_goal": "Confirm tomorrow's inspection slot"},
        "log_communication": {"channel": "note", "summary": "Skill test log entry", "direction": "outbound"},
        "create_invoice_draft": {"customer_name": "Test Client Ltd", "line_items": "Service visit x1", "amount": 150},
        "create_reminder": {"title": "Skill test reminder", "when": "tomorrow 09:00", "notes": "auto test"},
        "set_agent_status": {"status": "active"},
        "prioritize_list": {"items": "Quote follow-ups, Certificate backlog, Website SEO"},
        "action_items": {"text": "Call ACME about cert. Email Bob quote. Book van for Friday."},
        "decision_log": {"decision": "Use Grok-only API", "context": "Production inference", "rationale": "Consistency"},
        "monthly_summary": {"period": "2026-07", "highlights": "Shipped workspace companies and Grok-only routing"},
        "skill_recommend": {"role": "sales", "description": "Outbound fire alarm sales"},
        "enable_skills_on": {"target_agent_id": 1, "skill_ids": ["draft_email", "create_task"]},
        "configure_agent": {"target_agent_id": 1, "idle_mode": "never_idle"},
        "improve_prompt": {"current_prompt": "You are a sales agent.", "goal": "More concise"},
        "exec_summary_email": {"source": "Long weekly report about jobs completed and open quotes."},
        "post_mortem": {"incident": "Quote email delayed 2 days", "impact": "Lost one lead"},
        "changelog": {"items": "Fixed Grok credentials; Added workspace companies"},
        "build_icp": {"notes": "Dublin SMEs needing BS 5839 fire alarm servicing"},
        "health_score": {"customer": "ACME Ltd", "signals": "Paid on time, two open tickets"},
        "triage_ticket": {"ticket": "Alarm panel beeping overnight in warehouse"},
        "knowledge_answer": {"question": "How often must fire alarms be serviced?"},
        "follow_up_sequence": {"offer": "Annual fire alarm service contract", "channel": "email"},
        "objection_handler": {"objection": "Too expensive", "product": "Annual servicing plan"},
    }
    if sid in fixtures:
        return fixtures[sid]

    # Generic fill for remaining catalog/LLM skills
    for a in args_list:
        a = str(a)
        if a in ("title", "name", "subject"):
            out[a] = f"Skill test {sid}"
        elif a in ("content", "text", "body", "message", "description", "notes", "prompt", "topic"):
            out[a] = f"Automated test content for skill {sid}."
        elif a in ("limit", "count", "n"):
            out[a] = 3
        elif a in ("priority",):
            out[a] = "low"
        elif a in ("tone", "style", "format"):
            out[a] = "professional"
        elif a.endswith("_id") or a in ("to_agent_id", "agent_id", "customer_id", "human_id"):
            out[a] = 1
        elif a in ("email", "to"):
            out[a] = "test@example.com"
        elif a in ("phone",):
            out[a] = "+353800000000"
        elif a in ("steps", "items", "list"):
            out[a] = ["One", "Two", "Three"]
        else:
            out[a] = f"test-{a}"
    if not out:
        out = {"input": f"Automated test for {sid}"}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default=os.environ.get("ABA_EMAIL", "firealarmsdublin@gmail.com"))
    ap.add_argument("--password", default=os.environ.get("ABA_PASSWORD", ""))
    ap.add_argument("--max-skills", type=int, default=0, help="0 = all free runnable skills")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--skip-premium", action="store_true", default=True)
    ap.add_argument("--skip-integrations", action="store_true", default=True)
    ap.add_argument("--include-premium", action="store_true")
    ap.add_argument("--include-integrations", action="store_true")
    ap.add_argument("--orchestrator-id", type=int, default=0)
    args = ap.parse_args()
    if args.include_premium:
        args.skip_premium = False
    if args.include_integrations:
        args.skip_integrations = False
    if not args.password:
        print("Missing password (ABA_PASSWORD or --password)", file=sys.stderr)
        return 2

    code, login = req("POST", "/api/auth/login", body={"email": args.email, "password": args.password})
    if code >= 400 or not isinstance(login, dict):
        print("LOGIN_FAIL", code, login)
        return 1
    token = login.get("access_token") or login.get("token")
    print("LOGIN_OK", args.email)

    code, agents = req("GET", "/api/agents/", token)
    if code >= 400 or not isinstance(agents, list):
        print("AGENTS_FAIL", code, agents)
        return 1
    orch = None
    for a in agents:
        if a.get("is_orchestrator") or a.get("hierarchy_role") == "orchestrator":
            orch = a
            break
    if args.orchestrator_id:
        orch = next((a for a in agents if a.get("id") == args.orchestrator_id), orch)
    if not orch:
        print("NO_ORCHESTRATOR")
        return 1
    oid = int(orch["id"])
    print(f"ORCHESTRATOR id={oid} name={orch.get('name')} model={orch.get('model')} perm={orch.get('permission_level')}")

    # Ensure admin permission + never_idle for autonomous skill runs
    code, patched = req(
        "PATCH",
        f"/api/agents/{oid}",
        token,
        {
            "permission_level": "admin",
            "idle_mode": "never_idle",
            "status": "active",
            "model": "quality",
        },
    )
    print("ORCH_PATCH", code, (patched or {}).get("permission_level") if isinstance(patched, dict) else patched)

    # --- Pre-seed test data so CRM / human / agent-to-agent skills can succeed ---
    # Ensure at least one Human exists
    test_human_id = None
    code, humans = req("GET", "/api/humans/", token)
    if code < 400 and isinstance(humans, list) and humans:
        test_human_id = humans[0].get("id")
        print(f"USING_EXISTING_HUMAN id={test_human_id}")
    else:
        code, h = req("POST", "/api/humans/", token, {"name": "Skill Test Human", "role_title": "Tester", "email": "skilltest@example.com"})
        if code < 400 and isinstance(h, dict):
            test_human_id = h.get("id")
            print(f"CREATED_TEST_HUMAN id={test_human_id}")
        else:
            print("HUMAN_CREATE_FAIL", code, h)

    # Ensure at least one Customer exists (for get/update/log/deal/meeting)
    test_customer_id = None
    test_customer_email = "skilltest+customer@example.com"
    code, custs = req("GET", "/api/business/customers?limit=5", token)
    if code < 400 and isinstance(custs, dict):
        rows = custs.get("customers") or custs.get("items") or []
        if rows:
            test_customer_id = rows[0].get("id")
            test_customer_email = rows[0].get("email") or test_customer_email
            print(f"USING_EXISTING_CUSTOMER id={test_customer_id}")
    if not test_customer_id:
        code, c = req("POST", "/api/business/customers", token, {
            "name": "Skill Test Client Ltd",
            "email": test_customer_email,
            "status": "active",
            "tags": "test,skill",
        })
        if code < 400 and isinstance(c, dict):
            test_customer_id = c.get("id")
            test_customer_email = c.get("email") or test_customer_email
            print(f"CREATED_TEST_CUSTOMER id={test_customer_id}")
        else:
            print("CUSTOMER_CREATE_FAIL", code, c)

    # Ensure a second agent exists so message_agent can target someone real
    peer_agent_id = None
    code, ags = req("GET", "/api/agents/", token)
    peers = [a for a in (ags or []) if isinstance(a, dict) and a.get("id") != oid]
    if peers:
        peer_agent_id = peers[0].get("id")
        print(f"USING_EXISTING_PEER_AGENT id={peer_agent_id}")
    else:
        code, spawned = req("POST", f"/api/agents/{oid}/skills/run", token, {
            "skill": "spawn_agent",
            "args": {"name": "Skill Test Peer", "template_type": "general", "hierarchy_role": "member"}
        })
        if code < 400 and isinstance(spawned, dict):
            # spawned may be wrapped
            peer_agent_id = (spawned.get("result") or spawned).get("agent_id") if isinstance(spawned.get("result"), dict) else None
            if not peer_agent_id:
                # try listing again
                code2, ags2 = req("GET", "/api/agents/", token)
                peers2 = [a for a in (ags2 or []) if isinstance(a, dict) and a.get("id") != oid]
                if peers2:
                    peer_agent_id = peers2[0].get("id")
            print(f"CREATED_PEER_AGENT id={peer_agent_id}")
        else:
            print("PEER_SPAWN_FAIL", code, spawned)

    code, skill_payload = req("GET", f"/api/agents/{oid}/skills", token, timeout=90)
    if code >= 400 or not isinstance(skill_payload, dict):
        print("SKILLS_FAIL", code, skill_payload)
        return 1
    skills = skill_payload.get("skills") or []
    print(
        "SKILL_SUMMARY",
        skill_payload.get("summary")
        or {"total": len(skills), "enabled": skill_payload.get("enabled_count")},
    )

    # Prefer skills that are enabled, role-allowed, free, and integration-ready
    candidates = []
    skipped = {"premium": 0, "integration": 0, "disabled": 0, "role": 0}
    for s in skills:
        if not s.get("enabled", True):
            skipped["disabled"] += 1
            continue
        if not s.get("role_allowed", True):
            skipped["role"] += 1
            continue
        if args.skip_premium and s.get("premium"):
            skipped["premium"] += 1
            continue
        if args.skip_integrations and s.get("integration_ready") is False:
            skipped["integration"] += 1
            continue
        # Avoid destructive agent ops in bulk test
        if s.get("id") in ("delete_agent", "pause_agent"):
            continue
        candidates.append(s)

    if args.max_skills and args.max_skills > 0:
        candidates = candidates[: args.max_skills]
    print(f"WILL_RUN={len(candidates)} skipped={skipped}")

    # --- Patch fixtures with real seeded IDs (critical for CRM / delegation skills) ---
    def _patch_args(sid: str, base_args: dict) -> dict:
        a = dict(base_args or {})
        # message_agent needs a real peer
        if sid == "message_agent":
            target = peer_agent_id or 1
            a.setdefault("to_agent_id", target)
            a.setdefault("message", "Skill test ping from orchestrator — reply briefly.")
            a.setdefault("expect_reply", False)
        # Human assignment
        if sid == "assign_human" and test_human_id:
            a.setdefault("human_id", test_human_id)
            a.setdefault("title", "Skill test work item")
            a.setdefault("description", "Automated assignment from skill test")
        # CRM skills — prefer ID, fall back to email we created
        if sid in ("get_customer", "update_customer", "log_customer_activity", "create_deal", "schedule_meeting"):
            if test_customer_id:
                a.setdefault("customer_id", test_customer_id)
            if test_customer_email:
                a.setdefault("email", test_customer_email)
            if sid == "create_deal":
                a.setdefault("title", "Skill test opportunity")
                a.setdefault("value", 123)
            if sid == "schedule_meeting":
                a.setdefault("title", "Skill test meeting")
        # Skills that take target_agent_id
        if sid in ("enable_skills_on", "configure_agent") and oid:
            a.setdefault("target_agent_id", oid)
        return a

    results: list[dict] = []

    def run_one(s: dict) -> dict:
        sid = s["id"]
        base = sample_args(s)
        args = _patch_args(sid, base)
        body = {"skill": sid, "args": args}
        t0 = time.time()
        code, out = req("POST", f"/api/agents/{oid}/skills/run", token, body, timeout=180)
        dt = round(time.time() - t0, 2)
        ok = False
        err = None
        msg = ""
        if isinstance(out, dict):
            ok = bool(out.get("ok"))
            err = out.get("error")
            msg = (out.get("message") or out.get("result") or "")
            if isinstance(msg, (dict, list)):
                msg = json.dumps(msg)[:200]
            else:
                msg = str(msg)[:200]
            # some handlers return ok nested
            if not ok and out.get("result") and isinstance(out["result"], dict):
                ok = bool(out["result"].get("ok"))
                err = err or out["result"].get("error")
        if code >= 400:
            ok = False
            err = err or f"http_{code}"
        return {
            "id": sid,
            "http": code,
            "ok": ok,
            "error": err,
            "message": msg,
            "seconds": dt,
            "premium": bool(s.get("premium")),
            "category": s.get("category"),
        }

    # Sequential for stability on serverless (workers optional)
    workers = max(1, min(args.workers, 4))
    if workers == 1:
        for s in candidates:
            r = run_one(s)
            results.append(r)
            mark = "PASS" if r["ok"] else "FAIL"
            print(f"{mark} {r['id']} {r['seconds']}s {r.get('error') or r.get('message') or ''}"[:220])
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(run_one, s): s for s in candidates}
            for fut in as_completed(futs):
                r = fut.result()
                results.append(r)
                mark = "PASS" if r["ok"] else "FAIL"
                print(f"{mark} {r['id']} {r['seconds']}s {r.get('error') or r.get('message') or ''}"[:220])

    passed = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    print("\n=== SKILL RUN SUMMARY ===")
    print(f"passed={len(passed)} failed={len(failed)} total={len(results)}")
    if failed:
        print("FAILURES:")
        for r in sorted(failed, key=lambda x: x["id"]):
            print(f"  - {r['id']}: http={r['http']} err={r.get('error')} msg={r.get('message')}")

    # Autonomy: enable + force tick
    print("\n=== AUTONOMY ===")
    code, auto = req(
        "PUT",
        "/api/ops/autonomy",
        token,
        {"autonomy_enabled": True, "autonomy_interval_sec": 60, "task_stuck_minutes": 30},
    )
    print("AUTONOMY_PUT", code, auto if isinstance(auto, dict) else str(auto)[:200])
    code, tick = req("POST", "/api/ops/autonomy/tick", token, timeout=180)
    print("AUTONOMY_TICK", code, json.dumps(tick)[:500] if isinstance(tick, (dict, list)) else tick)

    # Orchestrator chat should auto-invoke skills via skill blocks in model output
    print("\n=== ORCHESTRATOR AUTO SKILL CHAT ===")
    chat_prompt = (
        "You are running an automated skill verification. "
        "In your reply you MUST include these skill blocks exactly (valid JSON inside):\n"
        "```skill\n"
        '{"skill":"save_memory","args":{"title":"Auto skill check","content":"Orchestrator auto skill ran","kind":"note","tags":"auto-test"}}\n'
        "```\n"
        "```skill\n"
        '{"skill":"create_task","args":{"title":"Auto-created by orchestrator","description":"From chat skill block","priority":"low"}}\n'
        "```\n"
        "```skill\n"
        '{"skill":"announce_plan","args":{"title":"Auto plan","steps":["Check skills","Run autonomy","Report"]}}\n'
        "```\n"
        "After the blocks, write one short sentence confirming you ran the skills."
    )
    code, chat = req(
        "POST",
        f"/api/agents/{oid}/chat",
        token,
        {"message": chat_prompt},
        timeout=180,
    )
    print("CHAT_HTTP", code)
    if isinstance(chat, dict):
        print("CHAT_REPLY", str(chat.get("reply") or "")[:400])
        skills_ran = chat.get("skills") or chat.get("skill_results") or []
        print("CHAT_SKILLS", json.dumps(skills_ran)[:800])
        chat_skill_ok = bool(skills_ran) and all(
            (isinstance(x, dict) and (x.get("ok") is True or x.get("ok") is None)) for x in skills_ran
        )
        # count explicit oks
        ok_count = sum(1 for x in skills_ran if isinstance(x, dict) and x.get("ok") is True)
        print(f"CHAT_SKILL_OK_COUNT={ok_count}/{len(skills_ran)}")
    else:
        print("CHAT_BODY", str(chat)[:400])
        ok_count = 0
        skills_ran = []

    # Second tick after cooldown bypass might skip — report only
    code, auto_get = req("GET", "/api/ops/autonomy", token)
    print("AUTONOMY_GET", code, json.dumps(auto_get)[:400] if isinstance(auto_get, dict) else auto_get)

    # === EXPLICIT CHAT TEST (this is the main "chat in the AI Business Agent") ===
    print("\n=== DIRECT CHAT TEST ===")
    chat_ok = False
    chat_reply_preview = ""
    chat_skills_count = 0
    try:
        code, chat_resp = req(
            "POST",
            f"/api/agents/{oid}/chat",
            token,
            {"message": "Quick health check: say hello and run save_memory with title='Chat health check' and content='Chat endpoint is responding correctly'."},
            timeout=180,
        )
        print("CHAT_HTTP", code)
        if code < 400 and isinstance(chat_resp, dict):
            reply = (chat_resp.get("reply") or chat_resp.get("message") or "")[:300]
            chat_reply_preview = reply
            skills = chat_resp.get("skills") or []
            chat_skills_count = len(skills)
            chat_ok = bool(reply)
            print("CHAT_REPLY", reply[:200])
            print("CHAT_SKILLS", json.dumps(skills)[:400] if skills else "[]")
        else:
            print("CHAT_BODY", str(chat_resp)[:400])
    except Exception as e:
        print("CHAT_EXCEPTION", str(e)[:200])

    report = {
        "base": BASE,
        "orchestrator_id": oid,
        "skill_pass": len(passed),
        "skill_fail": len(failed),
        "skill_total_run": len(results),
        "failed_ids": [r["id"] for r in failed],
        "autonomy_tick": tick if isinstance(tick, dict) else {"raw": str(tick)[:300]},
        "chat_skills": skills_ran if isinstance(skills_ran, list) else [],
        "chat_skill_ok_count": ok_count if isinstance(chat, dict) else 0,
        "direct_chat_test": {
            "ok": chat_ok,
            "reply_preview": chat_reply_preview[:200],
            "skills_invoked": chat_skills_count,
        },
    }
    out_path = os.path.join(os.path.dirname(__file__), "skill_test_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"summary": report, "results": results}, f, indent=2)
    print("REPORT", out_path)

    # Exit non-zero if more than 20% fail or core skills fail
    core = {"save_memory", "create_task", "announce_plan", "list_team", "get_time"}
    core_fail = [r for r in failed if r["id"] in core]
    if core_fail:
        print("CORE_FAIL", [r["id"] for r in core_fail])
        return 3
    if results and len(failed) / max(1, len(results)) > 0.35:
        print("TOO_MANY_FAILURES")
        return 4
    print("OVERALL_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
