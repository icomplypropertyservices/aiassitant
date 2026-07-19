"""Workspace read / search / comment skill handlers."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models


async def _skill_search_memory(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    q = (args.get("query") or args.get("q") or "").strip().lower()
    scope = (args.get("scope") or "workspace").lower()  # self | workspace
    try:
        limit = min(40, int(args.get("limit") or 20))
    except Exception:
        limit = 20
    if scope == "self":
        mems = (
            db.query(models.AgentMemory)
            .filter_by(agent_id=agent.id)
            .order_by(models.AgentMemory.id.desc())
            .limit(80)
            .all()
        )
    else:
        # All agents under this account (read workspace memories)
        mems = (
            db.query(models.AgentMemory)
            .filter_by(user_id=user.id)
            .order_by(models.AgentMemory.id.desc())
            .limit(120)
            .all()
        )
    if q:
        hits = [
            m for m in mems
            if q in (m.content or "").lower() or q in (m.title or "").lower() or q in (m.tags or "").lower()
        ]
    else:
        hits = list(mems)
    return {
        "ok": True,
        "count": len(hits[:limit]),
        "hits": [
            {
                "id": h.id,
                "agent_id": h.agent_id,
                "title": h.title,
                "content": (h.content or "")[:500],
                "kind": h.kind,
                "tags": h.tags,
            }
            for h in hits[:limit]
        ],
    }

async def _skill_search_knowledge(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Search training library text (agents can read the full library by default)."""
    from ..training_context import files_for_agent

    q = (args.get("query") or args.get("q") or "").strip().lower()
    try:
        limit = min(25, int(args.get("limit") or 12))
    except Exception:
        limit = 12
    files = files_for_agent(db, agent, max_files=80, max_chars=200_000)
    hits = []
    for f in files:
        name = (f.name or "").lower()
        body = (f.content_text or "")
        tags = (f.tags or "").lower()
        if not q or q in name or q in tags or q in body.lower():
            # Snippet around first match
            snippet = body[:400]
            if q and q in body.lower():
                idx = body.lower().find(q)
                start = max(0, idx - 80)
                snippet = body[start : start + 360]
            hits.append({
                "id": f.id,
                "name": f.name,
                "tags": f.tags,
                "snippet": snippet,
                "storage": f.storage,
            })
            if len(hits) >= limit:
                break
    return {
        "ok": True,
        "query": q or None,
        "count": len(hits),
        "files": hits,
        "message": f"Found {len(hits)} training file(s)" + (f" matching “{q}”" if q else ""),
    }

