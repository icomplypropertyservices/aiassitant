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
from ..agent_prompts import build_agent_system_prompt, build_task_prompt, team_context
from ..agent_roles import (
    agent_sort_key,
    find_orchestrator,
    is_orchestrator,
    promote_orchestrator,
    resolve_create_role,
)
from ..agent_serialize import agent_out, agents_out_list, task_dict
from ..agent_hierarchy import build_hierarchy_payload, ensure_main_orchestrator

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
    """Back-compat wrapper — prefer agent_prompts.team_context."""
    return team_context(a, db)


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
        log = models.ActivityLog(agent_id=agent_id, type=type_, message=message)
        db.add(log); db.commit()
        await manager.broadcast(f"agents:{user_id}", {
            "event": "activity", "agent_id": agent_id,
            "entry": {"id": log.id, "type": type_, "message": message, "created_at": log.created_at},
        })
    finally:
        db.close()

@router.get("/")
def list_agents(
    company_id: int | None = None,
    project_id: int | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(models.Agent).filter_by(user_id=user.id)
    if company_id is not None:
        q = q.filter_by(company_id=company_id)
    if project_id is not None:
        q = q.filter_by(project_id=project_id)
    agents = q.all()
    agents.sort(key=agent_sort_key)
    return agents_out_list(db, agents)


@router.get("/hierarchy")
def agent_hierarchy(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Full agent org tree: Main Orchestrator always first, then leads → reports."""
    return build_hierarchy_payload(db, user.id)


@router.post("/ensure-orchestrator")
async def ensure_orchestrator(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Create the Main AI Orchestrator if missing — always sits at top of hierarchy."""
    existing = find_orchestrator(db, user.id)
    if existing:
        promote_orchestrator(db, existing)
        db.commit()
        return agent_out(existing, db, include_team=True)

    ensure_credits(db, user.id)
    count = db.query(models.Agent).filter_by(user_id=user.id).count()
    max_agents = int(plan_limits(user.plan).get("agents") or 0)
    if user.role != "admin" and count >= max_agents:
        raise HTTPException(400, f"Your plan allows up to {max_agents} agents. Upgrade on Billing.")

    a = ensure_main_orchestrator(db, user)
    await log_activity(a.id, user.id, "info", "Main AI Orchestrator created — pinned at top of hierarchy")
    return agent_out(a, db, include_team=True)


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
        permission_level=getattr(a, "permission_level", None) or "operator",
        escalate_when=getattr(a, "escalate_when", None) or "on_failure",
        escalate_reason=getattr(a, "escalate_reason", None) or "",
        escalate_to=getattr(a, "escalate_to", None) or "parent",
        escalate_human_id=getattr(a, "escalate_human_id", None),
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

    role, is_lead, make_orch = resolve_create_role(
        hierarchy_role=data.hierarchy_role,
        template_type=data.template_type,
        is_lead=data.is_lead,
    )
    parent_id = data.parent_id
    if make_orch:
        parent_id = None
    if parent_id:
        _get_owned(parent_id, user, db)
    # Default non-orchestrator agents without parent → hang under main orchestrator
    if parent_id is None and not make_orch:
        orch = find_orchestrator(db, user.id)
        if orch:
            parent_id = orch.id

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

    from ..permissions import normalize_permission, normalize_escalate_when, normalize_escalate_to
    a = models.Agent(
        user_id=user.id, name=data.name, template_type=data.template_type,
        personality=data.personality, model=data.model, idle_mode=data.idle_mode,
        config=json.dumps(data.config),
        is_lead=is_lead,
        hierarchy_role=role,
        parent_id=parent_id,
        permission_level=normalize_permission(data.permission_level),
        escalate_when=normalize_escalate_when(data.escalate_when),
        escalate_reason=(data.escalate_reason or "").strip(),
        escalate_to=normalize_escalate_to(data.escalate_to),
        escalate_human_id=data.escalate_human_id,

        company_id=company_id,
        project_id=project_id,
    )
    db.add(a)
    db.flush()
    if make_orch:
        promote_orchestrator(db, a)
    db.commit()
    db.refresh(a)
    role_msg = " as Main Orchestrator" if make_orch else (" as Lead" if is_lead else (f" under #{parent_id}" if parent_id else ""))
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

@router.patch("/{agent_id}")
def update_agent(agent_id: int, data: AgentUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..permissions import normalize_permission, normalize_escalate_when, normalize_escalate_to
    a = _get_owned(agent_id, user, db)
    for field in ["name", "personality", "model", "idle_mode"]:
        v = getattr(data, field)
        if v is not None:
            setattr(a, field, v)
    if data.permission_level is not None:
        a.permission_level = normalize_permission(data.permission_level)
    if data.escalate_when is not None:
        a.escalate_when = normalize_escalate_when(data.escalate_when)
    if data.escalate_reason is not None:
        a.escalate_reason = (data.escalate_reason or "").strip()
    if data.escalate_to is not None:
        a.escalate_to = normalize_escalate_to(data.escalate_to)
    if data.escalate_human_id is not None:
        a.escalate_human_id = data.escalate_human_id or None
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
        cfg = json.loads((a.config if a else None) or "{}")
        model = a.model if a else "vps-fast"
        mode = mode_for_template(a.template_type if a else "")
        if mode == "coding" and model in ("vps-fast", "vps-quality"):
            model = "vps-qwen-coder"
        agent_snapshot_id = a.id if a else agent_id
    finally:
        db.close()

    try:
        await log_activity(agent_id, user_id, "thinking", f"Analysing task: {description[:80]}")
        db = SessionLocal()
        try:
            creds = credentials_for_user(db, user_id)
            agent_row = db.get(models.Agent, agent_snapshot_id)
            prompt = (
                build_task_prompt(db, agent_row, description, business_context=cfg)
                if agent_row
                else f"Complete this task:\n\n{description}"
            )
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


@router.get("/{agent_id}/skills")
def get_skills(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import list_skills_for_agent, SKILL_CATALOG
    a = _get_owned(agent_id, user, db)
    return {
        "agent_id": a.id,
        "skills": list_skills_for_agent(a, db),
        "catalog": SKILL_CATALOG,
    }


@router.put("/{agent_id}/skills")
def put_skills(agent_id: int, data: SkillsUpdateIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import set_enabled_skills, list_skills_for_agent
    a = _get_owned(agent_id, user, db)
    enabled = set_enabled_skills(db, a, data.enabled or [])
    return {"agent_id": a.id, "enabled": enabled, "skills": list_skills_for_agent(a, db)}


@router.post("/{agent_id}/skills/run")
async def run_skill(agent_id: int, data: SkillRunIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import execute_skill
    a = _get_owned(agent_id, user, db)
    ensure_credits(db, user.id)
    result = await execute_skill(db, a, user, data.skill, data.args or {})
    return result


@router.post("/{agent_id}/spawn")
async def spawn_child(agent_id: int, data: SpawnIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import execute_skill
    a = _get_owned(agent_id, user, db)
    return await execute_skill(db, a, user, "spawn_agent", data.model_dump())


@router.post("/{agent_id}/message-agent")
async def message_agent(agent_id: int, data: AgentMsgIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import execute_skill
    a = _get_owned(agent_id, user, db)
    ensure_credits(db, user.id)
    return await execute_skill(db, a, user, "message_agent", data.model_dump())


@router.get("/{agent_id}/messages")
def list_agent_messages(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    rows = (
        db.query(models.AgentMessage)
        .filter(
            models.AgentMessage.user_id == user.id,
            ((models.AgentMessage.from_agent_id == a.id) | (models.AgentMessage.to_agent_id == a.id)),
        )
        .order_by(models.AgentMessage.id.desc())
        .limit(80)
        .all()
    )
    out = []
    for m in rows:
        fa = db.get(models.Agent, m.from_agent_id)
        ta = db.get(models.Agent, m.to_agent_id)
        out.append({
            "id": m.id,
            "from_agent_id": m.from_agent_id,
            "from_name": fa.name if fa else "?",
            "to_agent_id": m.to_agent_id,
            "to_name": ta.name if ta else "?",
            "thread_key": m.thread_key,
            "content": m.content,
            "status": m.status,
            "created_at": m.created_at,
        })
    return {"messages": out}


@router.get("/{agent_id}/memory")
def list_memory(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    rows = (
        db.query(models.AgentMemory)
        .filter_by(agent_id=a.id)
        .order_by(models.AgentMemory.id.desc())
        .limit(100)
        .all()
    )
    return {
        "memories": [
            {
                "id": m.id,
                "kind": m.kind,
                "title": m.title,
                "content": m.content,
                "tags": m.tags,
                "knowledge_file_id": m.knowledge_file_id,
                "created_at": m.created_at,
            }
            for m in rows
        ]
    }


@router.post("/{agent_id}/memory")
async def save_memory(agent_id: int, data: MemoryIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import execute_skill
    a = _get_owned(agent_id, user, db)
    if data.save_to_training:
        return await execute_skill(
            db, a, user, "save_training",
            {"title": data.title, "content": data.content, "tags": data.tags},
        )
    return await execute_skill(
        db, a, user, "save_memory",
        {"title": data.title, "content": data.content, "kind": data.kind, "tags": data.tags},
    )


@router.delete("/{agent_id}/memory/{memory_id}")
def delete_memory(agent_id: int, memory_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    m = db.get(models.AgentMemory, memory_id)
    if not m or m.agent_id != a.id:
        raise HTTPException(404, "Memory not found")
    db.delete(m)
    db.commit()
    return {"ok": True}


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
    from ..agent_skills import run_skills_from_text
    from ..live_ops import emit_ops

    system = build_agent_system_prompt(db, a)
    llm_messages = [{"role": "user", "content": system}]
    for m in history[-16:]:
        llm_messages.append({"role": m.role if m.role in ("user", "assistant") else "user", "content": m.content})

    await emit_ops(
        user.id, kind="action", status="running",
        title=f"{a.name} thinking", detail=(text or "")[:200],
        agent_id=a.id, db=db,
    )

    creds = credentials_for_user(db, user.id)
    reply = ""
    async for chunk in stream_completion(llm_messages, model, mode, credentials=creds):
        reply += chunk
    reply = reply.strip()

    clean_reply, skill_results = await run_skills_from_text(db, a, user, reply)
    if skill_results:
        summary = "; ".join(
            f"{r.get('skill')}: {r.get('message') or r.get('error')}" for r in skill_results
        )
        if summary:
            clean_reply = (clean_reply + f"\n\n— Skills: {summary}").strip()

    db.add(models.Message(conversation_id=conv.id, role="assistant", content=clean_reply or reply))
    db.commit()

    inp = sum(estimate_tokens(m["content"]) for m in llm_messages)
    out = estimate_tokens(clean_reply or reply)
    charged = charge_usage(db, user, model, inp, out)
    await manager.broadcast(f"tokens:{user.id}", {
        "event": "usage", "tokens": charged["tokens"], "cost": charged["cost"], "model": model,
        "tokens_used_period": charged.get("tokens_used_period"),
    })
    await log_activity(a.id, user.id, "action", f"Replied to a direct chat message")
    await emit_ops(
        user.id, kind="action", status="done",
        title=f"{a.name} replied",
        detail=(clean_reply or reply)[:240],
        agent_id=a.id, db=db,
    )
    return {
        "reply": clean_reply or reply,
        "tokens": charged["tokens"],
        "cost": charged["cost"],
        "conversation_id": conv.id,
        "skills": skill_results,
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
            system = (
                build_agent_system_prompt(db, a_live)
                if a_live
                else f"You are {agent_name}. Personality: {personality}."
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
