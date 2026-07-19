"""Human teammates — My Human, message box, assign/delegate, AgentBay subcontractors."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..ownership import require_owned
from .. import models
from ..auth_utils import get_current_user
from ..live_ops import emit_ops
from .. import human_service

router = APIRouter(prefix="/humans", tags=["humans"])


class HumanIn(BaseModel):
    name: str
    email: str = ""
    phone: str = ""  # E.164 for SMS notify shortcuts
    role_title: str = ""
    skills: str = ""
    company_id: int | None = None
    project_id: int | None = None
    status: str = "active"
    capacity: int = 5
    notes: str = ""
    permission_level: str = "operator"
    escalate_when: str = "on_blocked"
    escalate_reason: str = ""
    escalate_to: str = "orchestrator"
    is_my_human: bool = False


class HumanUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    role_title: str | None = None
    skills: str | None = None
    company_id: int | None = None
    project_id: int | None = None
    status: str | None = None
    capacity: int | None = None
    notes: str | None = None
    permission_level: str | None = None
    escalate_when: str | None = None
    escalate_reason: str | None = None
    escalate_to: str | None = None
    is_my_human: bool | None = None


class AssignIn(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    agent_id: int | None = None
    project_id: int | None = None
    company_id: int | None = None
    message: str = ""  # also post to human message box


class MessageIn(BaseModel):
    content: str
    kind: str = "message"
    related_human_id: int | None = None
    task_id: int | None = None
    # When agent posts on behalf of itself
    sender_agent_id: int | None = None


class DelegateIn(BaseModel):
    """My Human (or any human) delegates work to another human and/or AI agent."""
    title: str
    description: str = ""
    to_human_id: int | None = None
    to_agent_id: int | None = None
    priority: str = "medium"
    message: str = ""  # note in message box
    project_id: int | None = None
    company_id: int | None = None


def _unread_count(db: Session, human_id: int, user_id: int) -> int:
    return (
        db.query(models.HumanMessage)
        .filter_by(user_id=user_id, human_id=human_id)
        .filter(models.HumanMessage.read_at.is_(None))
        .filter(models.HumanMessage.sender_role != "owner")
        .count()
    )


def _out(h: models.Human, db: Session) -> dict:
    open_n = (
        db.query(models.Task)
        .filter(
            models.Task.human_id == h.id,
            models.Task.status.in_(("todo", "queued", "in_progress", "review")),
        )
        .count()
    )
    co = db.get(models.Company, h.company_id) if h.company_id else None
    pr = db.get(models.Project, h.project_id) if h.project_id else None
    return {
        "id": h.id,
        "name": h.name,
        "email": h.email or "",
        "phone": getattr(h, "phone", None) or "",
        "role_title": h.role_title or "",
        "skills": h.skills or "",
        "company_id": h.company_id,
        "project_id": h.project_id,
        "company_name": co.name if co else None,
        "project_name": pr.name if pr else None,
        "status": h.status,
        "capacity": h.capacity or 5,
        "permission_level": getattr(h, "permission_level", None) or "operator",
        "escalate_when": getattr(h, "escalate_when", None) or "on_blocked",
        "escalate_reason": getattr(h, "escalate_reason", None) or "",
        "escalate_to": getattr(h, "escalate_to", None) or "orchestrator",
        "notes": h.notes or "",
        "is_my_human": bool(getattr(h, "is_my_human", False)),
        "open_tasks": open_n,
        "unread_messages": _unread_count(db, h.id, h.owner_user_id),
        "notify_ready": bool(
            (h.email or "").strip()
            and (getattr(h, "phone", None) or "").strip()
            and (h.status or "") == "active"
        ),
        "created_at": h.created_at,
        "updated_at": h.updated_at,
    }


@router.get("/")
def list_humans(db: Session = Depends(get_db), user=Depends(get_current_user)):
    my = human_service.ensure_my_human(db, user)
    db.commit()
    rows = (
        db.query(models.Human)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Human.is_my_human.desc(), models.Human.name)
        .all()
    )
    return {
        "humans": [_out(h, db) for h in rows],
        "count": len(rows),
        "my_human": _out(my, db),
        "my_human_id": my.id,
    }


@router.get("/my")
def get_my_human(db: Session = Depends(get_db), user=Depends(get_current_user)):
    h = human_service.ensure_my_human(db, user)
    db.commit()
    return _out(h, db)


@router.post("/my/ensure")
def ensure_my_human_route(db: Session = Depends(get_db), user=Depends(get_current_user)):
    h = human_service.ensure_my_human(db, user)
    db.commit()
    db.refresh(h)
    return {"ok": True, "human": _out(h, db)}


@router.post("/my/set/{human_id}")
def set_my_human_route(
    human_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        h = human_service.set_my_human(db, user, human_id)
        db.commit()
        db.refresh(h)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"ok": True, "human": _out(h, db)}


@router.get("/subcontractors")
def list_subcontractors(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """AgentBay hires (paid orders) visible as subcontractors for this account."""
    return human_service.list_agentbay_subcontractors(db, user)


@router.get("/inbox")
def human_inbox(
    limit: int = 60,
    unread_only: bool = False,
    mark_read: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Aggregated notification + message feed for the logged-in owner as human.
    Includes agent status updates, system notes, and owner messages on My Human.
    """
    my = human_service.ensure_my_human(db, user)
    db.commit()
    q = (
        db.query(models.HumanMessage)
        .filter_by(user_id=user.id, human_id=my.id)
        .order_by(models.HumanMessage.id.desc())
    )
    if unread_only:
        q = q.filter(models.HumanMessage.read_at.is_(None))
    rows = q.limit(min(200, max(1, int(limit or 60)))).all()
    items = []
    for m in rows:
        agent_name = None
        if m.sender_agent_id:
            a = db.get(models.Agent, m.sender_agent_id)
            agent_name = a.name if a else None
        items.append({
            "id": m.id,
            "human_id": m.human_id,
            "sender_role": m.sender_role,
            "sender_agent_id": m.sender_agent_id,
            "sender_agent_name": agent_name,
            "task_id": m.task_id,
            "content": m.content,
            "kind": m.kind or "message",
            "unread": m.read_at is None and (m.sender_role or "") != "owner",
            "read_at": m.read_at.isoformat() + "Z" if m.read_at else None,
            "created_at": m.created_at.isoformat() + "Z" if m.created_at else None,
        })
    unread = _unread_count(db, my.id, user.id)
    if mark_read:
        human_service.mark_messages_read(db, user, my.id)
        db.commit()
        unread = 0
        for it in items:
            it["unread"] = False
    return {
        "ok": True,
        "my_human": _out(my, db),
        "messages": items,
        "count": len(items),
        "unread_count": unread,
    }


