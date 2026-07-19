"""Agent task board and task CRUD endpoints."""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..ownership import require_owned
from .. import models
from ..auth_utils import get_current_user, ensure_credits
from ..ws import manager
from ..async_jobs import schedule as schedule_job
from ..task_status import normalize_status, initial_task_status
from ..agent_serialize import task_dict
from .agents_common import _get_owned, _run_task, log_activity, TaskIn, TaskStatusIn

log = logging.getLogger("app.agents")

router = APIRouter()


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
