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

_OPEN_STATUSES = ("todo", "queued", "in_progress", "review")
_TASK_STATUSES = frozenset({
    "todo", "queued", "in_progress", "review", "completed", "failed",
})


def _task_row(t: models.Task, *, full: bool = False) -> dict:
    out = {
        "id": t.id,
        "title": t.title or "",
        "status": t.status or "",
        "priority": t.priority or "medium",
        "agent_id": t.agent_id,
        "human_id": t.human_id,
        "assignee_type": getattr(t, "assignee_type", None) or (
            "human" if t.human_id else ("agent" if t.agent_id else "unassigned")
        ),
        "project_id": t.project_id,
        "company_id": t.company_id,
        "parent_task_id": getattr(t, "parent_task_id", None),
        "meeting_id": getattr(t, "meeting_id", None),
        "labels": t.labels or "",
        "description": (t.description or "")[:800 if full else 300],
    }
    if full:
        out["result"] = (t.result or "")[:6000]
        out["tokens_used"] = int(t.tokens_used or 0)
        out["created_at"] = t.created_at.isoformat() + "Z" if t.created_at else None
        out["completed_at"] = t.completed_at.isoformat() + "Z" if t.completed_at else None
        out["updated_at"] = t.updated_at.isoformat() + "Z" if t.updated_at else None
    else:
        out["result_preview"] = (t.result or "")[:200] if t.result else ""
    return out


def _query_tasks(
    db: Session,
    user: models.User,
    args: dict,
    *,
    default_limit: int = 30,
    max_limit: int = 80,
) -> tuple[list[models.Task], dict]:
    try:
        limit = min(max_limit, int(args.get("limit") or default_limit))
    except Exception:
        limit = default_limit
    q = (
        args.get("q")
        or args.get("query")
        or args.get("search")
        or args.get("text")
        or ""
    )
    q = str(q).strip().lower()
    status = (args.get("status") or "").strip().lower() or None
    priority = (args.get("priority") or "").strip().lower() or None
    agent_filter = args.get("agent_id")
    mine = args.get("mine")
    if isinstance(mine, str):
        mine = mine.strip().lower() in ("1", "true", "yes", "on")
    open_only = args.get("open_only") or args.get("open")
    if isinstance(open_only, str):
        open_only = open_only.strip().lower() in ("1", "true", "yes", "on")

    query = db.query(models.Task).filter_by(user_id=user.id)
    if status:
        if status in ("open", "active"):
            query = query.filter(models.Task.status.in_(_OPEN_STATUSES))
        else:
            query = query.filter(models.Task.status == status)
    elif open_only:
        query = query.filter(models.Task.status.in_(_OPEN_STATUSES))
    if priority:
        query = query.filter(models.Task.priority == priority)
    if agent_filter is not None and str(agent_filter) not in ("", "null", "none"):
        try:
            query = query.filter(models.Task.agent_id == int(agent_filter))
        except Exception:
            pass
    if mine:
        # caller passes agent via closure — handled by list/search with agent_id set by skill
        pass

    rows = query.order_by(models.Task.id.desc()).limit(200).all()
    if q:
        rows = [
            t for t in rows
            if q in f"{t.title or ''} {t.description or ''} {t.labels or ''} {t.result or ''}".lower()
            or q == str(t.id)
        ]
    meta = {
        "q": q or None,
        "status": status,
        "priority": priority,
        "limit": limit,
        "open_only": bool(open_only),
    }
    return rows[:limit], meta


