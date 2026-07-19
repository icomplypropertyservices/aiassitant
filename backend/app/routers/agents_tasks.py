"""Agent task board and task CRUD endpoints."""
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..ownership import require_owned
from .. import models
from ..auth_utils import get_current_user, ensure_credits
from ..ws import manager
from ..async_jobs import schedule as schedule_job
from ..task_status import normalize_status, initial_task_status
from ..agent_serialize import task_dict, agent_out
from .agents_common import _get_owned, _run_task, log_activity, TaskIn, TaskStatusIn

log = logging.getLogger("app.agents")

router = APIRouter()


class WorkflowRunIn(BaseModel):
    """Start a named multi-agent workflow (targets → CRM → outreach, etc.)."""
    workflow_id: str = Field(..., description="Preset id e.g. sales_targets_crm_outreach")
    agent_id: int | None = None  # optional owner; defaults to orchestrator
    count: int | None = None
    niche: str = ""
    extra: str = ""
    params: dict[str, Any] = {}
    company_id: int | None = None
    project_id: int | None = None
    priority: str = "high"


@router.get("/workflows")
def list_workflows(user=Depends(get_current_user)):
    """Named multi-agent workflow presets for the agent dashboard."""
    from ..workflows import list_workflow_presets
    return {"workflows": list_workflow_presets()}


