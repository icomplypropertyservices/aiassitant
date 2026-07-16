"""Canonical agent hierarchy / orchestrator helpers — one source of truth."""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import models

ROLES = ("orchestrator", "lead", "member", "specialist")


def is_orchestrator(agent: models.Agent | None) -> bool:
    if not agent:
        return False
    role = (getattr(agent, "hierarchy_role", None) or "").lower()
    tpl = (getattr(agent, "template_type", None) or "").lower()
    return role == "orchestrator" or tpl == "orchestrator"


def is_lead_agent(agent: models.Agent | None, *, reports_count: int | None = None) -> bool:
    if not agent:
        return False
    if is_orchestrator(agent):
        return True
    role = (getattr(agent, "hierarchy_role", None) or "").lower()
    if role == "lead" or getattr(agent, "is_lead", False):
        return True
    if reports_count is not None and reports_count > 0:
        return True
    return False


def normalize_role(agent: models.Agent, *, reports_count: int = 0) -> str:
    """Canonical hierarchy_role for API / prompts."""
    if is_orchestrator(agent):
        return "orchestrator"
    role = (getattr(agent, "hierarchy_role", None) or "").lower()
    if role in ROLES and role != "orchestrator":
        if role == "member" and is_lead_agent(agent, reports_count=reports_count):
            return "lead"
        return role
    if is_lead_agent(agent, reports_count=reports_count):
        return "lead"
    return "member"


def agent_sort_key(agent: models.Agent):
    """Orchestrator first, then leads, then everyone else."""
    role = normalize_role(agent)
    if role == "orchestrator":
        rank = 0
    elif role == "lead" or getattr(agent, "is_lead", False):
        rank = 1
    else:
        rank = 2
    return (rank, (agent.name or "").lower())


def find_orchestrator(db: Session, user_id: int) -> models.Agent | None:
    row = (
        db.query(models.Agent)
        .filter_by(user_id=user_id, hierarchy_role="orchestrator")
        .first()
    )
    if row:
        return row
    return (
        db.query(models.Agent)
        .filter_by(user_id=user_id, template_type="orchestrator")
        .first()
    )


def promote_orchestrator(db: Session, agent: models.Agent) -> models.Agent:
    """
    Make `agent` the sole Main Orchestrator for its user.
    Demotes any previous orchestrator to lead. Clears parent on the new root.
    """
    user_id = agent.user_id
    agent.hierarchy_role = "orchestrator"
    agent.is_lead = True
    agent.parent_id = None
    # Prefer template_type stay as-is; if blank, tag as orchestrator catalog type
    if not (agent.template_type or "").strip():
        agent.template_type = "orchestrator"

    for other in db.query(models.Agent).filter_by(user_id=user_id).all():
        if other.id == agent.id:
            continue
        if is_orchestrator(other):
            other.hierarchy_role = "lead"
            other.is_lead = True
            if (other.template_type or "").lower() == "orchestrator":
                # Keep historical name but rank as lead
                other.hierarchy_role = "lead"
    return agent


def attach_orphan_leads_under(db: Session, orchestrator: models.Agent) -> int:
    """Point root lead agents (no parent) at the main orchestrator. Returns count updated."""
    n = 0
    for other in db.query(models.Agent).filter_by(user_id=orchestrator.user_id).all():
        if other.id == orchestrator.id:
            continue
        if other.parent_id is not None:
            continue
        if is_orchestrator(other):
            continue
        if is_lead_agent(other) or (other.hierarchy_role or "") == "lead":
            other.parent_id = orchestrator.id
            n += 1
    return n


def resolve_create_role(
    *,
    hierarchy_role: str | None,
    template_type: str | None,
    is_lead: bool,
) -> tuple[str, bool, bool]:
    """
    Returns (role, is_lead, is_orchestrator) for agent creation.
    """
    tpl = (template_type or "").lower()
    role_in = (hierarchy_role or "").lower()
    orch = role_in == "orchestrator" or tpl == "orchestrator"
    if orch:
        return "orchestrator", True, True
    lead = bool(is_lead or role_in == "lead" or tpl == "lead")
    if lead:
        return "lead", True, False
    role = role_in if role_in in ROLES else "member"
    return role, False, False
