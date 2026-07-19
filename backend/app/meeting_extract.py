"""Extract actionable tasks from a meeting room thread.

Used when POST extract-tasks is called (or by callers that import this module).
Heuristic-first: action-looking lines from recent messages / summary become Tasks.
Optional LLM path can refine candidates when available.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models

# How many recent messages to scan
_DEFAULT_MESSAGE_LIMIT = 80
# Cap tasks created per extract call
_MAX_TASKS = 8
# Prefer 1–3 from summary when no action lines found
_SUMMARY_TASK_CAP = 3

# Lines that look like action items / todos
_ACTION_PREFIX = re.compile(
    r"""^
    (?:
        (?:[-*•]|\d+[.)])\s+          # bullet or numbered
        |
        (?:TODO|FIXME|ACTION|TASK)\s*[:\-–—]\s*  # TODO: …
        |
        (?:let'?s|please|need\s+to)\s+  # soft imperative
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Weaker prefixes only count as actions when the line is short (one step)
_SOFT_PREFIX = re.compile(
    r"^(?:we|ai|should|must|will)\s+\S+",
    re.IGNORECASE,
)

_VERB_START = re.compile(
    r"^(?:create|build|write|send|schedule|update|fix|review|draft|call|"
    r"email|follow\s*up|prepare|ship|deploy|implement|research|check|"
    r"confirm|book|assign|share|publish|launch|set\s+up|setup|add|remove|"
    r"refactor|test|document|summarize|notify|reach\s+out|investigate|"
    r"design|plan|organize|complete|finish|resolve)\b",
    re.IGNORECASE,
)

_SKIP_LINE = re.compile(
    r"^(?:hi|hello|hey|thanks|thank you|ok|okay|yes|no|sure|lol|hmm)\b",
    re.IGNORECASE,
)


def _clean_line(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"\s+", " ", s)
    # Strip common list markers after match
    s = re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", s)
    s = re.sub(
        r"^(?:TODO|FIXME|ACTION|TASK)\s*[:\-–—]\s*",
        "",
        s,
        flags=re.IGNORECASE,
    )
    # "Action: do X" / "Next step: Y"
    s = re.sub(
        r"^(?:action\s*items?|next\s*steps?|follow[- ]?ups?)\s*[:\-–—]\s*",
        "",
        s,
        flags=re.IGNORECASE,
    )
    return s.strip(" \t-–—:;")


def _is_action_line(line: str) -> bool:
    raw = (line or "").strip()
    if len(raw) < 8 or len(raw) > 400:
        return False
    if _SKIP_LINE.match(raw):
        return False
    # Decision/system noise
    if raw.lower().startswith(("[system]", "[decision]")):
        return False
    # Multi-sentence blobs are not a single action line
    if len(re.findall(r"[.!?]", raw)) >= 2:
        return False
    cleaned = _clean_line(raw)
    if len(cleaned) < 6:
        return False
    if _ACTION_PREFIX.match(raw) or _ACTION_PREFIX.match(cleaned):
        return True
    if _VERB_START.match(cleaned):
        return True
    # Soft prefixes only for concise one-step lines
    if len(cleaned) <= 100 and _SOFT_PREFIX.match(cleaned):
        return True
    # Explicit assignment / deadline phrasing
    if re.search(r"\b(?:will|should|needs?\s+to|must|please)\b", cleaned, re.I):
        if re.search(
            r"\b(?:by|before|tomorrow|today|this\s+week|asap|eod|eow)\b",
            cleaned,
            re.I,
        ) or re.search(r"\b(?:@\w+|assign(?:ed)?\s+to)\b", cleaned, re.I):
            return True
    return False


def _split_summary_into_tasks(summary: str, limit: int = _SUMMARY_TASK_CAP) -> list[str]:
    """Turn free-text summary into 1–3 task titles."""
    text = (summary or "").strip()
    if not text:
        return []
    candidates: list[str] = []

    def _add(title: str) -> bool:
        t = _clean_line(title)
        if not t or len(t) < 6:
            return False
        key = t.lower()
        if any(c.lower() == key for c in candidates):
            return False
        candidates.append(t[:200])
        return len(candidates) >= limit

    # Prefer bullet / numbered / clear action lines
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"^(?:[-*•]|\d+[.)])\s+", line) or _is_action_line(line):
            if _add(line):
                return candidates[:limit]
    if candidates:
        return candidates[:limit]

    # Sentence split — prefer imperative / verb-led sentences
    parts = re.split(r"(?<=[.!?])\s+|\n+|;+\s*", text)
    verbish: list[str] = []
    other: list[str] = []
    for p in parts:
        p = _clean_line(p)
        if len(p) < 12:
            continue
        if _is_action_line(p) or _VERB_START.match(p):
            verbish.append(p)
        else:
            other.append(p)
    for p in verbish + other:
        if _add(p):
            return candidates[:limit]
    if candidates:
        return candidates[:limit]
    # Single fallback task from whole summary
    return [text[:200]]