@router.get("/patterns")
def list_agent_patterns(
    q: str = "",
    category: str = "",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Reusable work patterns created by agents/leads (steps + checklists)."""
    from ..patterns import list_patterns
    return list_patterns(db, user, q=q or "", category=category or "")


class PatternIn(BaseModel):
    name: str
    description: str = ""
    steps: list[Any] = []
    checklist: list[Any] | str | None = None
    category: str = "general"
    tags: str = ""
    pattern_id: int | None = None
    agent_id: int | None = None


@router.post("/patterns")
def save_agent_pattern(
    data: PatternIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Create or update a workspace pattern (same as agent create_pattern skill)."""
    from ..patterns import save_pattern
    from ..agent_roles import find_orchestrator

    owner = None
    if data.agent_id:
        owner = _get_owned(data.agent_id, user, db)
    if not owner:
        owner = find_orchestrator(db, user.id)
    if not owner:
        owner = (
            db.query(models.Agent)
            .filter_by(user_id=user.id)
            .order_by(models.Agent.id)
            .first()
        )
    if not owner:
        raise HTTPException(400, "No agent to own the pattern")
    out = save_pattern(
        db,
        user,
        owner,
        name=data.name,
        description=data.description or "",
        steps=data.steps or [],
        checklist=data.checklist,
        category=data.category or "general",
        tags=data.tags or "",
        pattern_id=data.pattern_id,
    )
    if not out.get("ok"):
        raise HTTPException(400, out.get("error") or "Could not save pattern")
    return out


class PatternRunIn(BaseModel):
    pattern_id: int | str
    agent_id: int | None = None
    title: str = ""
    priority: str = "high"


@router.post("/patterns/run")
async def run_agent_pattern(
    data: PatternRunIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Run a saved pattern as a multi-agent workflow."""
    from ..agent_roles import find_orchestrator
    from ..orchestration.workflow_run import run_pattern

    ensure_credits(db, user.id)
    owner = None
    if data.agent_id:
        owner = _get_owned(data.agent_id, user, db)
    if not owner:
        owner = find_orchestrator(db, user.id)
    if not owner:
        owner = (
            db.query(models.Agent)
            .filter_by(user_id=user.id, status="active")
            .order_by(models.Agent.id)
            .first()
        )
    if not owner:
        raise HTTPException(400, "No active agent")
    result = await run_pattern(
        db, user, owner, data.pattern_id,
        title=data.title or "",
        priority=data.priority or "high",
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Pattern run failed")
    return result


@router.post("/workflows/run")
async def run_workflow(
    data: WorkflowRunIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Launch a multi-agent chain, e.g. get 50 sales targets → CRM → emails/calls → pipeline.
    Steps are assigned to sales / outreach / orchestrator via hierarchy routing.
    """
    from ..agent_roles import find_orchestrator
    from ..workflows import start_workflow, get_preset

    if not get_preset(data.workflow_id):
        raise HTTPException(404, f"Unknown workflow: {data.workflow_id}")
    ensure_credits(db, user.id)

    owner = None
    if data.agent_id:
        owner = _get_owned(data.agent_id, user, db)
    if not owner:
        owner = find_orchestrator(db, user.id)
    if not owner:
        # Fallback: any active agent
        owner = (
            db.query(models.Agent)
            .filter_by(user_id=user.id, status="active")
            .order_by(models.Agent.id)
            .first()
        )
    if not owner:
        raise HTTPException(400, "No active agent to own the workflow — create a team first")

    result = await start_workflow(
        db,
        user,
        owner,
        data.workflow_id,
        count=data.count,
        niche=data.niche or "",
        extra=data.extra or "",
        params=data.params or {},
        company_id=data.company_id,
        project_id=data.project_id,
        priority=data.priority or "high",
    )
    if not result.get("ok", True) and result.get("error"):
        raise HTTPException(400, result.get("error"))
    return result


@router.get("/{agent_id}/dashboard")
def agent_dashboard(
    agent_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Per-agent dashboard payload: identity/settings summary, task stats,
    recent tasks + activity, and suggested workflows for this role.
    """
    from ..workflows import list_workflow_presets
    from ..patterns import list_patterns
    from ..agent_scaffold import recommended_model, map_model

    a = _get_owned(agent_id, user, db)
    tasks = (
        db.query(models.Task)
        .filter_by(agent_id=a.id)
        .order_by(models.Task.id.desc())
        .limit(40)
        .all()
    )
    counts = {
        "todo": 0, "queued": 0, "in_progress": 0, "review": 0,
        "completed": 0, "failed": 0, "total": len(tasks),
    }
    for t in tasks:
        st = (t.status or "todo")
        if st in counts:
            counts[st] += 1
    open_n = counts["todo"] + counts["queued"] + counts["in_progress"] + counts["review"]

    activity = (
        db.query(models.ActivityLog)
        .filter_by(agent_id=a.id)
        .order_by(models.ActivityLog.id.desc())
        .limit(25)
        .all()
    )

    tpl = (a.template_type or "").lower()
    role = (a.hierarchy_role or "").lower()
    # Suggest sales workflows for sales/outreach/orchestrator/lead
    all_wf = list_workflow_presets()
    if tpl in ("sales", "outreach", "lead_gen", "crm") or "sales" in (a.name or "").lower():
        suggested = [w for w in all_wf if w.get("category") == "sales"]
    elif tpl in ("support", "booking") or "support" in (a.name or "").lower():
        suggested = [w for w in all_wf if w.get("category") == "support"]
    elif role in ("orchestrator", "lead") or tpl in ("orchestrator", "lead"):
        suggested = all_wf
    else:
        suggested = all_wf[:2]

    rec_model = recommended_model(a.template_type, a.hierarchy_role)
    current_model = map_model(a.model)

    return {
        "agent": agent_out(a, db, activity_limit=0),
        "settings": {
            "model": current_model,
            "recommended_model": rec_model,
            "model_upgrade_suggested": current_model in ("fast", "small", "medium")
            and rec_model not in ("fast", "small", "medium"),
            "status": a.status,
            "idle_mode": a.idle_mode,
            "permission_level": a.permission_level,
            "hierarchy_role": a.hierarchy_role,
            "template_type": a.template_type,
            "escalate_when": a.escalate_when,
            "escalate_to": a.escalate_to,
            "never_idle": (a.idle_mode or "") == "never_idle",
        },
        "stats": {
            **counts,
            "open": open_n,
            "tokens_used": sum(int(t.tokens_used or 0) for t in tasks),
            "cost": round(sum(float(t.cost or 0) for t in tasks), 4),
        },
        "tasks": [task_dict(t, db, lean=True) for t in tasks[:20]],
        "activity": [
            {
                "id": row.id,
                "type": row.type,
                "message": row.message,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in activity
        ],
        "workflows": suggested,
        "all_workflows": all_wf,
        "patterns": (list_patterns(db, user, limit=20).get("patterns") or []),
    }


@router.get("/tasks/board")
def tasks_board(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """All tasks for the subscriber — kanban workflow (batch name load)."""
    from ..agent_serialize import tasks_out_list
    rows = (
        db.query(models.Task)
        .filter_by(user_id=user.id)
        .order_by(models.Task.id.desc())
        .limit(200)
        .all()
    )
    serialized = tasks_out_list(db, rows, lean=True)
    columns = {
        "todo": [], "queued": [], "in_progress": [], "review": [],
        "completed": [], "failed": [],
    }
    for d in serialized:
        st = d.get("status") if d.get("status") in columns else "todo"
        columns[st].append(d)
    return {
        "columns": columns,
        "counts": {k: len(v) for k, v in columns.items()},
        "total": len(rows),
    }

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
    # Active + run_now → queued (autonomy/runner); run_now=false or paused → todo
    status = initial_task_status(agent=a, assignee_type="agent", run_now=data.run_now)
    t = models.Task(
        agent_id=a.id,
        user_id=user.id,
        project_id=data.project_id,
        company_id=company_id or a.company_id,
        title=(data.title or data.description[:60]).strip(),
        description=data.description,
        status=status,
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
    t = require_owned(
        db, models.Task, task_id, user,
        user_field='user_id', not_found="Task not found",
    )
    return task_dict(t, db)


@router.patch("/tasks/{task_id}")
async def update_task(task_id: int, data: TaskStatusIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = require_owned(
        db, models.Task, task_id, user,
        user_field='user_id', not_found="Task not found",
    )
    prev_status = (t.status or "")
    terminal_hit = None
    if data.status is not None:
        try:
            st = normalize_status(data.status)
        except ValueError as e:
            raise HTTPException(400, str(e))
        t.status = st
        if st == "completed":
            t.completed_at = datetime.utcnow()
        if st in ("completed", "failed") and prev_status != st:
            terminal_hit = st
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
    # Manual board complete/fail must advance auto-chain the same way task_runner does
    if terminal_hit:
        try:
            from ..task_chain import on_task_finished
            await on_task_finished(db, t, final_status=terminal_hit, commit=False)
        except Exception as chain_err:
            log.warning("task_chain on PATCH status failed: %s", chain_err)
    db.commit()
    db.refresh(t)
    await manager.broadcast(f"agents:{user.id}", {"event": "task_updated", "task": task_dict(t, db)})
    return task_dict(t, db)


@router.post("/tasks/{task_id}/run")
async def run_task(task_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Execute (or re-run) a task with its assigned agent."""
    t = require_owned(
        db, models.Task, task_id, user,
        user_field='user_id', not_found="Task not found",
    )
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
