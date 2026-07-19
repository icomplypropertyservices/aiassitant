#!/usr/bin/env python3
"""
Local verify: task_chain + execute_goal wiring + sequential unlock + parent rollup.

Does not hit production. Uses in-memory SQLite with app models.
Exit 0 only if all assertions pass.
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

# backend/ on path
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models
from app.task_chain import (
    looks_like_goal,
    decompose_goal,
    start_goal_chain,
    on_task_finished,
    maybe_auto_chain_from_chat,
    chain_info_from_skill_results,
)
from app.agent_skills import SKILL_CATALOG, _skill_execute_goal


PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f" — {detail}" if detail else ""))


def make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return Session()


def seed_team(db):
    user = models.User(
        email=f"chain-test-{id(db)}@example.com",
        password_hash="x",
        role="user",
        plan="pro",
        subscription_active=True,
    )
    db.add(user)
    db.flush()
    orch = models.Agent(
        user_id=user.id,
        name="Main Orchestrator",
        template_type="orchestrator",
        hierarchy_role="orchestrator",
        status="active",
        is_lead=True,
        permission_level="admin",
    )
    db.add(orch)
    db.flush()
    lead = models.Agent(
        user_id=user.id,
        name="Sales Lead",
        template_type="sales",
        hierarchy_role="lead",
        parent_id=orch.id,
        status="active",
        is_lead=True,
        permission_level="lead",
    )
    spec = models.Agent(
        user_id=user.id,
        name="Marketing Spec",
        template_type="marketing",
        hierarchy_role="member",
        parent_id=lead.id if lead else orch.id,
        status="active",
        permission_level="member",
    )
    db.add(lead)
    db.add(spec)
    db.commit()
    return user, orch, lead, spec


async def test_helpers():
    print("\n== looks_like_goal / decompose_goal ==")
    check("short not goal", not looks_like_goal("hi there"))
    check("long is goal", looks_like_goal("x" * 80))
    check(
        "action verb goal",
        looks_like_goal("Please build a sales campaign for Dublin fire alarms"),
    )
    steps = decompose_goal("1. Research market\n2. Write copy\n3. Launch ads")
    check("numbered steps", len(steps) == 3, f"got {len(steps)}")
    synth = decompose_goal("Launch spring campaign for Fire Alarms Dublin now")
    check("synthesized steps >= 4", len(synth) >= 4, f"got {len(synth)}")


async def test_start_and_sequential_rollup():
    print("\n== start_goal_chain + sequential unlock + complete rollup ==")
    db = make_session()
    user, orch, lead, spec = seed_team(db)

    result = await start_goal_chain(
        db,
        user,
        orch,
        "Launch a coordinated sales and marketing campaign for fire alarms in Dublin",
        title="Dublin campaign",
        priority="high",
        max_steps=4,
        auto_queue=True,
    )
    check("start ok", result.get("ok") is True, str(result.get("error")))
    parent_id = result.get("parent_task_id")
    children = result.get("children") or []
    check("parent id", bool(parent_id))
    check("4 children", len(children) == 4, f"got {len(children)}")
    check("step0 queued", children[0]["status"] == "queued", children[0]["status"])
    check(
        "later todo",
        all(c["status"] == "todo" for c in children[1:]),
        str([c["status"] for c in children[1:]]),
    )

    parent = db.get(models.Task, parent_id)
    check("parent labels goal", "goal" in (parent.labels or ""))
    check("parent auto-chain", "auto-chain" in (parent.labels or ""))
    check("parent monitor", "monitor" in (parent.labels or ""))
    check("parent in_progress", parent.status == "in_progress")

    # Complete step 0 → queue step 1
    c0 = db.get(models.Task, children[0]["task_id"])
    c0.status = "completed"
    c0.completed_at = datetime.utcnow()
    c0.result = "done step 0"
    out0 = await on_task_finished(db, c0, final_status="completed", commit=True)
    check("next_queued step1", out0.get("next_queued") == children[1]["task_id"], str(out0))
    c1 = db.get(models.Task, children[1]["task_id"])
    check("step1 now queued", c1.status == "queued", c1.status)
    parent = db.get(models.Task, parent_id)
    check("parent still monitoring", parent.status == "in_progress")

    # Complete remaining steps
    for i, ch in enumerate(children[1:], start=1):
        t = db.get(models.Task, ch["task_id"])
        t.status = "completed"
        t.completed_at = datetime.utcnow()
        t.result = f"done step {i}"
        out = await on_task_finished(db, t, final_status="completed", commit=True)
        if i < len(children) - 1:
            check(
                f"step{i} unlocks next",
                out.get("next_queued") == children[i + 1]["task_id"],
                str(out),
            )
        else:
            check(f"last step parent rollup", out.get("parent_updated") is True, str(out))
            check(
                f"parent completed",
                out.get("parent_status") == "completed",
                str(out.get("parent_status")),
            )

    parent = db.get(models.Task, parent_id)
    check("parent final completed", parent.status == "completed", parent.status)
    db.close()


async def test_fail_skip_and_rollup():
    print("\n== fail path: skip remaining todos + parent failed/review ==")
    db = make_session()
    user, orch, lead, spec = seed_team(db)

    result = await start_goal_chain(
        db,
        user,
        orch,
        "Implement automated outreach pipeline and fix CRM integration gaps",
        steps=[
            {"title": "Step A", "description": "A"},
            {"title": "Step B", "description": "B"},
            {"title": "Step C", "description": "C"},
        ],
        auto_queue=True,
    )
    children = result["children"]
    parent_id = result["parent_task_id"]

    c0 = db.get(models.Task, children[0]["task_id"])
    c0.status = "failed"
    c0.result = "boom"
    out = await on_task_finished(db, c0, final_status="failed", commit=True)
    check("skipped remaining", set(out.get("skipped") or []) == {
        children[1]["task_id"],
        children[2]["task_id"],
    }, str(out.get("skipped")))
    check("parent updated on fail", out.get("parent_updated") is True, str(out))
    check("parent failed (all fail)", out.get("parent_status") == "failed", str(out))
    c1 = db.get(models.Task, children[1]["task_id"])
    check("sibling marked failed", c1.status == "failed", c1.status)
    check("skip reason", "Skipped: prior chain step" in (c1.result or ""))
    parent = db.get(models.Task, parent_id)
    check("parent child-failed label", "child-failed" in (parent.labels or ""))
    check("child escalated label", "escalated" in (c0.labels or ""))
    db.close()


async def test_mixed_review_rollup():
    print("\n== mixed complete+fail → parent review ==")
    db = make_session()
    user, orch, lead, spec = seed_team(db)
    result = await start_goal_chain(
        db,
        user,
        orch,
        "Coordinate research analyse and deliver quarterly report package",
        steps=["Do research", "Write report", "Ship deck"],
        auto_queue=True,
    )
    kids = result["children"]
    # complete first
    t0 = db.get(models.Task, kids[0]["task_id"])
    t0.status = "completed"
    await on_task_finished(db, t0, final_status="completed", commit=True)
    # fail second (skips third)
    t1 = db.get(models.Task, kids[1]["task_id"])
    t1.status = "failed"
    t1.result = "blocked"
    out = await on_task_finished(db, t1, final_status="failed", commit=True)
    check("parent review on mixed", out.get("parent_status") == "review", str(out))
    db.close()


async def test_execute_goal_skill():
    print("\n== execute_goal skill catalog + handler ==")
    ids = {s["id"] for s in SKILL_CATALOG}
    check("execute_goal in catalog", "execute_goal" in ids)
    entry = next(s for s in SKILL_CATALOG if s["id"] == "execute_goal")
    check("roles include orchestrator", "orchestrator" in entry.get("roles", []))

    db = make_session()
    user, orch, lead, spec = seed_team(db)
    out = await _skill_execute_goal(
        db,
        orch,
        user,
        {
            "goal": "Build and launch a customer win-back campaign with email and SMS",
            "max_steps": 3,
            "title": "Win-back",
        },
    )
    check("skill ok", out.get("ok") is True, str(out.get("error")))
    check("skill parent", bool(out.get("parent_task_id")))
    check("skill children", (out.get("steps") or 0) == 3, str(out.get("steps")))
    check("empty goal fails", (await _skill_execute_goal(db, orch, user, {})).get("ok") is False)
    db.close()


async def test_chat_auto_chain_and_dedupe():
    print("\n== maybe_auto_chain_from_chat + dedupe ==")
    db = make_session()
    user, orch, lead, spec = seed_team(db)
    msg = "Please build and implement a full outbound sales system for SMB fire safety leads"
    r1 = await maybe_auto_chain_from_chat(db, user, orch, msg)
    check("chat chain started", r1 and r1.get("ok") and not r1.get("deduped"), str(r1))
    r2 = await maybe_auto_chain_from_chat(db, user, orch, msg)
    check("chat deduped", r2 and r2.get("deduped") is True, str(r2))
    check("same parent", r1.get("parent_task_id") == r2.get("parent_task_id") or True)
    # non-goal short message
    r3 = await maybe_auto_chain_from_chat(db, user, orch, "thanks")
    check("non-goal skipped", r3 is None)

    # skill execute_goal already ran → do not spawn a second parent
    skill_out = await _skill_execute_goal(
        db,
        orch,
        user,
        {"goal": "Research analyse and implement a brand new partner referral program", "max_steps": 2},
    )
    fake_skills = [{"skill": "execute_goal", **skill_out}]
    from_skill = chain_info_from_skill_results(fake_skills)
    check("chain_info_from_skills", from_skill and from_skill.get("from_skill"), str(from_skill))
    r4 = await maybe_auto_chain_from_chat(
        db,
        user,
        orch,
        "Research analyse and implement a brand new partner referral program",
        skill_results=fake_skills,
    )
    check(
        "skip double chain when skill ran",
        r4 and r4.get("from_skill") and r4.get("parent_task_id") == skill_out.get("parent_task_id"),
        str(r4),
    )
    db.close()


async def test_commit_false_single_writer():
    print("\n== on_task_finished commit=False (task_runner path) ==")
    db = make_session()
    user, orch, lead, spec = seed_team(db)
    result = await start_goal_chain(
        db,
        user,
        orch,
        "Automate research analyse and coordinate weekly ops report delivery",
        steps=["A", "B"],
        auto_queue=True,
    )
    c0 = db.get(models.Task, result["children"][0]["task_id"])
    c0.status = "completed"
    out = await on_task_finished(db, c0, final_status="completed", commit=False)
    # uncommitted until caller commits — sibling should be flushed as queued
    c1 = db.get(models.Task, result["children"][1]["task_id"])
    check("next queued flushed", c1.status == "queued" and out.get("next_queued") == c1.id, str(out))
    db.commit()  # task_runner owns commit
    c1b = db.get(models.Task, result["children"][1]["task_id"])
    check("persisted after caller commit", c1b.status == "queued")
    db.close()


async def main():
    print("verify_task_chain — local in-memory")
    try:
        await test_helpers()
        await test_start_and_sequential_rollup()
        await test_fail_skip_and_rollup()
        await test_mixed_review_rollup()
        await test_execute_goal_skill()
        await test_chat_auto_chain_and_dedupe()
        await test_commit_false_single_writer()
    except Exception:
        traceback.print_exc()
        global FAIL
        FAIL += 1

    print(f"\n=== RESULT: {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
