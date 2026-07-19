"""Shared agent/task JSON serialization (reusable across routers).

List endpoints use batch queries — avoid per-row N+1 on agent lists / task boards.
"""
from __future__ import annotations

import json
from collections import defaultdict
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models
from .agent_roles import is_orchestrator, is_lead_agent, normalize_role
from .agent_prompts import team_context


def task_dict(
    t: models.Task,
    db: Session | None = None,
    *,
    agent_names: dict[int, str] | None = None,
    human_names: dict[int, str] | None = None,
    project_names: dict[int, str] | None = None,
    lean: bool = False,
) -> dict:
    agent_name = None
    if t.agent_id:
        if agent_names is not None:
            agent_name = agent_names.get(t.agent_id)
        elif db:
            a = db.get(models.Agent, t.agent_id)
            agent_name = a.name if a else None
    human_name = None
    human_id = getattr(t, "human_id", None)
    if human_id:
        if human_names is not None:
            human_name = human_names.get(human_id)
        elif db:
            h = db.get(models.Human, human_id)
            human_name = h.name if h else None
    project_name = None
    if t.project_id:
        if project_names is not None:
            project_name = project_names.get(t.project_id)
        elif db:
            p = db.get(models.Project, t.project_id)
            project_name = p.name if p else None
    out = {
        "id": t.id,
        "title": t.title or (t.description or "")[:60],
        "description": (t.description or "")[:500] if lean else t.description,
        "status": t.status,
        "priority": getattr(t, "priority", None) or "medium",
        "labels": getattr(t, "labels", None) or "",
        "result": "" if lean else (t.result or ""),
        "agent_id": t.agent_id,
        "agent_name": agent_name,
        "human_id": human_id,
        "human_name": human_name,
        "assignee_type": getattr(t, "assignee_type", None) or ("human" if human_id else "agent"),
        "project_id": t.project_id,
        "project_name": project_name,
        "company_id": t.company_id,
        "parent_task_id": getattr(t, "parent_task_id", None),
        "meeting_id": getattr(t, "meeting_id", None),
        "tokens_used": t.tokens_used or 0,
        "cost": t.cost or 0.0,
        "created_at": t.created_at,
        "completed_at": t.completed_at,
        "updated_at": getattr(t, "updated_at", None),
    }
    return out


def tasks_out_list(db: Session, tasks: list[models.Task], *, lean: bool = True) -> list[dict]:
    """Batch name resolution for task boards (fast)."""
    if not tasks:
        return []
    agent_ids = {t.agent_id for t in tasks if t.agent_id}
    human_ids = {getattr(t, "human_id", None) for t in tasks if getattr(t, "human_id", None)}
    project_ids = {t.project_id for t in tasks if t.project_id}
    agent_names: dict[int, str] = {}
    human_names: dict[int, str] = {}
    project_names: dict[int, str] = {}
    if agent_ids:
        for a in db.query(models.Agent.id, models.Agent.name).filter(models.Agent.id.in_(agent_ids)).all():
            agent_names[a.id] = a.name
    if human_ids:
        for h in db.query(models.Human.id, models.Human.name).filter(models.Human.id.in_(human_ids)).all():
            human_names[h.id] = h.name
    if project_ids:
        for p in db.query(models.Project.id, models.Project.name).filter(models.Project.id.in_(project_ids)).all():
            project_names[p.id] = p.name
    return [
        task_dict(
            t, db,
            agent_names=agent_names,
            human_names=human_names,
            project_names=project_names,
            lean=lean,
        )
        for t in tasks
    ]


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
    parent_names: dict[int, str] | None = None,
    reports_count_map: dict[int, int] | None = None,
    stats_map: dict[int, dict] | None = None,
    lean: bool = False,
) -> dict:
    # List path: skip activity + integrations + multi-count queries
    if lean:
        reports_count = (reports_count_map or {}).get(a.id, 0)
        orch = is_orchestrator(a)
        lead = is_lead_agent(a, reports_count=reports_count)
        role = normalize_role(a, reports_count=reports_count)
        company_name = company_names.get(a.company_id) if company_names and a.company_id else None
        project_name = project_names.get(a.project_id) if project_names and a.project_id else None
        parent_name = parent_names.get(a.parent_id) if parent_names and a.parent_id else None
        stats = (stats_map or {}).get(a.id) or {
            "tasks": 0, "completed": 0, "open": 0, "conversations": 0, "reports": reports_count,
        }
        stats["reports"] = reports_count
        return {
            "id": a.id,
            "name": a.name,
            "template_type": a.template_type,
            "personality": (a.personality or "")[:120],
            "model": a.model,
            "status": a.status,
            "idle_mode": a.idle_mode,
            "permission_level": getattr(a, "permission_level", None) or "operator",
            "escalate_when": getattr(a, "escalate_when", None) or "on_failure",
            "escalate_reason": "",
            "escalate_to": getattr(a, "escalate_to", None) or "parent",
            "escalate_human_id": getattr(a, "escalate_human_id", None),
            "company_id": a.company_id,
            "project_id": a.project_id,
            "company_name": company_name,
            "project_name": project_name,
            "parent_id": a.parent_id,
            "parent_name": parent_name,
            "is_lead": lead,
            "is_orchestrator": orch,
            "hierarchy_role": role,
            "reports_count": reports_count,
            "config": {},
            "created_at": a.created_at,
            "stats": stats,
            "activity": [],
            "integrations": [],
        }

    logs = (
        db.query(models.ActivityLog)
        .filter_by(agent_id=a.id)
        .order_by(models.ActivityLog.id.desc())
        .limit(activity_limit)
        .all()
    ) if activity_limit else []
    if stats_map is not None and a.id in stats_map:
        st = stats_map[a.id]
        tasks, done, open_tasks, convs = st["tasks"], st["completed"], st["open"], st["conversations"]
    else:
        tasks = db.query(models.Task).filter_by(agent_id=a.id).count()
        done = db.query(models.Task).filter_by(agent_id=a.id, status="completed").count()
        open_tasks = db.query(models.Task).filter(
            models.Task.agent_id == a.id,
            models.Task.status.in_(["todo", "queued", "in_progress", "review"]),
        ).count()
        convs = db.query(models.Conversation).filter_by(agent_id=a.id, user_id=a.user_id).count()
    reports = db.query(models.Agent).filter_by(parent_id=a.id).all()
    parent = db.get(models.Agent, a.parent_id) if a.parent_id else None
    reports_count = len(reports) if reports_count_map is None else reports_count_map.get(a.id, len(reports))
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
        "permission_level": getattr(a, "permission_level", None) or "operator",
        "escalate_when": getattr(a, "escalate_when", None) or "on_failure",
        "escalate_reason": getattr(a, "escalate_reason", None) or "",
        "escalate_to": getattr(a, "escalate_to", None) or "parent",
        "escalate_human_id": getattr(a, "escalate_human_id", None),
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