async def _skill_list_tasks(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    args = dict(args or {})
    mine = args.get("mine")
    if isinstance(mine, str):
        mine = mine.strip().lower() in ("1", "true", "yes", "on")
    if mine or (args.get("scope") or "").strip().lower() in ("self", "me", "my"):
        args["agent_id"] = agent.id
    rows, meta = _query_tasks(db, user, args)
    out = [_task_row(t) for t in rows]
    return {
        "ok": True,
        "count": len(out),
        "tasks": out,
        "filters": meta,
        "message": f"Found {len(out)} task(s)",
    }


async def _skill_search_tasks(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Full-text-ish search across titles, descriptions, labels, results."""
    args = dict(args or {})
    q = (args.get("q") or args.get("query") or args.get("search") or "").strip()
    if not q:
        return {"ok": False, "error": "q / query is required for search_tasks"}
    args.setdefault("limit", 40)
    rows, meta = _query_tasks(db, user, args, default_limit=40, max_limit=80)
    out = [_task_row(t) for t in rows]
    return {
        "ok": True,
        "count": len(out),
        "query": q,
        "tasks": out,
        "filters": meta,
        "message": f"Search “{q}”: {len(out)} task(s)",
    }


async def _skill_get_task(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        tid = int(args.get("task_id") or args.get("id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "task_id required"}
    t = db.get(models.Task, tid)
    if not t or t.user_id != user.id:
        return {"ok": False, "error": "task not found"}
    children = (
        db.query(models.Task)
        .filter_by(user_id=user.id, parent_task_id=t.id)
        .order_by(models.Task.id.asc())
        .limit(40)
        .all()
    )
    return {
        "ok": True,
        "task": _task_row(t, full=True),
        "children": [_task_row(c) for c in children],
        "message": f"Task #{t.id}: {t.title or '(untitled)'} [{t.status}]",
    }


async def _skill_update_task(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Update task fields (status, result, priority, title, description, labels, assignee)."""
    try:
        tid = int(args.get("task_id") or args.get("id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "task_id required"}
    t = db.get(models.Task, tid)
    if not t or t.user_id != user.id:
        return {"ok": False, "error": "task not found"}

    changed: list[str] = []
    if args.get("title") is not None:
        t.title = str(args.get("title") or "").strip()[:200]
        changed.append("title")
    if args.get("description") is not None:
        t.description = str(args.get("description") or "")
        changed.append("description")
    if args.get("priority") is not None:
        pr = str(args.get("priority") or "medium").strip().lower()
        if pr in ("low", "medium", "high", "urgent"):
            t.priority = pr
            changed.append("priority")
    if args.get("labels") is not None:
        t.labels = str(args.get("labels") or "")[:500]
        changed.append("labels")
    if args.get("agent_id") is not None:
        try:
            aid = int(args.get("agent_id")) if args.get("agent_id") not in ("", None) else None
        except (TypeError, ValueError):
            aid = None
        if aid is not None:
            a = db.get(models.Agent, aid)
            if not a or a.user_id != user.id:
                return {"ok": False, "error": "agent not found"}
            t.agent_id = aid
            t.assignee_type = "agent"
            changed.append("agent_id")
    if args.get("human_id") is not None:
        try:
            hid = int(args.get("human_id")) if args.get("human_id") not in ("", None) else None
        except (TypeError, ValueError):
            hid = None
        if hid is not None:
            h = db.get(models.Human, hid)
            if not h or h.owner_user_id != user.id:
                return {"ok": False, "error": "human not found"}
            t.human_id = hid
            t.assignee_type = "human"
            changed.append("human_id")

    status = (args.get("status") or "").strip().lower()
    if status:
        if status not in _TASK_STATUSES:
            return {
                "ok": False,
                "error": f"status must be one of: {', '.join(sorted(_TASK_STATUSES))}",
            }
        t.status = status
        changed.append("status")
        if status == "completed":
            t.completed_at = datetime.utcnow()
        elif status in _OPEN_STATUSES:
            t.completed_at = None

    result = args.get("result") or args.get("response") or args.get("reply") or args.get("note")
    if result is not None:
        note = str(result).strip()
        if note:
            # Append progress notes rather than wipe previous result
            append = args.get("append_result")
            if isinstance(append, str):
                append = append.strip().lower() not in ("0", "false", "no")
            elif append is None:
                append = True
            stamp = datetime.utcnow().isoformat() + "Z"
            line = f"[{stamp}] {agent.name}: {note}"
            if append and (t.result or "").strip():
                t.result = f"{(t.result or '').rstrip()}\n\n{line}"
            else:
                t.result = note
            changed.append("result")

    if not changed:
        return {"ok": False, "error": "no fields to update (status, result, priority, title, …)"}

    t.updated_at = datetime.utcnow()
    # Activity log
    try:
        db.add(models.ActivityLog(
            agent_id=agent.id,
            type="task_update",
            message=f"Updated task #{t.id} ({', '.join(changed)}): {t.title or ''}",
        ))
    except Exception:
        pass
    db.commit()
    db.refresh(t)

    # Chain unlock when a step completes/fails
    if status in ("completed", "failed"):
        try:
            from ..task_chain import on_task_finished
            import asyncio
            if asyncio.iscoroutinefunction(on_task_finished):
                await on_task_finished(db, t, final_status=status, commit=True)
            else:
                on_task_finished(db, t, final_status=status, commit=True)
        except Exception:
            pass

    # Live UI
    try:
        from ..ws import manager
        from ..agent_serialize import task_dict
        await manager.broadcast(
            f"agents:{user.id}",
            {"event": "task_updated", "task": task_dict(t, db)},
        )
    except Exception:
        pass

    return {
        "ok": True,
        "message": f"Updated task #{t.id}: {', '.join(changed)}",
        "changed": changed,
        "task": _task_row(t, full=True),
    }


async def _skill_respond_to_task(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Write a response/result on a task and optionally complete or re-queue it."""
    args = dict(args or {})
    response = (
        args.get("response")
        or args.get("result")
        or args.get("reply")
        or args.get("note")
        or args.get("body")
        or ""
    )
    if not str(response).strip():
        return {"ok": False, "error": "response / result text is required"}
    complete = args.get("complete")
    if complete is None:
        complete = args.get("done")
    if isinstance(complete, str):
        complete = complete.strip().lower() in ("1", "true", "yes", "on")
    # Default: complete unless they set status explicitly or complete=false
    if args.get("status"):
        pass
    elif complete is False:
        args["status"] = "in_progress"
    else:
        args["status"] = "completed"
    args["result"] = response
    args["append_result"] = args.get("append_result", True)
    out = await _skill_update_task(db, agent, user, args)
    if out.get("ok"):
        out["message"] = (
            f"Responded to task #{args.get('task_id') or args.get('id')} "
            f"→ {args.get('status')}"
        )
    return out


async def _skill_complete_task(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Mark a task completed with an optional result summary."""
    args = dict(args or {})
    args["status"] = "completed"
    if args.get("result") is None and args.get("response"):
        args["result"] = args.get("response")
    out = await _skill_update_task(db, agent, user, args)
    if out.get("ok"):
        out["message"] = f"Completed task #{args.get('task_id') or args.get('id')}"
        # Advance auto-chain: next sibling was queued — start it now (not daily cron)
        try:
            from ..task_runner import kick_queued_task
            next_id = None
            # on_task_finished inside update_task may have set next sibling queued
            tid = int(args.get("task_id") or args.get("id"))
            parent_id = (out.get("task") or {}).get("parent_task_id")
            if parent_id:
                nxt = (
                    db.query(models.Task)
                    .filter(
                        models.Task.parent_task_id == parent_id,
                        models.Task.status == "queued",
                        models.Task.id != tid,
                    )
                    .order_by(models.Task.id.asc())
                    .first()
                )
                if nxt:
                    next_id = nxt.id
                    await kick_queued_task(next_id, user_id=user.id)
                    out["next_task_started"] = next_id
        except Exception:
            pass
    return out


async def _skill_claim_task(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Assign this agent to a task, attach done-when targets, and queue for immediate run."""
    args = dict(args or {})
    try:
        tid = int(args.get("task_id") or args.get("id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "task_id required"}
    t = db.get(models.Task, tid)
    if not t or t.user_id != user.id:
        return {"ok": False, "error": "task not found"}
    if (t.status or "") in ("completed", "failed"):
        return {"ok": False, "error": f"task already {t.status}"}

    t.agent_id = agent.id
    t.assignee_type = "agent"
    t.human_id = None

    success = (
        args.get("success_criteria")
        or args.get("done_when")
        or args.get("acceptance")
        or args.get("target")
        or ""
    )
    success = str(success).strip()
    if success and "DONE WHEN:" not in (t.description or "").upper():
        t.description = (
            f"{(t.description or t.title or '').rstrip()}\n\n"
            f"---\nDONE WHEN: {success}\n"
            f"TARGET: {success}\n"
            f"Claimed by {agent.name}. Call complete_task when the target is met."
        )[:8000]
    elif "DONE WHEN:" not in (t.description or "").upper():
        t.description = (
            f"{(t.description or t.title or '').rstrip()}\n\n"
            f"---\nDONE WHEN: Produce the concrete deliverable for “{t.title or 'this task'}”.\n"
            f"Claimed by {agent.name}. Call complete_task with evidence when done."
        )[:8000]

    labels = t.labels or ""
    for tag in ("claimed", "self-assigned"):
        if tag not in labels:
            labels = f"{labels},{tag}".strip(",") if labels else tag
    t.labels = labels
    t.status = "queued"
    t.updated_at = datetime.utcnow()
    try:
        db.add(models.ActivityLog(
            agent_id=agent.id,
            type="task_claim",
            message=f"Claimed task #{t.id}: {t.title or ''}",
        ))
    except Exception:
        pass
    db.commit()
    db.refresh(t)

    kicked = False
    try:
        from ..task_runner import kick_queued_task
        kicked = await kick_queued_task(
            t.id,
            user_id=user.id,
            agent_id=agent.id,
            description=t.description,
            agent_name=agent.name,
        )
    except Exception:
        kicked = False

    try:
        from ..ws import manager
        from ..agent_serialize import task_dict
        await manager.broadcast(
            f"agents:{user.id}",
            {"event": "task_updated", "task": task_dict(t, db)},
        )
    except Exception:
        pass

    return {
        "ok": True,
        "message": (
            f"Claimed task #{t.id} → queued"
            + (" · run started" if kicked else " · waiting for runner")
        ),
        "task_id": t.id,
        "status": t.status,
        "run_started": kicked,
        "task": _task_row(t, full=True),
    }


async def _skill_set_task_status(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Set task status only (todo | queued | in_progress | review | completed | failed)."""
    args = dict(args or {})
    if not args.get("status"):
        return {"ok": False, "error": "status is required"}
    out = await _skill_update_task(db, agent, user, args)
    # If agent set status to queued, start immediately
    if out.get("ok") and str(args.get("status") or "").lower() == "queued":
        try:
            from ..task_runner import kick_queued_task
            tid = int(args.get("task_id") or args.get("id"))
            await kick_queued_task(tid, user_id=user.id)
        except Exception:
            pass
    return out


async def _skill_delete_task(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Delete a task the workspace owns (agents can clean up board items)."""
    try:
        tid = int(args.get("task_id") or args.get("id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "task_id required"}
    t = db.get(models.Task, tid)
    if not t or t.user_id != user.id:
        return {"ok": False, "error": "task not found"}
    title = t.title or f"#{t.id}"
    # Soft-delete children first if any (avoid orphan open chain)
    children = db.query(models.Task).filter_by(parent_task_id=t.id).all()
    for ch in children:
        db.delete(ch)
    db.delete(t)
    try:
        db.add(models.ActivityLog(
            agent_id=agent.id,
            type="task_delete",
            message=f"Deleted task #{tid}: {title}",
        ))
    except Exception:
        pass
    db.commit()
    try:
        from ..ws import manager
        await manager.broadcast(
            f"agents:{user.id}",
            {"event": "task_deleted", "task_id": tid},
        )
    except Exception:
        pass
    return {"ok": True, "message": f"Deleted task #{tid} ({title})", "task_id": tid}

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

async def _skill_list_activity(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Read activity logs for this agent, another agent, or the whole workspace."""
    args = dict(args or {})
    try:
        limit = min(80, max(1, int(args.get("limit") or 30)))
    except (TypeError, ValueError):
        limit = 30
    q = (args.get("q") or args.get("query") or args.get("search") or "").strip().lower()
    type_filter = (args.get("type") or args.get("kind") or "").strip().lower() or None

    mine = args.get("mine")
    if isinstance(mine, str):
        mine = mine.strip().lower() in ("1", "true", "yes", "on")
    agent_id = args.get("agent_id")
    try:
        agent_id = int(agent_id) if agent_id not in (None, "") else None
    except (TypeError, ValueError):
        agent_id = None
    if mine and agent_id is None:
        agent_id = agent.id

    # Scope: all agents owned by this user (workspace-wide read)
    team_ids = [a.id for a in db.query(models.Agent).filter_by(user_id=user.id).all()]
    if not team_ids:
        return {"ok": True, "count": 0, "logs": [], "message": "No agents in workspace"}

    query = db.query(models.ActivityLog).filter(models.ActivityLog.agent_id.in_(team_ids))
    if agent_id is not None:
        if agent_id not in team_ids:
            return {"ok": False, "error": "agent not found in workspace"}
        query = query.filter(models.ActivityLog.agent_id == agent_id)
    if type_filter:
        query = query.filter(models.ActivityLog.type == type_filter)

    rows = query.order_by(models.ActivityLog.id.desc()).limit(min(200, limit * 3)).all()
    # Name map
    names = {
        a.id: a.name
        for a in db.query(models.Agent).filter(models.Agent.id.in_(team_ids)).all()
    }
    out = []
    for r in rows:
        msg = r.message or ""
        if q and q not in msg.lower() and q not in (r.type or "").lower() and q not in (names.get(r.agent_id) or "").lower():
            continue
        out.append({
            "id": r.id,
            "agent_id": r.agent_id,
            "agent_name": names.get(r.agent_id) or f"agent:{r.agent_id}",
            "type": r.type,
            "message": msg[:500],
            "created_at": r.created_at.isoformat() + "Z" if getattr(r, "created_at", None) and hasattr(r.created_at, "isoformat") else None,
        })
        if len(out) >= limit:
            break

    scope = f"agent #{agent_id}" if agent_id else "workspace"
    return {
        "ok": True,
        "count": len(out),
        "scope": scope,
        "logs": out,
        "message": f"{len(out)} activity log(s) ({scope})",
    }


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
    # Recent activity across the team (agents can read all logs)
    team_ids = [a.id for a in db.query(models.Agent).filter_by(user_id=user.id).limit(80).all()]
    recent_logs = []
    if team_ids:
        name_map = {
            a.id: a.name
            for a in db.query(models.Agent).filter(models.Agent.id.in_(team_ids)).all()
        }
        for r in (
            db.query(models.ActivityLog)
            .filter(models.ActivityLog.agent_id.in_(team_ids))
            .order_by(models.ActivityLog.id.desc())
            .limit(12)
            .all()
        ):
            recent_logs.append({
                "agent_id": r.agent_id,
                "agent_name": name_map.get(r.agent_id),
                "type": r.type,
                "message": (r.message or "")[:180],
            })
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
            "recent_activity": recent_logs,
            "you": {"agent_id": agent.id, "name": agent.name, "role": agent.hierarchy_role},
        },
        "message": "Workspace snapshot ready — use list_activity for full logs; list_* / get_* for detail.",
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
    '_skill_search_tasks',
    '_skill_get_task',
    '_skill_update_task',
    '_skill_respond_to_task',
    '_skill_complete_task',
    '_skill_claim_task',
    '_skill_set_task_status',
    '_skill_delete_task',
    '_skill_list_humans',
    '_skill_list_activity',
    '_skill_read_workspace',
    '_skill_comment',
]
