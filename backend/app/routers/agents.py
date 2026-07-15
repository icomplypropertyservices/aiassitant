import asyncio, json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db, SessionLocal
from .. import models
from ..auth_utils import get_current_user, user_from_ws_token, ensure_credits
from ..ws import manager
from ..llm import stream_completion, complete, provider_hint
from .. import channels
from ..pricing import estimate_tokens
from ..plans import plan_limits
from ..usage_billing import charge_usage
from ..user_keys import credentials_for_user
from ..async_jobs import schedule as schedule_job
from ..task_status import ALLOWED as TASK_STATUSES, normalize_status

router = APIRouter(prefix="/agents", tags=["agents"])


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
    """Text for lead/member prompts describing hierarchy."""
    parts = []
    role = getattr(a, "hierarchy_role", None) or ("lead" if getattr(a, "is_lead", False) else "member")
    parts.append(f"Hierarchy role: {role}.")
    if a.parent_id:
        lead = db.get(models.Agent, a.parent_id)
        if lead:
            parts.append(f"You report to lead agent: {lead.name} (id={lead.id}).")
    reports = db.query(models.Agent).filter_by(parent_id=a.id).all()
    if reports:
        names = ", ".join(f"{r.name} [{r.template_type}/{r.status}]" for r in reports)
        parts.append(f"You lead this team ({len(reports)}): {names}.")
        parts.append("As lead you may recommend delegation, prioritise work, and summarise team status.")
    return " ".join(parts)


class AgentIn(BaseModel):
    name: str
    template_type: str = "custom"
    personality: str = "Professional, friendly and concise."
    model: str = "vps-fast"
    idle_mode: str = "allow_idle"
    config: dict = {}
    is_lead: bool = False
    hierarchy_role: str = "member"  # lead | member | specialist
    parent_id: int | None = None
    company_id: int | None = None
    project_id: int | None = None

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

def task_dict(t: models.Task, db: Session | None = None):
    agent_name = None
    if t.agent_id and db:
        a = db.get(models.Agent, t.agent_id)
        agent_name = a.name if a else None
    project_name = None
    if t.project_id and db:
        p = db.get(models.Project, t.project_id)
        project_name = p.name if p else None
    return {
        "id": t.id,
        "title": t.title or (t.description or "")[:60],
        "description": t.description,
        "status": t.status,
        "priority": getattr(t, "priority", None) or "medium",
        "labels": getattr(t, "labels", None) or "",
        "result": t.result or "",
        "agent_id": t.agent_id,
        "agent_name": agent_name,
        "project_id": t.project_id,
        "project_name": project_name,
        "company_id": t.company_id,
        "tokens_used": t.tokens_used or 0,
        "cost": t.cost or 0.0,
        "created_at": t.created_at,
        "completed_at": t.completed_at,
        "updated_at": getattr(t, "updated_at", None),
    }

def agent_out(a: models.Agent, db: Session, activity_limit: int = 8, include_team: bool = False):
    logs = (
        db.query(models.ActivityLog)
        .filter_by(agent_id=a.id)
        .order_by(models.ActivityLog.id.desc())
        .limit(activity_limit)
        .all()
    )
    tasks = db.query(models.Task).filter_by(agent_id=a.id).count()
    done = db.query(models.Task).filter_by(agent_id=a.id, status="completed").count()
    open_tasks = db.query(models.Task).filter(
        models.Task.agent_id == a.id,
        models.Task.status.in_(["todo", "queued", "in_progress", "review"]),
    ).count()
    convs = db.query(models.Conversation).filter_by(agent_id=a.id, user_id=a.user_id).count()
    reports = db.query(models.Agent).filter_by(parent_id=a.id).all()
    parent = db.get(models.Agent, a.parent_id) if a.parent_id else None
    is_lead = bool(getattr(a, "is_lead", False) or (getattr(a, "hierarchy_role", "") == "lead") or len(reports) > 0)
    role = getattr(a, "hierarchy_role", None) or ("lead" if is_lead else "member")
    out = {
        "id": a.id, "name": a.name, "template_type": a.template_type, "personality": a.personality,
        "model": a.model, "status": a.status, "idle_mode": a.idle_mode,
        "company_id": a.company_id, "project_id": a.project_id,
        "parent_id": a.parent_id,
        "parent_name": parent.name if parent else None,
        "is_lead": is_lead,
        "hierarchy_role": role,
        "reports_count": len(reports),
        "config": json.loads(a.config or "{}"), "created_at": a.created_at,
        "stats": {
            "tasks": tasks, "completed": done, "open": open_tasks,
            "conversations": convs, "reports": len(reports),
        },
        "activity": [{"id": l.id, "type": l.type, "message": l.message, "created_at": l.created_at} for l in reversed(logs)],
    }
    if include_team:
        out["reports"] = [
            {
                "id": r.id, "name": r.name, "template_type": r.template_type,
                "status": r.status, "model": r.model, "hierarchy_role": r.hierarchy_role or "member",
                "open_tasks": db.query(models.Task).filter(
                    models.Task.agent_id == r.id,
                    models.Task.status.in_(["todo", "queued", "in_progress", "review"]),
                ).count(),
            }
            for r in reports
        ]
        out["team_context"] = _team_context(a, db)
    return out