def _batch_reports_count(db: Session, agents: list[models.Agent]) -> dict[int, int]:
    ids = [a.id for a in agents]
    if not ids:
        return {}
    rows = (
        db.query(models.Agent.parent_id, func.count(models.Agent.id))
        .filter(models.Agent.parent_id.in_(ids))
        .group_by(models.Agent.parent_id)
        .all()
    )
    return {int(pid): int(n) for pid, n in rows if pid}


def _batch_task_stats(db: Session, agents: list[models.Agent]) -> dict[int, dict]:
    """One GROUP BY for all agents' task stats (list speed)."""
    ids = [a.id for a in agents]
    out: dict[int, dict] = {
        i: {"tasks": 0, "completed": 0, "open": 0, "conversations": 0, "reports": 0}
        for i in ids
    }
    if not ids:
        return out
    open_statuses = ("todo", "queued", "in_progress", "review")
    # total + completed + open in few queries
    for aid, n in (
        db.query(models.Task.agent_id, func.count(models.Task.id))
        .filter(models.Task.agent_id.in_(ids))
        .group_by(models.Task.agent_id)
        .all()
    ):
        if aid in out:
            out[aid]["tasks"] = int(n)
    for aid, n in (
        db.query(models.Task.agent_id, func.count(models.Task.id))
        .filter(models.Task.agent_id.in_(ids), models.Task.status == "completed")
        .group_by(models.Task.agent_id)
        .all()
    ):
        if aid in out:
            out[aid]["completed"] = int(n)
    for aid, n in (
        db.query(models.Task.agent_id, func.count(models.Task.id))
        .filter(models.Task.agent_id.in_(ids), models.Task.status.in_(open_statuses))
        .group_by(models.Task.agent_id)
        .all()
    ):
        if aid in out:
            out[aid]["open"] = int(n)
    for aid, n in (
        db.query(models.Conversation.agent_id, func.count(models.Conversation.id))
        .filter(models.Conversation.agent_id.in_(ids))
        .group_by(models.Conversation.agent_id)
        .all()
    ):
        if aid in out:
            out[aid]["conversations"] = int(n)
    return out


def agents_out_list(db: Session, agents: list[models.Agent], *, lean: bool = True) -> list[dict]:
    """Fast list serializer — lean=True skips activity/integrations per agent (default)."""
    if not agents:
        return []
    company_names, project_names = load_name_maps(db, agents)
    parent_ids = {a.parent_id for a in agents if a.parent_id}
    parent_names: dict[int, str] = {}
    if parent_ids:
        for row in db.query(models.Agent.id, models.Agent.name).filter(models.Agent.id.in_(parent_ids)).all():
            parent_names[row.id] = row.name
    reports_count_map = _batch_reports_count(db, agents)
    stats_map = _batch_task_stats(db, agents) if lean else {}
    return [
        agent_out(
            a, db,
            activity_limit=0 if lean else 8,
            company_names=company_names,
            project_names=project_names,
            parent_names=parent_names,
            reports_count_map=reports_count_map,
            stats_map=stats_map if lean else None,
            lean=lean,
        )
        for a in agents
    ]
