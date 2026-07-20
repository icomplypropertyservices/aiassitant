"""Hierarchy tree, core team, parent/promote, and delegate endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import get_current_user, ensure_credits
from ..agent_serialize import agent_out, task_dict
from ..agent_hierarchy import build_hierarchy_payload
from ..task_status import initial_task_status
from ..async_jobs import schedule as schedule_job
from .agents_common import (
    _get_owned,
    _apply_hierarchy,
    _run_task,
    log_activity,
    HierarchyIn,
    DelegateIn,
)

router = APIRouter()


@router.get("/hierarchy")
def agent_hierarchy(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Full agent org tree: Main Orchestrator always first, then leads → reports."""
    return build_hierarchy_payload(db, user.id)


@router.get("/core-team")
def get_core_team_api(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Pinned Core Team for this account (orchestrator, leads, My Human)."""
    from ..core_team import get_core_team
    return get_core_team(db, user)


@router.post("/core-team/ensure")
async def ensure_core_team_api(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """
    Create the default Core Team if missing (orchestrator + key leads + My Human).
    Respects plan agent caps. Idempotent.
    """
    from ..usage_billing import heal_subscription_flags, subscription_is_live

    if heal_subscription_flags(db, user):
        try:
            db.commit()
            db.refresh(user)
        except Exception:
            db.rollback()
    if user.role != "admin" and not subscription_is_live(user):
        raise HTTPException(402, "Choose a subscription plan to set up your Core Team")
    ensure_credits(db, user.id)
    from ..core_team import ensure_core_team
    result = ensure_core_team(db, user)
    if result.get("created_ids"):
        for aid in result["created_ids"][:3]:
            try:
                await log_activity(aid, user.id, "info", "Added to Core Team")
            except Exception:
                pass
    return result

@router.put("/{agent_id}/hierarchy")
async def set_hierarchy(agent_id: int, data: HierarchyIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Set lead flag, parent, and/or direct reports for an agent."""
    a = _get_owned(agent_id, user, db)
    _apply_hierarchy(
        a, db, user,
        parent_id=data.parent_id,
        clear_parent=data.clear_parent or data.parent_id == 0,
        is_lead=data.is_lead,
        hierarchy_role=data.hierarchy_role,
        report_ids=data.report_ids,
    )
    db.commit()
    db.refresh(a)
    await log_activity(a.id, user.id, "info", "Hierarchy updated")
    return agent_out(a, db, include_team=True)


@router.post("/{agent_id}/delegate")
async def delegate_task(agent_id: int, data: DelegateIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Lead agent delegates a task to a report (or any owned agent)."""
    lead = _get_owned(agent_id, user, db)
    target = _get_owned(data.to_agent_id, user, db)
    # Prefer target reporting to this lead, but allow any agent the user owns
    ensure_credits(db, user.id)
    # Active + run_now → queued for autonomy/runner; paused or opt-out → todo
    status = initial_task_status(agent=target, assignee_type="agent", run_now=data.run_now)
    t = models.Task(
        agent_id=target.id,
        user_id=user.id,
        project_id=target.project_id,
        company_id=target.company_id,
        title=(data.title or data.description[:60]).strip(),
        description=f"[Delegated by {lead.name}] {data.description}",
        status=status,
        priority=data.priority or "medium",
        labels="delegated",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    await log_activity(lead.id, user.id, "action", f"Delegated task to {target.name}: {data.description[:60]}")
    await log_activity(target.id, user.id, "info", f"Task received from lead {lead.name}: {data.description[:60]}")
    if data.run_now:
        if target.status != "active":
            t.status = "todo"
            db.commit()
            raise HTTPException(400, f"{target.name} is paused — task saved as todo")
        await schedule_job(_run_task(target.id, user.id, t.id, t.description, target.name))
    return {"task": task_dict(t, db), "from_lead": lead.name, "to_agent": target.name}

