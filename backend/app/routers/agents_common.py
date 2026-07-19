"""Shared helpers and schemas for agents routers."""
import logging
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..ownership import require_owned
from .. import models
from ..ws import manager
from ..plans import plan_limits
from ..agent_prompts import team_context
from ..agent_roles import promote_orchestrator

log = logging.getLogger("app.agents")


def _agent_plan_cap(db: Session, user) -> tuple[int, int, bool]:
    """Return (current_count, max_agents, is_admin). max_agents from plan_limits."""
    count = db.query(models.Agent).filter_by(user_id=user.id).count()
    max_agents = int(plan_limits(user.plan).get("agents") or 0)
    is_admin = user.role == "admin"
    return count, max_agents, is_admin


def _require_agent_slot(db: Session, user) -> tuple[int, int]:
    """Raise 400 if non-admin is at/over plan agent cap. Returns (count, max_agents)."""
    count, max_agents, is_admin = _agent_plan_cap(db, user)
    if not is_admin and count >= max_agents:
        raise HTTPException(
            400,
            f"Your plan allows up to {max_agents} agents. Upgrade on Billing.",
        )
    return count, max_agents


def mode_for_template(template_type: str) -> str:
    tt = (template_type or "").lower()
    if any(k in tt for k in ("sales", "marketing")):
        return "sales"
    if any(k in tt for k in ("support", "reviews", "booking")):
        return "support"
    if any(k in tt for k in ("coding", "code", "dev", "ops")):
        return "coding" if "coding" in tt or "code" in tt or "dev" in tt else "general"
    if "lead" in tt:
        return "general"
    return "general"


def _would_cycle(db: Session, agent_id: int, new_parent_id: int) -> bool:
    """True if setting parent_id would create a cycle."""
    seen = set()
    cur = new_parent_id
    while cur:
        if cur == agent_id:
            return True
        if cur in seen:
            return True
        seen.add(cur)
        p = db.get(models.Agent, cur)
        cur = p.parent_id if p else None
    return False


def _team_context(a: models.Agent, db: Session) -> str:
    """Back-compat wrapper — prefer agent_prompts.team_context."""
    return team_context(a, db)


class AgentIn(BaseModel):
    name: str
    template_type: str = "custom"
    personality: str = "Professional, friendly and concise."
    model: str = "quality"
    idle_mode: str = "never_idle"
    config: dict = {}
    is_lead: bool = False
    hierarchy_role: str = "member"  # lead | member | specialist
    parent_id: int | None = None
    company_id: int | None = None
    project_id: int | None = None
    permission_level: str = "operator"
    escalate_when: str = "on_failure"
    escalate_reason: str = ""
    escalate_to: str = "parent"
    escalate_human_id: int | None = None


class AgentUpdate(BaseModel):
    name: str | None = None
    personality: str | None = None
    model: str | None = None
    idle_mode: str | None = None
    config: dict | None = None
    is_lead: bool | None = None
    hierarchy_role: str | None = None
    parent_id: int | None = None  # set null by sending 0 or use HierarchyIn
    company_id: int | None = None
    project_id: int | None = None
    permission_level: str | None = None
    escalate_when: str | None = None
    escalate_reason: str | None = None
    escalate_to: str | None = None
    escalate_human_id: int | None = None


class HierarchyIn(BaseModel):
    parent_id: int | None = None  # None / omit to clear? use clear_parent
    clear_parent: bool = False
    is_lead: bool | None = None
    hierarchy_role: str | None = None
    report_ids: list[int] | None = None  # make these agents report to this one


class DelegateIn(BaseModel):
    to_agent_id: int
    description: str
    title: str = ""
    priority: str = "medium"
    run_now: bool = True


class TaskIn(BaseModel):
    description: str
    title: str = ""
    project_id: int | None = None
    priority: str = "medium"
    labels: str = ""
    run_now: bool = True


class AgentChatIn(BaseModel):
    message: str
    conversation_id: int | None = None


