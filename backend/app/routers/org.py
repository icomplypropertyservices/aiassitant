"""Companies → Projects → Tasks hierarchy for subscribers."""
import asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..auth_utils import get_current_user, ensure_credits
from ..plans import plan_limits
from ..task_status import normalize_status

router = APIRouter(prefix="/org", tags=["org"])


def _require_active(user: models.User):
    if user.role == "admin":
        return
    if not user.subscription_active or user.plan in (None, "", "none"):
        raise HTTPException(402, "Choose a subscription plan to continue")


def _company_owned(db, company_id: int, user) -> models.Company:
    c = db.get(models.Company, company_id)
    if not c or (c.owner_user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Company not found")
    return c


def _project_owned(db, project_id: int, user) -> models.Project:
    p = db.get(models.Project, project_id)
    if not p or (p.owner_user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Project not found")
    return p


class CompanyIn(BaseModel):
    name: str = Field(min_length=1)
    industry: str = ""
    notes: str = ""


class ProjectIn(BaseModel):
    company_id: int
    name: str = Field(min_length=1)
    description: str = ""
    status: str = "active"


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class TaskIn(BaseModel):
    project_id: int
    title: str = ""
    description: str = Field(min_length=1)
    agent_id: int | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    agent_id: int | None = None


class TaskRunIn(BaseModel):
    agent_id: int | None = None


def company_out(c: models.Company, db: Session):
    projects = db.query(models.Project).filter_by(company_id=c.id).count()
    tasks = db.query(models.Task).filter_by(company_id=c.id).count()
    return {
        "id": c.id,
        "name": c.name,
        "industry": c.industry,
        "notes": c.notes,
        "created_at": c.created_at,
        "project_count": projects,
        "task_count": tasks,
    }


def project_out(p: models.Project, db: Session):
    tasks = db.query(models.Task).filter_by(project_id=p.id).count()
    open_tasks = db.query(models.Task).filter(
        models.Task.project_id == p.id,
        models.Task.status.in_(["todo", "queued", "in_progress"]),
    ).count()
    return {
        "id": p.id,
        "company_id": p.company_id,
        "name": p.name,
        "description": p.description,
        "status": p.status,
        "created_at": p.created_at,
        "task_count": tasks,
        "open_tasks": open_tasks,
    }


def task_out(t: models.Task):
    return {
        "id": t.id,
        "project_id": t.project_id,
        "company_id": t.company_id,
        "agent_id": t.agent_id,
        "title": t.title or (t.description or "")[:60],
        "description": t.description,
        "result": t.result or "",
        "status": t.status,
        "tokens_used": t.tokens_used or 0,
        "cost": t.cost or 0.0,
        "created_at": t.created_at,
        "completed_at": t.completed_at,
    }


@router.get("/tree")
def org_tree(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Subscriber → companies → projects → tasks summary."""
    _require_active(user)
    companies = db.query(models.Company).filter_by(owner_user_id=user.id).order_by(models.Company.id.desc()).all()
    tree = []
    for c in companies:
        projects = db.query(models.Project).filter_by(company_id=c.id).order_by(models.Project.id.desc()).all()
        tree.append({
            **company_out(c, db),
            "projects": [
                {
                    **project_out(p, db),
                    "tasks": [
                        task_out(t) for t in
                        db.query(models.Task).filter_by(project_id=p.id).order_by(models.Task.id.desc()).limit(50).all()
                    ],
                }
                for p in projects
            ],
        })
    return {
        "subscriber": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "plan": user.plan,
            "subscription_active": user.subscription_active or user.role == "admin",
        },
        "companies": tree,
    }


@router.get("/companies")
def list_companies(db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_active(user)
    rows = db.query(models.Company).filter_by(owner_user_id=user.id).order_by(models.Company.id.desc()).all()
    return [company_out(c, db) for c in rows]


@router.post("/companies")
def create_company(data: CompanyIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_active(user)
    limits = plan_limits(user.plan)
    count = db.query(models.Company).filter_by(owner_user_id=user.id).count()
    max_c = int(limits.get("companies") or 0)
    if user.role != "admin" and count >= max_c:
        raise HTTPException(400, f"Your plan allows {max_c} companies. Upgrade on Billing.")
    c = models.Company(
        owner_user_id=user.id,
        name=data.name.strip(),
        industry=data.industry.strip(),
        notes=data.notes.strip(),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return company_out(c, db)


@router.patch("/companies/{company_id}")
def update_company(company_id: int, data: CompanyIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = _company_owned(db, company_id, user)
    c.name = data.name.strip()
    c.industry = data.industry.strip()
    c.notes = data.notes.strip()
    db.commit()
    return company_out(c, db)


@router.delete("/companies/{company_id}")
def delete_company(company_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = _company_owned(db, company_id, user)
    projects = db.query(models.Project).filter_by(company_id=c.id).all()
    project_ids = [p.id for p in projects]
    for p in projects:
        db.query(models.Task).filter_by(project_id=p.id).delete()
        db.delete(p)
    # Detach agents linked to this company / its projects (avoid orphan FKs)
    for a in db.query(models.Agent).filter_by(company_id=c.id).all():
        a.company_id = None
        if a.project_id and a.project_id in project_ids:
            a.project_id = None
    if project_ids:
        for a in db.query(models.Agent).filter(models.Agent.project_id.in_(project_ids)).all():
            a.project_id = None
            if a.company_id == c.id:
                a.company_id = None
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.get("/projects")
def list_projects(company_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_active(user)
    q = db.query(models.Project).filter_by(owner_user_id=user.id)
    if company_id:
        q = q.filter_by(company_id=company_id)
    return [project_out(p, db) for p in q.order_by(models.Project.id.desc()).all()]


@router.post("/projects")
def create_project(data: ProjectIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_active(user)
    _company_owned(db, data.company_id, user)
    limits = plan_limits(user.plan)
    count = db.query(models.Project).filter_by(owner_user_id=user.id).count()
    max_p = int(limits.get("projects") or 0)
    if user.role != "admin" and count >= max_p:
        raise HTTPException(400, f"Your plan allows {max_p} projects. Upgrade on Billing.")
    p = models.Project(
        company_id=data.company_id,
        owner_user_id=user.id,
        name=data.name.strip(),
        description=data.description.strip(),
        status=data.status or "active",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return project_out(p, db)


@router.patch("/projects/{project_id}")
def update_project(project_id: int, data: ProjectUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    p = _project_owned(db, project_id, user)
    if data.name is not None:
        p.name = data.name.strip()
    if data.description is not None:
        p.description = data.description.strip()
    if data.status is not None:
        p.status = data.status
    db.commit()
    return project_out(p, db)


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    p = _project_owned(db, project_id, user)
    db.query(models.Task).filter_by(project_id=p.id).delete()
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.get("/tasks")
def list_tasks(project_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_active(user)
    q = db.query(models.Task).filter_by(user_id=user.id)
    if project_id:
        q = q.filter_by(project_id=project_id)
    return [task_out(t) for t in q.order_by(models.Task.id.desc()).limit(100).all()]


@router.post("/tasks")
def create_task(data: TaskIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_active(user)
    p = _project_owned(db, data.project_id, user)
    if data.agent_id:
        a = db.get(models.Agent, data.agent_id)
        if not a or a.user_id != user.id:
            raise HTTPException(400, "Invalid agent")
    t = models.Task(
        project_id=p.id,
        company_id=p.company_id,
        user_id=user.id,
        agent_id=data.agent_id,
        title=(data.title or data.description[:60]).strip(),
        description=data.description.strip(),
        status="todo",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return task_out(t)


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, data: TaskUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = db.get(models.Task, task_id)
    if not t or (t.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Task not found")
    if data.title is not None:
        t.title = data.title.strip()
    if data.description is not None:
        t.description = data.description.strip()
    if data.status is not None:
        try:
            st = normalize_status(data.status)
        except ValueError as e:
            raise HTTPException(400, str(e))
        t.status = st
        if st == "completed":
            t.completed_at = datetime.utcnow()
    if data.agent_id is not None:
        if data.agent_id:
            a = db.get(models.Agent, data.agent_id)
            if not a or (a.user_id != user.id and user.role != "admin"):
                raise HTTPException(400, "Invalid agent")
            t.agent_id = data.agent_id
        else:
            t.agent_id = None
    if hasattr(t, "updated_at"):
        t.updated_at = datetime.utcnow()
    db.commit()
    return task_out(t)


@router.post("/tasks/{task_id}/run")
async def run_org_task(
    task_id: int,
    data: TaskRunIn | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Execute an org task via the same agent run path as /agents/tasks/{id}/run."""
    from .agents import _run_task, log_activity

    t = db.get(models.Task, task_id)
    if not t or (t.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Task not found")

    body = data or TaskRunIn()
    agent_id = body.agent_id if body.agent_id is not None else t.agent_id
    if body.agent_id is not None:
        a = db.get(models.Agent, body.agent_id)
        if not a or (a.user_id != user.id and user.role != "admin"):
            raise HTTPException(400, "Invalid agent")
        t.agent_id = body.agent_id
        agent_id = body.agent_id
    if not agent_id:
        raise HTTPException(400, "Assign an agent to this task first (or pass agent_id)")

    a = db.get(models.Agent, agent_id)
    if not a or (a.user_id != user.id and user.role != "admin"):
        raise HTTPException(400, "Invalid agent")
    if a.status != "active":
        raise HTTPException(400, "Agent is paused")

    ensure_credits(db, user.id)
    t.status = "queued"
    t.result = ""
    if hasattr(t, "updated_at"):
        t.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(t)
    await log_activity(a.id, user.id, "info", f"Running org task: {(t.title or t.description)[:80]}")
    asyncio.create_task(_run_task(a.id, user.id, t.id, t.description, a.name))
    return task_out(t)


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = db.get(models.Task, task_id)
    if not t or (t.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Task not found")
    db.delete(t)
    db.commit()
    return {"ok": True}
