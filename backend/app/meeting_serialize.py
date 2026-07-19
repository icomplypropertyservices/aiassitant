"""Shared meeting room / participant / message JSON serialization (for meetings router).

Mirrors agent_serialize patterns:
- batch entity maps for list endpoints (avoid N+1)
- safe getattr for optional columns
- ISO datetimes with trailing Z for naive UTC
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models


def _dt(v: datetime | None) -> str | None:
    """ISO-8601 serialize; naive datetimes treated as UTC (append Z)."""
    if not v:
        return None
    if isinstance(v, datetime):
        return v.isoformat() + ("Z" if v.tzinfo is None else "")
    return str(v)


def _parse_json(raw: str | None, default: Any = None) -> Any:
    if default is None:
        default = {}
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _agent_label(a: models.Agent | None, fallback_id: int | None = None) -> str | None:
    if a is not None:
        name = (getattr(a, "name", None) or "").strip()
        return name or f"Agent #{a.id}"
    if fallback_id:
        return f"Agent #{fallback_id}"
    return None


def _human_label(h: models.Human | None, fallback_id: int | None = None) -> str | None:
    if h is not None:
        name = (getattr(h, "name", None) or "").strip()
        return name or f"Human #{h.id}"
    if fallback_id:
        return f"Human #{fallback_id}"
    return None


def _user_label(u: models.User | None, fallback_id: int | None = None) -> str | None:
    if u is not None:
        name = (getattr(u, "name", None) or "").strip()
        email = (getattr(u, "email", None) or "").strip()
        return name or email or f"User #{u.id}"
    if fallback_id:
        return f"User #{fallback_id}"
    return None


def _agent_detail(a: models.Agent | None) -> str:
    if a is None:
        return ""
    return (
        (getattr(a, "template_type", None) or "").strip()
        or (getattr(a, "hierarchy_role", None) or "").strip()
        or ""
    )


def _human_detail(h: models.Human | None) -> str:
    if h is None:
        return ""
    return (getattr(h, "role_title", None) or "").strip()


# ── Batch loaders (agent_serialize load_name_maps style) ─────────────────

def load_entity_maps(
    db: Session,
    *,
    agent_ids: set[int] | None = None,
    human_ids: set[int] | None = None,
    user_ids: set[int] | None = None,
    company_ids: set[int] | None = None,
    project_ids: set[int] | None = None,
    task_ids: set[int] | None = None,
) -> dict[str, dict[int, Any]]:
    """Batch-load agents/humans/users/companies/projects/tasks by id."""
    agents: dict[int, models.Agent] = {}
    humans: dict[int, models.Human] = {}
    users: dict[int, models.User] = {}
    companies: dict[int, models.Company] = {}
    projects: dict[int, models.Project] = {}
    tasks: dict[int, models.Task] = {}

    if agent_ids:
        for a in db.query(models.Agent).filter(models.Agent.id.in_(agent_ids)).all():
            agents[a.id] = a
    if human_ids:
        for h in db.query(models.Human).filter(models.Human.id.in_(human_ids)).all():
            humans[h.id] = h
    if user_ids:
        for u in db.query(models.User).filter(models.User.id.in_(user_ids)).all():
            users[u.id] = u
    if company_ids:
        for c in db.query(models.Company).filter(models.Company.id.in_(company_ids)).all():
            companies[c.id] = c
    if project_ids:
        for p in db.query(models.Project).filter(models.Project.id.in_(project_ids)).all():
            projects[p.id] = p
    if task_ids:
        for t in db.query(models.Task).filter(models.Task.id.in_(task_ids)).all():
            tasks[t.id] = t

    return {
        "agents": agents,
        "humans": humans,
        "users": users,
        "companies": companies,
        "projects": projects,
        "tasks": tasks,
    }


def _ids_from_rooms(rooms: list[models.MeetingRoom]) -> dict[str, set[int]]:
    agent_ids: set[int] = set()
    company_ids: set[int] = set()
    project_ids: set[int] = set()
    task_ids: set[int] = set()
    for r in rooms:
        cid = getattr(r, "chair_agent_id", None)
        if cid:
            agent_ids.add(int(cid))
        if getattr(r, "company_id", None):
            company_ids.add(int(r.company_id))
        if getattr(r, "project_id", None):
            project_ids.add(int(r.project_id))
        if getattr(r, "task_id", None):
            task_ids.add(int(r.task_id))
    return {
        "agent_ids": agent_ids,
        "company_ids": company_ids,
        "project_ids": project_ids,
        "task_ids": task_ids,
    }


def _ids_from_participants(parts: list[models.MeetingParticipant]) -> dict[str, set[int]]:
    agent_ids: set[int] = set()
    human_ids: set[int] = set()
    user_ids: set[int] = set()
    for p in parts:
        if getattr(p, "agent_id", None):
            agent_ids.add(int(p.agent_id))
        if getattr(p, "human_id", None):
            human_ids.add(int(p.human_id))
        if getattr(p, "user_id", None):
            user_ids.add(int(p.user_id))
    return {
        "agent_ids": agent_ids,
        "human_ids": human_ids,
        "user_ids": user_ids,
    }


def _ids_from_messages(msgs: list[models.MeetingMessage]) -> dict[str, set[int]]:
    agent_ids: set[int] = set()
    human_ids: set[int] = set()
    user_ids: set[int] = set()
    for m in msgs:
        if getattr(m, "sender_agent_id", None):
            agent_ids.add(int(m.sender_agent_id))
        if getattr(m, "sender_human_id", None):
            human_ids.add(int(m.sender_human_id))
        if getattr(m, "sender_user_id", None):
            user_ids.add(int(m.sender_user_id))
    return {
        "agent_ids": agent_ids,
        "human_ids": human_ids,
        "user_ids": user_ids,
    }


def _resolve_entity(
    entity_id: int | None,
    cache: dict[int, Any] | None,
    db: Session | None,
    model: type,
) -> Any | None:
    if not entity_id:
        return None
    eid = int(entity_id)
    if cache is not None:
        return cache.get(eid)
    if db is not None:
        return db.get(model, eid)
    return None


# ── Serializers ──────────────────────────────────────────────────────────

def participant_out(
    p: models.MeetingParticipant,
    db: Session | None = None,
    *,
    agents: dict[int, models.Agent] | None = None,
    humans: dict[int, models.Human] | None = None,
    users: dict[int, models.User] | None = None,
) -> dict:
    """Serialize a MeetingParticipant. Prefer preloaded maps; fall back to db.get."""
    agent_id = getattr(p, "agent_id", None)
    human_id = getattr(p, "human_id", None)
    user_id = getattr(p, "user_id", None)
    kind = (getattr(p, "kind", None) or "agent").lower()

    agent = _resolve_entity(agent_id, agents, db, models.Agent)
    human = _resolve_entity(human_id, humans, db, models.Human)
    user = _resolve_entity(user_id, users, db, models.User)

    # Use fallback labels only when we attempted resolution (db or maps present)
    can_resolve = db is not None or agents is not None or humans is not None or users is not None
    fb = True if can_resolve else False

    agent_name = _agent_label(agent, agent_id if fb else None) if agent_id else None
    human_name = _human_label(human, human_id if fb else None) if human_id else None
    user_name = _user_label(user, user_id if fb else None) if user_id else None

    display_name: str | None = None
    detail = ""
    if kind == "agent":
        display_name = agent_name
        detail = _agent_detail(agent)
    elif kind == "human":
        display_name = human_name
        detail = _human_detail(human)
    elif kind == "user":
        display_name = user_name
        detail = "owner" if user is not None or (user_id and fb) else ""

    return {
        "id": p.id,
        "room_id": p.room_id,
        "kind": getattr(p, "kind", None) or "agent",
        "role": getattr(p, "role", None) or "member",
        "user_id": user_id,
        "user_name": user_name,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "human_id": human_id,
        "human_name": human_name,
        "display_name": display_name,
        "name": display_name or "",
        "detail": detail,
        "last_read_at": _dt(getattr(p, "last_read_at", None)),
        "joined_at": _dt(getattr(p, "joined_at", None)),
    }


def message_out(
    m: models.MeetingMessage,
    db: Session | None = None,
    *,
    agents: dict[int, models.Agent] | None = None,
    humans: dict[int, models.Human] | None = None,
    users: dict[int, models.User] | None = None,
) -> dict:
    """Serialize a MeetingMessage. Prefer preloaded maps; fall back to db.get."""
    sender_agent_id = getattr(m, "sender_agent_id", None)
    sender_human_id = getattr(m, "sender_human_id", None)
    sender_user_id = getattr(m, "sender_user_id", None)
    kind = (getattr(m, "sender_kind", None) or "user").lower()

    agent = _resolve_entity(sender_agent_id, agents, db, models.Agent)
    human = _resolve_entity(sender_human_id, humans, db, models.Human)
    user = _resolve_entity(sender_user_id, users, db, models.User)

    can_resolve = db is not None or agents is not None or humans is not None or users is not None
    fb = True if can_resolve else False

    sender_agent_name = (
        _agent_label(agent, sender_agent_id if fb else None) if sender_agent_id else None
    )
    sender_human_name = (
        _human_label(human, sender_human_id if fb else None) if sender_human_id else None
    )
    sender_user_name = (
        _user_label(user, sender_user_id if fb else None) if sender_user_id else None
    )

    sender_name = ""
    if kind == "agent":
        sender_name = sender_agent_name or ""
    elif kind == "human":
        sender_name = sender_human_name or ""
    elif kind == "user":
        sender_name = sender_user_name or ""
    elif kind == "system":
        sender_name = "System"

    return {
        "id": m.id,
        "room_id": m.room_id,
        "sender_kind": getattr(m, "sender_kind", None) or "user",
        "sender_user_id": sender_user_id,
        "sender_user_name": sender_user_name,
        "sender_agent_id": sender_agent_id,
        "sender_agent_name": sender_agent_name,
        "sender_human_id": sender_human_id,
        "sender_human_name": sender_human_name,
        "sender_name": sender_name,
        "content": getattr(m, "content", None) or "",
        "msg_type": getattr(m, "msg_type", None) or "chat",
        "meta": _parse_json(getattr(m, "meta_json", None), {}),
        "created_at": _dt(getattr(m, "created_at", None)),
    }


def room_out(
    room: models.MeetingRoom,
    db: Session | None = None,
    *,
    with_participants: bool = True,
    with_messages: bool = False,
    message_limit: int = 50,
    # Optional preloaded data (list batching)
    participants: list[models.MeetingParticipant] | None = None,
    messages: list[models.MeetingMessage] | None = None,
    message_count: int | None = None,
    participant_count: int | None = None,
    agents: dict[int, models.Agent] | None = None,
    humans: dict[int, models.Human] | None = None,
    users: dict[int, models.User] | None = None,
    companies: dict[int, models.Company] | None = None,
    projects: dict[int, models.Project] | None = None,
    tasks: dict[int, models.Task] | None = None,
) -> dict:
    """Serialize a MeetingRoom.

    Always includes: status, room_type, message_count, participant_count.
    When with_participants=True, includes participants[].
    When with_messages=True, includes messages[]; else messages=null.
    Datetimes are ISO strings.
    """
    chair_agent_id = getattr(room, "chair_agent_id", None)
    company_id = getattr(room, "company_id", None)
    project_id = getattr(room, "project_id", None)
    task_id = getattr(room, "task_id", None)

    # Participants first so we can batch-resolve with room-linked entities
    part_rows: list[models.MeetingParticipant] = []
    if with_participants:
        if participants is not None:
            part_rows = list(participants)
        elif db is not None:
            try:
                part_rows = (
                    db.query(models.MeetingParticipant)
                    .filter_by(room_id=room.id)
                    .order_by(models.MeetingParticipant.id)
                    .all()
                )
            except Exception:
                # Missing participant table/columns — leave empty rather than 500
                part_rows = []

    msg_rows: list[models.MeetingMessage] = []
    if with_messages:
        if messages is not None:
            msg_rows = list(messages)
        elif db is not None:
            try:
                msgs = (
                    db.query(models.MeetingMessage)
                    .filter_by(room_id=room.id)
                    .order_by(models.MeetingMessage.id.desc())
                    .limit(message_limit)
                    .all()
                )
                msg_rows = list(reversed(msgs))
            except Exception:
                msg_rows = []

    # Single-room path: batch-load all referenced entities once
    if db is not None and agents is None:
        p_ids = _ids_from_participants(part_rows)
        m_ids = _ids_from_messages(msg_rows)
        agent_ids = set(p_ids["agent_ids"]) | set(m_ids["agent_ids"])
        if chair_agent_id:
            agent_ids.add(int(chair_agent_id))
        maps = load_entity_maps(
            db,
            agent_ids=agent_ids,
            human_ids=p_ids["human_ids"] | m_ids["human_ids"],
            user_ids=p_ids["user_ids"] | m_ids["user_ids"],
            company_ids={int(company_id)} if company_id else set(),
            project_ids={int(project_id)} if project_id else set(),
            task_ids={int(task_id)} if task_id else set(),
        )
        agents = maps["agents"]
        humans = maps["humans"]
        users = maps["users"]
        companies = maps["companies"]
        projects = maps["projects"]
        tasks = maps["tasks"]

    chair_agent = _resolve_entity(chair_agent_id, agents, db, models.Agent)
    company = _resolve_entity(company_id, companies, db, models.Company)
    project = _resolve_entity(project_id, projects, db, models.Project)
    task = _resolve_entity(task_id, tasks, db, models.Task)

    chair_agent_name = None
    if chair_agent is not None:
        chair_agent_name = (getattr(chair_agent, "name", None) or "").strip() or None

    company_name = getattr(company, "name", None) if company else None
    project_name = getattr(project, "name", None) if project else None
    task_title = None
    if task is not None:
        title = (getattr(task, "title", None) or "").strip()
        desc = (getattr(task, "description", None) or "")[:120]
        task_title = title or (desc or None)

    participants_out = [
        participant_out(p, db, agents=agents, humans=humans, users=users)
        for p in part_rows
    ]

    if participant_count is None:
        if with_participants:
            participant_count = len(participants_out)
        elif db is not None:
            try:
                participant_count = (
                    db.query(models.MeetingParticipant)
                    .filter_by(room_id=room.id)
                    .count()
                )
            except Exception:
                participant_count = 0
        else:
            participant_count = 0

    if message_count is None:
        if db is not None:
            try:
                message_count = (
                    db.query(models.MeetingMessage)
                    .filter_by(room_id=room.id)
                    .count()
                )
            except Exception:
                message_count = 0
        else:
            message_count = 0

    messages_out = (
        [
            message_out(m, db, agents=agents, humans=humans, users=users)
            for m in msg_rows
        ]
        if with_messages
        else None
    )

    return {
        "id": room.id,
        "user_id": getattr(room, "user_id", None),
        "company_id": company_id,
        "company_name": company_name,
        "project_id": project_id,
        "project_name": project_name,
        "task_id": task_id,
        "task_title": task_title,
        "title": (getattr(room, "title", None) or "Meeting"),
        "purpose": getattr(room, "purpose", None) or "",
        "room_type": getattr(room, "room_type", None) or "brainstorm",
        "status": getattr(room, "status", None) or "open",
        "chair_agent_id": chair_agent_id,
        "chair_agent_name": chair_agent_name,
        "chair_name": chair_agent_name,  # alias for existing router clients
        "settings": _parse_json(getattr(room, "settings_json", None), {}),
        "summary_text": getattr(room, "summary_text", None) or "",
        "created_at": _dt(getattr(room, "created_at", None)),
        "closed_at": _dt(getattr(room, "closed_at", None)),
        "participant_count": participant_count,
        "message_count": message_count,
        "participants": participants_out if with_participants else [],
        "messages": messages_out,
    }


def rooms_out_list(
    db: Session,
    rooms: list[models.MeetingRoom],
    *,
    with_participants: bool = True,
    with_messages: bool = False,
    message_limit: int = 50,
) -> list[dict]:
    """Batch-serialize many rooms (list endpoint) — avoids N+1 queries."""
    if not rooms:
        return []

    room_ids = [r.id for r in rooms]

    # Message counts in one GROUP BY (empty if message table/cols lag)
    try:
        msg_counts: dict[int, int] = dict(
            db.query(models.MeetingMessage.room_id, func.count(models.MeetingMessage.id))
            .filter(models.MeetingMessage.room_id.in_(room_ids))
            .group_by(models.MeetingMessage.room_id)
            .all()
        )
    except Exception:
        msg_counts = {}

    # Participants for all rooms (or counts only)
    all_parts: list[models.MeetingParticipant] = []
    parts_by_room: dict[int, list[models.MeetingParticipant]] = defaultdict(list)
    part_counts: dict[int, int] = {}
    if with_participants:
        try:
            all_parts = (
                db.query(models.MeetingParticipant)
                .filter(models.MeetingParticipant.room_id.in_(room_ids))
                .order_by(models.MeetingParticipant.id)
                .all()
            )
            for p in all_parts:
                parts_by_room[p.room_id].append(p)
        except Exception:
            all_parts = []
    else:
        try:
            part_counts = dict(
                db.query(
                    models.MeetingParticipant.room_id,
                    func.count(models.MeetingParticipant.id),
                )
                .filter(models.MeetingParticipant.room_id.in_(room_ids))
                .group_by(models.MeetingParticipant.room_id)
                .all()
            )
        except Exception:
            part_counts = {}

    # Optional messages (rare for list)
    msgs_by_room: dict[int, list[models.MeetingMessage]] = defaultdict(list)
    all_msgs: list[models.MeetingMessage] = []
    if with_messages:
        try:
            raw_msgs = (
                db.query(models.MeetingMessage)
                .filter(models.MeetingMessage.room_id.in_(room_ids))
                .order_by(models.MeetingMessage.id.desc())
                .all()
            )
            for m in raw_msgs:
                bucket = msgs_by_room[m.room_id]
                if len(bucket) < message_limit:
                    bucket.append(m)
            for rid in list(msgs_by_room.keys()):
                msgs_by_room[rid] = list(reversed(msgs_by_room[rid]))
                all_msgs.extend(msgs_by_room[rid])
        except Exception:
            msgs_by_room = defaultdict(list)
            all_msgs = []

    r_ids = _ids_from_rooms(rooms)
    p_ids = _ids_from_participants(all_parts)
    m_ids = _ids_from_messages(all_msgs)
    maps = load_entity_maps(
        db,
        agent_ids=r_ids["agent_ids"] | p_ids["agent_ids"] | m_ids["agent_ids"],
        human_ids=p_ids["human_ids"] | m_ids["human_ids"],
        user_ids=p_ids["user_ids"] | m_ids["user_ids"],
        company_ids=r_ids["company_ids"],
        project_ids=r_ids["project_ids"],
        task_ids=r_ids["task_ids"],
    )

    out: list[dict] = []
    for r in rooms:
        rid = r.id
        if with_participants:
            pcount = len(parts_by_room.get(rid, []))
            prows: list[models.MeetingParticipant] | None = parts_by_room.get(rid, [])
        else:
            pcount = part_counts.get(rid, 0)
            prows = None

        out.append(
            room_out(
                r,
                db,
                with_participants=with_participants,
                with_messages=with_messages,
                message_limit=message_limit,
                participants=prows,
                messages=msgs_by_room.get(rid) if with_messages else None,
                message_count=msg_counts.get(rid, 0),
                participant_count=pcount,
                agents=maps["agents"],
                humans=maps["humans"],
                users=maps["users"],
                companies=maps["companies"],
                projects=maps["projects"],
                tasks=maps["tasks"],
            )
        )
    return out