class TaskStatusIn(BaseModel):
    status: str
    priority: str | None = None
    title: str | None = None
    description: str | None = None
    agent_id: int | None = None


class SkillsUpdateIn(BaseModel):
    enabled: list[str] = []


class SkillRunIn(BaseModel):
    skill: str
    args: dict = {}


class MemoryIn(BaseModel):
    title: str = ""
    content: str
    kind: str = "note"
    tags: str = ""
    save_to_training: bool = False


class AgentMsgIn(BaseModel):
    to_agent_id: int
    message: str
    expect_reply: bool = True


class SpawnIn(BaseModel):
    name: str
    template_type: str = "custom"
    personality: str = "Professional, friendly and concise."
    hierarchy_role: str = "member"
    parent_id: int | None = None


async def log_activity(agent_id: int, user_id: int, type_: str, message: str):
    db = SessionLocal()
    try:
        entry = models.ActivityLog(agent_id=agent_id, type=type_, message=message)
        db.add(entry)
        db.commit()
        await manager.broadcast(f"agents:{user_id}", {
            "event": "activity", "agent_id": agent_id,
            "entry": {"id": entry.id, "type": type_, "message": message, "created_at": entry.created_at},
        })
    finally:
        db.close()


def _get_owned(agent_id: int, user, db) -> models.Agent:
    a = require_owned(
        db, models.Agent, agent_id, user,
        user_field='user_id', not_found="Agent not found",
    )
    return a


def _apply_hierarchy(a: models.Agent, db: Session, user, *, parent_id=None, clear_parent=False,
                     is_lead=None, hierarchy_role=None, report_ids=None):
    if clear_parent:
        a.parent_id = None
    elif parent_id is not None:
        if parent_id == a.id:
            raise HTTPException(400, "An agent cannot report to itself")
        if parent_id == 0:
            a.parent_id = None
        else:
            parent = _get_owned(parent_id, user, db)
            if _would_cycle(db, a.id, parent_id):
                raise HTTPException(400, "That parent would create a hierarchy cycle")
            a.parent_id = parent_id
            # Parent becomes a lead automatically
            parent.is_lead = True
            if (parent.hierarchy_role or "member") == "member":
                parent.hierarchy_role = "lead"

    if is_lead is not None:
        a.is_lead = is_lead
        if is_lead and (a.hierarchy_role or "member") == "member":
            a.hierarchy_role = "lead"
        if not is_lead and a.hierarchy_role == "lead":
            a.hierarchy_role = "member"
    if hierarchy_role is not None:
        if hierarchy_role not in ("orchestrator", "lead", "member", "specialist"):
            raise HTTPException(400, "hierarchy_role must be orchestrator, lead, member, or specialist")
        if hierarchy_role == "orchestrator":
            promote_orchestrator(db, a)
        else:
            a.hierarchy_role = hierarchy_role
            a.is_lead = hierarchy_role == "lead" or a.is_lead

    if report_ids is not None:
        a.is_lead = True
        if (a.hierarchy_role or "member") == "member":
            a.hierarchy_role = "lead"
        for rid in report_ids:
            if rid == a.id:
                continue
            child = _get_owned(rid, user, db)
            if _would_cycle(db, rid, a.id):
                raise HTTPException(400, f"Cannot assign agent #{rid} — would create a cycle")
            child.parent_id = a.id
            if (child.hierarchy_role or "") == "lead" and not child.is_lead:
                pass
            if child.hierarchy_role == "lead" and child.id == a.id:
                continue
            if child.hierarchy_role not in ("lead", "specialist"):
                child.hierarchy_role = child.hierarchy_role or "member"


async def _run_task(agent_id: int, user_id: int, task_id: int, description: str, agent_name: str):
    """Delegate to task_runner (single implementation)."""
    from ..task_runner import run_agent_task
    await run_agent_task(agent_id, user_id, task_id, description, agent_name)