@router.get("/dashboard")
def human_dashboard(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Human desk: inbox summary, open tasks assigned to humans, recent agent notifications."""
    my = human_service.ensure_my_human(db, user)
    db.commit()
    unread = _unread_count(db, my.id, user.id)
    recent = human_service.list_human_messages(db, user, my.id, limit=30)
    # Open tasks for any human on this account (human assignee or human_id set)
    open_tasks = (
        db.query(models.Task)
        .filter(
            models.Task.user_id == user.id,
            models.Task.status.in_(("todo", "queued", "in_progress", "review")),
            models.Task.human_id.isnot(None),
        )
        .order_by(models.Task.id.desc())
        .limit(40)
        .all()
    )
    task_items = []
    for t in open_tasks:
        h = db.get(models.Human, t.human_id) if t.human_id else None
        a = db.get(models.Agent, t.agent_id) if t.agent_id else None
        task_items.append({
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "priority": t.priority,
            "human_id": t.human_id,
            "human_name": h.name if h else None,
            "agent_id": t.agent_id,
            "agent_name": a.name if a else None,
            "labels": t.labels or "",
            "updated_at": t.updated_at.isoformat() + "Z" if getattr(t, "updated_at", None) else None,
        })
    # Recent ops of kind human / notify
    ops = []
    try:
        from ..live_ops import list_ops
        for ev in list_ops(db, user.id, limit=40):
            kind = (ev.get("kind") or "") if isinstance(ev, dict) else getattr(ev, "kind", "")
            title = (ev.get("title") or "") if isinstance(ev, dict) else getattr(ev, "title", "")
            if kind in ("human", "action") or "human" in (title or "").lower() or "notify" in (title or "").lower():
                ops.append(ev if isinstance(ev, dict) else {
                    "kind": kind,
                    "title": title,
                    "detail": getattr(ev, "detail", None),
                    "status": getattr(ev, "status", None),
                    "created_at": getattr(ev, "created_at", None),
                })
    except Exception:
        ops = []

    humans = (
        db.query(models.Human)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Human.is_my_human.desc(), models.Human.name)
        .all()
    )
    return {
        "ok": True,
        "my_human": _out(my, db),
        "unread_count": unread,
        "recent_messages": recent,
        "open_human_tasks": task_items,
        "ops": ops[:20],
        "team": [_out(h, db) for h in humans],
        "stats": {
            "team_size": len(humans),
            "unread": unread,
            "open_tasks": len(task_items),
            "messages": len(recent),
        },
    }


@router.post("/inbox/mark-read")
def mark_inbox_read(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    my = human_service.ensure_my_human(db, user)
    n = human_service.mark_messages_read(db, user, my.id)
    db.commit()
    return {"ok": True, "marked": n, "human_id": my.id}


@router.post("/")
async def create_human(data: HumanIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    # Ensure primary exists first
    human_service.ensure_my_human(db, user)
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    from ..permissions import normalize_permission, normalize_escalate_when, normalize_escalate_to
    make_primary = bool(data.is_my_human)
    h = models.Human(
        owner_user_id=user.id,
        name=name,
        email=(data.email or "").strip(),
        phone=(getattr(data, "phone", None) or "").strip(),
        role_title=(data.role_title or "").strip(),
        skills=(data.skills or "").strip(),
        company_id=data.company_id,
        project_id=data.project_id,
        status=data.status or "active",
        capacity=max(1, int(data.capacity or 5)),
        notes=(data.notes or "").strip(),
        permission_level=normalize_permission(data.permission_level),
        escalate_when=normalize_escalate_when(data.escalate_when),
        escalate_reason=(data.escalate_reason or "").strip(),
        escalate_to=normalize_escalate_to(data.escalate_to),
        is_my_human=False,
    )
    db.add(h)
    db.flush()
    if make_primary:
        human_service.set_my_human(db, user, h.id)
    db.commit()
    db.refresh(h)
    await emit_ops(
        user.id,
        kind="human",
        status="info",
        title=f"Human added: {h.name}",
        detail=h.role_title or h.email or "",
        human_id=h.id,
        db=db,
    )
    return _out(h, db)


@router.get("/{human_id}")
def get_human(human_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    h = require_owned(
        db, models.Human, human_id, user,
        user_field='owner_user_id', not_found="Human not found",
    )
    tasks = (
        db.query(models.Task)
        .filter_by(human_id=h.id)
        .order_by(models.Task.id.desc())
        .limit(40)
        .all()
    )
    try:
        messages = human_service.list_human_messages(db, user, h.id, limit=40)
    except ValueError:
        messages = []
    return {
        **_out(h, db),
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "status": t.status,
                "priority": t.priority,
                "agent_id": t.agent_id,
                "created_at": t.created_at,
            }
            for t in tasks
        ],
        "messages": messages,
    }


@router.put("/{human_id}")
def update_human(
    human_id: int,
    data: HumanUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    h = require_owned(
        db, models.Human, human_id, user,
        user_field='owner_user_id', not_found="Human not found",
    )
    from ..permissions import normalize_permission, normalize_escalate_when, normalize_escalate_to
    for field in ("name", "email", "phone", "role_title", "skills", "status", "notes"):
        val = getattr(data, field)
        if val is not None:
            setattr(h, field, val.strip() if isinstance(val, str) else val)
    if data.company_id is not None:
        h.company_id = data.company_id or None
    if data.project_id is not None:
        h.project_id = data.project_id or None
    if data.capacity is not None:
        h.capacity = max(1, int(data.capacity))
    if data.permission_level is not None:
        h.permission_level = normalize_permission(data.permission_level)
    if data.escalate_when is not None:
        h.escalate_when = normalize_escalate_when(data.escalate_when)
    if data.escalate_reason is not None:
        h.escalate_reason = (data.escalate_reason or "").strip()
    if data.escalate_to is not None:
        h.escalate_to = normalize_escalate_to(data.escalate_to)
    if data.is_my_human is True:
        human_service.set_my_human(db, user, h.id)
    h.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(h)
    return _out(h, db)


@router.delete("/{human_id}")
def delete_human(human_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    h = require_owned(
        db, models.Human, human_id, user,
        user_field='owner_user_id', not_found="Human not found",
    )
    if getattr(h, "is_my_human", False):
        raise HTTPException(
            400,
            "Cannot remove My Human. Designate another person as My Human first, or keep this primary operator.",
        )
    for t in db.query(models.Task).filter_by(human_id=h.id).all():
        t.human_id = None
        if t.assignee_type == "human":
            t.assignee_type = "agent" if t.agent_id else "unassigned"
    # Clear message box + related_human_id refs so FK delete does not 500
    db.query(models.HumanMessage).filter_by(human_id=h.id).delete(synchronize_session=False)
    db.query(models.HumanMessage).filter_by(related_human_id=h.id).update(
        {"related_human_id": None}, synchronize_session=False
    )
    # Escalation logs may point at this human
    try:
        db.query(models.EscalationLog).filter_by(from_human_id=h.id).update(
            {"from_human_id": None}, synchronize_session=False
        )
        db.query(models.EscalationLog).filter_by(to_human_id=h.id).update(
            {"to_human_id": None}, synchronize_session=False
        )
    except Exception:
        pass
    db.delete(h)
    db.commit()
    return {"ok": True}


@router.get("/{human_id}/messages")
def get_messages(
    human_id: int,
    limit: int = 80,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        msgs = human_service.list_human_messages(db, user, human_id, limit=limit)
        human_service.mark_messages_read(db, user, human_id)
        db.commit()
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"messages": msgs, "count": len(msgs)}


@router.post("/{human_id}/messages")
async def post_message(
    human_id: int,
    data: MessageIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    role = "owner"
    agent_id = data.sender_agent_id
    if agent_id:
        a = db.get(models.Agent, agent_id)
        if not a or a.user_id != user.id:
            raise HTTPException(400, "Invalid sender_agent_id")
        role = "agent"
    try:
        msg = human_service.post_human_message(
            db,
            user=user,
            human_id=human_id,
            content=data.content,
            sender_role=role,
            sender_agent_id=agent_id,
            related_human_id=data.related_human_id,
            task_id=data.task_id,
            kind=data.kind or "message",
        )
        db.commit()
        db.refresh(msg)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    h = db.get(models.Human, human_id)
    # Optional email/SMS notify when owner messages
    notify = None
    if role == "owner" and h:
        try:
            from ..human_notify import notify_human
            notify = await notify_human(
                db,
                user,
                title=f"Message for {h.name}",
                details=(data.content or "")[:2000],
                human_id=h.id,
                link_path=f"/humans",
            )
        except Exception as e:
            notify = {"ok": False, "error": str(e)[:200]}

    await emit_ops(
        user.id,
        kind="human",
        status="info",
        title=f"Message → {h.name if h else human_id}",
        detail=(data.content or "")[:200],
        human_id=human_id,
        agent_id=agent_id,
        db=db,
    )
    msgs = human_service.list_human_messages(db, user, human_id, limit=40)
    return {"ok": True, "messages": msgs, "notify": notify}


@router.post("/{human_id}/assign")
async def assign_work(
    human_id: int,
    data: AssignIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    h = require_owned(
        db, models.Human, human_id, user,
        user_field='owner_user_id', not_found="Human not found",
    )
    title = (data.title or "").strip()
    if not title:
        raise HTTPException(400, "title required")
    agent_id = data.agent_id
    if agent_id:
        a = db.get(models.Agent, agent_id)
        if not a or a.user_id != user.id:
            raise HTTPException(400, "Invalid agent_id")
    t = models.Task(
        user_id=user.id,
        human_id=h.id,
        agent_id=agent_id,
        assignee_type="human",
        company_id=data.company_id or h.company_id,
        project_id=data.project_id or h.project_id,
        title=title,
        description=(data.description or title).strip(),
        status="todo",
        priority=data.priority or "medium",
        labels="human,allocated" + (",my-human" if getattr(h, "is_my_human", False) else ""),
    )
    db.add(t)
    db.flush()
    note = (data.message or "").strip() or f"Task assigned: {title}"
    human_service.post_human_message(
        db,
        user=user,
        human_id=h.id,
        content=note,
        sender_role="owner",
        sender_agent_id=agent_id,
        task_id=t.id,
        kind="task_delegate",
    )
    db.commit()
    db.refresh(t)
    await emit_ops(
        user.id,
        kind="human",
        status="queued",
        title=f"Assigned to {h.name}",
        detail=title,
        human_id=h.id,
        agent_id=agent_id,
        task_id=t.id,
        db=db,
    )
    return {
        "ok": True,
        "task": {
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "human_id": h.id,
            "agent_id": agent_id,
        },
        "human": _out(h, db),
    }


@router.post("/{human_id}/delegate")
async def delegate_work(
    human_id: int,
    data: DelegateIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    From My Human (or any human): create a task for another human and/or agent,
    and log the delegation in both message boxes.
    """
    source = require_owned(
        db, models.Human, human_id, user,
        user_field='owner_user_id', not_found="Human not found",
    )
    title = (data.title or "").strip()
    if not title:
        raise HTTPException(400, "title required")
    if not data.to_human_id and not data.to_agent_id:
        raise HTTPException(400, "Provide to_human_id and/or to_agent_id")

    to_human = None
    if data.to_human_id:
        to_human = db.get(models.Human, data.to_human_id)
        if not to_human or to_human.owner_user_id != user.id:
            raise HTTPException(400, "Invalid to_human_id")
    to_agent = None
    if data.to_agent_id:
        to_agent = db.get(models.Agent, data.to_agent_id)
        if not to_agent or to_agent.user_id != user.id:
            raise HTTPException(400, "Invalid to_agent_id")

    assignee_type = "human" if to_human else "agent"
    t = models.Task(
        user_id=user.id,
        human_id=to_human.id if to_human else None,
        agent_id=to_agent.id if to_agent else None,
        assignee_type=assignee_type,
        company_id=data.company_id or source.company_id,
        project_id=data.project_id or source.project_id,
        title=title,
        description=(data.description or title).strip(),
        status="todo" if to_human else "queued",
        priority=data.priority or "medium",
        labels=f"delegated,from-human-{source.id}"
        + (",my-human" if getattr(source, "is_my_human", False) else ""),
    )
    db.add(t)
    db.flush()

    targets = []
    if to_human:
        targets.append(f"human:{to_human.name}")
    if to_agent:
        targets.append(f"agent:{to_agent.name}")
    body = (
        (data.message or "").strip()
        or f"{source.name} delegated “{title}” → {', '.join(targets)}"
    )
    # Source human thread
    human_service.post_human_message(
        db,
        user=user,
        human_id=source.id,
        content=body,
        sender_role="human",
        related_human_id=to_human.id if to_human else None,
        sender_agent_id=to_agent.id if to_agent else None,
        task_id=t.id,
        kind="task_delegate",
    )
    # Target human thread
    if to_human:
        human_service.post_human_message(
            db,
            user=user,
            human_id=to_human.id,
            content=f"Delegated from {source.name}: {body}",
            sender_role="human",
            related_human_id=source.id,
            sender_agent_id=to_agent.id if to_agent else None,
            task_id=t.id,
            kind="task_delegate",
        )
    db.commit()
    db.refresh(t)

    await emit_ops(
        user.id,
        kind="human",
        status="queued",
        title=f"{source.name} delegated: {title}",
        detail=", ".join(targets),
        human_id=source.id,
        agent_id=to_agent.id if to_agent else None,
        task_id=t.id,
        db=db,
    )
    return {
        "ok": True,
        "task": {
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "human_id": to_human.id if to_human else None,
            "agent_id": to_agent.id if to_agent else None,
            "from_human_id": source.id,
        },
        "from_human": _out(source, db),
        "to_human": _out(to_human, db) if to_human else None,
    }
