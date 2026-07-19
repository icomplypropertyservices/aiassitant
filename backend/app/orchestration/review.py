"""Lead review / reject of subagent work — single implementation."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..patterns import format_feedback_block, normalize_checklist
from ..agent_roles import is_lead_agent, is_orchestrator

log = logging.getLogger("app.orchestration.review")


def can_review(agent: models.Agent, task: models.Task, assignee: models.Agent | None) -> bool:
    if is_orchestrator(agent) or is_lead_agent(agent):
        return True
    if (agent.hierarchy_role or "") in ("lead", "orchestrator"):
        return True
    if (agent.permission_level or "") in ("lead", "admin"):
        return True
    if assignee and assignee.parent_id == agent.id:
        return True
    # No self-review for leads of their own specialist work (block self-approve gaming)
    if task.agent_id == agent.id and not is_orchestrator(agent):
        return False
    return False


def normalize_review_action(raw: str | None, *, has_feedback: bool) -> str:
    a = (raw or "").strip().lower()
    if a in ("ok", "pass", "accepted", "approve", "approved", "lgtm", "yes"):
        return "approve"
    if a in (
        "reject", "rejected", "fail", "failed", "no", "wrong", "redo", "rework",
        "changes", "changes_requested", "request_changes", "revise", "fix",
    ):
        return "reject"
    return "reject" if has_feedback else "approve"


async def review_task(
    db: Session,
    agent: models.Agent,
    user: models.User,
    *,
    task_id: int,
    action: str | None = None,
    feedback: str = "",
    checks_failed: list[str] | None = None,
    message_fn=None,
) -> dict[str, Any]:
    """
    Approve → completed + chain unlock.
    Reject → WHAT'S WRONG block, requeue, notify assignee, kick.
    """
    from ..task_runner import kick_queued_task

    t = db.get(models.Task, task_id)
    if not t or t.user_id != user.id:
        return {"ok": False, "error": "task not found"}

    assignee = db.get(models.Agent, t.agent_id) if t.agent_id else None
    if not can_review(agent, t, assignee):
        return {
            "ok": False,
            "error": "Only leads/orchestrators (or the assignee's parent) may review_task",
        }

    fb = (feedback or "").strip()
    failed = normalize_checklist(checks_failed)
    act = normalize_review_action(action, has_feedback=bool(fb or failed))

    if act == "approve":
        note = fb or "Lead approved — acceptance met."
        prev = (t.result or "").strip()
        t.result = (prev + f"\n\n[LEAD APPROVED by {agent.name}] {note}").strip()[:12000]
        t.status = "completed"
        t.completed_at = datetime.utcnow()
        labels = t.labels or ""
        for tag in ("lead-approved", "reviewed"):
            if tag not in labels:
                labels = f"{labels},{tag}".strip(",") if labels else tag
        drop = {"needs-review", "needs-revision", "lead-rejected", "has-feedback", "requires-review"}
        t.labels = ",".join(p for p in labels.split(",") if p and p not in drop)
        t.updated_at = datetime.utcnow()
        try:
            db.add(models.ActivityLog(
                agent_id=agent.id,
                type="review",
                message=f"Approved task #{t.id}: {note[:160]}",
            ))
        except Exception:
            pass
        try:
            from ..task_chain import on_task_finished
            await on_task_finished(db, t, final_status="completed", commit=False)
        except Exception as e:
            log.warning("review approve chain: %s", e)
        db.commit()
        db.refresh(t)

        next_id = None
        try:
            if t.parent_task_id:
                nxt = (
                    db.query(models.Task)
                    .filter(
                        models.Task.parent_task_id == t.parent_task_id,
                        models.Task.status == "queued",
                        models.Task.id != t.id,
                    )
                    .order_by(models.Task.id.asc())
                    .first()
                )
                if nxt:
                    next_id = nxt.id
                    await kick_queued_task(nxt.id, user_id=user.id)
        except Exception:
            pass

        if message_fn and assignee and assignee.id != agent.id:
            try:
                await message_fn(db, agent, user, {
                    "to_agent_id": assignee.id,
                    "message": (
                        f"Lead {agent.name} APPROVED your task #{t.id} "
                        f"“{t.title or ''}”. {note}"
                    )[:2000],
                    "expect_reply": False,
                })
            except Exception:
                pass

        return {
            "ok": True,
            "action": "approve",
            "message": f"Task #{t.id} approved by {agent.name}",
            "task_id": t.id,
            "status": t.status,
            "next_task_started": next_id,
        }

    # ── REJECT ───────────────────────────────────────────────────
    if not fb and not failed:
        fb = (
            "Work does not meet DONE WHEN / CHECKLIST. "
            "Re-read acceptance criteria and deliver again."
        )
    block = format_feedback_block(fb, checks_failed=failed, reviewer=agent.name or "Lead")
    desc = t.description or ""
    if "=== WHAT'S WRONG" in desc:
        desc = desc.split("=== WHAT'S WRONG")[0].rstrip()
    t.description = (desc + "\n" + block)[:8000]
    prev_result = (t.result or "").strip()
    t.result = (
        prev_result
        + f"\n\n[LEAD REJECTED by {agent.name}] {fb[:500]}"
        + (f"\nFailed checks: {', '.join(failed)}" if failed else "")
    ).strip()[:12000]
    t.status = "queued"
    t.completed_at = None
    t.updated_at = datetime.utcnow()
    labels = t.labels or ""
    for tag in ("needs-revision", "lead-rejected", "has-feedback", "needs-review"):
        if tag not in labels:
            labels = f"{labels},{tag}".strip(",") if labels else tag
    t.labels = labels

    try:
        db.add(models.ActivityLog(
            agent_id=agent.id,
            type="review",
            message=f"Rejected task #{t.id} — rework: {fb[:140]}",
        ))
        if assignee:
            db.add(models.ActivityLog(
                agent_id=assignee.id,
                type="feedback",
                message=f"Lead {agent.name} said work on #{t.id} is wrong: {fb[:160]}",
            ))
    except Exception:
        pass
    db.commit()
    db.refresh(t)

    msg_ok = False
    if message_fn and assignee and assignee.id != agent.id:
        try:
            checks_txt = ""
            if failed:
                checks_txt = "\nFailed checks:\n" + "\n".join(f"- {c}" for c in failed)
            mr = await message_fn(db, agent, user, {
                "to_agent_id": assignee.id,
                "message": (
                    f"YOUR WORK ON TASK #{t.id} WAS REJECTED by lead {agent.name}.\n"
                    f"Task: {t.title or ''}\n"
                    f"WHAT'S WRONG: {fb}\n"
                    f"{checks_txt}\n"
                    f"Fix the issues and complete_task #{t.id} again with evidence."
                )[:4000],
                "expect_reply": False,
            })
            msg_ok = bool(mr.get("ok"))
        except Exception:
            msg_ok = False

    kicked = False
    if t.agent_id:
        try:
            kicked = await kick_queued_task(
                t.id,
                user_id=user.id,
                agent_id=t.agent_id,
                description=t.description,
                agent_name=assignee.name if assignee else None,
            )
        except Exception:
            kicked = False

    try:
        from ..ws import manager
        from ..agent_serialize import task_dict
        await manager.broadcast(
            f"agents:{user.id}",
            {"event": "task_updated", "task": task_dict(t, db)},
        )
        await manager.broadcast(
            f"agents:{user.id}",
            {
                "event": "task_rejected",
                "task_id": t.id,
                "agent_id": t.agent_id,
                "reviewer_id": agent.id,
                "feedback": fb[:500],
            },
        )
    except Exception:
        pass

    return {
        "ok": True,
        "action": "reject",
        "message": (
            f"Task #{t.id} rejected — agent informed"
            + (" · re-run started" if kicked else " · re-queued")
            + (" · message sent" if msg_ok else "")
        ),
        "task_id": t.id,
        "status": t.status,
        "feedback": fb[:500],
        "checks_failed": failed,
        "agent_notified": msg_ok,
        "run_started": kicked,
        "assignee_id": t.agent_id,
        "assignee_name": assignee.name if assignee else None,
    }