def _load_messages(db: Session, room_id: int, limit: int = _DEFAULT_MESSAGE_LIMIT) -> list[models.MeetingMessage]:
    return (
        db.query(models.MeetingMessage)
        .filter(models.MeetingMessage.room_id == room_id)
        .order_by(models.MeetingMessage.id.desc())
        .limit(limit)
        .all()
    )


def _collect_candidate_titles(
    messages: list[models.MeetingMessage],
    summary: str,
) -> tuple[list[str], str]:
    """Heuristic: action lines from chat, else 1–3 from summary.

    Returns (titles, source) where source is ``actions`` | ``summary`` | ``empty``.
    """
    titles: list[str] = []
    seen: set[str] = set()

    # Oldest → newest so extraction order matches conversation flow
    for msg in reversed(messages):
        if (msg.msg_type or "chat") in ("system", "task_created"):
            continue
        content = (msg.content or "").strip()
        if not content:
            continue
        for line in content.splitlines():
            line = line.strip()
            if not _is_action_line(line):
                continue
            title = _clean_line(line)
            if not title:
                continue
            key = title.lower()
            if key in seen:
                continue
            seen.add(key)
            titles.append(title)
            if len(titles) >= _MAX_TASKS:
                return titles, "actions"

    if titles:
        return titles, "actions"

    for t in _split_summary_into_tasks(summary, _SUMMARY_TASK_CAP):
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        titles.append(t)
    if titles:
        return titles[:_MAX_TASKS], "summary"
    return [], "empty"


def _resolve_agent_id(db: Session, room: models.MeetingRoom, user: models.User) -> int | None:
    """Prefer chair agent, else first agent participant owned by user."""
    if room.chair_agent_id:
        a = db.get(models.Agent, room.chair_agent_id)
        if a and (a.user_id == user.id or user.role == "admin"):
            return a.id
    parts = (
        db.query(models.MeetingParticipant)
        .filter(
            models.MeetingParticipant.room_id == room.id,
            models.MeetingParticipant.kind == "agent",
            models.MeetingParticipant.agent_id.isnot(None),
        )
        .order_by(models.MeetingParticipant.id.asc())
        .all()
    )
    for p in parts:
        a = db.get(models.Agent, p.agent_id)
        if a and (a.user_id == user.id or user.role == "admin"):
            return a.id
    # Fall back to room's linked task agent
    if room.task_id:
        parent = db.get(models.Task, room.task_id)
        if parent and parent.agent_id:
            return parent.agent_id
    return None


def _task_out(t: models.Task) -> dict[str, Any]:
    return {
        "id": t.id,
        "project_id": t.project_id,
        "company_id": t.company_id,
        "agent_id": t.agent_id,
        "human_id": t.human_id,
        "meeting_id": t.meeting_id,
        "parent_task_id": t.parent_task_id,
        "title": t.title or (t.description or "")[:60],
        "description": t.description or "",
        "status": t.status,
        "priority": t.priority or "medium",
        "assignee_type": t.assignee_type or "unassigned",
        "labels": t.labels or "",
        "created_at": t.created_at.isoformat() + "Z" if t.created_at else None,
    }


