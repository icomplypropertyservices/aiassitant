"""
Self-running workspace engine.

Each tick (local background loop or HTTP /ops/autonomy/tick):
  1. Ensure main orchestrator exists
  2. Run queued tasks for active agents with execute permission
  3. Escalate stuck / failed / high-priority work per agent+human policies
  4. Give never_idle agents useful work when idle
  5. Broadcast live ops summary
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .database import SessionLocal
from .permissions import (
    can_execute,
    normalize_escalate_to,
    normalize_escalate_when,
    normalize_permission,
)
from .live_ops import emit_ops
from .agent_hierarchy import ensure_main_orchestrator
from .agent_roles import find_orchestrator, is_orchestrator


def get_or_create_settings(db: Session, user_id: int) -> models.WorkspaceSettings:
    row = db.query(models.WorkspaceSettings).filter_by(user_id=user_id).first()
    if row:
        return row
    row = models.WorkspaceSettings(
        user_id=user_id,
        # Default on, but interval is long so RunPod is not hammered
        autonomy_enabled=True,
        autonomy_interval_sec=300,
        task_stuck_minutes=30,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def settings_out(row: models.WorkspaceSettings) -> dict:
    return {
        "user_id": row.user_id,
        "autonomy_enabled": bool(row.autonomy_enabled),
        "autonomy_interval_sec": row.autonomy_interval_sec or 300,
        "task_stuck_minutes": row.task_stuck_minutes or 30,
        "last_autonomy_run": row.last_autonomy_run,
        "last_autonomy_summary": row.last_autonomy_summary or "",
        "policy": json.loads(row.policy_json or "{}"),
    }


async def escalate_task(
    db: Session,
    task: models.Task,
    *,
    reason_code: str,
    reason_text: str,
    from_agent: models.Agent | None = None,
    from_human: models.Human | None = None,
) -> models.EscalationLog | None:
    """Create escalation and re-route task when possible."""
    user_id = task.user_id
    to_agent_id = None
    to_human_id = None

    agent = from_agent or (db.get(models.Agent, task.agent_id) if task.agent_id else None)
    human = from_human or (db.get(models.Human, task.human_id) if getattr(task, "human_id", None) else None)

    policy_when = "on_failure"
    policy_to = "parent"
    escalate_human_id = None
    if agent:
        policy_when = normalize_escalate_when(getattr(agent, "escalate_when", None))
        policy_to = normalize_escalate_to(getattr(agent, "escalate_to", None))
        escalate_human_id = getattr(agent, "escalate_human_id", None)
        if policy_when == "never" and reason_code not in ("custom", "manual"):
            return None
    elif human:
        policy_when = normalize_escalate_when(getattr(human, "escalate_when", None))
        policy_to = normalize_escalate_to(getattr(human, "escalate_to", None))

    # Resolve target
    if policy_to == "parent" and agent and agent.parent_id:
        to_agent_id = agent.parent_id
    elif policy_to == "orchestrator" or (policy_to == "parent" and agent and not agent.parent_id):
        orch = find_orchestrator(db, user_id)
        if orch and (not agent or orch.id != agent.id):
            to_agent_id = orch.id
    elif policy_to == "human":
        to_human_id = escalate_human_id or (human.id if human else None)
        if not to_human_id:
            # first active human with lead/admin permission
            h = (
                db.query(models.Human)
                .filter_by(owner_user_id=user_id, status="active")
                .order_by(models.Human.id)
                .first()
            )
            if h:
                to_human_id = h.id
    # owner = leave assigned but log for banner

    log = models.EscalationLog(
        user_id=user_id,
        task_id=task.id,
        from_agent_id=agent.id if agent else None,
        from_human_id=human.id if human else None,
        to_agent_id=to_agent_id,
        to_human_id=to_human_id,
        reason_code=reason_code,
        reason_text=reason_text[:2000],
        status="open",
    )
    db.add(log)

    # Reassign open work
    if to_agent_id:
        task.agent_id = to_agent_id
        task.assignee_type = "agent"
        task.status = "queued" if task.status in ("failed", "in_progress", "todo") else task.status
        task.labels = ((task.labels or "") + ",escalated").strip(",")
    elif to_human_id:
        task.human_id = to_human_id
        task.assignee_type = "human"
        task.status = "todo"
        task.labels = ((task.labels or "") + ",escalated").strip(",")

    db.commit()
    db.refresh(log)

    await emit_ops(
        user_id,
        kind="system",
        status="failed" if reason_code in ("failure", "on_failure") else "info",
        title=f"Escalated: {(task.title or task.description or '')[:80]}",
        detail=f"{reason_code}: {reason_text[:200]}",
        agent_id=to_agent_id or (agent.id if agent else None),
        human_id=to_human_id,
        task_id=task.id,
        payload={"escalation_id": log.id, "reason_code": reason_code},
        db=db,
    )
    return log


def should_escalate_for_policy(when: str, *, reason_code: str, priority: str = "medium") -> bool:
    when = normalize_escalate_when(when)
    if when == "never":
        return False
    if when == "always_review":
        return reason_code in ("review", "always_review", "completed")
    if when == "on_failure":
        return reason_code in ("failure", "on_failure", "failed")
    if when == "on_blocked":
        return reason_code in ("blocked", "on_blocked", "permission")
    if when == "high_priority":
        return (priority or "").lower() in ("high", "urgent") or reason_code == "high_priority"
    if when == "sla_breach":
        return reason_code in ("sla_breach", "stuck", "sla")
    if when == "customer_vip":
        return reason_code in ("customer_vip", "vip")
    if when == "value_threshold":
        return reason_code in ("value_threshold", "value")
    if when == "custom":
        return True
    return False


async def _run_queued_tasks(db: Session, user: models.User, summary: dict) -> None:
    from .task_runner import run_agent_task
    from .async_jobs import schedule
    from .agent_scaffold import resolve_runtime

    from . import config as app_config

    max_tasks = int(getattr(app_config, "AUTONOMY_MAX_TASKS_PER_TICK", 1) or 1)
    queued = (
        db.query(models.Task)
        .filter(
            models.Task.user_id == user.id,
            models.Task.status == "queued",
            models.Task.agent_id.isnot(None),
        )
        .order_by(models.Task.id)
        .limit(max(1, max_tasks))
        .all()
    )
    for t in queued:
        agent = db.get(models.Agent, t.agent_id)
        if not agent:
            continue
        rt = resolve_runtime(agent)
        if not rt.can_execute:
            if should_escalate_for_policy(
                getattr(agent, "escalate_when", None) or "on_blocked",
                reason_code="permission",
                priority=t.priority or "medium",
            ):
                await escalate_task(
                    db, t,
                    reason_code="permission",
                    reason_text=f"Agent {agent.name} cannot execute ({rt.permission_level}/{rt.status})",
                    from_agent=agent,
                )
                summary["escalated"] += 1
            continue
        summary["tasks_started"] += 1
        await emit_ops(
            user.id, kind="action", status="running",
            title="Autonomy running task",
            detail=(t.title or t.description or "")[:160],
            agent_id=agent.id, task_id=t.id, db=db,
        )
        await schedule(run_agent_task(agent.id, user.id, t.id, t.description, agent.name))


async def _check_stuck_and_failed(db: Session, user: models.User, settings: models.WorkspaceSettings, summary: dict) -> None:
    stuck_mins = max(5, int(settings.task_stuck_minutes or 30))
    cutoff = datetime.utcnow() - timedelta(minutes=stuck_mins)

    stuck = (
        db.query(models.Task)
        .filter(
            models.Task.user_id == user.id,
            models.Task.status == "in_progress",
        )
        .limit(20)
        .all()
    )
    for t in stuck:
        updated = getattr(t, "updated_at", None) or t.created_at
        if updated and updated > cutoff:
            continue
        agent = db.get(models.Agent, t.agent_id) if t.agent_id else None
        when = getattr(agent, "escalate_when", None) if agent else "sla_breach"
        if agent and not should_escalate_for_policy(when, reason_code="sla_breach", priority=t.priority or "medium"):
            # still escalate if policy is sla_breach or on_blocked
            if normalize_escalate_when(when) not in ("sla_breach", "on_blocked", "on_failure", "custom", "high_priority"):
                continue
        await escalate_task(
            db, t,
            reason_code="sla_breach",
            reason_text=f"Stuck in progress > {stuck_mins} minutes",
            from_agent=agent,
        )
        summary["escalated"] += 1

    failed = (
        db.query(models.Task)
        .filter(models.Task.user_id == user.id, models.Task.status == "failed")
        .order_by(models.Task.id.desc())
        .limit(10)
        .all()
    )
    for t in failed:
        # Only escalate once (label marker)
        labels = (t.labels or "")
        if "escalated" in labels:
            continue
        agent = db.get(models.Agent, t.agent_id) if t.agent_id else None
        when = getattr(agent, "escalate_when", None) if agent else "on_failure"
        if agent and not should_escalate_for_policy(when, reason_code="failure", priority=t.priority or "medium"):
            continue
        await escalate_task(
            db, t,
            reason_code="failure",
            reason_text=(t.result or "Task failed")[:500],
            from_agent=agent,
        )
        summary["escalated"] += 1

    # High priority todos unassigned / waiting
    hot = (
        db.query(models.Task)
        .filter(
            models.Task.user_id == user.id,
            models.Task.status.in_(("todo", "queued")),
            models.Task.priority.in_(("high", "urgent")),
        )
        .limit(10)
        .all()
    )
    for t in hot:
        if "escalated" in (t.labels or ""):
            continue
        agent = db.get(models.Agent, t.agent_id) if t.agent_id else None
        when = getattr(agent, "escalate_when", None) if agent else "high_priority"
        if agent and normalize_escalate_when(when) not in ("high_priority", "always_review", "custom"):
            continue
        if not agent:
            continue
        await escalate_task(
            db, t,
            reason_code="high_priority",
            reason_text=f"High priority work needs attention: {t.priority}",
            from_agent=agent,
        )
        summary["escalated"] += 1


async def _feed_never_idle(db: Session, user: models.User, summary: dict) -> None:
    """
    Give up to N never_idle agents proactive work when they have no open tasks.
    Prefer orchestrator → leads → others. Does not mutate idle_mode/permissions.
    Hard-capped to protect RunPod GPU (default 1 feed / tick).
    """
    from . import config as app_config
    from .agent_roles import agent_sort_key
    from .agent_scaffold import resolve_runtime

    max_feeds = int(getattr(app_config, "AUTONOMY_MAX_IDLE_FEEDS", 1) or 0)
    if max_feeds <= 0:
        return

    agents = (
        db.query(models.Agent)
        .filter_by(user_id=user.id, status="active", idle_mode="never_idle")
        .all()
    )
    agents = sorted(agents, key=agent_sort_key)

    fed = 0
    for a in agents:
        if fed >= max_feeds:
            break
        rt = resolve_runtime(a)
        if not rt.can_execute:
            continue
        open_n = (
            db.query(models.Task)
            .filter(
                models.Task.agent_id == a.id,
                models.Task.status.in_(("todo", "queued", "in_progress", "review")),
            )
            .count()
        )
        if open_n > 0:
            continue

        role = rt.hierarchy_role
        title = f"Autonomy cycle · {a.name}"
        desc = (
            f"You are {a.name} ({role}), running autonomously.\n"
            f"1) Review your scope (company/project if set).\n"
            f"2) List top 3 concrete actions for the business today.\n"
            f"3) Use free skills when useful (save_memory, create_task, list_customers, "
            f"generate_content, draft_email). Do NOT use paid send/call/image skills "
            f"unless essential and already enabled.\n"
            f"4) Be concise. Escalate only if blocked.\n"
        )
        t = models.Task(
            user_id=user.id,
            agent_id=a.id,
            company_id=a.company_id,
            project_id=a.project_id,
            title=title,
            description=desc,
            status="queued",
            priority="low",
            labels="autonomy,self-run",
            assignee_type="agent",
        )
        db.add(t)
        db.commit()
        fed += 1
        summary["idle_tasks"] += 1
        await emit_ops(
            user.id, kind="action", status="queued",
            title=f"{a.name} autonomy task",
            detail="Idle never_idle agent assigned capped self-run",
            agent_id=a.id, task_id=t.id, db=db,
        )


async def run_user_cycle(db: Session, user: models.User) -> dict[str, Any]:
    from . import config as app_config

    settings = get_or_create_settings(db, user.id)
    summary = {
        "user_id": user.id,
        "tasks_started": 0,
        "escalated": 0,
        "idle_tasks": 0,
        "skipped": False,
        "reason": "",
    }
    if not settings.autonomy_enabled:
        summary["skipped"] = True
        summary["reason"] = "autonomy_disabled"
        return summary

    # Respect min interval so rapid UI ticks / cron overlaps do not flood the GPU
    min_iv = int(getattr(app_config, "AUTONOMY_MIN_INTERVAL_SEC", 300) or 300)
    user_iv = max(min_iv, int(settings.autonomy_interval_sec or min_iv))
    last = settings.last_autonomy_run
    if last and (datetime.utcnow() - last) < timedelta(seconds=user_iv):
        summary["skipped"] = True
        summary["reason"] = f"cooldown_{user_iv}s"
        return summary

    # Ensure orchestrator exists only — do NOT rewrite every agent each tick
    try:
        ensure_main_orchestrator(db, user)
    except Exception as e:
        summary["reason"] = f"orchestrator_error:{e}"

    await _check_stuck_and_failed(db, user, settings, summary)
    await _feed_never_idle(db, user, summary)
    await _run_queued_tasks(db, user, summary)

    settings.last_autonomy_run = datetime.utcnow()
    settings.last_autonomy_summary = (
        f"started={summary['tasks_started']} escalated={summary['escalated']} "
        f"idle_tasks={summary['idle_tasks']}"
    )
    settings.updated_at = datetime.utcnow()
    db.commit()

    await emit_ops(
        user.id,
        kind="system",
        status="done",
        title="Autonomy cycle complete",
        detail=settings.last_autonomy_summary,
        db=db,
    )
    return summary


async def run_global_tick() -> dict[str, Any]:
    """One tick across all eligible users (local loop or cron)."""
    db = SessionLocal()
    results = []
    try:
        users = (
            db.query(models.User)
            .filter(
                (models.User.subscription_active == True)  # noqa: E712
                | (models.User.role == "admin")
                | (models.User.plan.notin_(["none", ""]))
            )
            .all()
        )
        # Also include users with agents even if plan oddities
        if not users:
            users = db.query(models.User).limit(50).all()
        for u in users:
            try:
                # refresh settings attachment
                u = db.get(models.User, u.id)
                r = await run_user_cycle(db, u)
                results.append(r)
            except Exception as e:
                results.append({"user_id": u.id, "error": str(e)})
        return {
            "ok": True,
            "users": len(results),
            "results": results,
            "at": datetime.utcnow().isoformat() + "Z",
        }
    finally:
        db.close()


async def autonomy_background_loop():
    """Local long-running loop (disabled on Vercel)."""
    import asyncio
    while True:
        try:
            db = SessionLocal()
            try:
                # Use min interval among enabled workspaces, default 45s
                rows = db.query(models.WorkspaceSettings).filter_by(autonomy_enabled=True).all()
                interval = 45
                if rows:
                    interval = min(max(15, r.autonomy_interval_sec or 45) for r in rows)
            finally:
                db.close()
            await run_global_tick()
            await asyncio.sleep(interval)
        except Exception:
            await asyncio.sleep(60)
