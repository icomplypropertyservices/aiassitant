"""Permissions catalog + team matrix (agents + humans)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import get_current_user
from ..permissions import (
    PERMISSION_LEVELS,
    ESCALATE_WHEN,
    ESCALATE_TO,
    normalize_permission,
    normalize_escalate_when,
    normalize_escalate_to,
)

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get("/catalog")
def permissions_catalog(user=Depends(get_current_user)):
    return {
        "levels": PERMISSION_LEVELS,
        "escalate_when": ESCALATE_WHEN,
        "escalate_to": ESCALATE_TO,
    }


@router.get("/matrix")
def permissions_matrix(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """All agents + humans with permission / escalate settings for the workspace."""
    agents = (
        db.query(models.Agent)
        .filter_by(user_id=user.id)
        .order_by(models.Agent.name)
        .all()
    )
    humans = (
        db.query(models.Human)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Human.name)
        .all()
    )
    agent_rows = []
    for a in agents:
        co = db.get(models.Company, a.company_id) if a.company_id else None
        agent_rows.append({
            "kind": "agent",
            "id": a.id,
            "name": a.name,
            "role": a.hierarchy_role or "member",
            "permission_level": getattr(a, "permission_level", None) or "operator",
            "escalate_when": getattr(a, "escalate_when", None) or "on_failure",
            "escalate_to": getattr(a, "escalate_to", None) or "parent",
            "escalate_reason": getattr(a, "escalate_reason", None) or "",
            "status": a.status,
            "company_id": a.company_id,
            "company_name": co.name if co else None,
            "idle_mode": a.idle_mode,
        })
    human_rows = []
    for h in humans:
        co = db.get(models.Company, h.company_id) if h.company_id else None
        human_rows.append({
            "kind": "human",
            "id": h.id,
            "name": h.name,
            "role": h.role_title or "teammate",
            "email": h.email or "",
            "permission_level": getattr(h, "permission_level", None) or "operator",
            "escalate_when": getattr(h, "escalate_when", None) or "on_blocked",
            "escalate_to": getattr(h, "escalate_to", None) or "orchestrator",
            "escalate_reason": getattr(h, "escalate_reason", None) or "",
            "status": h.status,
            "company_id": h.company_id,
            "company_name": co.name if co else None,
        })
    return {
        "owner": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "plan": user.plan,
        },
        "agents": agent_rows,
        "humans": human_rows,
        "levels": PERMISSION_LEVELS,
    }


class AgentPermIn(BaseModel):
    permission_level: str | None = None
    escalate_when: str | None = None
    escalate_to: str | None = None
    escalate_reason: str | None = None
    idle_mode: str | None = None


class HumanPermIn(BaseModel):
    permission_level: str | None = None
    escalate_when: str | None = None
    escalate_to: str | None = None
    escalate_reason: str | None = None


@router.patch("/agents/{agent_id}")
def update_agent_permissions(
    agent_id: int,
    data: AgentPermIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    a = db.get(models.Agent, agent_id)
    if not a or (a.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Agent not found")
    if data.permission_level is not None:
        a.permission_level = normalize_permission(data.permission_level)
    if data.escalate_when is not None:
        a.escalate_when = normalize_escalate_when(data.escalate_when)
    if data.escalate_to is not None:
        a.escalate_to = normalize_escalate_to(data.escalate_to)
    if data.escalate_reason is not None:
        a.escalate_reason = data.escalate_reason.strip()
    if data.idle_mode is not None and data.idle_mode in ("never_idle", "allow_idle"):
        a.idle_mode = data.idle_mode
    db.commit()
    return {"ok": True, "id": a.id, "permission_level": a.permission_level}


@router.patch("/humans/{human_id}")
def update_human_permissions(
    human_id: int,
    data: HumanPermIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    h = db.get(models.Human, human_id)
    if not h or (h.owner_user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Human not found")
    if data.permission_level is not None:
        h.permission_level = normalize_permission(data.permission_level)
    if data.escalate_when is not None:
        h.escalate_when = normalize_escalate_when(data.escalate_when)
    if data.escalate_to is not None:
        h.escalate_to = normalize_escalate_to(data.escalate_to)
    if data.escalate_reason is not None:
        h.escalate_reason = data.escalate_reason.strip()
    db.commit()
    return {"ok": True, "id": h.id, "permission_level": h.permission_level}
