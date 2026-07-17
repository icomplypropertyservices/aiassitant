"""Shared agent/task JSON serialization (reusable across routers)."""
from __future__ import annotations

import json
from sqlalchemy.orm import Session

from . import models
from .agent_roles import is_orchestrator, is_lead_agent, normalize_role
from .agent_prompts import team_context


def task_dict(t: models.Task, db: Session | None = None) -> dict:
    agent_name = None
    if t.agent_id and db:
        a = db.get(models.Agent, t.agent_id)
        agent_name = a.name if a else None
    human_name = None
    human_id = getattr(t, "human_id", None)
    if human_id and db:
        h = db.get(models.Human, human_id)
        human_name = h.name if h else None
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
        "human_id": human_id,
        "human_name": human_name,
        "assignee_type": getattr(t, "assignee_type", None) or ("human" if human_id else "agent"),
        "project_id": t.project_id,
        "project_name": project_name,
        "company_id": t.company_id,
        "tokens_used": t.tokens_used or 0,
        "cost": t.cost or 0.0,
        "created_at": t.created_at,
        "completed_at": t.completed_at,
        "updated_at": getattr(t, "updated_at", None),
    }


def _integrations_summary(a: models.Agent, db: Session) -> list[dict]:
    links = db.query(models.AgentIntegration).filter_by(agent_id=a.id).all()
    out = []
    for link in links:
        c = db.get(models.IntegrationConnection, link.connection_id)
        if not c:
            continue
        out.append({
            "connection_id": c.id,
            "app_id": c.app_id,
            "display_name": c.display_name or c.app_id,
            "status": c.status,
            "permission": link.permission or "full",
        })
    return out


def agent_out(
    a: models.Agent,
    db: Session,
    activity_limit: int = 8,
    include_team: bool = False,
    *,
    company_names: dict[int, str] | None = None,
    project_names: dict[int, str] | None = None,
) -> dict:
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
    reports_count = len(reports)
    orch = is_orchestrator(a)
    lead = is_lead_agent(a, reports_count=reports_count)
    role = normalize_role(a, reports_count=reports_count)

    company_name = None
    project_name = None
    if a.company_id:
        if company_names is not None:
            company_name = company_names.get(a.company_id)
        else:
            co = db.get(models.Company, a.company_id)
            company_name = co.name if co else None
    if a.project_id:
        if project_names is not None:
            project_name = project_names.get(a.project_id)
        else:
            pr = db.get(models.Project, a.project_id)
            project_name = pr.name if pr else None

    out = {
        "id": a.id,
        "name": a.name,
        "template_type": a.template_type,
        "personality": a.personality,
        "model": a.model,
        "status": a.status,
        "idle_mode": a.idle_mode,
        "company_id": a.company_id,
        "project_id": a.project_id,
        "company_name": company_name,
        "project_name": project_name,
        "parent_id": a.parent_id,
        "parent_name": parent.name if parent else None,
        "is_lead": lead,
        "is_orchestrator": orch,
        "hierarchy_role": role,
        "reports_count": reports_count,
        "config": json.loads(a.config or "{}"),
        "created_at": a.created_at,
        "stats": {
            "tasks": tasks,
            "completed": done,
            "open": open_tasks,
            "conversations": convs,
            "reports": reports_count,
        },
        "activity": [
            {"id": l.id, "type": l.type, "message": l.message, "created_at": l.created_at}
            for l in reversed(logs)
        ],
        "integrations": _integrations_summary(a, db),
    }
    if include_team:
        out["reports"] = [
            {
                "id": r.id,
                "name": r.name,
                "template_type": r.template_type,
                "status": r.status,
                "model": r.model,
                "hierarchy_role": normalize_role(r),
                "is_orchestrator": is_orchestrator(r),
                "open_tasks": db.query(models.Task).filter(
                    models.Task.agent_id == r.id,
                    models.Task.status.in_(["todo", "queued", "in_progress", "review"]),
                ).count(),
            }
            for r in reports
        ]
        out["team_context"] = team_context(a, db)
    return out


def load_name_maps(db: Session, agents: list[models.Agent]) -> tuple[dict[int, str], dict[int, str]]:
    """Batch company/project names for a list of agents."""
    cids = {a.company_id for a in agents if a.company_id}
    pids = {a.project_id for a in agents if a.project_id}
    company_names: dict[int, str] = {}
    project_names: dict[int, str] = {}
    if cids:
        for c in db.query(models.Company).filter(models.Company.id.in_(cids)).all():
            company_names[c.id] = c.name
    if pids:
        for p in db.query(models.Project).filter(models.Project.id.in_(pids)).all():
            project_names[p.id] = p.name
    return company_names, project_names


def agents_out_list(db: Session, agents: list[models.Agent]) -> list[dict]:
    company_names, project_names = load_name_maps(db, agents)
    return [
        agent_out(a, db, company_names=company_names, project_names=project_names)
        for a in agents
    ]