async def _skill_list_tasks(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        limit = min(80, int(args.get("limit") or 30))
    except Exception:
        limit = 30
    q = (args.get("q") or "").strip().lower()
    status = (args.get("status") or "").strip().lower() or None
    agent_filter = args.get("agent_id")
    query = db.query(models.Task).filter_by(user_id=user.id)
    if status:
        query = query.filter(models.Task.status == status)
    if agent_filter is not None:
        try:
            query = query.filter(models.Task.agent_id == int(agent_filter))
        except Exception:
            pass
    rows = query.order_by(models.Task.id.desc()).limit(120).all()
    out = []
    for t in rows:
        blob = f"{t.title or ''} {t.description or ''} {t.labels or ''}".lower()
        if q and q not in blob:
            continue
        out.append({
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "priority": t.priority,
            "agent_id": t.agent_id,
            "human_id": t.human_id,
            "project_id": t.project_id,
            "description": (t.description or "")[:300],
        })
        if len(out) >= limit:
            break
    return {"ok": True, "count": len(out), "tasks": out}

async def _skill_get_task(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        tid = int(args.get("task_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "task_id required"}
    t = db.get(models.Task, tid)
    if not t or t.user_id != user.id:
        return {"ok": False, "error": "task not found"}
    return {
        "ok": True,
        "task": {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "status": t.status,
            "priority": t.priority,
            "result": (t.result or "")[:4000],
            "agent_id": t.agent_id,
            "human_id": t.human_id,
            "project_id": t.project_id,
            "company_id": t.company_id,
            "meeting_id": t.meeting_id,
            "labels": t.labels,
        },
    }

async def _skill_list_humans(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        limit = min(50, int(args.get("limit") or 30))
    except Exception:
        limit = 30
    q = (args.get("q") or "").strip().lower()
    rows = (
        db.query(models.Human)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Human.id.asc())
        .limit(80)
        .all()
    )
    out = []
    for h in rows:
        if q and q not in f"{h.name or ''} {h.email or ''} {h.role_title or ''}".lower():
            continue
        out.append({
            "id": h.id,
            "name": h.name,
            "email": h.email,
            "phone": h.phone,
            "role_title": h.role_title,
            "status": h.status,
            "is_my_human": bool(getattr(h, "is_my_human", False)),
            "capacity": h.capacity,
        })
        if len(out) >= limit:
            break
    return {"ok": True, "count": len(out), "humans": out}

async def _skill_read_workspace(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Compact snapshot so agents can orient without asking the human."""
    agents_n = db.query(models.Agent).filter_by(user_id=user.id).count()
    tasks_open = (
        db.query(models.Task)
        .filter(
            models.Task.user_id == user.id,
            models.Task.status.in_(["todo", "queued", "in_progress", "review"]),
        )
        .count()
    )
    customers_n = db.query(models.Customer).filter_by(owner_user_id=user.id).count()
    humans_n = db.query(models.Human).filter_by(owner_user_id=user.id).count()
    meetings_open = (
        db.query(models.MeetingRoom)
        .filter(
            models.MeetingRoom.user_id == user.id,
            models.MeetingRoom.status.in_(["open", "active"]),
        )
        .count()
    )
    companies = db.query(models.Company).filter_by(owner_user_id=user.id).limit(20).all()
    projects = db.query(models.Project).filter_by(owner_user_id=user.id).limit(30).all()
    recent_tasks = (
        db.query(models.Task)
        .filter_by(user_id=user.id)
        .order_by(models.Task.id.desc())
        .limit(8)
        .all()
    )
    return {
        "ok": True,
        "snapshot": {
            "agents": agents_n,
            "open_tasks": tasks_open,
            "customers": customers_n,
            "humans": humans_n,
            "open_meetings": meetings_open,
            "companies": [{"id": c.id, "name": c.name, "industry": c.industry} for c in companies],
            "projects": [{"id": p.id, "name": p.name, "company_id": p.company_id, "status": p.status} for p in projects],
            "recent_tasks": [
                {"id": t.id, "title": t.title, "status": t.status, "agent_id": t.agent_id}
                for t in recent_tasks
            ],
            "you": {"agent_id": agent.id, "name": agent.name, "role": agent.hierarchy_role},
        },
        "message": "Workspace snapshot ready — use list_* / get_* / comment for detail.",
    }

async def _skill_comment(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """
    Universal comment / note on workspace records.

    target_type: customer | task | meeting | human | deal | memory
    """
    ttype = (args.get("target_type") or args.get("type") or "").strip().lower()
    body = (args.get("body") or args.get("content") or args.get("message") or "").strip()
    title = (args.get("title") or f"Note from {agent.name}").strip()[:200]
    if not body:
        return {"ok": False, "error": "body is required"}
    try:
        tid = int(args.get("target_id") or args.get("id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "target_id is required"}

    if ttype in ("customer", "crm", "contact"):
        c = db.get(models.Customer, tid)
        if not c or c.owner_user_id != user.id:
            return {"ok": False, "error": "customer not found"}
        act = models.CustomerActivity(
            customer_id=c.id,
            owner_user_id=user.id,
            kind="note",
            title=title,
            body=body,
            agent_id=agent.id,
        )
        db.add(act)
        c.last_contacted_at = datetime.utcnow()
        c.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "message": f"Commented on customer {c.name}", "activity_id": act.id, "target_type": "customer", "target_id": c.id}

    if ttype in ("task", "todo"):
        t = db.get(models.Task, tid)
        if not t or t.user_id != user.id:
            return {"ok": False, "error": "task not found"}
        note = f"\n\n---\n[{datetime.utcnow().isoformat()}Z] {agent.name}: {body}"
        t.description = ((t.description or "") + note)[-12000:]
        t.updated_at = datetime.utcnow()
        db.add(models.ActivityLog(agent_id=agent.id, type="info", message=f"Task #{t.id} comment: {body[:200]}"))
        db.commit()
        return {"ok": True, "message": f"Commented on task #{t.id}", "target_type": "task", "target_id": t.id}

    if ttype in ("meeting", "meeting_room", "room"):
        room = db.get(models.MeetingRoom, tid)
        if not room or room.user_id != user.id:
            return {"ok": False, "error": "meeting not found"}
        msg = models.MeetingMessage(
            room_id=room.id,
            sender_kind="agent",
            sender_agent_id=agent.id,
            content=body,
            msg_type="chat",
        )
        db.add(msg)
        db.commit()
        return {"ok": True, "message": f"Posted to meeting “{room.title}”", "message_id": msg.id, "target_type": "meeting", "target_id": room.id}

    if ttype in ("human", "teammate", "person"):
        h = db.get(models.Human, tid)
        if not h or h.owner_user_id != user.id:
            return {"ok": False, "error": "human not found"}
        hm = models.HumanMessage(
            user_id=user.id,
            human_id=h.id,
            sender_role="agent",
            sender_agent_id=agent.id,
            content=body,
            kind="message",
        )
        db.add(hm)
        db.commit()
        return {"ok": True, "message": f"Messaged human {h.name}", "message_id": hm.id, "target_type": "human", "target_id": h.id}

    if ttype in ("deal", "opportunity"):
        d = db.get(models.Deal, tid)
        if not d or d.owner_user_id != user.id:
            return {"ok": False, "error": "deal not found"}
        act = models.CustomerActivity(
            customer_id=d.customer_id,
            owner_user_id=user.id,
            kind="note",
            title=title or f"Deal note: {d.title}",
            body=body,
            deal_id=d.id,
            agent_id=agent.id,
        )
        db.add(act)
        db.commit()
        return {"ok": True, "message": f"Commented on deal “{d.title}”", "activity_id": act.id, "target_type": "deal", "target_id": d.id}

    if ttype in ("memory", "agent", "self"):
        mem = models.AgentMemory(
            agent_id=agent.id if ttype != "agent" else tid,
            user_id=user.id,
            kind="note",
            title=title,
            content=body,
        )
        if ttype == "agent":
            other = db.get(models.Agent, tid)
            if not other or other.user_id != user.id:
                return {"ok": False, "error": "agent not found"}
            mem.agent_id = other.id
        db.add(mem)
        db.commit()
        return {"ok": True, "message": "Saved memory note", "memory_id": mem.id, "target_type": "memory"}

    return {
        "ok": False,
        "error": "target_type must be one of: customer, task, meeting, human, deal, memory",
    }


__all__ = [
    '_skill_search_memory',
    '_skill_search_knowledge',
    '_skill_list_tasks',
    '_skill_get_task',
    '_skill_list_humans',
    '_skill_read_workspace',
    '_skill_comment',
]
