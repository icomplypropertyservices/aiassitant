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
    """Offline task board read — autonomy invent path always uses this before inventing work."""
    args = dict(args or {})
    mine = args.get("mine")
    if isinstance(mine, str):
        mine = mine.strip().lower() in ("1", "true", "yes", "on")
    if mine or (args.get("scope") or "").strip().lower() in ("self", "me", "my"):
        args["agent_id"] = agent.id
    try:
        rows, meta = _query_tasks(db, user, args)
        out = [_task_row(t) for t in rows]
    except Exception as e:
        return {
            "ok": False,
            "error": f"list_tasks failed: {e}",
            "error_code": "task_error",
            "retryable": False,
            "skill": "list_tasks",
            "tasks": [],
            "count": 0,
        }
    return {
        "ok": True,
        "skill": "list_tasks",
        "mode": "task_read",
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
    """Mark a task completed (or submit for lead review) with a result summary."""
    from ..agent_roles import is_lead_agent, is_orchestrator
    from ..orchestration.acceptance import task_requires_review

    args = dict(args or {})
    if args.get("result") is None and args.get("response"):
        args["result"] = args.get("response")

    # Lead-assigned / checklist work → "review" until lead approves (canonical flags)
    skip_review = args.get("skip_review") or args.get("force_complete")
    if isinstance(skip_review, str):
        skip_review = skip_review.strip().lower() in ("1", "true", "yes", "on")
    try:
        tid = int(args.get("task_id") or args.get("id"))
    except (TypeError, ValueError):
        tid = None
    if tid is None:
        return {
            "ok": False,
            "error": "task_id required",
            "error_code": "validation",
            "retryable": False,
            "skill": "complete_task",
            "guidance": "Pass task_id from list_tasks / create_task before completing.",
        }
    t_pre = db.get(models.Task, tid) if tid else None
    if t_pre is None or t_pre.user_id != user.id:
        return {
            "ok": False,
            "error": "task not found",
            "error_code": "not_found",
            "retryable": False,
            "skill": "complete_task",
        }
    is_lead = (
        is_orchestrator(agent)
        or is_lead_agent(agent)
        or (agent.hierarchy_role or "") in ("lead", "orchestrator")
        or (agent.permission_level or "") in ("lead", "admin")
    )
    needs_lead = bool(
        t_pre
        and not skip_review
        and task_requires_review(t_pre)
        and not is_lead
    )
    if needs_lead:
        args["status"] = "review"
        result_note = str(args.get("result") or "").strip()
        if result_note and "submitted for lead review" not in result_note.lower():
            args["result"] = (
                f"{result_note}\n\n[Submitted for lead review — waiting for review_task approve/reject]"
            )
        else:
            args["result"] = args.get("result") or "Submitted for lead review"
    else:
        args["status"] = "completed"

    out = await _skill_update_task(db, agent, user, args)
    if isinstance(out, dict):
        out.setdefault("skill", "complete_task")
        if out.get("ok") is False and out.get("retryable") is None:
            out.setdefault("error_code", "validation")
            out["retryable"] = False
    if out.get("ok"):
        out["mode"] = "task_write"
        if needs_lead:
            out["message"] = (
                f"Task #{args.get('task_id') or args.get('id')} submitted for lead review. "
                f"Lead must review_task (approve or reject with what's wrong)."
            )
            out["awaiting_review"] = True
            # Notify parent lead via activity + agent message (no circular skill import)
            try:
                if t_pre and t_pre.agent_id:
                    assignee = db.get(models.Agent, t_pre.agent_id) or agent
                    lead = (
                        db.get(models.Agent, assignee.parent_id)
                        if assignee and assignee.parent_id
                        else None
                    )
                    if lead:
                        body = (
                            f"Task #{t_pre.id} “{t_pre.title or ''}” is ready for your review. "
                            f"Use review_task: approve, or reject with feedback + checks_failed."
                        )[:2000]
                        db.add(models.ActivityLog(
                            agent_id=lead.id,
                            type="review_needed",
                            message=body[:500],
                        ))
                        lo, hi = sorted([agent.id, lead.id])
                        db.add(models.AgentMessage(
                            user_id=user.id,
                            from_agent_id=agent.id,
                            to_agent_id=lead.id,
                            thread_key=f"{lo}-{hi}",
                            content=body,
                            status="sent",
                        ))
                        db.commit()
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
        else:
            out["message"] = f"Completed task #{args.get('task_id') or args.get('id')}"
            # Advance auto-chain: next sibling was queued — start it now (not daily cron)
            try:
                from ..task_runner import kick_queued_task
                next_id = None
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


async def _skill_create_company(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Create a company in the workspace."""
    name = (args.get("name") or args.get("company") or "").strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    c = models.Company(
        owner_user_id=user.id,
        name=name[:200],
        industry=(args.get("industry") or "")[:120],
        notes=(args.get("notes") or args.get("description") or "")[:4000],
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    try:
        db.add(models.ActivityLog(
            agent_id=agent.id,
            type="ops",
            message=f"Created company “{c.name}” (#{c.id})",
        ))
        db.commit()
    except Exception:
        pass
    return {
        "ok": True,
        "message": f"Company “{c.name}” created (#{c.id})",
        "company_id": c.id,
        "name": c.name,
    }


async def _skill_create_project(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Create a project (optionally under a company) so work can be sorted and staffed."""
    name = (args.get("name") or args.get("project") or args.get("title") or "").strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    company_id = args.get("company_id")
    try:
        company_id = int(company_id) if company_id not in (None, "") else None
    except (TypeError, ValueError):
        company_id = None
    if company_id is None:
        co = (
            db.query(models.Company)
            .filter_by(owner_user_id=user.id)
            .order_by(models.Company.id)
            .first()
        )
        if co:
            company_id = co.id
        else:
            # Auto-create a home company so orchestrator can make projects immediately
            co = models.Company(
                owner_user_id=user.id,
                name=f"{user.email or 'Workspace'} company"[:120],
                industry="",
                notes="Auto-created when orchestrator made a project",
            )
            db.add(co)
            db.flush()
            company_id = co.id
    else:
        co = db.get(models.Company, company_id)
        if not co or co.owner_user_id != user.id:
            return {"ok": False, "error": "company not found"}

    status = (args.get("status") or "active").strip().lower()
    if status not in ("active", "paused", "done"):
        status = "active"
    p = models.Project(
        company_id=company_id,
        owner_user_id=user.id,
        name=name[:200],
        description=(args.get("description") or args.get("notes") or "")[:8000],
        status=status,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    try:
        db.add(models.ActivityLog(
            agent_id=agent.id,
            type="ops",
            message=f"Created project “{p.name}” (#{p.id}) under company #{company_id}",
        ))
        db.commit()
    except Exception:
        pass
    return {
        "ok": True,
        "message": f"Project “{p.name}” created (#{p.id})",
        "project_id": p.id,
        "company_id": company_id,
        "name": p.name,
        "status": p.status,
    }


async def _skill_list_projects(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """List workspace projects with open-task pressure."""
    try:
        limit = min(80, int(args.get("limit") or 40))
    except Exception:
        limit = 40
    q = db.query(models.Project).filter_by(owner_user_id=user.id)
    company_id = args.get("company_id")
    if company_id not in (None, ""):
        try:
            q = q.filter_by(company_id=int(company_id))
        except (TypeError, ValueError):
            pass
    status = (args.get("status") or "").strip().lower()
    if status:
        q = q.filter_by(status=status)
    rows = q.order_by(models.Project.id.desc()).limit(120).all()
    search = (args.get("q") or args.get("query") or "").strip().lower()
    out = []
    for p in rows:
        if search and search not in (p.name or "").lower() and search not in (p.description or "").lower():
            continue
        open_n = (
            db.query(models.Task)
            .filter(
                models.Task.user_id == user.id,
                models.Task.project_id == p.id,
                models.Task.status.in_(list(_OPEN_STATUSES)),
            )
            .count()
        )
        stuck_n = (
            db.query(models.Task)
            .filter(
                models.Task.user_id == user.id,
                models.Task.project_id == p.id,
                models.Task.status.in_(["todo", "queued", "in_progress", "review", "failed"]),
            )
            .count()
        )
        out.append({
            "id": p.id,
            "name": p.name,
            "status": p.status,
            "company_id": p.company_id,
            "description": (p.description or "")[:200],
            "open_tasks": open_n,
            "pressure": stuck_n,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })
        if len(out) >= limit:
            break
    out.sort(key=lambda x: (-int(x.get("open_tasks") or 0), x.get("id") or 0))
    return {
        "ok": True,
        "count": len(out),
        "projects": out,
        "message": f"{len(out)} project(s) — use sort_late_projects to unstick overdue work",
    }


async def _skill_sort_late_projects(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """
    Find late/stuck projects & tasks, re-queue, create recovery work, notify human.
    Orchestrator primary tool for "sort out late projects".
    """
    from datetime import timedelta

    try:
        days_late = max(1, min(90, int(args.get("days_late") or args.get("days") or 3)))
    except Exception:
        days_late = 3
    try:
        limit = min(50, int(args.get("limit") or 20))
    except Exception:
        limit = 20

    def _flag(raw, default=True):
        if raw is None:
            return default
        if isinstance(raw, str):
            return raw.strip().lower() not in ("0", "false", "no", "off")
        return bool(raw)

    requeue = _flag(args.get("requeue"), True)
    create_recovery = _flag(args.get("create_recovery_tasks") or args.get("create_tasks"), True)
    notify = _flag(args.get("notify_human") or args.get("notify"), True)

    cutoff = datetime.utcnow() - timedelta(days=days_late)
    open_statuses = list(_OPEN_STATUSES)

    tq = db.query(models.Task).filter(
        models.Task.user_id == user.id,
        models.Task.status.in_(open_statuses + ["failed"]),
    )
    company_id = args.get("company_id")
    project_id = args.get("project_id")
    if company_id not in (None, ""):
        try:
            tq = tq.filter(models.Task.company_id == int(company_id))
        except (TypeError, ValueError):
            pass
    if project_id not in (None, ""):
        try:
            tq = tq.filter(models.Task.project_id == int(project_id))
        except (TypeError, ValueError):
            pass

    candidates = tq.order_by(models.Task.id.asc()).limit(200).all()
    late_tasks = []
    for t in candidates:
        updated = t.updated_at or t.created_at
        age_old = bool(updated and updated < cutoff)
        high_stuck = (t.priority or "") in ("high", "urgent") and (t.status or "") in open_statuses
        failed = (t.status or "") == "failed"
        if age_old or high_stuck or failed:
            late_tasks.append(t)
        if len(late_tasks) >= limit:
            break

    # Projects with late tasks or paused/old active with open work
    project_pressure: dict[int, dict] = {}
    for t in late_tasks:
        if not t.project_id:
            continue
        bucket = project_pressure.setdefault(t.project_id, {"late_task_ids": [], "count": 0})
        bucket["late_task_ids"].append(t.id)
        bucket["count"] += 1

    projects = (
        db.query(models.Project)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Project.id.desc())
        .limit(80)
        .all()
    )
    late_projects = []
    for p in projects:
        open_n = (
            db.query(models.Task)
            .filter(
                models.Task.user_id == user.id,
                models.Task.project_id == p.id,
                models.Task.status.in_(open_statuses),
            )
            .count()
        )
        pressure = project_pressure.get(p.id, {}).get("count", 0)
        old_active = (
            (p.status or "") == "active"
            and p.created_at
            and p.created_at < cutoff
            and open_n > 0
        )
        if pressure or old_active or (p.status or "") == "paused" and open_n:
            late_projects.append({
                "id": p.id,
                "name": p.name,
                "status": p.status,
                "open_tasks": open_n,
                "late_tasks": pressure,
                "reason": (
                    "paused_with_open_work" if (p.status or "") == "paused" and open_n
                    else "late_tasks" if pressure
                    else "aging_with_open_work"
                ),
            })

    late_projects.sort(key=lambda x: (-x["late_tasks"], -x["open_tasks"]))
    late_projects = late_projects[:limit]

    requeued: list[int] = []
    recovery_ids: list[int] = []
    actions: list[str] = []

    if requeue:
        for t in late_tasks:
            if (t.status or "") in ("todo", "failed", "review"):
                # Only requeue if assignee active (or unassigned → orchestrator)
                aid = t.agent_id or agent.id
                arow = db.get(models.Agent, aid) if aid else agent
                if arow and (arow.status or "") == "active":
                    t.agent_id = arow.id
                    t.status = "queued"
                    t.updated_at = datetime.utcnow()
                    labs = t.labels or ""
                    if "late-sorted" not in labs:
                        labs = f"{labs},late-sorted".strip(",") if labs else "late-sorted"
                    t.labels = labs
                    requeued.append(t.id)
        if requeued:
            db.commit()
            try:
                from ..task_runner import kick_queued_task
                for tid in requeued[:12]:
                    await kick_queued_task(tid, user_id=user.id)
            except Exception:
                pass
            actions.append(f"Re-queued {len(requeued)} late task(s)")

    if create_recovery and late_projects:
        for pinfo in late_projects[:5]:
            p = db.get(models.Project, pinfo["id"])
            if not p:
                continue
            title = f"Recovery: sort late work on {p.name}"[:200]
            # Avoid duplicate open recovery tasks
            exists = (
                db.query(models.Task)
                .filter(
                    models.Task.user_id == user.id,
                    models.Task.project_id == p.id,
                    models.Task.title == title,
                    models.Task.status.in_(open_statuses),
                )
                .first()
            )
            if exists:
                continue
            desc = (
                f"Project #{p.id} “{p.name}” is late/stuck "
                f"({pinfo['late_tasks']} late tasks, {pinfo['open_tasks']} open).\n"
                f"DONE WHEN: All high-priority open tasks reassigned or completed; "
                f"status_update to human with remaining blockers.\n"
                f"CHECKLIST:\n  [ ] list_tasks for this project\n"
                f"  [ ] requeue or reassign stuck work\n"
                f"  [ ] notify human of status\n"
                f"Assigned by orchestrator late-sort."
            )
            rt = models.Task(
                user_id=user.id,
                agent_id=agent.id,
                company_id=p.company_id,
                project_id=p.id,
                title=title,
                description=desc,
                status="queued" if (agent.status or "") == "active" else "todo",
                priority="high",
                labels="late-recovery,orchestrator,has-checklist,needs-review",
                assignee_type="agent",
            )
            db.add(rt)
            db.flush()
            recovery_ids.append(rt.id)
        if recovery_ids:
            db.commit()
            try:
                from ..task_runner import kick_queued_task
                for tid in recovery_ids[:5]:
                    await kick_queued_task(tid, user_id=user.id)
            except Exception:
                pass
            actions.append(f"Created {len(recovery_ids)} recovery task(s)")

    notify_result = None
    if notify and (late_projects or late_tasks):
        try:
            from .meta_agents import _skill_status_update
            highlights = (
                f"Late sort: {len(late_projects)} project(s), {len(late_tasks)} task(s) "
                f"(>{days_late}d or stuck). "
                + ("; ".join(actions) if actions else "Reviewed only.")
            )
            notify_result = await _skill_status_update(db, agent, user, {
                "project": "Late project sort",
                "period": f"last {days_late}d+",
                "status": "amber" if late_tasks else "green",
                "highlights": highlights,
                "notify": True,
            })
            actions.append("Notified human")
        except Exception as e:
            notify_result = {"ok": False, "error": str(e)[:200]}

    try:
        db.add(models.ActivityLog(
            agent_id=agent.id,
            type="ops",
            message=(
                f"Sorted late work: {len(late_projects)} projects, "
                f"{len(late_tasks)} tasks · {', '.join(actions) or 'scan only'}"
            )[:500],
        ))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    return {
        "ok": True,
        "message": (
            f"Late work sorted: {len(late_projects)} project(s), {len(late_tasks)} task(s). "
            + (" · ".join(actions) if actions else "No automatic actions — review list.")
        ),
        "days_late": days_late,
        "late_projects": late_projects,
        "late_tasks": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "project_id": t.project_id,
                "agent_id": t.agent_id,
                "updated_at": (t.updated_at or t.created_at).isoformat()
                if (t.updated_at or t.created_at) else None,
            }
            for t in late_tasks
        ],
        "requeued_task_ids": requeued,
        "recovery_task_ids": recovery_ids,
        "actions": actions,
        "notify": notify_result,
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
    '_skill_create_company',
    '_skill_create_project',
    '_skill_list_projects',
    '_skill_sort_late_projects',
    '_skill_comment',
]
