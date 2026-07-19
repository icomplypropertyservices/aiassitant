"""Local end-to-end skill smoke (no network premium side-effects)."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal, engine, Base  # noqa: E402
from app import models  # noqa: E402
from app.schema_migrate import ensure_schema  # noqa: E402
from app.agent_skills import execute_skill, set_enabled_skills, SKILL_CATALOG  # noqa: E402


def _ensure_user(db):
    user = db.query(models.User).filter_by(email="skilltest@local.dev").first()
    if not user:
        kwargs = dict(
            email="skilltest@local.dev",
            name="Skill Test",
            role="user",
            plan="professional",
            subscription_active=True,
        )
        user = models.User(**kwargs)
        if hasattr(user, "password_hash"):
            user.password_hash = "x"
        if hasattr(user, "hashed_password"):
            user.hashed_password = "x"
        db.add(user)
        db.commit()
        db.refresh(user)

    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal:
        bal = models.Balance(user_id=user.id)
        db.add(bal)
        db.commit()
        db.refresh(bal)
    for attr, val in (
        ("credits", 100.0),
        ("tokens_included", 1_000_000),
        ("tokens_used_period", 0),
    ):
        if hasattr(bal, attr):
            setattr(bal, attr, val)
    db.commit()
    return user


async def main() -> int:
    ensure_schema(engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = _ensure_user(db)
        orch = (
            db.query(models.Agent)
            .filter_by(user_id=user.id, hierarchy_role="orchestrator")
            .first()
        )
        if not orch:
            orch = models.Agent(
                user_id=user.id,
                name="Test Orchestrator",
                hierarchy_role="orchestrator",
                is_lead=True,
                template_type="orchestrator",
                status="active",
                idle_mode="never_idle",
                permission_level="admin",
                model="fast",
                personality="Test orchestrator",
            )
            db.add(orch)
            db.commit()
            db.refresh(orch)

        core = [
            "spawn_agent",
            "message_agent",
            "save_memory",
            "create_task",
            "announce_plan",
            "list_customers",
            "get_customer",
            "update_customer",
            "log_customer_activity",
            "create_deal",
            "schedule_meeting",
            "list_diary",
            "list_team",
            "list_tasks",
            "get_time",
            "summarize",
            "research",
            "draft_email",
            "use_app",
            "assign_human",
            "status_update",
            "execute_goal",
            "clone_agent",
            "spawn_specialist",
            "qualify_lead",
        ]
        set_enabled_skills(db, orch, core + [s["id"] for s in SKILL_CATALOG[:80]])

        cust = (
            db.query(models.Customer)
            .filter_by(owner_user_id=user.id, email="cust@test.local")
            .first()
        )
        if not cust:
            cust = models.Customer(
                owner_user_id=user.id,
                name="ACME Test",
                email="cust@test.local",
                status="active",
                phone="+10000000000",
            )
            db.add(cust)
            db.commit()
            db.refresh(cust)

        human = db.query(models.Human).filter_by(owner_user_id=user.id).first()
        if not human:
            human = models.Human(
                owner_user_id=user.id,
                name="My Human",
                email="human@test.local",
                status="active",
                is_my_human=True,
            )
            db.add(human)
            db.commit()
            db.refresh(human)

        member = (
            db.query(models.Agent)
            .filter_by(user_id=user.id, name="Skill Peer")
            .first()
        )
        if not member:
            member = models.Agent(
                user_id=user.id,
                name="Skill Peer",
                hierarchy_role="member",
                parent_id=orch.id,
                status="active",
                idle_mode="never_idle",
                permission_level="operator",
                model="fast",
                personality="Peer",
                template_type="sales",
            )
            db.add(member)
            db.commit()
            db.refresh(member)

        tests = [
            ("get_time", {}),
            ("list_customers", {"limit": 5}),
            ("get_customer", {"customer_id": cust.id}),
            ("update_customer", {"customer_id": cust.id, "notes": "skill smoke note"}),
            (
                "log_customer_activity",
                {"customer_id": cust.id, "title": "Smoke log", "body": "ok"},
            ),
            (
                "create_deal",
                {"customer_id": cust.id, "title": "Smoke deal", "value": 100},
            ),
            (
                "schedule_meeting",
                {
                    "customer_id": cust.id,
                    "title": "Smoke meet",
                    "start_at": (datetime.utcnow() + timedelta(days=1)).isoformat(),
                },
            ),
            ("list_diary", {"limit": 5}),
            ("save_memory", {"title": "mem", "content": "hello", "kind": "note"}),
            (
                "create_task",
                {
                    "title": "Smoke task",
                    "description": "from skill test",
                    "run_now": False,
                },
            ),
            ("announce_plan", {"title": "Smoke plan", "steps": ["A", "B"]}),
            (
                "message_agent",
                {
                    "to_agent_id": member.id,
                    "message": "ping from smoke",
                    "expect_reply": False,
                },
            ),
            (
                "assign_human",
                {"title": "Human smoke task", "description": "please review"},
            ),
            (
                "summarize",
                {
                    "text": "Fire alarms need annual service. Dublin SMEs need BS 5839 compliance."
                },
            ),
            ("research", {"topic": "fire alarm servicing Ireland"}),
            ("draft_email", {"to": "a@b.com", "subject": "Hi", "goal": "intro"}),
            ("use_app", {"app_id": "1", "action": "status"}),
            ("use_app", {"app_id": "gmail", "action": "status"}),
            (
                "spawn_agent",
                {
                    "name": "Smoke Child",
                    "template_type": "sales",
                    "hierarchy_role": "member",
                },
            ),
            ("list_team", {}),
            (
                "status_update",
                {
                    "project": "Smoke",
                    "highlights": "all green",
                    "status": "green",
                    "notify": False,
                },
            ),
            ("qualify_lead", {"lead": "ACME", "notes": "warm inbound"}),
            ("list_tasks", {"limit": 5}),
        ]

        results = []
        for sid, args in tests:
            try:
                r = await execute_skill(db, orch, user, sid, args)
                ok = bool(r.get("ok")) and not r.get("error")
                err = r.get("error") or ""
                # Expected soft-fails (clearer errors, not crashes)
                if sid == "use_app" and (
                    "connection id" in err
                    or "No connected" in err
                    or "Connect " in err
                    or "Unknown app" in err
                ):
                    # Soft-fail is correct without a live integration connection
                    ok = True
                    err = f"(expected) {err}"
                results.append(
                    {
                        "id": sid,
                        "ok": ok,
                        "error": err or None,
                        "message": (r.get("message") or "")[:100],
                    }
                )
                print(
                    ("PASS" if ok else "FAIL"),
                    sid,
                    "->",
                    (err or r.get("message") or "")[:120],
                )
            except Exception as e:
                results.append({"id": sid, "ok": False, "error": str(e)})
                print("EXC", sid, e)

        passed = sum(1 for r in results if r["ok"])
        print("---")
        print(f"pass={passed}/{len(results)}")
        out = ROOT / "scripts" / "skill_smoke_local_report.json"
        # scripts dir may be parent
        out = Path(__file__).resolve().parent / "skill_smoke_local_report.json"
        out.write_text(json.dumps({"pass": passed, "total": len(results), "results": results}, indent=2), encoding="utf-8")
        print("wrote", out)
        return 0 if passed == len(results) else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