def extract_tasks_from_room(
    db: Session,
    room: models.MeetingRoom,
    user: models.User,
    *,
    message_limit: int = _DEFAULT_MESSAGE_LIMIT,
    max_tasks: int = _MAX_TASKS,
    agent_id: int | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Load last messages, create Tasks from action lines or summary.

    - status = ``queued`` when an *active* agent is assigned, else ``todo``
    - each Task gets ``meeting_id`` set to the room
    - posts a system MeetingMessage with ``msg_type=task_created``

    Returns ``{"ok": True, "tasks": [...], "count": N, "source": "..."}``.
    """
    from .task_status import initial_task_status

    if not room:
        return {"ok": False, "error": "room required", "tasks": [], "count": 0}
    if room.user_id != user.id and getattr(user, "role", None) != "admin":
        return {"ok": False, "error": "not authorized for this room", "tasks": [], "count": 0}

    messages = _load_messages(db, room.id, limit=message_limit)
    summary = (room.summary_text or "").strip()
    titles, source = _collect_candidate_titles(messages, summary)

    # If still empty, synthesize a single follow-up from room purpose/title
    if not titles:
        fallback = _clean_line(room.purpose or room.title or "Follow up on meeting")
        if not fallback:
            fallback = f"Follow up: {room.title or f'Meeting #{room.id}'}"
        titles = [fallback[:200]]
        source = "fallback"

    titles = titles[: max(1, min(int(max_tasks or _MAX_TASKS), _MAX_TASKS))]

    resolved_agent = agent_id
    agent_row = None
    if resolved_agent is not None:
        agent_row = db.get(models.Agent, resolved_agent)
        if not agent_row or (agent_row.user_id != user.id and user.role != "admin"):
            resolved_agent = None
            agent_row = None
    if resolved_agent is None:
        resolved_agent = _resolve_agent_id(db, room, user)
        agent_row = db.get(models.Agent, resolved_agent) if resolved_agent else None

    assignee_type = "agent" if resolved_agent else "unassigned"
    status = initial_task_status(
        agent=agent_row,
        assignee_type=assignee_type,
        run_now=True,
    )
    parent_task_id = room.task_id if room.task_id else None

    created: list[models.Task] = []
    for title in titles:
        desc_parts = [
            title,
            f"\n\n— Extracted from meeting #{room.id}"
            + (f" · {room.title}" if room.title else ""),
        ]
        if summary and source in ("summary", "fallback"):
            desc_parts.append(f"\nMeeting summary:\n{summary[:1500]}")
        t = models.Task(
            project_id=room.project_id,
            company_id=room.company_id,
            agent_id=resolved_agent,
            human_id=None,
            assignee_type=assignee_type,
            user_id=user.id,
            parent_task_id=parent_task_id,
            meeting_id=room.id,
            title=title[:200],
            description="".join(desc_parts).strip(),
            status=status,
            priority="medium",
            labels="meeting,extracted",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(t)
        created.append(t)

    db.flush()

    # System message: task_created
    task_ids = [t.id for t in created]
    meta = {
        "task_ids": task_ids,
        "count": len(created),
        "source": source,
        "status": status,
        "agent_id": resolved_agent,
    }
    titles_preview = "; ".join(t.title for t in created[:5])
    if len(created) > 5:
        titles_preview += f" (+{len(created) - 5} more)"
    sys_msg = models.MeetingMessage(
        room_id=room.id,
        sender_kind="system",
        sender_user_id=None,
        sender_agent_id=None,
        sender_human_id=None,
        content=(
            f"Created {len(created)} task(s) from this meeting "
            f"(status={status}"
            + (f", agent_id={resolved_agent}" if resolved_agent else "")
            + f"): {titles_preview}"
        ),
        msg_type="task_created",
        meta_json=json.dumps(meta),
        created_at=datetime.utcnow(),
    )
    db.add(sys_msg)

    if commit:
        db.commit()
        for t in created:
            db.refresh(t)
        db.refresh(sys_msg)
    else:
        db.flush()

    return {
        "ok": True,
        "room_id": room.id,
        "tasks": [_task_out(t) for t in created],
        "count": len(created),
        "source": source,
        "status": status,
        "agent_id": resolved_agent,
        "message_id": sys_msg.id,
        "messages_scanned": len(messages),
    }