async def log_activity(agent_id: int, user_id: int, type_: str, message: str):
    db = SessionLocal()
    try:
        log = models.ActivityLog(agent_id=agent_id, type=type_, message=message)
        db.add(log); db.commit()
        await manager.broadcast(f"agents:{user_id}", {
            "event": "activity", "agent_id": agent_id,
            "entry": {"id": log.id, "type": type_, "message": message, "created_at": log.created_at},
        })
    finally:
        db.close()

@router.get("/")
def list_agents(db: Session = Depends(get_db), user=Depends(get_current_user)):
    agents = db.query(models.Agent).filter_by(user_id=user.id).order_by(models.Agent.id.desc()).all()
    return [agent_out(a, db) for a in agents]


@router.get("/hierarchy")
def agent_hierarchy(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Full agent org tree: roots (leads / no parent) → nested reports."""
    agents = db.query(models.Agent).filter_by(user_id=user.id).order_by(models.Agent.name).all()
    by_parent: dict[int | None, list] = {}
    for a in agents:
        by_parent.setdefault(a.parent_id, []).append(a)

    def node(a: models.Agent) -> dict:
        kids = by_parent.get(a.id, [])
        return {
            **agent_out(a, db),
            "children": [node(c) for c in kids],
        }

    roots = by_parent.get(None, [])
    # Also treat leads with no parent as roots even if filtered above
    tree = [node(a) for a in roots]
    leads = [agent_out(a, db) for a in agents if getattr(a, "is_lead", False) or a.hierarchy_role == "lead" or a.id in by_parent]
    return {
        "tree": tree,
        "leads": [agent_out(a, db) for a in agents if getattr(a, "is_lead", False) or (a.hierarchy_role or "") == "lead" or by_parent.get(a.id)],
        "flat": [agent_out(a, db) for a in agents],
        "total": len(agents),
    }


@router.get("/tasks/board")
def tasks_board(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """All tasks for the subscriber — kanban workflow (separate from chat)."""
    rows = (
        db.query(models.Task)
        .filter_by(user_id=user.id)
        .order_by(models.Task.id.desc())
        .limit(200)
        .all()
    )
    columns = {
        "todo": [], "queued": [], "in_progress": [], "review": [],
        "completed": [], "failed": [],
    }
    for t in rows:
        st = t.status if t.status in columns else "todo"
        columns[st].append(task_dict(t, db))
    return {
        "columns": columns,
        "counts": {k: len(v) for k, v in columns.items()},
        "total": len(rows),
    }


@router.get("/{agent_id}")
def get_agent(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    out = agent_out(a, db, activity_limit=40, include_team=True)
    out["recent_tasks"] = [
        task_dict(t, db)
        for t in db.query(models.Task).filter_by(agent_id=a.id).order_by(models.Task.id.desc()).limit(30).all()
    ]
    # Team tasks for lead view
    report_ids = [r["id"] for r in out.get("reports") or []]
    if report_ids:
        team_tasks = (
            db.query(models.Task)
            .filter(models.Task.agent_id.in_(report_ids))
            .order_by(models.Task.id.desc())
            .limit(40)
            .all()
        )
        out["team_tasks"] = [task_dict(t, db) for t in team_tasks]
    else:
        out["team_tasks"] = []
    conv = (
        db.query(models.Conversation)
        .filter_by(user_id=user.id, agent_id=a.id)
        .order_by(models.Conversation.id.desc())
        .first()
    )
    out["chat"] = None
    if conv:
        msgs = (
            db.query(models.Message)
            .filter_by(conversation_id=conv.id)
            .order_by(models.Message.id)
            .all()
        )
        out["chat"] = {
            "conversation_id": conv.id,
            "messages": [{"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at} for m in msgs],
        }
    return out


@router.get("/{agent_id}/activity")
def agent_activity(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    logs = (
        db.query(models.ActivityLog)
        .filter_by(agent_id=a.id)
        .order_by(models.ActivityLog.id.desc())
        .limit(100)
        .all()
    )
    return [
        {"id": l.id, "type": l.type, "message": l.message, "created_at": l.created_at}
        for l in logs
    ]


@router.post("/{agent_id}/duplicate")
async def duplicate_agent(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    count = db.query(models.Agent).filter_by(user_id=user.id).count()
    max_agents = int(plan_limits(user.plan).get("agents") or 0)
    if user.role != "admin" and count >= max_agents:
        raise HTTPException(400, f"Your plan allows up to {max_agents} agents.")
    clone = models.Agent(
        user_id=user.id,
        name=f"{a.name} (copy)",
        template_type=a.template_type,
        personality=a.personality,
        model=a.model,
        idle_mode=a.idle_mode,
        status="paused",
        config=a.config,
        company_id=a.company_id,
        project_id=a.project_id,
        parent_id=a.parent_id,
        is_lead=False,
        hierarchy_role="member",
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    await log_activity(clone.id, user.id, "info", f"Cloned from agent #{a.id}")
    return agent_out(clone, db)

@router.post("/")
async def create_agent(data: AgentIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user.role != "admin" and (not user.subscription_active or user.plan in (None, "", "none")):
        raise HTTPException(402, "Choose a subscription plan to create agents")
    ensure_credits(db, user.id)
    count = db.query(models.Agent).filter_by(user_id=user.id).count()
    max_agents = int(plan_limits(user.plan).get("agents") or 0)
    if user.role != "admin" and count >= max_agents:
        raise HTTPException(400, f"Your plan allows up to {max_agents} agents. Upgrade on Billing.")

    is_lead = bool(data.is_lead or data.hierarchy_role == "lead" or data.template_type == "lead")
    role = data.hierarchy_role or ("lead" if is_lead else "member")
    if is_lead:
        role = "lead"
    parent_id = data.parent_id
    if parent_id:
        parent = _get_owned(parent_id, user, db)
        if is_lead and parent_id:
            pass  # leads can still report to a higher lead
    if is_lead and parent_id is None:
        parent_id = None

    company_id = data.company_id
    project_id = data.project_id
    if project_id:
        p = db.get(models.Project, project_id)
        if not p or (p.owner_user_id != user.id and user.role != "admin"):
            raise HTTPException(400, "Invalid project")
        if company_id is None:
            company_id = p.company_id
        elif company_id != p.company_id:
            raise HTTPException(400, "project_id does not belong to company_id")
    if company_id:
        c = db.get(models.Company, company_id)
        if not c or (c.owner_user_id != user.id and user.role != "admin"):
            raise HTTPException(400, "Invalid company")

    a = models.Agent(
        user_id=user.id, name=data.name, template_type=data.template_type,
        personality=data.personality, model=data.model, idle_mode=data.idle_mode,
        config=json.dumps(data.config),
        is_lead=is_lead,
        hierarchy_role=role,
        parent_id=parent_id,
        company_id=company_id,
        project_id=project_id,
    )
    db.add(a); db.commit(); db.refresh(a)
    role_msg = " as Lead" if is_lead else (f" under lead #{parent_id}" if parent_id else "")
    await log_activity(a.id, user.id, "info", f"Agent '{a.name}' created{role_msg} and online")
    return agent_out(a, db, include_team=True)

def _get_owned(agent_id: int, user, db) -> models.Agent:
    a = db.get(models.Agent, agent_id)
    if not a or (a.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Agent not found")
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
        if hierarchy_role not in ("lead", "member", "specialist"):
            raise HTTPException(400, "hierarchy_role must be lead, member, or specialist")
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

@router.patch("/{agent_id}")
def update_agent(agent_id: int, data: AgentUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    for field in ["name", "personality", "model", "idle_mode"]:
        v = getattr(data, field)
        if v is not None:
            setattr(a, field, v)
    if data.config is not None:
        a.config = json.dumps(data.config)
    if data.parent_id is not None or data.is_lead is not None or data.hierarchy_role is not None:
        _apply_hierarchy(
            a, db, user,
            parent_id=data.parent_id if data.parent_id is not None else None,
            clear_parent=data.parent_id == 0,
            is_lead=data.is_lead,
            hierarchy_role=data.hierarchy_role,
        )
    if data.company_id is not None or data.project_id is not None:
        company_id = data.company_id if data.company_id is not None else a.company_id
        project_id = data.project_id if data.project_id is not None else a.project_id
        # Allow clearing with 0
        if data.company_id == 0:
            company_id = None
        if data.project_id == 0:
            project_id = None
        if project_id:
            p = db.get(models.Project, project_id)
            if not p or (p.owner_user_id != user.id and user.role != "admin"):
                raise HTTPException(400, "Invalid project")
            if company_id is None:
                company_id = p.company_id
            elif company_id != p.company_id:
                raise HTTPException(400, "project_id does not belong to company_id")
        if company_id:
            c = db.get(models.Company, company_id)
            if not c or (c.owner_user_id != user.id and user.role != "admin"):
                raise HTTPException(400, "Invalid company")
        if data.company_id is not None:
            a.company_id = None if data.company_id == 0 else company_id
        if data.project_id is not None:
            a.project_id = None if data.project_id == 0 else project_id
        if data.company_id is not None and data.project_id is None and a.project_id:
            # Keep project if still under company; else clear
            p = db.get(models.Project, a.project_id)
            if not p or p.company_id != a.company_id:
                a.project_id = None
    db.commit()
    return agent_out(a, db, include_team=True)


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
    t = models.Task(
        agent_id=target.id,
        user_id=user.id,
        project_id=target.project_id,
        company_id=target.company_id,
        title=(data.title or data.description[:60]).strip(),
        description=f"[Delegated by {lead.name}] {data.description}",
        status="queued" if data.run_now else "todo",
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

@router.post("/{agent_id}/pause")
async def pause(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    a.status = "paused"; db.commit()
    await log_activity(a.id, a.user_id, "info", "Agent paused")
    return agent_out(a, db)

@router.post("/{agent_id}/resume")
async def resume(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    a.status = "active"; db.commit()
    await log_activity(a.id, a.user_id, "info", "Agent resumed")
    return agent_out(a, db)

@router.delete("/{agent_id}")
def delete_agent(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    # Re-parent reports to this agent's parent (or root)
    for child in db.query(models.Agent).filter_by(parent_id=a.id).all():
        child.parent_id = a.parent_id
    db.query(models.ActivityLog).filter_by(agent_id=a.id).delete()
    db.query(models.Task).filter_by(agent_id=a.id).delete()
    db.delete(a); db.commit()
    return {"ok": True}

async def _run_task(agent_id: int, user_id: int, task_id: int, description: str, agent_name: str):
    db = SessionLocal()
    try:
        t = db.get(models.Task, task_id)
        t.status = "in_progress"
        db.commit()
        a = db.get(models.Agent, agent_id)
        cfg = json.loads(a.config or "{}")
        model, personality = a.model, a.personality
        mode = mode_for_template(a.template_type)
        # Prefer Qwen Coder on VPS for coding agents if they left default model
        if mode == "coding" and model in ("vps-fast", "vps-quality"):
            model = "vps-qwen-coder"
    finally:
        db.close()

    try:
        await log_activity(agent_id, user_id, "thinking", f"Analysing task: {description[:80]}")
        prompt = (
            f"You are {agent_name}, an AI business agent. Personality: {personality}. "
            f"Business context: {json.dumps(cfg)}. Complete this task and produce the final "
            f"deliverable text (e.g. the email/message itself), no preamble:\n\n{description}"
        )
        db = SessionLocal()
        try:
            creds = credentials_for_user(db, user_id)
        finally:
            db.close()
        output = await complete(
            [{"role": "user", "content": prompt}], model, mode, credentials=creds,
        )

        inp, out = estimate_tokens(prompt), estimate_tokens(output)
        db = SessionLocal()
        try:
            user = db.get(models.User, user_id)
            t = db.get(models.Task, task_id)
            company_id = t.company_id if t else None
            project_id = t.project_id if t else None
            if t and t.agent_id and (not company_id or not project_id):
                agent_row = db.get(models.Agent, t.agent_id)
                if agent_row:
                    company_id = company_id or agent_row.company_id
                    project_id = project_id or agent_row.project_id
            charged = charge_usage(
                db, user, model, inp, out,
                company_id=company_id, project_id=project_id,
            )
            cost = charged["cost"]
            if t:
                t.tokens_used = (t.tokens_used or 0) + charged["tokens"]
                t.cost = (t.cost or 0) + cost
                db.commit()
        finally:
            db.close()
        await manager.broadcast(
            f"tokens:{user_id}",
            {"event": "usage", "tokens": inp + out, "cost": cost, "model": model,
             "tokens_used_period": charged.get("tokens_used_period")},
        )
        await log_activity(agent_id, user_id, "action", f"Drafted deliverable: {output[:100]}")

        if cfg.get("notify_email"):
            ok, detail = await channels.send_email(
                cfg["notify_email"], f"{agent_name}: task completed", output,
                credentials=creds,
            )
            await log_activity(agent_id, user_id, "email", detail)
        if cfg.get("notify_sms"):
            ok, detail = await channels.send_sms(
                cfg["notify_sms"], output[:300], credentials=creds,
            )
            await log_activity(agent_id, user_id, "sms", detail)

        db = SessionLocal()
        try:
            t = db.get(models.Task, task_id)
            t.status = "completed"
            t.result = output
            t.completed_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()
        await log_activity(agent_id, user_id, "done", "Task completed — deliverable saved and delivered")
        await manager.broadcast(
            f"agents:{user_id}",
            {"event": "task_done", "agent_id": agent_id, "task_id": task_id},
        )
    except Exception as e:
        db = SessionLocal()
        try:
            t = db.get(models.Task, task_id)
            if t:
                t.status = "failed"
                t.result = str(e)[:500]
                t.completed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
        await log_activity(agent_id, user_id, "info", f"Task failed: {str(e)[:120]}")
        await manager.broadcast(
            f"agents:{user_id}",
            {"event": "task_done", "agent_id": agent_id, "task_id": task_id},
        )

@router.post("/{agent_id}/tasks")
async def assign_task(agent_id: int, data: TaskIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    if data.run_now and a.status != "active":
        raise HTTPException(400, "Agent is paused — resume it before running tasks")
    ensure_credits(db, user.id)
    company_id = None
    if data.project_id:
        p = db.get(models.Project, data.project_id)
        if not p or p.owner_user_id != user.id:
            raise HTTPException(400, "Invalid project")
        company_id = p.company_id
    t = models.Task(
        agent_id=a.id,
        user_id=user.id,
        project_id=data.project_id,
        company_id=company_id or a.company_id,
        title=(data.title or data.description[:60]).strip(),
        description=data.description,
        status="queued" if data.run_now else "todo",
        priority=data.priority or "medium",
        labels=data.labels or "",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    await log_activity(a.id, user.id, "info", f"Task received: {data.description[:80]}")
    if data.run_now:
        await schedule_job(_run_task(a.id, user.id, t.id, data.description, a.name))
    return task_dict(t, db)


@router.get("/{agent_id}/tasks")
def list_tasks(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    tasks = db.query(models.Task).filter_by(agent_id=a.id).order_by(models.Task.id.desc()).limit(50).all()
    return [task_dict(t, db) for t in tasks]


@router.get("/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = db.get(models.Task, task_id)
    if not t or (t.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Task not found")
    return task_dict(t, db)


@router.patch("/tasks/{task_id}")
async def update_task(task_id: int, data: TaskStatusIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = db.get(models.Task, task_id)
    if not t or (t.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Task not found")
    if data.status is not None:
        try:
            st = normalize_status(data.status)
        except ValueError as e:
            raise HTTPException(400, str(e))
        t.status = st
        if st == "completed":
            t.completed_at = datetime.utcnow()
    if data.priority is not None:
        t.priority = data.priority
    if data.title is not None:
        t.title = data.title.strip()
    if data.description is not None:
        t.description = data.description.strip()
    if data.agent_id is not None:
        if data.agent_id:
            _get_owned(data.agent_id, user, db)
        t.agent_id = data.agent_id or None
    t.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(t)
    await manager.broadcast(f"agents:{user.id}", {"event": "task_updated", "task": task_dict(t, db)})
    return task_dict(t, db)


@router.post("/tasks/{task_id}/run")
async def run_task(task_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Execute (or re-run) a task with its assigned agent."""
    t = db.get(models.Task, task_id)
    if not t or (t.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Task not found")
    if not t.agent_id:
        raise HTTPException(400, "Assign an agent to this task first")
    a = _get_owned(t.agent_id, user, db)
    if a.status != "active":
        raise HTTPException(400, "Agent is paused")
    ensure_credits(db, user.id)
    t.status = "queued"
    t.result = ""
    db.commit()
    await log_activity(a.id, user.id, "info", f"Re-running task: {(t.title or t.description)[:80]}")
    await schedule_job(_run_task(a.id, user.id, t.id, t.description, a.name))
    return task_dict(t, db)


@router.post("/{agent_id}/chat")
async def chat_with_agent(agent_id: int, data: AgentChatIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    ensure_credits(db, user.id)
    mode = mode_for_template(a.template_type)
    model = a.model
    if mode == "coding" and model in ("vps-fast", "vps-quality"):
        model = "vps-qwen-coder"

    conv = None
    if data.conversation_id:
        conv = db.get(models.Conversation, data.conversation_id)
        if not conv or conv.user_id != user.id or conv.agent_id != a.id:
            conv = None
    if not conv:
        conv = (
            db.query(models.Conversation)
            .filter_by(user_id=user.id, agent_id=a.id)
            .order_by(models.Conversation.id.desc())
            .first()
        )
    if not conv:
        conv = models.Conversation(
            user_id=user.id, agent_id=a.id,
            title=f"Chat · {a.name}", mode=mode,
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

    text = (data.message or "").strip()
    db.add(models.Message(conversation_id=conv.id, role="user", content=text))
    db.commit()

    history = (
        db.query(models.Message)
        .filter_by(conversation_id=conv.id)
        .order_by(models.Message.id)
        .all()
    )
    team = _team_context(a, db)
    system = (
        f"You are {a.name}, an AI business agent. Personality: {a.personality}. "
        f"Template type: {a.template_type}. Config: {a.config}. {team}"
    )
    llm_messages = [{"role": "user", "content": system}]
    for m in history[-16:]:
        llm_messages.append({"role": m.role if m.role in ("user", "assistant") else "user", "content": m.content})

    creds = credentials_for_user(db, user.id)
    reply = ""
    async for chunk in stream_completion(llm_messages, model, mode, credentials=creds):
        reply += chunk
    reply = reply.strip()
    db.add(models.Message(conversation_id=conv.id, role="assistant", content=reply))
    db.commit()

    inp = sum(estimate_tokens(m["content"]) for m in llm_messages)
    out = estimate_tokens(reply)
    charged = charge_usage(db, user, model, inp, out)
    await manager.broadcast(f"tokens:{user.id}", {
        "event": "usage", "tokens": charged["tokens"], "cost": charged["cost"], "model": model,
        "tokens_used_period": charged.get("tokens_used_period"),
    })
    await log_activity(a.id, user.id, "action", f"Replied to a direct chat message")
    return {
        "reply": reply,
        "tokens": charged["tokens"],
        "cost": charged["cost"],
        "conversation_id": conv.id,
        # Best-effort from selected model + whether user/platform keys exist (not actual fallback path)
        "provider_hint": provider_hint(model, creds),
    }


@router.websocket("/{agent_id}/ws/chat")
async def agent_live_chat(ws: WebSocket, agent_id: int, token: str = Query("")):
    """Streaming live chat with a single agent."""
    db = SessionLocal()
    user = user_from_ws_token(token, db)
    if not user:
        db.close()
        await ws.close(code=4401)
        return
    a = db.get(models.Agent, agent_id)
    if not a or (a.user_id != user.id and user.role != "admin"):
        db.close()
        await ws.close(code=4404)
        return
    agent_id = a.id
    user_id = user.id
    agent_name = a.name
    personality = a.personality
    template_type = a.template_type
    model = a.model
    config_raw = a.config or "{}"
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            text = (data.get("message") or "").strip()
            if not text:
                continue
            if data.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
                continue

            bal = db.query(models.Balance).filter_by(user_id=user_id).first()
            user_obj = db.get(models.User, user_id)
            # light credit gate
            try:
                from ..auth_utils import ensure_credits
                ensure_credits(db, user_id)
            except HTTPException as he:
                await ws.send_text(json.dumps({"type": "error", "content": he.detail}))
                continue

            mode = mode_for_template(template_type)
            use_model = model
            if mode == "coding" and use_model in ("vps-fast", "vps-quality"):
                use_model = "vps-qwen-coder"

            conv = (
                db.query(models.Conversation)
                .filter_by(user_id=user_id, agent_id=agent_id)
                .order_by(models.Conversation.id.desc())
                .first()
            )
            if not conv:
                conv = models.Conversation(
                    user_id=user_id, agent_id=agent_id,
                    title=f"Chat · {agent_name}", mode=mode,
                )
                db.add(conv)
                db.commit()
                db.refresh(conv)
            await ws.send_text(json.dumps({
                "type": "conversation", "conversation_id": conv.id,
            }))

            db.add(models.Message(conversation_id=conv.id, role="user", content=text))
            db.commit()

            history = (
                db.query(models.Message)
                .filter_by(conversation_id=conv.id)
                .order_by(models.Message.id)
                .all()
            )
            a_live = db.get(models.Agent, agent_id)
            team = _team_context(a_live, db) if a_live else ""
            system = (
                f"You are {agent_name}, an AI business agent. Personality: {personality}. "
                f"Type: {template_type}. Config: {config_raw}. {team}"
            )
            llm_messages = [{"role": "user", "content": system}]
            for m in history[-16:]:
                llm_messages.append({
                    "role": m.role if m.role in ("user", "assistant") else "user",
                    "content": m.content,
                })

            await ws.send_text(json.dumps({"type": "start"}))
            creds = credentials_for_user(db, user_id)
            reply = ""
            async for chunk in stream_completion(llm_messages, use_model, mode, credentials=creds):
                reply += chunk
                await ws.send_text(json.dumps({"type": "chunk", "content": chunk}))
            reply = reply.strip()
            db.add(models.Message(conversation_id=conv.id, role="assistant", content=reply))
            db.commit()

            inp = sum(estimate_tokens(m["content"]) for m in llm_messages)
            out = estimate_tokens(reply)
            charged = charge_usage(db, user_obj, use_model, inp, out)
            await ws.send_text(json.dumps({
                "type": "done",
                "tokens": charged["tokens"],
                "cost": charged["cost"],
                "conversation_id": conv.id,
            }))
            await manager.broadcast(f"tokens:{user_id}", {
                "event": "usage", "tokens": charged["tokens"], "cost": charged["cost"],
                "model": use_model, "tokens_used_period": charged.get("tokens_used_period"),
            })
            await log_activity(agent_id, user_id, "action", "Live chat reply sent")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_text(json.dumps({"type": "error", "content": str(e)[:200]}))
        except Exception:
            pass
    finally:
        db.close()


@router.websocket("/ws")
async def agents_ws(ws: WebSocket, token: str = Query("")):
    db = SessionLocal()
    user = user_from_ws_token(token, db)
    db.close()
    if not user:
        await ws.close(code=4401); return
    channel = f"agents:{user.id}"
    await manager.connect(channel, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(channel, ws)
