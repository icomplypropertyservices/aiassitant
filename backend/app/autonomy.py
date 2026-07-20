"""
Self-running workspace engine.

Each tick (local background loop or HTTP /ops/autonomy/tick):
  1. Ensure main orchestrator exists
  2. Run queued tasks for active agents with execute permission
  3. Escalate stuck / failed / high-priority work per agent+human policies
  4. Give never_idle agents useful work when idle (capped CRM/workflow invent)
  5. Broadcast live ops summary + health signals

Fail-smart reliability:
  - Terminal provider failures (credits, spending limit, 403/permission,
    LLM unavailable) are NEVER requeued — marked failed + labeled.
  - never_idle self-run invent is hard-capped (AUTONOMY_MAX_IDLE_FEEDS ≤ 2)
    and soft-skipped when recent LLM/credits failures dominate.
  - Close-skill / chain rollup leaves no open zombies on fail-fast paths.

CRON / offline production:
  - Vercel: GET /api/ops/autonomy/tick-all (see root vercel.json schedule
    `0 6 * * *` plus external keep-alive every ~5m).
  - Auth: Authorization: Bearer <CRON_SECRET> or X-Cron-Secret header
    (same CRON_SECRET env as Vercel Project → Environment Variables).
  - Health: run_global_tick() returns health block (queued, terminal fails,
    idle feeds, self_run_skipped). /health exposes autonomy_cron path.
  - No owner browser session required — agents drain queues offline.
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
    requeue: bool = True,
    commit: bool = True,
) -> models.EscalationLog | None:
    """Create escalation and optionally re-route task.

    requeue=True (default): reassign to parent/orchestrator/human and set
    queued/todo so work continues (stuck recovery, autonomy).
    requeue=False: log escalation + mark labels only — keep current status
    (used by task_chain on terminal failed steps so we do not un-fail them).

    commit=True (default): persist here.
    commit=False: flush only so the caller owns the transaction (task_runner /
    on_task_finished single-writer path).
    """
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

    # Always stamp escalated so autonomy failed-scan does not re-fire forever
    labels = task.labels or ""
    if "escalated" not in labels:
        task.labels = (labels + ",escalated").strip(",") if labels else "escalated"

    # Reassign open work only when requeue is requested
    if requeue:
        if to_agent_id:
            task.agent_id = to_agent_id
            task.assignee_type = "agent"
            task.status = "queued" if task.status in ("failed", "in_progress", "todo") else task.status
        elif to_human_id:
            task.human_id = to_human_id
            task.assignee_type = "human"
            task.status = "todo"

    if commit:
        db.commit()
        db.refresh(log)
    else:
        db.flush()

    try:
        await emit_ops(
            user_id,
            kind="system",
            status="failed" if reason_code in ("failure", "on_failure") else "info",
            title=f"Escalated: {(task.title or task.description or '')[:80]}",
            detail=f"{reason_code}: {reason_text[:200]}",
            agent_id=to_agent_id or (agent.id if agent else None),
            human_id=to_human_id,
            task_id=task.id,
            payload={"escalation_id": log.id, "reason_code": reason_code, "requeue": requeue},
            # Private session when caller owns the transaction — emit_ops always commits.
            db=None if not commit else db,
        )
    except Exception as e:
        # Never fail the escalation itself because of ops/banner side effects
        # (e.g. SQLite lock while caller still holds an open write txn).
        log_mod = __import__("logging").getLogger("app.autonomy")
        log_mod.warning("emit_ops on escalate failed: %s", e)
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


async def _promote_assigned_todos(db: Session, user: models.User, summary: dict) -> None:
    """Agent-owned todos (not waiting auto-chain steps) → queued so they actually run."""
    from .agent_scaffold import resolve_runtime

    todos = (
        db.query(models.Task)
        .filter(
            models.Task.user_id == user.id,
            models.Task.status == "todo",
            models.Task.agent_id.isnot(None),
            models.Task.assignee_type == "agent",
        )
        .order_by(models.Task.id)
        .limit(20)
        .all()
    )
    promoted = 0
    for t in todos:
        labels = t.labels or ""
        # Sequential chain steps stay todo until previous step completes
        if "auto-chain" in labels and "step" in labels:
            # Only promote if no sibling in flight and this is the earliest open step
            if t.parent_task_id:
                siblings = (
                    db.query(models.Task)
                    .filter(models.Task.parent_task_id == t.parent_task_id)
                    .order_by(models.Task.id)
                    .all()
                )
                in_flight = any((s.status or "") in ("queued", "in_progress") for s in siblings)
                earlier_todo = any(
                    s.id < t.id and (s.status or "") == "todo" for s in siblings
                )
                if in_flight or earlier_todo:
                    continue
        agent = db.get(models.Agent, t.agent_id)
        if not agent or (agent.status or "") != "active":
            continue
        rt = resolve_runtime(agent)
        if not rt.can_execute:
            continue
        t.status = "queued"
        t.updated_at = datetime.utcnow()
        promoted += 1
    if promoted:
        db.commit()
        summary["todos_promoted"] = summary.get("todos_promoted", 0) + promoted


def _is_terminal_provider_task(task: models.Task) -> bool:
    """True when task failed due to LLM/credits/permission — never requeue."""
    labels = (task.labels or "").lower()
    for tag in (
        "llm_unavailable",
        "credits_exhausted",
        "llm_permission_denied",
        "spending_limit",
    ):
        if tag in labels:
            return True
    result = task.result or ""
    low = result.lower()
    # Explicit result phrases (incl. xAI spending-limit / permission-denied)
    if any(
        p in low
        for p in (
            "spending limit",
            "spending_limit",
            "permission-denied",
            "permission denied",
            "[llm_unavailable]",
            "[credits_exhausted]",
            "[llm_permission_denied]",
            "grok is not available",
            "ai is paused",
            "credit wallet is empty",
        )
    ):
        return True
    try:
        from .llm import is_terminal_llm_failure
        if is_terminal_llm_failure(result):
            return True
    except Exception:
        pass
    return False


def _wallet_hard_blocked(db: Session, user: models.User) -> bool:
    """True when meter hard_block (included tokens exhausted + credits < MIN).

    Admin never hard-blocked. Shared by invent soft-skip + queue soft-skip + health.
    """
    if getattr(user, "role", None) == "admin":
        return False
    try:
        from .usage_billing import meter_snapshot
        return bool(meter_snapshot(db, user).get("hard_block"))
    except Exception:
        return False


def _is_self_run_labels(labels: str | None) -> bool:
    """Labels that mark invent/fluff autonomy work (not auto-chain board steps)."""
    low = (labels or "").lower()
    if "self-run" in low:
        return True
    if "autonomy" in low and "auto-chain" not in low:
        return True
    return False


def _is_claimable_board_task(task: models.Task) -> bool:
    """Unassigned open board work that never_idle may claim (not chain-wait / terminal)."""
    if not task:
        return False
    if task.agent_id is not None:
        return False
    if (task.status or "") not in ("todo", "queued"):
        return False
    labels = (task.labels or "").lower()
    if "chain-skipped" in labels:
        return False
    # Sequential auto-chain steps stay todo until on_task_finished unlocks them
    if "auto-chain" in labels and "step" in labels and (task.status or "") == "todo":
        return False
    if _is_terminal_provider_task(task):
        return False
    return True


def _claim_unassigned_board_task(
    db: Session,
    user: models.User,
    agent: models.Agent,
    *,
    candidates_limit: int = 12,
) -> models.Task | None:
    """
    Prefer real board work over invent. Scans several unassigned rows so a
    terminal/unclaimable first row cannot block the rest (race-tight claim).

    Commits on successful claim. Marks terminal unassigned rows failed.
    """
    rows = (
        db.query(models.Task)
        .filter(
            models.Task.user_id == user.id,
            models.Task.status.in_(("todo", "queued")),
            models.Task.agent_id.is_(None),
        )
        .order_by(models.Task.id.asc())
        .limit(max(1, candidates_limit))
        .all()
    )
    dirty_terminal = False
    for t in rows:
        # Concurrent tick may have claimed between query and loop
        try:
            db.refresh(t)
        except Exception:
            pass
        if t.agent_id is not None:
            continue
        if (t.status or "") not in ("todo", "queued"):
            continue
        if _is_terminal_provider_task(t):
            t.status = "failed"
            t.completed_at = t.completed_at or datetime.utcnow()
            t.updated_at = datetime.utcnow()
            labs = [x.strip() for x in (t.labels or "").split(",") if x.strip()]
            if "llm_unavailable" not in {x.lower() for x in labs}:
                labs.append("llm_unavailable")
            t.labels = ",".join(labs)[:500]
            if not (t.result or "").strip().startswith("["):
                t.result = (
                    f"[LLM_UNAVAILABLE] Unassigned terminal provider failure — not claimed.\n"
                    f"{t.result or ''}"
                )[:12000]
            dirty_terminal = True
            continue
        if not _is_claimable_board_task(t):
            continue
        # Claim
        t.agent_id = agent.id
        t.assignee_type = "agent"
        t.status = "queued"
        t.updated_at = datetime.utcnow()
        if "DONE WHEN:" not in (t.description or "").upper():
            t.description = (
                f"{(t.description or t.title or '').rstrip()}\n\n"
                f"---\nDONE WHEN: Deliver the concrete output for this board item.\n"
                f"Claimed by {agent.name} via autonomy. Call complete_task with evidence."
            )[:8000]
        db.commit()
        try:
            db.refresh(t)
        except Exception:
            pass
        # Lost race if another worker reassigned after our write (rare)
        if t.agent_id != agent.id:
            continue
        return t
    if dirty_terminal:
        try:
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
    return None


def _self_run_soft_skip_state(
    db: Session,
    user: models.User,
    *,
    open_self_runs: int = 0,
    max_feeds: int = 1,
) -> dict[str, Any]:
    """
    All invent/queue soft-skip reasons for self-run fluff.

    Paths (any → skip invent; queue skip uses same wallet/llm flags):
      - credits_hard_block (wallet meter hard_block)
      - recent_llm_failures (terminal provider fails dominate)
      - open_self_run_cap (open self-run backlog ≥ max_feeds)
    Board claims always allowed when skip is only invent-related.
    """
    reasons: list[str] = []
    wallet = _wallet_hard_blocked(db, user)
    if wallet:
        reasons.append("credits_hard_block")
    try:
        if _recent_llm_failures_dominate(db, user.id):
            reasons.append("recent_llm_failures")
    except Exception:
        pass
    if max_feeds > 0 and open_self_runs >= max_feeds:
        reasons.append("open_self_run_cap")
    # Prefer ops-actionable primary: wallet > llm > cap
    primary = None
    for key in ("credits_hard_block", "recent_llm_failures", "open_self_run_cap"):
        if key in reasons:
            primary = key
            break
    return {
        "skip_invent": bool(reasons),
        "skip_queue_self_run": bool(wallet or "recent_llm_failures" in reasons),
        "wallet_hard_block": wallet,
        "reasons": reasons,
        "primary": primary,
    }


async def _requeue_stalled_in_progress(db: Session, user: models.User, summary: dict) -> None:
    """
    Keep agents busy: if a run left a task in_progress without complete_task and
    it has been idle long enough, re-queue so the runner continues until done.

    Never requeues LLM-unavailable / spending-limit / permission-denied tasks.
    """
    from .agent_scaffold import resolve_runtime

    # Short enough that offline cron (every 5m) recovers interrupted serverless runs
    try:
        from .async_jobs import is_serverless
        idle_mins = 3 if is_serverless() else 6
    except Exception:
        idle_mins = 4
    cutoff = datetime.utcnow() - timedelta(minutes=idle_mins)
    rows = (
        db.query(models.Task)
        .filter(
            models.Task.user_id == user.id,
            models.Task.status == "in_progress",
            models.Task.agent_id.isnot(None),
        )
        .order_by(models.Task.id)
        .limit(15)
        .all()
    )
    n = 0
    skipped_terminal = 0
    for t in rows:
        updated = getattr(t, "updated_at", None) or t.created_at
        if updated and updated > cutoff:
            continue
        result = (t.result or "")
        # Terminal provider failures must not re-enter the queue
        if _is_terminal_provider_task(t):
            # Promote to failed so stuck scanners / board show truth
            t.status = "failed"
            t.completed_at = t.completed_at or datetime.utcnow()
            t.updated_at = datetime.utcnow()
            labs = [x.strip() for x in (t.labels or "").split(",") if x.strip()]
            if "llm_unavailable" not in {x.lower() for x in labs}:
                labs.append("llm_unavailable")
                t.labels = ",".join(labs)[:500]
            if not result.strip().startswith("["):
                t.result = (
                    f"[LLM_UNAVAILABLE] Stalled with provider/billing failure — not requeued.\n"
                    f"{result}"
                )[:12000]
            skipped_terminal += 1
            continue
        # Prefer tasks the runner itself left unfinished
        markers = (
            "STILL IN PROGRESS",
            "AUTO-REQUEUE",
            "NEEDS ATTENTION",
            "awaiting_complete",
        )
        if not any(m in result for m in markers) and (t.tokens_used or 0) == 0:
            # Fresh/unknown — still re-queue if truly stale
            if not updated or updated > cutoff:
                continue
        if result.count("[AUTO-REQUEUE]") >= 3:
            continue
        agent = db.get(models.Agent, t.agent_id)
        if not agent or (agent.status or "") != "active":
            continue
        rt = resolve_runtime(agent)
        if not rt.can_execute:
            continue
        t.status = "queued"
        t.updated_at = datetime.utcnow()
        t.result = (
            (result or "").rstrip()
            + f"\n\n[AUTO-REQUEUE] Stalled in_progress >{idle_mins}m — continuing until complete_task."
        )[:12000]
        n += 1
    if n or skipped_terminal:
        db.commit()
        if n:
            summary["stalled_requeued"] = summary.get("stalled_requeued", 0) + n
        if skipped_terminal:
            summary["stalled_terminal_failed"] = (
                summary.get("stalled_terminal_failed", 0) + skipped_terminal
            )


async def _run_queued_tasks(db: Session, user: models.User, summary: dict) -> None:
    from .task_runner import run_agent_task, kick_queued_task
    from .async_jobs import schedule
    from .agent_scaffold import resolve_runtime

    from . import config as app_config

    # First: promote stagnant agent todos into the queue
    try:
        await _promote_assigned_todos(db, user, summary)
    except Exception:
        pass
    # Keep unfinished work moving (busy until complete_task)
    try:
        await _requeue_stalled_in_progress(db, user, summary)
    except Exception:
        pass

    max_tasks = int(getattr(app_config, "AUTONOMY_MAX_TASKS_PER_TICK", 3) or 3)
    # Offline ticks must actually run agent LLM work (owner may not be logged in).
    try:
        from .async_jobs import is_serverless
        offline_budget = 120.0 if is_serverless() else 180.0
        if is_serverless():
            # Stay under Vercel maxDuration while still finishing real work
            max_tasks = min(max_tasks, 4)
    except Exception:
        offline_budget = 120.0

    # Soft-skip invent/fluff runs when wallet hard-blocked or LLM terminal fails dominate.
    # Real board / auto-chain work still drains. Paths share _self_run_soft_skip_state.
    skip_state = _self_run_soft_skip_state(db, user, open_self_runs=0, max_feeds=1)
    soft_skip_self_run = bool(skip_state.get("skip_queue_self_run"))
    summary["wallet_hard_block"] = bool(skip_state.get("wallet_hard_block"))
    if skip_state.get("reasons"):
        summary["soft_skip_reasons"] = list(skip_state["reasons"])
    if soft_skip_self_run:
        summary["self_run_queue_soft_skip"] = True
        # Prefer wallet as queue skip reason when present (ops-actionable)
        summary["self_run_queue_skip_reason"] = (
            "credits_hard_block"
            if skip_state.get("wallet_hard_block")
            else (skip_state.get("primary") or "recent_llm_failures")
        )
        if not summary.get("self_run_skipped") and skip_state.get("primary"):
            summary["self_run_skipped"] = skip_state["primary"]

    queued = (
        db.query(models.Task)
        .filter(
            models.Task.user_id == user.id,
            models.Task.status == "queued",
            models.Task.agent_id.isnot(None),
        )
        .order_by(models.Task.id)
        .limit(max(1, max_tasks * 3 if soft_skip_self_run else max_tasks))
        .all()
    )
    started = 0
    for t in queued:
        if started >= max_tasks:
            break
        labels = (t.labels or "").lower()
        # Terminal provider failures must never re-enter the runner
        if _is_terminal_provider_task(t):
            t.status = "failed"
            t.completed_at = t.completed_at or datetime.utcnow()
            t.updated_at = datetime.utcnow()
            labs = [x.strip() for x in (t.labels or "").split(",") if x.strip()]
            if "llm_unavailable" not in {x.lower() for x in labs}:
                labs.append("llm_unavailable")
            t.labels = ",".join(labs)[:500]
            if not (t.result or "").strip().startswith("["):
                t.result = (
                    f"[LLM_UNAVAILABLE] Queued terminal provider failure — not started.\n"
                    f"{t.result or ''}"
                )[:12000]
            db.commit()
            summary["stalled_terminal_failed"] = summary.get("stalled_terminal_failed", 0) + 1
            continue
        if soft_skip_self_run and _is_self_run_labels(labels):
            summary["self_run_queue_skipped"] = summary.get("self_run_queue_skipped", 0) + 1
            continue
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
        started += 1
        await emit_ops(
            user.id, kind="action", status="running",
            title="Autonomy running task (offline OK)",
            detail=(t.title or t.description or "")[:160],
            agent_id=agent.id, task_id=t.id, db=db,
        )
        # Always run_inline=True so work proceeds without a browser session
        try:
            ok = await kick_queued_task(
                t.id,
                user_id=user.id,
                agent_id=agent.id,
                description=t.description,
                agent_name=agent.name,
                run_inline=True,
                timeout_sec=offline_budget,
            )
            if not ok:
                await schedule(
                    run_agent_task(agent.id, user.id, t.id, t.description, agent.name),
                    timeout_sec=offline_budget,
                )
        except Exception:
            await schedule(
                run_agent_task(agent.id, user.id, t.id, t.description, agent.name),
                timeout_sec=offline_budget,
            )


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
        # Provider/billing dead-ends: mark failed, do not requeue via escalate
        if _is_terminal_provider_task(t):
            t.status = "failed"
            t.completed_at = t.completed_at or datetime.utcnow()
            t.updated_at = datetime.utcnow()
            labs = [x.strip() for x in (t.labels or "").split(",") if x.strip()]
            if "llm_unavailable" not in {x.lower() for x in labs}:
                labs.append("llm_unavailable")
            if "escalated" not in {x.lower() for x in labs}:
                labs.append("escalated")
            t.labels = ",".join(labs)[:500]
            db.commit()
            summary["stalled_terminal_failed"] = summary.get("stalled_terminal_failed", 0) + 1
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
        # Only escalate once (label marker). chain-skipped = intentional abort
        # after a prior auto-chain step failed — never re-queue those.
        labels = (t.labels or "")
        if "escalated" in labels or "chain-skipped" in labels:
            continue
        # LLM/credits/403 failures: log once without requeue (re-running cannot help)
        if _is_terminal_provider_task(t):
            agent = db.get(models.Agent, t.agent_id) if t.agent_id else None
            await escalate_task(
                db, t,
                reason_code="failure",
                reason_text=(t.result or "LLM/provider unavailable")[:500],
                from_agent=agent,
                requeue=False,
            )
            summary["escalated"] += 1
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
        labels = t.labels or ""
        if "escalated" in labels or "chain-skipped" in labels:
            continue
        # Sequential auto-chain steps stay todo until on_task_finished unlocks
        # them. Escalating with requeue=True would force parallel runs.
        if "auto-chain" in labels and (t.status or "") == "todo":
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


def _recent_llm_failures_dominate(
    db: Session,
    user_id: int,
    *,
    lookback_hours: float = 2.0,
    sample: int = 8,
    min_llm: int = 2,
) -> bool:
    """True when recent task failures are mostly LLM/credits/403 (easy soft skip).

    Stops autonomy inventing endless self-run tasks while the provider is down
    or the wallet is empty. Real board claims still proceed.
    """
    try:
        from .llm import is_terminal_llm_failure
    except Exception:
        return False

    cutoff = datetime.utcnow() - timedelta(hours=max(0.25, lookback_hours))
    rows = (
        db.query(models.Task)
        .filter(
            models.Task.user_id == user_id,
            models.Task.status == "failed",
        )
        .order_by(models.Task.id.desc())
        .limit(max(3, sample))
        .all()
    )
    if not rows:
        return False

    recent = []
    for t in rows:
        when = getattr(t, "completed_at", None) or getattr(t, "updated_at", None) or t.created_at
        if when and when < cutoff:
            continue
        recent.append(t)
    if len(recent) < min_llm:
        # Also count very fresh failures without timestamps in range
        if len(rows) >= min_llm:
            recent = rows[:sample]
        else:
            return False

    llm_n = 0
    for t in recent:
        res = t.result or ""
        labels = (t.labels or "").lower()
        if is_terminal_llm_failure(res):
            llm_n += 1
        elif "self-run" in labels and any(
            m in res
            for m in (
                "[LLM_UNAVAILABLE]",
                "[CREDITS_EXHAUSTED]",
                "[LLM_PERMISSION_DENIED]",
            )
        ):
            llm_n += 1

    if llm_n < min_llm:
        return False
    # Dominate: at least half of recent failures are LLM-shaped
    return llm_n * 2 >= len(recent)


def _invent_self_run_spec(agent: models.Agent, *, role: str) -> tuple[str, str, str]:
    """
    Build a capped, useful never_idle invent (CRM / workflow style when safe).

    Returns (title, description, labels). Prefer real skills + complete_task;
    never invent paid spam (mass send/call/image).
    """
    name = (agent.name or "Agent").strip() or "Agent"
    tpl = (getattr(agent, "template_type", None) or "").lower()
    role_l = (role or getattr(agent, "hierarchy_role", None) or "").lower()
    name_l = name.lower()

    is_sales = (
        tpl in ("sales", "crm", "lead_gen", "outreach")
        or "sales" in name_l
        or "crm" in name_l
        or "outreach" in name_l
        or "lead" in name_l
    )
    is_support = tpl in ("support", "customer", "success") or "support" in name_l
    is_marketing = tpl in ("marketing", "content", "seo", "social") or "market" in name_l
    is_coding = tpl in ("coding", "developer", "engineer", "qa") or "dev" in name_l
    is_orch = role_l in ("orchestrator", "lead") or "orchestrat" in name_l

    if is_sales:
        title = f"CRM pulse · {name}"
        desc = (
            f"You are {name} ({role or tpl or 'sales'}), running a short CRM hygiene pass.\n"
            f"1) list_customers (limit 15) and list_deals / list_pipelines — note gaps.\n"
            f"2) Pick 1–3 real rows: update_customer notes, create_deal if missing, "
            f"qualify_lead or score_lead when ICP signals exist, log_customer_activity.\n"
            f"3) If a stale open deal needs a stage nudge, move_deal with a reason.\n"
            f"4) save_memory key=crm_pulse_summary with counts you touched.\n"
            f"5) MUST end with complete_task on THIS task_id with evidence (ids + what changed).\n\n"
            f"DONE WHEN: ≥1 CRM skill write (customer/deal/qualify/activity) + complete_task.\n"
            f"TARGET: Board/CRM shows fresher data; no mass send_email/call.\n"
            f"Do NOT use paid send/call/image skills unless essential.\n"
        )
        labels = "autonomy,self-run,self-assigned,crm"
    elif is_support:
        title = f"Support queue pulse · {name}"
        desc = (
            f"You are {name} ({role or 'support'}), clearing useful support work.\n"
            f"1) list_tasks mine=true + open high-priority todos; claim or finish one.\n"
            f"2) list_customers for any flagged / recent; add a short diary note or activity.\n"
            f"3) If blocked, set_task_status failed with a clear reason — else complete_task.\n\n"
            f"DONE WHEN: One support/CRM board item advanced with skill evidence.\n"
            f"TARGET: Owner can see progress without login babysitting.\n"
        )
        labels = "autonomy,self-run,self-assigned,support"
    elif is_marketing:
        title = f"Content workflow pulse · {name}"
        desc = (
            f"You are {name} ({role or 'marketing'}).\n"
            f"1) list_tasks + read_workspace — claim open marketing work if any.\n"
            f"2) Else draft one concrete asset (draft_email or generate_content outline) "
            f"and save_memory key=content_pulse.\n"
            f"3) complete_task with the deliverable text (no paid image/video unless asked).\n\n"
            f"DONE WHEN: One draft or board completion with evidence.\n"
            f"TARGET: Reusable marketing artifact in task result / memory.\n"
        )
        labels = "autonomy,self-run,self-assigned,marketing"
    elif is_coding:
        title = f"Eng backlog pulse · {name}"
        desc = (
            f"You are {name} ({role or 'engineering'}).\n"
            f"1) list_tasks mine=true — finish or advance one coding task with real notes.\n"
            f"2) Else write a short implementation plan + checklist for the top open goal "
            f"and save_memory key=eng_pulse.\n"
            f"3) complete_task with the plan or patch summary.\n\n"
            f"DONE WHEN: One engineering deliverable (plan/patch notes) + complete_task.\n"
        )
        labels = "autonomy,self-run,self-assigned,coding"
    elif is_orch:
        title = f"Workflow pulse · {name}"
        desc = (
            f"You are {name} ({role or 'orchestrator'}), keeping multi-agent work moving.\n"
            f"1) list_tasks (open/queued/in_progress) — find stalled board or chain steps.\n"
            f"2) Prefer claim_task / re-assign via create_task for a concrete specialist, "
            f"or complete a small orphan todo yourself with skills.\n"
            f"3) Optional: pipeline_summary or status_update if CRM work exists.\n"
            f"4) MUST complete_task this pulse with what you unblocked.\n\n"
            f"DONE WHEN: One real board/chain/CRM action + complete_task evidence.\n"
            f"TARGET: No new endless fluff — only useful workflow progress.\n"
            f"Do NOT invent multi-step goal chains unless the board is empty of open work.\n"
        )
        labels = "autonomy,self-run,self-assigned,workflow"
    else:
        title = f"Ops deliverable · {name}"
        desc = (
            f"You are {name} ({role or tpl or 'specialist'}), running autonomously.\n"
            f"1) list_tasks mine=true and read_workspace — see open work.\n"
            f"2) If open work exists, claim_task or complete_task it with a real result.\n"
            f"3) Else one useful CRM/workflow action: list_customers + note, draft_email, "
            f"or create_task for yourself with DONE WHEN, then do it now.\n"
            f"4) MUST end by complete_task on the task you worked (include task_id + result).\n\n"
            f"DONE WHEN: At least one board task completed with skill evidence.\n"
            f"TARGET: One concrete business deliverable — not a chat-only reply.\n"
            f"Do NOT use paid send/call/image skills unless essential.\n"
        )
        labels = "autonomy,self-run,self-assigned"

    return title[:200], desc[:8000], labels


async def _feed_never_idle(db: Session, user: models.User, summary: dict) -> None:
    """
    Give up to N never_idle agents proactive work when they have no open tasks.
    Prefer orchestrator → leads → others. Does not mutate idle_mode/permissions.

    Cap (AUTONOMY_MAX_IDLE_FEEDS, default 1, hard max 2):
      - counts board claims + self-run invents per tick
      - self-run invent also blocked when open self-run backlog already ≥ cap
      - invents are CRM/workflow-style (role-aware), not empty chat fluff
    """
    from . import config as app_config
    from .agent_roles import agent_sort_key
    from .agent_scaffold import resolve_runtime

    # Enforce low default: clamp again here so mis-imports / old configs stay safe
    raw_feeds = int(getattr(app_config, "AUTONOMY_MAX_IDLE_FEEDS", 1) or 0)
    max_feeds = max(0, min(2, raw_feeds))
    summary["idle_feed_cap"] = max_feeds
    if max_feeds <= 0:
        summary["self_run_skipped"] = "idle_feeds_disabled"
        summary["soft_skip_reasons"] = ["idle_feeds_disabled"]
        return

    # Cap open self-run backlog across the workspace (not just this tick)
    open_self_runs = 0
    try:
        open_self_rows = (
            db.query(models.Task)
            .filter(
                models.Task.user_id == user.id,
                models.Task.status.in_(("todo", "queued", "in_progress")),
            )
            .limit(40)
            .all()
        )
        open_self_runs = sum(
            1 for t in open_self_rows if _is_self_run_labels(t.labels)
        )
    except Exception:
        open_self_runs = 0

    # Soft-skip invent only (board claims still run). All paths via one helper:
    # credits_hard_block | recent_llm_failures | open_self_run_cap
    skip_state = _self_run_soft_skip_state(
        db, user, open_self_runs=open_self_runs, max_feeds=max_feeds,
    )
    skip_self_run = bool(skip_state.get("skip_invent"))
    summary["wallet_hard_block"] = bool(skip_state.get("wallet_hard_block"))
    if skip_state.get("reasons"):
        summary["soft_skip_reasons"] = list(skip_state["reasons"])
        summary["self_run_skipped"] = skip_state.get("primary") or skip_state["reasons"][0]
        log_mod = __import__("logging").getLogger("app.autonomy")
        log_mod.info(
            "autonomy soft-skip self-run invent user=%s reasons=%s",
            user.id,
            skip_state["reasons"],
        )

    agents = (
        db.query(models.Agent)
        .filter_by(user_id=user.id, status="active", idle_mode="never_idle")
        .all()
    )
    agents = sorted(agents, key=agent_sort_key)

    fed = 0
    self_runs_created = 0
    board_claimed = 0
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
        # Prefer claiming real open board work over inventing self-runs (race-tight)
        claimed = _claim_unassigned_board_task(db, user, a)
        if claimed:
            fed += 1
            board_claimed += 1
            summary["idle_tasks"] += 1
            summary["board_claimed"] = board_claimed
            # Leave queued — _run_queued_tasks (same tick) runs with run_inline=True offline
            await emit_ops(
                user.id, kind="action", status="queued",
                title=f"{a.name} claimed board task",
                detail=(claimed.title or "")[:160],
                agent_id=a.id, task_id=claimed.id, db=db,
            )
            continue

        if skip_self_run:
            # Do not invent while wallet blocked / LLM down / open self-run at cap
            continue
        if self_runs_created >= max_feeds:
            continue
        if open_self_runs + self_runs_created >= max_feeds:
            skip_self_run = True
            summary["self_run_skipped"] = summary.get("self_run_skipped") or "open_self_run_cap"
            reasons = list(summary.get("soft_skip_reasons") or [])
            if "open_self_run_cap" not in reasons:
                reasons.append("open_self_run_cap")
            summary["soft_skip_reasons"] = reasons
            continue

        # Last-chance board claim (board may have opened mid-tick / after terminal purge)
        claimed_again = _claim_unassigned_board_task(db, user, a)
        if claimed_again:
            fed += 1
            board_claimed += 1
            summary["idle_tasks"] += 1
            summary["board_claimed"] = board_claimed
            await emit_ops(
                user.id, kind="action", status="queued",
                title=f"{a.name} claimed board task",
                detail=(claimed_again.title or "")[:160],
                agent_id=a.id, task_id=claimed_again.id, db=db,
            )
            continue

        title, desc, labels = _invent_self_run_spec(a, role=role or "")
        t = models.Task(
            user_id=user.id,
            agent_id=a.id,
            company_id=a.company_id,
            project_id=a.project_id,
            title=title,
            description=desc,
            status="queued",
            priority="medium",
            labels=labels,
            assignee_type="agent",
        )
        db.add(t)
        db.commit()
        db.refresh(t)
        fed += 1
        self_runs_created += 1
        summary["idle_tasks"] += 1
        summary["self_runs_created"] = self_runs_created
        # Queue only here — same-tick _run_queued_tasks executes offline (no login)
        await emit_ops(
            user.id, kind="action", status="queued",
            title=f"{a.name} autonomy task",
            detail=title[:160],
            agent_id=a.id, task_id=t.id, db=db,
        )


def _attach_cycle_health(db: Session, user: models.User, summary: dict) -> dict:
    """Lightweight board health for cron /ops tick responses (no extra LLM).

    Useful ops fields:
      wallet_hard_block — stop inventing / running self-run fluff
      soft_skip_reasons — credits_hard_block | recent_llm_failures | open_self_run_cap
      board_claimed vs self_runs_created — prefer-board ratio
      unassigned_open — backlog still free for claim
      terminal fails — never requeued path health
    """
    try:
        # Always re-check wallet for health even if invent path did not run
        if "wallet_hard_block" not in summary:
            summary["wallet_hard_block"] = _wallet_hard_blocked(db, user)
        elif summary.get("wallet_hard_block") is None:
            summary["wallet_hard_block"] = _wallet_hard_blocked(db, user)

        open_q = (
            db.query(models.Task)
            .filter(
                models.Task.user_id == user.id,
                models.Task.status.in_(("queued", "in_progress", "todo")),
                models.Task.agent_id.isnot(None),
            )
            .count()
        )
        unassigned_open = (
            db.query(models.Task)
            .filter(
                models.Task.user_id == user.id,
                models.Task.status.in_(("todo", "queued")),
                models.Task.agent_id.is_(None),
            )
            .count()
        )
        failed_recent = (
            db.query(models.Task)
            .filter(models.Task.user_id == user.id, models.Task.status == "failed")
            .order_by(models.Task.id.desc())
            .limit(12)
            .all()
        )
        terminal_n = sum(1 for t in failed_recent if _is_terminal_provider_task(t))
        reasons = list(summary.get("soft_skip_reasons") or [])
        if summary.get("self_run_skipped") and summary["self_run_skipped"] not in reasons:
            reasons.append(summary["self_run_skipped"])
        summary["health"] = {
            "open_agent_tasks": open_q,
            "unassigned_open": unassigned_open,
            "recent_failed": len(failed_recent),
            "recent_terminal_provider_fails": terminal_n,
            "wallet_hard_block": bool(summary.get("wallet_hard_block")),
            "llm_soft_skip": bool(summary.get("self_run_skipped") or reasons),
            "self_run_skipped": summary.get("self_run_skipped") or None,
            "soft_skip_reasons": reasons,
            "self_run_queue_soft_skip": bool(summary.get("self_run_queue_soft_skip")),
            "self_run_queue_skip_reason": summary.get("self_run_queue_skip_reason"),
            "self_run_queue_skipped": summary.get("self_run_queue_skipped", 0),
            "stalled_requeued": summary.get("stalled_requeued", 0),
            "stalled_terminal_failed": summary.get("stalled_terminal_failed", 0),
            "board_claimed": summary.get("board_claimed", 0),
            "self_runs_created": summary.get("self_runs_created", 0),
            "prefer_board": (
                int(summary.get("board_claimed") or 0)
                >= int(summary.get("self_runs_created") or 0)
            ),
            "idle_feed_cap": summary.get("idle_feed_cap"),
            "tasks_started": summary.get("tasks_started", 0),
            "escalated": summary.get("escalated", 0),
            "todos_promoted": summary.get("todos_promoted", 0),
        }
    except Exception as e:
        summary["health"] = {"error": str(e)[:160]}
    return summary


async def run_user_cycle(db: Session, user: models.User) -> dict[str, Any]:
    from . import config as app_config

    settings = get_or_create_settings(db, user.id)
    summary = {
        "user_id": user.id,
        "tasks_started": 0,
        "escalated": 0,
        "idle_tasks": 0,
        "todos_promoted": 0,
        "skipped": False,
        "reason": "",
    }
    # Ensure orchestrator exists only — do NOT rewrite every agent each tick
    try:
        ensure_main_orchestrator(db, user)
    except Exception as e:
        summary["reason"] = f"orchestrator_error:{e}"

    # Always drain queued work offline (even if autonomy_enabled is false).
    # Proactive idle feeds / stuck scans only when autonomy is on.
    autonomy_on = bool(settings.autonomy_enabled)

    # Respect min interval so rapid UI ticks / cron overlaps do not flood the GPU
    # with proactive idle feeds. Queued work is still drained (production cron
    # must process backlog even if a recent manual tick advanced last_run).
    min_iv = int(getattr(app_config, "AUTONOMY_MIN_INTERVAL_SEC", 120) or 120)
    user_iv = max(min_iv, int(settings.autonomy_interval_sec or min_iv))
    last = settings.last_autonomy_run
    on_cooldown = bool(last and (datetime.utcnow() - last) < timedelta(seconds=user_iv))

    if not autonomy_on:
        await _run_queued_tasks(db, user, summary)
        summary["reason"] = "queue_drain_only_autonomy_off"
        if summary["tasks_started"] == 0:
            summary["skipped"] = True
        else:
            settings.last_autonomy_summary = (
                f"offline drain started={summary['tasks_started']} (autonomy off)"
            )
            settings.updated_at = datetime.utcnow()
            db.commit()
        return _attach_cycle_health(db, user, summary)

    if on_cooldown:
        await _run_queued_tasks(db, user, summary)
        summary["reason"] = f"cooldown_drain_{user_iv}s"
        if summary["tasks_started"] == 0:
            summary["skipped"] = True
        else:
            settings.last_autonomy_summary = (
                f"drain started={summary['tasks_started']} "
                f"(cooldown {user_iv}s — idle feed skipped)"
            )
            settings.updated_at = datetime.utcnow()
            db.commit()
            await emit_ops(
                user.id,
                kind="system",
                status="done",
                title="Autonomy drain (cooldown)",
                detail=settings.last_autonomy_summary,
                db=db,
            )
        return _attach_cycle_health(db, user, summary)

    await _check_stuck_and_failed(db, user, settings, summary)
    await _feed_never_idle(db, user, summary)
    await _run_queued_tasks(db, user, summary)

    settings.last_autonomy_run = datetime.utcnow()
    skip_note = summary.get("self_run_skipped")
    term_n = summary.get("stalled_terminal_failed", 0)
    settings.last_autonomy_summary = (
        f"started={summary['tasks_started']} escalated={summary['escalated']} "
        f"idle_tasks={summary['idle_tasks']}"
        + (f" self_run_skipped={skip_note}" if skip_note else "")
        + (f" terminal_failed={term_n}" if term_n else "")
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
    return _attach_cycle_health(db, user, summary)


def _users_needing_autonomy(db: Session, *, limit: int = 80) -> list[models.User]:
    """
    Workspaces that keep running when the owner is offline / not logged in:
      - open agent tasks (queued / in_progress / todo)
      - never_idle active agents
      - autonomy_enabled workspaces
      - active agents (so default workspaces still tick)
    No browser session required — cron/tick-all drives this.
    """
    from sqlalchemy import or_, and_

    # 1) Users with open agent work (highest priority — finish chains offline)
    busy_uids = {
        r[0]
        for r in (
            db.query(models.Task.user_id)
            .filter(
                models.Task.status.in_(["queued", "in_progress", "todo"]),
                models.Task.agent_id.isnot(None),
            )
            .distinct()
            .limit(limit * 3)
            .all()
        )
        if r[0]
    }

    # 2) never_idle agents must keep getting self-work offline
    never_idle_uids = {
        r[0]
        for r in (
            db.query(models.Agent.user_id)
            .filter(
                models.Agent.status == "active",
                models.Agent.idle_mode == "never_idle",
            )
            .distinct()
            .limit(limit * 3)
            .all()
        )
        if r[0]
    }

    # 3) Any workspace with active agents
    agent_uids = {
        r[0]
        for r in (
            db.query(models.Agent.user_id)
            .filter(models.Agent.status == "active")
            .distinct()
            .limit(limit * 3)
            .all()
        )
        if r[0]
    }

    # 4) Explicit autonomy_enabled
    settings_on = {
        r.user_id
        for r in db.query(models.WorkspaceSettings)
        .filter(models.WorkspaceSettings.autonomy_enabled == True)  # noqa: E712
        .limit(limit * 3)
        .all()
        if r.user_id
    }

    # Busy queues always win; never_idle and autonomy-on always included;
    # active agents included so work continues without login.
    candidate_ids = list(busy_uids | never_idle_uids | settings_on | agent_uids)
    if not candidate_ids:
        # Fall back: anyone with a real plan / admin
        return (
            db.query(models.User)
            .filter(
                or_(
                    models.User.subscription_active == True,  # noqa: E712
                    models.User.role == "admin",
                    and_(
                        models.User.plan.isnot(None),
                        models.User.plan.notin_(["none", ""]),
                    ),
                )
            )
            .order_by(models.User.id)
            .limit(limit)
            .all()
        )

    # Prefer users with busy queues, then never_idle, then others
    ordered = sorted(
        set(candidate_ids),
        key=lambda uid: (
            0 if uid in busy_uids else 1,
            0 if uid in never_idle_uids else 1,
            uid,
        ),
    )[:limit]

    users = (
        db.query(models.User)
        .filter(models.User.id.in_(ordered))
        .all()
    )
    by_id = {u.id: u for u in users}
    return [by_id[i] for i in ordered if i in by_id]


async def run_global_tick() -> dict[str, Any]:
    """One tick across all eligible users (local loop or cron) — no login required.

    Agents continue tasks while the human is logged out: this is the production
    offline engine driven by GET /api/ops/autonomy/tick-all.
    """
    from . import config as app_config

    db = SessionLocal()
    results = []
    try:
        max_users = int(getattr(app_config, "AUTONOMY_MAX_USERS_PER_TICK", 25) or 25)
        try:
            from .async_jobs import is_serverless
            if is_serverless():
                # Stay under Vercel maxDuration while still draining offline queues
                max_users = min(max_users, 12)
        except Exception:
            pass
        users = _users_needing_autonomy(db, limit=max(5, max_users))
        for u in users:
            try:
                u = db.get(models.User, u.id)
                if not u:
                    continue
                # Ensure autonomy defaults on so offline work is not stuck disabled forever
                settings = get_or_create_settings(db, u.id)
                has_open = (
                    db.query(models.Task)
                    .filter(
                        models.Task.user_id == u.id,
                        models.Task.status.in_(["queued", "in_progress", "todo"]),
                        models.Task.agent_id.isnot(None),
                    )
                    .first()
                    is not None
                )
                # Default on; force on when open agent work exists so offline ticks drain queues
                if settings.autonomy_enabled is not True and (
                    has_open or settings.autonomy_enabled is None
                ):
                    settings.autonomy_enabled = True
                    db.commit()
                r = await run_user_cycle(db, u)
                r["offline"] = True
                r["login_required"] = False
                results.append(r)
            except Exception as e:
                results.append({
                    "user_id": getattr(u, "id", None),
                    "error": str(e)[:300],
                    "offline": True,
                })
        # Aggregate health for cron dashboards / keep-alive pingers
        started = sum(int(r.get("tasks_started") or 0) for r in results if isinstance(r, dict))
        escalated = sum(int(r.get("escalated") or 0) for r in results if isinstance(r, dict))
        terminal = sum(
            int((r.get("health") or {}).get("stalled_terminal_failed") or r.get("stalled_terminal_failed") or 0)
            for r in results
            if isinstance(r, dict)
        )
        errors = sum(1 for r in results if isinstance(r, dict) and r.get("error"))
        soft_skips = sum(
            1
            for r in results
            if isinstance(r, dict) and (r.get("self_run_skipped") or (r.get("health") or {}).get("self_run_skipped"))
        )
        wallet_blocked_users = sum(
            1
            for r in results
            if isinstance(r, dict)
            and (
                r.get("wallet_hard_block")
                or (r.get("health") or {}).get("wallet_hard_block")
            )
        )
        board_claimed_total = sum(
            int((r.get("health") or {}).get("board_claimed") or r.get("board_claimed") or 0)
            for r in results
            if isinstance(r, dict)
        )
        self_runs_total = sum(
            int((r.get("health") or {}).get("self_runs_created") or r.get("self_runs_created") or 0)
            for r in results
            if isinstance(r, dict)
        )
        return {
            "ok": True,
            "users": len(results),
            "results": results,
            "at": datetime.utcnow().isoformat() + "Z",
            "offline": True,
            "login_required": False,
            "note": "Agents keep running tasks without an owner browser session",
            # CRON health signals — use for keep-alive / ops monitoring (no secrets)
            "health": {
                "users_ticked": len(results),
                "users_errored": errors,
                "tasks_started_total": started,
                "escalated_total": escalated,
                "terminal_provider_failed_total": terminal,
                "self_run_soft_skip_users": soft_skips,
                "wallet_hard_block_users": wallet_blocked_users,
                "board_claimed_total": board_claimed_total,
                "self_runs_created_total": self_runs_total,
                "prefer_board": board_claimed_total >= self_runs_total,
                "cron_path": "/api/ops/autonomy/tick-all",
                "cron_auth": "Bearer CRON_SECRET or X-Cron-Secret",
            },
        }
    finally:
        db.close()


async def autonomy_background_loop():
    """Local long-running loop (disabled on Vercel — use cron /ops/autonomy/tick-all)."""
    import asyncio
    from . import config as app_config

    while True:
        try:
            db = SessionLocal()
            try:
                rows = db.query(models.WorkspaceSettings).filter_by(autonomy_enabled=True).all()
                # Default 60s local; floor 30s so GPU is not thrashed
                interval = int(getattr(app_config, "AUTONOMY_LOOP_SEC", 60) or 60)
                if rows:
                    interval = min(max(30, r.autonomy_interval_sec or interval) for r in rows)
                    interval = max(30, min(interval, 300))
            finally:
                db.close()
            await run_global_tick()
            await asyncio.sleep(interval)
        except Exception:
            await asyncio.sleep(60)
