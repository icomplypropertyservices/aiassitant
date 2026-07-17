"""Human teammates — add people and allocate work."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import get_current_user
from ..live_ops import emit_ops

router = APIRouter(prefix="/humans", tags=["humans"])


class HumanIn(BaseModel):
    name: str
    email: str = ""
    role_title: str = ""
    skills: str = ""
    company_id: int | None = None
    project_id: int | None = None
    status: str = "active"
    capacity: int = 5
    notes: str = ""
    permission_level: str = "operator"
    escalate_when: str = "on_blocked"
    escalate_reason: str = ""
    escalate_to: str = "orchestrator"


class HumanUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    role_title: str | None = None
    skills: str | None = None
    company_id: int | None = None
    project_id: int | None = None
    status: str | None = None
    capacity: int | None = None
    notes: str | None = None
    permission_level: str | None = None
    escalate_when: str | None = None
    escalate_reason: str | None = None
    escalate_to: str | None = None


class AssignIn(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    agent_id: int | None = None
    project_id: int | None = None
    company_id: int | None = None


def _out(h: models.Human, db: Session) -> dict:
    open_n = (
        db.query(models.Task)
        .filter(
            models.Task.human_id == h.id,
            models.Task.status.in_(("todo", "queued", "in_progress", "review")),
        )
        .count()
    )
    co = db.get(models.Company, h.company_id) if h.company_id else None
    pr = db.get(models.Project, h.project_id) if h.project_id else None
    return {
        "id": h.id,
        "name": h.name,
        "email": h.email or "",
        "role_title": h.role_title or "",
        "skills": h.skills or "",
        "company_id": h.company_id,
        "project_id": h.project_id,
        "company_name": co.name if co else None,
        "project_name": pr.name if pr else None,
        "status": h.status,
        "capacity": h.capacity or 5,
        "permission_level": getattr(h, "permission_level", None) or "operator",
        "escalate_when": getattr(h, "escalate_when", None) or "on_blocked",
        "escalate_reason": getattr(h, "escalate_reason", None) or "",
        "escalate_to": getattr(h, "escalate_to", None) or "orchestrator",
        "notes": h.notes or "",
        "open_tasks": open_n,
        "created_at": h.created_at,
        "updated_at": h.updated_at,
    }


@router.get("/")
def list_humans(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = (
        db.query(models.Human)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Human.name)
        .all()
    )
    return {"humans": [_out(h, db) for h in rows], "count": len(rows)}


@router.post("/")
async def create_human(data: HumanIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    from ..permissions import normalize_permission, normalize_escalate_when, normalize_escalate_to
    h = models.Human(
        owner_user_id=user.id,
        name=name,
        email=(data.email or "").strip(),
        role_title=(data.role_title or "").strip(),
        skills=(data.skills or "").strip(),
        company_id=data.company_id,
        project_id=data.project_id,
        status=data.status or "active",
        capacity=max(1, int(data.capacity or 5)),
        notes=(data.notes or "").strip(),
        permission_level=normalize_permission(data.permission_level),
        escalate_when=normalize_escalate_when(data.escalate_when),
        escalate_reason=(data.escalate_reason or "").strip(),
        escalate_to=normalize_escalate_to(data.escalate_to),
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    await emit_ops(
        user.id,
        kind="human",
        status="info",
        title=f"Human added: {h.name}",
        detail=h.role_title or h.email or "",
        human_id=h.id,
        db=db,
    )
    return _out(h, db)


@router.get("/{human_id}")
def get_human(human_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    h = db.get(models.Human, human_id)
    if not h or h.owner_user_id != user.id:
        raise HTTPException(404, "Human not found")
    tasks = (
        db.query(models.Task)
        .filter_by(human_id=h.id)
        .order_by(models.Task.id.desc())
        .limit(40)
        .all()
    )
    return {
        **_out(h, db),
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "status": t.status,
                "priority": t.priority,
                "agent_id": t.agent_id,
                "created_at": t.created_at,
            }
            for t in tasks
        ],
    }


@router.put("/{human_id}")
def update_human(
    human_id: int,
    data: HumanUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    h = db.get(models.Human, human_id)
    if not h or h.owner_user_id != user.id:
        raise HTTPException(404, "Human not found")
    from ..permissions import normalize_permission, normalize_escalate_when, normalize_escalate_to
    for field in ("name", "email", "role_title", "skills", "status", "notes"):
        val = getattr(data, field)
        if val is not None:
            setattr(h, field, val.strip() if isinstance(val, str) else val)
    if data.company_id is not None:
        h.company_id = data.company_id or None
    if data.project_id is not None:
        h.project_id = data.project_id or None
    if data.capacity is not None:
        h.capacity = max(1, int(data.capacity))
    if data.permission_level is not None:
        h.permission_level = normalize_permission(data.permission_level)
    if data.escalate_when is not None:
        h.escalate_when = normalize_escalate_when(data.escalate_when)
    if data.escalate_reason is not None:
        h.escalate_reason = (data.escalate_reason or "").strip()
    if data.escalate_to is not None:
        h.escalate_to = normalize_escalate_to(data.escalate_to)
    h.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(h)
    return _out(h, db)


@router.delete("/{human_id}")
def delete_human(human_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    h = db.get(models.Human, human_id)
    if not h or h.owner_user_id != user.id:
        raise HTTPException(404, "Human not found")
    # Unassign tasks rather than delete work history
    for t in db.query(models.Task).filter_by(human_id=h.id).all():
        t.human_id = None
        if t.assignee_type == "human":
            t.assignee_type = "agent" if t.agent_id else "unassigned"
    db.delete(h)
    db.commit()
    return {"ok": True}


@router.post("/{human_id}/assign")
async def assign_work(
    human_id: int,
    data: AssignIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    h = db.get(models.Human, human_id)
    if not h or h.owner_user_id != user.id:
        raise HTTPException(404, "Human not found")
    title = (data.title or "").strip()
    if not title:
        raise HTTPException(400, "title required")
    agent_id = data.agent_id
    if agent_id:
        a = db.get(models.Agent, agent_id)
        if not a or a.user_id != user.id:
            raise HTTPException(400, "Invalid agent_id")
    t = models.Task(
        user_id=user.id,
        human_id=h.id,
        agent_id=agent_id,
        assignee_type="human",
        company_id=data.company_id or h.company_id,
        project_id=data.project_id or h.project_id,
        title=title,
        description=(data.description or title).strip(),
        status="todo",
        priority=data.priority or "medium",
        labels="human,allocated",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    await emit_ops(
        user.id,
        kind="human",
        status="queued",
        title=f"Assigned to {h.name}",
        detail=title,
        human_id=h.id,
        agent_id=agent_id,
        task_id=t.id,
        db=db,
    )
    return {
        "ok": True,
        "task": {
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "human_id": h.id,
            "agent_id": agent_id,
        },
        "human": _out(h, db),
    }
