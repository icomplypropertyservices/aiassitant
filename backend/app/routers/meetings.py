"""Meeting rooms — multi-party human + agent brainstorm / war-room threads."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from ..database import get_db
from ..ownership import require_owned
from .. import models
from ..auth_utils import get_current_user, ensure_credits
from ..live_ops import emit_ops
from ..llm import complete
from ..user_keys import credentials_for_user
from ..usage_billing import bill_llm_turn
from ..meeting_runner import run_meeting_round
from ..meeting_extract import extract_tasks_from_room
from ..meeting_serialize import (
    room_out as serialize_room,
    participant_out as serialize_participant,
    message_out as serialize_message,
    rooms_out_list,
)
from ..task_status import initial_task_status

log = logging.getLogger("app.meetings")

router = APIRouter(prefix="/meetings", tags=["meetings"])

ROOM_TYPES = {"brainstorm", "task_war_room", "standup", "review"}
ROOM_STATUSES = {"open", "active", "closed"}
PARTICIPANT_KINDS = {"user", "agent", "human"}
PARTICIPANT_ROLES = {"chair", "member", "observer"}
MSG_TYPES = {"chat", "decision", "task_created", "system"}
SENDER_KINDS = {"user", "agent", "human", "system"}

# Cache of live DB columns per table (None = inspect failed → assume model is fine)
_DB_COLS_CACHE: dict[str, set[str] | None] = {}


# ── Schemas ──────────────────────────────────────────────────────────────

class MeetingCreate(BaseModel):
    title: str = "Meeting"
    purpose: str = ""
    room_type: str = "brainstorm"
    company_id: int | None = None
    project_id: int | None = None
    task_id: int | None = None
    chair_agent_id: int | None = None
    settings: dict | None = None
    # Optional; null / omitted / [] all mean "no extra participants"
    # (owner is still auto-joined as user participant when that table is available)
    participants: list[dict] | None = Field(default=None)


class MeetingUpdate(BaseModel):
    title: str | None = None
    purpose: str | None = None
    room_type: str | None = None
    status: str | None = None
    company_id: int | None = None
    project_id: int | None = None
    task_id: int | None = None
    chair_agent_id: int | None = None
    settings: dict | None = None
    summary_text: str | None = None


class ParticipantIn(BaseModel):
    kind: str = "agent"  # user | agent | human
    role: str = "member"  # chair | member | observer
    user_id: int | None = None
    agent_id: int | None = None
    human_id: int | None = None


class MessageIn(BaseModel):
    content: str
    msg_type: str = "chat"
    # Optional: post as agent / human (defaults to current user)
    sender_kind: str = "user"
    sender_agent_id: int | None = None
    sender_human_id: int | None = None
    meta: dict | None = None


class RoundIn(BaseModel):
    prompt: str = ""
    max_turns: int = 1


class SummarizeIn(BaseModel):
    model: str = "fast"
    style: str = "concise"  # concise | detailed | decisions


class ExtractTasksIn(BaseModel):
    model: str = "fast"
    create: bool = True  # when true, persist Task rows linked to meeting
    assign_to_chair: bool = True


# ── Schema resilience (missing columns / partial Neon lag) ───────────────

def _is_schema_error(exc: BaseException) -> bool:
    """True for SQLite/Postgres errors caused by missing tables/columns."""
    if isinstance(exc, (OperationalError, ProgrammingError)):
        return True
    msg = str(exc).lower()
    needles = (
        "no such column",
        "no such table",
        "undefinedcolumn",
        "undefinedtable",
        "does not exist",
        "unknown column",
        "has no column",
    )
    return any(n in msg for n in needles)


def _db_columns(db: Session, table: str) -> set[str] | None:
    """Live column names for *table*, or None if inspect unavailable."""
    if table in _DB_COLS_CACHE:
        return _DB_COLS_CACHE[table]
    try:
        bind = db.get_bind()
        insp = sa_inspect(bind)
        if table not in insp.get_table_names():
            _DB_COLS_CACHE[table] = set()
            return set()
        cols = {c["name"] for c in insp.get_columns(table)}
        _DB_COLS_CACHE[table] = cols
        return cols
    except Exception as e:
        log.debug("column inspect failed for %s: %s", table, e)
        _DB_COLS_CACHE[table] = None
        return None


def _col_ok(db: Session, table: str, col: str) -> bool:
    """Whether *col* is safe to use on *table* (model + live DB when known)."""
    model_map = {
        "meeting_rooms": models.MeetingRoom,
        "meeting_participants": models.MeetingParticipant,
        "meeting_messages": models.MeetingMessage,
    }
    model = model_map.get(table)
    if model is not None and not hasattr(model, col):
        return False
    live = _db_columns(db, table)
    if live is None:
        return True  # cannot inspect — trust model
    return col in live


def _dt_iso(v) -> str | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v.isoformat() + ("Z" if v.tzinfo is None else "")
    return str(v)


def _minimal_room_out(room: models.MeetingRoom) -> dict:
    """Serialize a room using only getattr — never touches related tables."""
    return {
        "id": getattr(room, "id", None),
        "user_id": getattr(room, "user_id", None),
        "company_id": getattr(room, "company_id", None),
        "company_name": None,
        "project_id": getattr(room, "project_id", None),
        "project_name": None,
        "task_id": getattr(room, "task_id", None),
        "task_title": None,
        "title": (getattr(room, "title", None) or "Meeting"),
        "purpose": getattr(room, "purpose", None) or "",
        "room_type": getattr(room, "room_type", None) or "brainstorm",
        "status": getattr(room, "status", None) or "open",
        "chair_agent_id": getattr(room, "chair_agent_id", None),
        "chair_agent_name": None,
        "chair_name": None,
        "settings": {},
        "summary_text": getattr(room, "summary_text", None) or "",
        "created_at": _dt_iso(getattr(room, "created_at", None)),
        "closed_at": _dt_iso(getattr(room, "closed_at", None)),
        "participant_count": 0,
        "message_count": 0,
        "participants": [],
        "messages": None,
    }


def _safe_rollback(db: Session) -> None:
    try:
        db.rollback()
    except Exception:
        pass


# ── Serialization (shared module + thin wrappers) ────────────────────────

def _participant_out(p: models.MeetingParticipant, db: Session) -> dict:
    return serialize_participant(p, db)


def _message_out(m: models.MeetingMessage | dict, db: Session | None = None) -> dict:
    if isinstance(m, dict):
        return m
    return serialize_message(m, db)


def _room_out(
    room: models.MeetingRoom,
    db: Session,
    *,
    with_participants: bool = True,
    with_messages: bool = False,
    message_limit: int = 50,
) -> dict:
    """Full serialize with graceful fallback when participant/message cols lag."""
    try:
        return serialize_room(
            room,
            db,
            with_participants=with_participants,
            with_messages=with_messages,
            message_limit=message_limit,
        )
    except Exception as e:
        if not _is_schema_error(e):
            # Non-schema bugs: retry without related rows, then minimal
            log.warning("room_out failed room=%s: %s", getattr(room, "id", None), e)
        else:
            log.warning(
                "room_out schema lag room=%s: %s",
                getattr(room, "id", None),
                e,
            )
        _safe_rollback(db)
        try:
            return serialize_room(
                room,
                db,
                with_participants=False,
                with_messages=False,
            )
        except Exception as e2:
            log.warning("room_out bare fallback room=%s: %s", getattr(room, "id", None), e2)
            _safe_rollback(db)
            return _minimal_room_out(room)


def _rooms_out_list_safe(
    db: Session,
    rows: list,
    *,
    with_participants: bool = True,
    with_messages: bool = False,
) -> list[dict]:
    try:
        return rooms_out_list(
            db,
            rows,
            with_participants=with_participants,
            with_messages=with_messages,
        )
    except Exception as e:
        log.warning("rooms_out_list failed (schema?): %s", e)
        _safe_rollback(db)
        out: list[dict] = []
        for r in rows:
            try:
                out.append(
                    serialize_room(
                        r, db, with_participants=False, with_messages=False,
                    )
                )
            except Exception:
                out.append(_minimal_room_out(r))
        return out


# ── Access helpers ───────────────────────────────────────────────────────

def _get_room(db: Session, room_id: int, user: models.User) -> models.MeetingRoom:
    try:
        room = db.get(models.MeetingRoom, room_id)
    except Exception as e:
        if _is_schema_error(e):
            log.error("get meeting schema error id=%s: %s", room_id, e)
            _safe_rollback(db)
            raise HTTPException(
                503,
                "Meeting storage is not fully migrated (missing columns). Retry shortly.",
            ) from e
        raise
    if not room or room.user_id != user.id:
        raise HTTPException(404, "Meeting not found")
    return room


def _add_system_message(
    db: Session,
    room_id: int,
    content: str,
    *,
    msg_type: str = "system",
    meta: dict | None = None,
) -> models.MeetingMessage | None:
    """Best-effort system message — missing message columns must not abort create."""
    try:
        kwargs: dict = {
            "room_id": room_id,
            "sender_kind": "system",
            "content": (content or "").strip(),
        }
        if _col_ok(db, "meeting_messages", "msg_type"):
            kwargs["msg_type"] = msg_type if msg_type in MSG_TYPES else "system"
        if _col_ok(db, "meeting_messages", "meta_json"):
            kwargs["meta_json"] = json.dumps(meta or {})
        m = models.MeetingMessage(**kwargs)
        db.add(m)
        return m
    except Exception as e:
        log.warning("system message skipped room=%s: %s", room_id, e)
        return None


def _room_kwargs_for_create(
    db: Session,
    *,
    user_id: int,
    title: str,
    purpose: str,
    room_type: str,
    company_id: int | None,
    project_id: int | None,
    task_id: int | None,
    chair_agent_id: int | None,
    settings: dict | None,
) -> dict:
    """Build MeetingRoom constructor kwargs, skipping columns missing from DB."""
    desired: list[tuple[str, object]] = [
        ("user_id", user_id),
        ("title", title),
        ("purpose", purpose),
        ("room_type", room_type),
        ("status", "open"),
        ("company_id", company_id),
        ("project_id", project_id),
        ("task_id", task_id),
        ("chair_agent_id", chair_agent_id),
        ("settings_json", json.dumps(settings or {})),
        ("summary_text", ""),
    ]
    out: dict = {}
    for col, val in desired:
        if not hasattr(models.MeetingRoom, col):
            continue
        if not _col_ok(db, "meeting_rooms", col):
            log.warning("skip meeting_rooms.%s (missing in DB)", col)
            continue
        out[col] = val
    # user_id is required — always include if model has it
    if "user_id" not in out and hasattr(models.MeetingRoom, "user_id"):
        out["user_id"] = user_id
    if "title" not in out and hasattr(models.MeetingRoom, "title"):
        out["title"] = title
    return out


def _add_participant_row(db: Session, **fields) -> models.MeetingParticipant | None:
    """Insert a participant row using only columns present in the live DB."""
    try:
        clean: dict = {}
        for k, v in fields.items():
            if not hasattr(models.MeetingParticipant, k):
                continue
            if not _col_ok(db, "meeting_participants", k):
                continue
            clean[k] = v
        if "room_id" not in clean:
            return None
        p = models.MeetingParticipant(**clean)
        db.add(p)
        return p
    except Exception as e:
        log.warning("participant insert skipped: %s fields=%s", e, fields)
        return None


def _validate_participant(
    db: Session,
    user: models.User,
    data: ParticipantIn | dict,
) -> dict:
    if isinstance(data, dict):
        kind = (data.get("kind") or "agent").strip().lower()
        role = (data.get("role") or "member").strip().lower()
        user_id = data.get("user_id")
        agent_id = data.get("agent_id")
        human_id = data.get("human_id")
    else:
        kind = (data.kind or "agent").strip().lower()
        role = (data.role or "member").strip().lower()
        user_id = data.user_id
        agent_id = data.agent_id
        human_id = data.human_id

    if kind not in PARTICIPANT_KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(PARTICIPANT_KINDS)}")
    if role not in PARTICIPANT_ROLES:
        raise HTTPException(400, f"role must be one of {sorted(PARTICIPANT_ROLES)}")

    if kind == "agent":
        if not agent_id:
            raise HTTPException(400, "agent_id required for kind=agent")
        a = db.get(models.Agent, int(agent_id))
        if not a or a.user_id != user.id:
            raise HTTPException(404, "Agent not found")
        return {
            "kind": "agent",
            "role": role,
            "agent_id": a.id,
            "user_id": None,
            "human_id": None,
        }

    if kind == "human":
        if not human_id:
            raise HTTPException(400, "human_id required for kind=human")
        h = db.get(models.Human, int(human_id))
        if not h or h.owner_user_id != user.id:
            raise HTTPException(404, "Human not found")
        return {
            "kind": "human",
            "role": role,
            "human_id": h.id,
            "user_id": None,
            "agent_id": None,
        }

    # kind == user
    uid = int(user_id) if user_id else user.id
    if uid != user.id:
        # Only the workspace owner may join as "user" for now
        raise HTTPException(403, "Only the workspace owner can join as user")
    return {
        "kind": "user",
        "role": role,
        "user_id": uid,
        "agent_id": None,
        "human_id": None,
    }


def _participant_exists(db: Session, room_id: int, fields: dict) -> models.MeetingParticipant | None:
    q = db.query(models.MeetingParticipant).filter_by(room_id=room_id, kind=fields["kind"])
    if fields["kind"] == "agent":
        q = q.filter_by(agent_id=fields["agent_id"])
    elif fields["kind"] == "human":
        q = q.filter_by(human_id=fields["human_id"])
    else:
        q = q.filter_by(user_id=fields["user_id"])
    return q.first()


def _transcript(db: Session, room: models.MeetingRoom, limit: int = 80) -> str:
    msgs = (
        db.query(models.MeetingMessage)
        .filter_by(room_id=room.id)
        .order_by(models.MeetingMessage.id.desc())
        .limit(limit)
        .all()
    )
    msgs = list(reversed(msgs))
    lines = []
    for m in msgs:
        label = m.sender_kind or "unknown"
        if m.sender_kind == "agent" and m.sender_agent_id:
            a = db.get(models.Agent, m.sender_agent_id)
            label = a.name if a else f"agent:{m.sender_agent_id}"
        elif m.sender_kind == "human" and m.sender_human_id:
            h = db.get(models.Human, m.sender_human_id)
            label = h.name if h else f"human:{m.sender_human_id}"
        elif m.sender_kind == "user" and m.sender_user_id:
            u = db.get(models.User, m.sender_user_id)
            label = (u.name or u.email) if u else f"user:{m.sender_user_id}"
        elif m.sender_kind == "system":
            label = "system"
        lines.append(f"[{m.msg_type or 'chat'}] {label}: {m.content or ''}")
    return "\n".join(lines)


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("")
@router.get("/")
def list_meetings(
    status: str | None = Query(None),
    room_type: str | None = Query(None),
    project_id: int | None = Query(None),
    task_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """List meetings. Filters that target missing columns are skipped (not 500)."""
    try:
        q = db.query(models.MeetingRoom).filter_by(user_id=user.id)
        if status and _col_ok(db, "meeting_rooms", "status"):
            q = q.filter(models.MeetingRoom.status == status)
        if room_type and _col_ok(db, "meeting_rooms", "room_type"):
            q = q.filter(models.MeetingRoom.room_type == room_type)
        if project_id is not None and _col_ok(db, "meeting_rooms", "project_id"):
            q = q.filter(models.MeetingRoom.project_id == project_id)
        if task_id is not None and _col_ok(db, "meeting_rooms", "task_id"):
            q = q.filter(models.MeetingRoom.task_id == task_id)
        rows = q.order_by(models.MeetingRoom.id.desc()).limit(limit).all()
    except Exception as e:
        if not _is_schema_error(e):
            raise
        log.warning("list_meetings query schema lag: %s", e)
        _safe_rollback(db)
        # Bare fallback: user_id only (no optional filters)
        try:
            rows = (
                db.query(models.MeetingRoom)
                .filter_by(user_id=user.id)
                .order_by(models.MeetingRoom.id.desc())
                .limit(limit)
                .all()
            )
        except Exception as e2:
            log.error("list_meetings unusable schema: %s", e2)
            _safe_rollback(db)
            return {
                "meetings": [],
                "count": 0,
                "warning": "schema_incomplete",
            }

    meetings = _rooms_out_list_safe(
        db, rows, with_participants=True, with_messages=False,
    )
    return {
        "meetings": meetings,
        "count": len(meetings),
    }


@router.post("")
@router.post("/")
async def create_meeting(
    data: MeetingCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Create a meeting room.

    Works with no / null / empty ``participants`` — only the owner is auto-joined
    when the participants table is available. Optional link fields that are
    missing from the live DB are skipped rather than failing the insert.
    """
    title = (data.title or "Meeting").strip() or "Meeting"
    room_type = (data.room_type or "brainstorm").strip().lower()
    if room_type not in ROOM_TYPES:
        raise HTTPException(400, f"room_type must be one of {sorted(ROOM_TYPES)}")

    company_id = data.company_id
    project_id = data.project_id
    task_id = data.task_id
    chair_agent_id = data.chair_agent_id

    if company_id is not None:
        co = require_owned(
            db, models.Company, company_id, user,
            user_field='owner_user_id', not_found="Company not found",
        )
    if project_id is not None:
        pr = require_owned(
            db, models.Project, project_id, user,
            user_field='owner_user_id', not_found="Project not found",
        )
    if task_id is not None:
        t = require_owned(
            db, models.Task, task_id, user,
            user_field='user_id', not_found="Task not found",
        )
    if chair_agent_id is not None:
        a = require_owned(
            db, models.Agent, chair_agent_id, user,
            user_field='user_id', not_found="Chair agent not found",
        )
    # Drop optional FKs whose columns are missing in the live schema
    if company_id is not None and not _col_ok(db, "meeting_rooms", "company_id"):
        company_id = None
    if project_id is not None and not _col_ok(db, "meeting_rooms", "project_id"):
        project_id = None
    if task_id is not None and not _col_ok(db, "meeting_rooms", "task_id"):
        task_id = None
    if chair_agent_id is not None and not _col_ok(db, "meeting_rooms", "chair_agent_id"):
        chair_agent_id = None

    room_kwargs = _room_kwargs_for_create(
        db,
        user_id=user.id,
        title=title,
        purpose=(data.purpose or "").strip(),
        room_type=room_type,
        company_id=company_id,
        project_id=project_id,
        task_id=task_id,
        chair_agent_id=chair_agent_id,
        settings=data.settings,
    )
    try:
        room = models.MeetingRoom(**room_kwargs)
        db.add(room)
        db.flush()
    except Exception as e:
        if _is_schema_error(e):
            log.error("create meeting schema error: %s kwargs=%s", e, list(room_kwargs))
            _safe_rollback(db)
            # Invalidate column cache and retry with minimal core fields only
            _DB_COLS_CACHE.pop("meeting_rooms", None)
            minimal = {
                k: v
                for k, v in {
                    "user_id": user.id,
                    "title": title,
                    "purpose": (data.purpose or "").strip(),
                    "room_type": room_type,
                    "status": "open",
                }.items()
                if hasattr(models.MeetingRoom, k) and _col_ok(db, "meeting_rooms", k)
            }
            if "user_id" not in minimal:
                minimal["user_id"] = user.id
            try:
                room = models.MeetingRoom(**minimal)
                db.add(room)
                db.flush()
            except Exception as e2:
                _safe_rollback(db)
                raise HTTPException(
                    503,
                    f"Cannot create meeting (schema incomplete): {e2}",
                ) from e2
        else:
            _safe_rollback(db)
            raise

    # Participants are optional — create succeeds even when none are provided
    # and even when the participants table/columns are lagging.
    try:
        _add_participant_row(
            db,
            room_id=room.id,
            kind="user",
            user_id=user.id,
            role="chair" if not chair_agent_id else "member",
        )
        if chair_agent_id:
            _add_participant_row(
                db,
                room_id=room.id,
                kind="agent",
                agent_id=chair_agent_id,
                role="chair",
            )

        for raw in data.participants or []:
            if not isinstance(raw, dict):
                continue
            try:
                fields = _validate_participant(db, user, raw)
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(400, f"Invalid participant: {e}") from e
            try:
                if _participant_exists(db, room.id, fields):
                    continue
            except Exception as e:
                log.warning("participant exists check skipped: %s", e)
            # Don't double-add owner/chair agent
            if fields["kind"] == "user" and fields.get("user_id") == user.id:
                continue
            if fields["kind"] == "agent" and fields.get("agent_id") == chair_agent_id:
                continue
            _add_participant_row(db, room_id=room.id, **fields)
    except HTTPException:
        raise
    except Exception as e:
        # Participants are non-fatal for create
        log.warning("participant bootstrap skipped room=%s: %s", room.id, e)

    purpose_val = getattr(room, "purpose", None) or (data.purpose or "").strip()
    purpose_bit = f" Purpose: {purpose_val}" if purpose_val else ""
    _add_system_message(
        db,
        room.id,
        f'Meeting "{title}" opened ({room_type}).{purpose_bit}'.strip(),
        msg_type="system",
        meta={"event": "created"},
    )
    try:
        db.commit()
    except Exception as e:
        if _is_schema_error(e):
            log.error("create meeting commit schema error: %s", e)
            _safe_rollback(db)
            raise HTTPException(
                503,
                f"Cannot create meeting (schema incomplete): {e}",
            ) from e
        raise
    try:
        db.refresh(room)
    except Exception:
        pass

    try:
        await emit_ops(
            user.id,
            kind="system",
            status="info",
            title=f"Meeting opened: {title}",
            detail=getattr(room, "purpose", None) or room_type,
            task_id=getattr(room, "task_id", None),
            db=db,
            payload={"meeting_id": room.id},
        )
    except Exception as e:
        log.warning("emit_ops after create skipped: %s", e)

    return _room_out(room, db, with_participants=True, with_messages=True)


@router.get("/{room_id}")
def get_meeting(
    room_id: int,
    include_messages: bool = Query(True),
    message_limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    room = _get_room(db, room_id, user)
    return _room_out(
        room,
        db,
        with_participants=True,
        with_messages=include_messages,
        message_limit=message_limit,
    )


@router.patch("/{room_id}")
def update_meeting(
    room_id: int,
    data: MeetingUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    room = _get_room(db, room_id, user)
    if data.title is not None:
        room.title = (data.title or "").strip() or room.title
    if data.purpose is not None:
        room.purpose = (data.purpose or "").strip()
    if data.room_type is not None:
        rt = data.room_type.strip().lower()
        if rt not in ROOM_TYPES:
            raise HTTPException(400, f"room_type must be one of {sorted(ROOM_TYPES)}")
        room.room_type = rt
    if data.status is not None:
        st = data.status.strip().lower()
        if st not in ROOM_STATUSES:
            raise HTTPException(400, f"status must be one of {sorted(ROOM_STATUSES)}")
        room.status = st
        if st == "closed" and not room.closed_at:
            room.closed_at = datetime.utcnow()
        if st != "closed":
            room.closed_at = None
    if data.company_id is not None:
        if data.company_id:
            co = require_owned(
                db, models.Company, data.company_id, user,
                user_field='owner_user_id', not_found="Company not found",
            )
        room.company_id = data.company_id
    if data.project_id is not None:
        if data.project_id:
            pr = require_owned(
                db, models.Project, data.project_id, user,
                user_field='owner_user_id', not_found="Project not found",
            )
        room.project_id = data.project_id
    if data.task_id is not None:
        if data.task_id:
            t = require_owned(
                db, models.Task, data.task_id, user,
                user_field='user_id', not_found="Task not found",
            )
        room.task_id = data.task_id
    if data.chair_agent_id is not None:
        if data.chair_agent_id:
            a = require_owned(
                db, models.Agent, data.chair_agent_id, user,
                user_field='user_id', not_found="Chair agent not found",
            )
        room.chair_agent_id = data.chair_agent_id
    if data.settings is not None:
        room.settings_json = json.dumps(data.settings)
    if data.summary_text is not None:
        room.summary_text = data.summary_text or ""
    db.commit()
    db.refresh(room)
    return _room_out(room, db, with_participants=True, with_messages=False)


class InviteAgentsIn(BaseModel):
    """Bulk invite agents into a room (UI + skills)."""
    agent_ids: list[int] = Field(default_factory=list)
    role: str = "member"


@router.post("/{room_id}/participants")
def add_participant(
    room_id: int,
    data: ParticipantIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    room = _get_room(db, room_id, user)
    if (room.status or "").lower() == "closed":
        raise HTTPException(400, "Meeting is closed")
    fields = _validate_participant(db, user, data)
    try:
        existing = _participant_exists(db, room.id, fields)
    except Exception:
        existing = None
    if existing:
        return _participant_out(existing, db)

    # Prefer resilient insert (skips missing columns / lagging Neon schema)
    p = _add_participant_row(db, room_id=room.id, **fields)
    if p is None:
        try:
            p = models.MeetingParticipant(room_id=room.id, **fields)
            db.add(p)
            db.flush()
        except Exception as e:
            _safe_rollback(db)
            raise HTTPException(
                503,
                f"Could not add participant (DB schema): {e}",
            ) from e

    name_hint = ""
    if fields["kind"] == "agent":
        a = db.get(models.Agent, fields["agent_id"])
        name_hint = a.name if a else f"agent:{fields['agent_id']}"
        # Keep chair_agent_id in sync when inviting as chair
        if fields.get("role") == "chair" and hasattr(room, "chair_agent_id"):
            try:
                room.chair_agent_id = fields["agent_id"]
            except Exception:
                pass
    elif fields["kind"] == "human":
        h = db.get(models.Human, fields["human_id"])
        name_hint = h.name if h else f"human:{fields['human_id']}"
    else:
        name_hint = "user"
    _add_system_message(
        db,
        room.id,
        f"{name_hint} joined the meeting as {fields['role']}.",
        meta={"event": "participant_joined", **{k: v for k, v in fields.items() if v is not None}},
    )
    if (room.status or "").lower() == "open":
        room.status = "active"
    try:
        db.commit()
        if p is not None:
            db.refresh(p)
    except Exception as e:
        _safe_rollback(db)
        raise HTTPException(500, f"Failed to save participant: {e}") from e
    if p is None:
        # Last resort: re-query after commit
        p = _participant_exists(db, room.id, fields)
    if p is None:
        raise HTTPException(500, "Participant saved but could not be reloaded")
    return _participant_out(p, db)


@router.post("/{room_id}/participants/invite")
def invite_agents(
    room_id: int,
    data: InviteAgentsIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Invite one or many agents in a single call (primary UI path)."""
    room = _get_room(db, room_id, user)
    if (room.status or "").lower() == "closed":
        raise HTTPException(400, "Meeting is closed")
    role = (data.role or "member").strip().lower()
    if role not in PARTICIPANT_ROLES:
        role = "member"
    ids: list[int] = []
    for raw in data.agent_ids or []:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    # de-dupe preserve order
    seen: set[int] = set()
    ordered: list[int] = []
    for aid in ids:
        if aid in seen:
            continue
        seen.add(aid)
        ordered.append(aid)
    if not ordered:
        raise HTTPException(400, "agent_ids required")

    added = []
    already = []
    failed = []
    for aid in ordered:
        try:
            fields = _validate_participant(
                db, user, {"kind": "agent", "agent_id": aid, "role": role},
            )
            existing = _participant_exists(db, room.id, fields)
            if existing:
                already.append(_participant_out(existing, db))
                continue
            p = _add_participant_row(db, room_id=room.id, **fields)
            if p is None:
                p = models.MeetingParticipant(room_id=room.id, **fields)
                db.add(p)
                db.flush()
            a = db.get(models.Agent, aid)
            name = a.name if a else f"agent:{aid}"
            _add_system_message(
                db,
                room.id,
                f"{name} joined the meeting as {role}.",
                meta={"event": "participant_joined", "kind": "agent", "agent_id": aid, "role": role},
            )
            added.append({"agent_id": aid, "name": name, "role": role, "id": getattr(p, "id", None)})
        except HTTPException as he:
            failed.append({"agent_id": aid, "error": he.detail})
        except Exception as e:
            failed.append({"agent_id": aid, "error": str(e)[:200]})

    if (room.status or "").lower() == "open" and added:
        room.status = "active"
    try:
        db.commit()
    except Exception as e:
        _safe_rollback(db)
        raise HTTPException(500, f"Failed to invite agents: {e}") from e

    # Return full participant list so UI can refresh in one shot
    room = _get_room(db, room_id, user)
    out = _room_out(room, db, with_participants=True, with_messages=False)
    return {
        "ok": True,
        "added": added,
        "already": already,
        "failed": failed,
        "added_count": len(added),
        "participants": out.get("participants") or [],
        "meeting": out,
    }


@router.delete("/{room_id}/participants/{participant_id}")
def remove_participant(
    room_id: int,
    participant_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    room = _get_room(db, room_id, user)
    p = db.get(models.MeetingParticipant, participant_id)
    if not p or p.room_id != room.id:
        raise HTTPException(404, "Participant not found")
    info = _participant_out(p, db)
    db.delete(p)
    _add_system_message(
        db,
        room.id,
        f"{info.get('name') or p.kind} left the meeting.",
        meta={"event": "participant_left", "participant_id": participant_id},
    )
    db.commit()
    return {"ok": True, "removed_id": participant_id}


@router.get("/{room_id}/messages")
def list_messages(
    room_id: int,
    limit: int = Query(100, ge=1, le=500),
    after_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    room = _get_room(db, room_id, user)
    q = db.query(models.MeetingMessage).filter_by(room_id=room.id)
    if after_id is not None:
        q = q.filter(models.MeetingMessage.id > after_id)
        rows = q.order_by(models.MeetingMessage.id.asc()).limit(limit).all()
    else:
        rows = (
            q.order_by(models.MeetingMessage.id.desc())
            .limit(limit)
            .all()
        )
        rows = list(reversed(rows))
    return {
        "room_id": room.id,
        "messages": [_message_out(m, db) for m in rows],
        "count": len(rows),
    }


@router.post("/{room_id}/messages")
async def post_message(
    room_id: int,
    data: MessageIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    room = _get_room(db, room_id, user)
    if room.status == "closed":
        raise HTTPException(400, "Meeting is closed")
    content = (data.content or "").strip()
    if not content:
        raise HTTPException(400, "content required")

    msg_type = (data.msg_type or "chat").strip().lower()
    if msg_type not in MSG_TYPES:
        raise HTTPException(400, f"msg_type must be one of {sorted(MSG_TYPES)}")

    sender_kind = (data.sender_kind or "user").strip().lower()
    if sender_kind not in SENDER_KINDS:
        raise HTTPException(400, f"sender_kind must be one of {sorted(SENDER_KINDS)}")

    sender_user_id = None
    sender_agent_id = None
    sender_human_id = None

    if sender_kind == "user":
        sender_user_id = user.id
    elif sender_kind == "agent":
        if not data.sender_agent_id:
            raise HTTPException(400, "sender_agent_id required for sender_kind=agent")
        a = require_owned(
            db, models.Agent, data.sender_agent_id, user,
            user_field='user_id', not_found="Agent not found",
        )
        sender_agent_id = a.id
        # Ensure agent is a participant
        if not _participant_exists(db, room.id, {
            "kind": "agent", "agent_id": a.id, "user_id": None, "human_id": None,
        }):
            db.add(models.MeetingParticipant(
                room_id=room.id, kind="agent", agent_id=a.id, role="member",
            ))
    elif sender_kind == "human":
        if not data.sender_human_id:
            raise HTTPException(400, "sender_human_id required for sender_kind=human")
        h = require_owned(
            db, models.Human, data.sender_human_id, user,
            user_field='owner_user_id', not_found="Human not found",
        )
        sender_human_id = h.id
        if not _participant_exists(db, room.id, {
            "kind": "human", "human_id": h.id, "user_id": None, "agent_id": None,
        }):
            db.add(models.MeetingParticipant(
                room_id=room.id, kind="human", human_id=h.id, role="member",
            ))
    else:
        # system — allowed but rare from client
        pass

    if room.status == "open":
        room.status = "active"

    m = models.MeetingMessage(
        room_id=room.id,
        sender_kind=sender_kind,
        sender_user_id=sender_user_id,
        sender_agent_id=sender_agent_id,
        sender_human_id=sender_human_id,
        content=content,
        msg_type=msg_type,
        meta_json=json.dumps(data.meta or {}),
    )
    db.add(m)
    db.commit()
    db.refresh(m)

    await emit_ops(
        user.id,
        kind="action",
        status="info",
        title=f"Meeting message: {room.title}",
        detail=content[:200],
        agent_id=sender_agent_id,
        human_id=sender_human_id,
        task_id=room.task_id,
        db=db,
        payload={"meeting_id": room.id, "message_id": m.id},
    )
    return _message_out(m, db)


@router.post("/{room_id}/round")
async def run_round(
    room_id: int,
    data: RoundIn | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Run one multi-agent discussion round (optionally repeated ``max_turns`` times).
    Calls ``meeting_runner.run_meeting_round(db, room_id, user_id)``.
    """
    room = _get_room(db, room_id, user)
    if (room.status or "").lower() == "closed":
        raise HTTPException(400, "Meeting is closed")
    body = data or RoundIn()

    # Optional kickoff prompt as a user message before agents speak
    prompt = (body.prompt or "").strip()
    if prompt:
        db.add(models.MeetingMessage(
            room_id=room.id,
            sender_kind="user",
            sender_user_id=user.id,
            content=prompt,
            msg_type="chat",
            meta_json=json.dumps({"event": "round_prompt"}),
            created_at=datetime.utcnow(),
        ))
        db.commit()

    ensure_credits(db, user.id)

    try:
        max_turns = max(1, min(int(body.max_turns or 1), 5))
    except (TypeError, ValueError):
        max_turns = 1

    # Router style: run_meeting_round(db, room_id, user_id, prompt=…)
    # → list[MeetingMessage] (skill style with User returns a dict)
    new_msgs: list = []
    try:
        for turn_i in range(max_turns):
            # Focus prompt only on the first turn (already posted as chat above)
            batch = await run_meeting_round(
                db,
                room.id,
                user.id,
                prompt=prompt if turn_i == 0 else "",
            )
            if isinstance(batch, dict):
                # Defensive: skill-style dict payload
                if not batch.get("ok") and batch.get("error"):
                    raise HTTPException(500, f"Meeting round failed: {batch.get('error')}")
                raw_list = batch.get("messages") or []
                # messages may already be dicts
                if not raw_list:
                    break
                new_msgs.extend(raw_list)
            elif not batch:
                break
            else:
                new_msgs.extend(batch)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Meeting round failed room=%s", room_id)
        raise HTTPException(500, f"Meeting round failed: {e}") from e

    try:
        db.refresh(room)
    except Exception:
        room = db.get(models.MeetingRoom, room_id) or room

    if (room.status or "").lower() == "open":
        room.status = "active"
        db.commit()
        try:
            db.refresh(room)
        except Exception:
            pass

    serialized = []
    for m in new_msgs:
        try:
            serialized.append(_message_out(m, db))
        except Exception as e:
            log.warning("serialize round message failed: %s", e)
            if isinstance(m, models.MeetingMessage):
                serialized.append({
                    "id": m.id,
                    "room_id": m.room_id,
                    "sender_kind": m.sender_kind,
                    "sender_agent_id": m.sender_agent_id,
                    "content": m.content or "",
                    "msg_type": m.msg_type or "chat",
                    "meta": {},
                    "created_at": None,
                })

    return {
        "ok": True,
        "room_id": room.id,
        "messages": serialized,
        "count": len(serialized),
        "turns": max_turns,
        "meeting": _room_out(
            room, db, with_participants=True, with_messages=True, message_limit=30,
        ),
    }


@router.post("/{room_id}/summarize")
async def summarize_meeting(
    room_id: int,
    data: SummarizeIn | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    room = _get_room(db, room_id, user)
    body = data or SummarizeIn()
    transcript = _transcript(db, room, limit=100)
    if not transcript.strip():
        raise HTTPException(400, "No messages to summarize")

    ensure_credits(db, user.id)
    style = (body.style or "concise").strip().lower()
    style_hint = {
        "concise": "Write a short bullet summary (5–10 bullets).",
        "detailed": "Write a detailed structured summary with sections.",
        "decisions": "Focus on decisions made, open questions, and action items only.",
    }.get(style, "Write a short bullet summary.")

    system = (
        "You are a meeting secretary. Summarize the multi-party discussion clearly. "
        "Use the participants' names. Do not invent facts not present in the transcript."
    )
    user_prompt = (
        f"Meeting title: {room.title}\n"
        f"Purpose: {room.purpose or '(none)'}\n"
        f"Type: {room.room_type}\n\n"
        f"Style: {style_hint}\n\n"
        f"Transcript:\n{transcript}\n\n"
        "Produce the summary now."
    )

    creds = credentials_for_user(db, user.id)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]
    model = body.model or "fast"
    try:
        summary = await complete(messages, model, mode="general", credentials=creds, max_tokens=1500)
    except Exception as e:
        raise HTTPException(502, f"Summarization LLM failed: {e}") from e

    summary = (summary or "").strip()
    if not summary:
        raise HTTPException(502, "Empty summary from model")

    room.summary_text = summary
    _add_system_message(
        db,
        room.id,
        f"Summary updated:\n{summary[:1500]}",
        msg_type="system",
        meta={"event": "summarized", "style": style},
    )
    db.commit()
    try:
        bill_llm_turn(db, user, model, messages, summary)
    except Exception:
        pass

    await emit_ops(
        user.id,
        kind="action",
        status="done",
        title=f"Meeting summarized: {room.title}",
        detail=summary[:200],
        task_id=room.task_id,
        db=db,
        payload={"meeting_id": room.id},
    )
    return {
        "ok": True,
        "room_id": room.id,
        "summary": summary,
        "meeting": _room_out(room, db, with_participants=False, with_messages=False),
    }


def _parse_tasks_json(text: str) -> list[dict]:
    """Extract a JSON array of tasks from model output."""
    raw = (text or "").strip()
    if not raw:
        return []
    # Prefer fenced json
    m = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", raw, re.I)
    if m:
        raw = m.group(1)
    else:
        start = raw.find("[")
        end = raw.rfind("]")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if isinstance(data, dict) and isinstance(data.get("tasks"), list):
        data = data["tasks"]
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, str):
            title = item.strip()
            if title:
                out.append({"title": title, "description": "", "priority": "medium"})
            continue
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or item.get("task") or item.get("name") or "").strip()
        if not title:
            continue
        out.append({
            "title": title[:200],
            "description": (item.get("description") or item.get("detail") or "").strip()[:4000],
            "priority": (item.get("priority") or "medium").strip().lower()[:20] or "medium",
            "assignee_type": (item.get("assignee_type") or "").strip().lower() or None,
            "agent_id": item.get("agent_id"),
            "human_id": item.get("human_id"),
        })
    return out[:30]


def _safe_int(val) -> int | None:
    if val is None or val is False or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _task_row_out(t: models.Task) -> dict:
    return {
        "id": t.id,
        "title": t.title or (t.description or "")[:60],
        "description": t.description or "",
        "priority": t.priority or "medium",
        "status": t.status,
        "agent_id": t.agent_id,
        "human_id": t.human_id,
        "assignee_type": t.assignee_type or "unassigned",
        "meeting_id": t.meeting_id,
        "parent_task_id": t.parent_task_id,
        "project_id": t.project_id,
        "company_id": t.company_id,
        "labels": t.labels or "",
        "created_at": t.created_at.isoformat() + "Z" if t.created_at else None,
    }


@router.post("/{room_id}/extract-tasks")
async def extract_tasks(
    room_id: int,
    data: ExtractTasksIn | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Create Tasks from recent messages (action lines) or room summary.

    Prefers LLM JSON extraction; falls back to heuristic
    ``meeting_extract.extract_tasks_from_room`` when LLM is unavailable or
    returns unparseable output.

    - status via ``initial_task_status`` (queued when active agent assigned)
    - each Task gets ``meeting_id``
    - posts system MeetingMessage with ``msg_type=task_created``
    """
    room = _get_room(db, room_id, user)
    body = data or ExtractTasksIn()
    transcript = _transcript(db, room, limit=100)
    has_source = bool(
        transcript.strip()
        or (room.summary_text or "").strip()
        or (room.purpose or "").strip()
        or (room.title or "").strip()
    )
    if not has_source:
        raise HTTPException(400, "No messages or summary to extract tasks from")

    participants = (
        db.query(models.MeetingParticipant)
        .filter_by(room_id=room.id)
        .all()
    )
    agent_ids = [p.agent_id for p in participants if p.kind == "agent" and p.agent_id]
    human_ids = [p.human_id for p in participants if p.kind == "human" and p.human_id]
    agent_names: list[str] = []
    for aid in agent_ids:
        a = db.get(models.Agent, aid)
        if a:
            agent_names.append(f"id={a.id} name={a.name}")

    default_agent_id: int | None = None
    if body.assign_to_chair and room.chair_agent_id:
        default_agent_id = room.chair_agent_id
    if default_agent_id is None and agent_ids:
        default_agent_id = agent_ids[0]
    if default_agent_id is not None:
        da = db.get(models.Agent, default_agent_id)
        if not da or da.user_id != user.id:
            default_agent_id = agent_ids[0] if agent_ids else None

    extracted: list[dict] = []
    source = "llm"
    llm_error = None

    # Try LLM when there is transcript/summary; heuristic fallback always works.
    if transcript.strip() or (room.summary_text or "").strip():
        try:
            ensure_credits(db, user.id)
            system = (
                "You extract actionable tasks from a meeting transcript. "
                "Respond with ONLY a JSON array of objects: "
                '[{"title":"...","description":"...","priority":"low|medium|high|urgent"}]. '
                "No prose outside the JSON."
            )
            source_text = transcript
            if room.summary_text:
                source_text = (
                    f"Existing summary:\n{room.summary_text}\n\nTranscript:\n{transcript}"
                )
            user_prompt = (
                f"Meeting: {room.title}\nPurpose: {room.purpose or '(none)'}\n"
                f"Available agents: {', '.join(agent_names) or 'none'}\n\n"
                f"{source_text}\n\n"
                "Extract concrete follow-up tasks (max 15)."
            )

            creds = credentials_for_user(db, user.id)
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ]
            model = body.model or "fast"
            reply = await complete(
                messages, model, mode="general", credentials=creds, max_tokens=1500
            )
            try:
                bill_llm_turn(db, user, model, messages, reply or "")
            except Exception:
                pass
            extracted = _parse_tasks_json(reply or "")
            if not extracted:
                llm_error = "parse_failed"
        except HTTPException as he:
            # Credits / plan gates — fall back to heuristic instead of failing hard
            llm_error = f"http_{getattr(he, 'status_code', 402)}"
            extracted = []
        except Exception as e:
            log.warning("extract-tasks LLM failed room=%s: %s", room_id, e)
            llm_error = str(e)[:300]
            extracted = []
    else:
        llm_error = "no_transcript_for_llm"

    # Heuristic fallback: action lines / summary / purpose
    if not extracted:
        source = "heuristic"
        if body.create:
            result = extract_tasks_from_room(
                db,
                room,
                user,
                agent_id=default_agent_id,
                commit=True,
            )
            if not result.get("ok"):
                raise HTTPException(400, result.get("error") or "Extract failed")
            created = result.get("tasks") or []
            await emit_ops(
                user.id,
                kind="action",
                status="done",
                title=f"Extracted {len(created)} tasks from meeting",
                detail=room.title or "",
                task_id=room.task_id,
                db=db,
                payload={
                    "meeting_id": room.id,
                    "task_ids": [
                        c.get("id") for c in created
                        if isinstance(c, dict) and c.get("id")
                    ],
                    "source": source,
                    "llm_error": llm_error,
                },
            )
            return {
                "ok": True,
                "room_id": room.id,
                "created": True,
                "tasks": created,
                "count": len(created),
                "source": result.get("source") or source,
                "llm_error": llm_error,
            }

        # Dry-run: heuristic titles without persisting
        from ..meeting_extract import (
            _collect_candidate_titles,
            _load_messages,
            _split_summary_into_tasks,
        )

        msgs = _load_messages(db, room.id, limit=80)
        titles, heur_src = _collect_candidate_titles(msgs, room.summary_text or "")
        if not titles:
            titles = _split_summary_into_tasks(
                room.summary_text or room.purpose or room.title or "Follow up on meeting"
            )
        dry = [{"title": t, "description": "", "priority": "medium"} for t in titles]
        return {
            "ok": True,
            "room_id": room.id,
            "created": False,
            "tasks": dry,
            "count": len(dry),
            "source": f"heuristic:{heur_src}",
            "llm_error": llm_error,
        }

    created: list[dict] = []
    if body.create:
        now = datetime.utcnow()
        for item in extracted:
            agent_id = _safe_int(item.get("agent_id"))
            if agent_id is None:
                agent_id = default_agent_id
            if (
                agent_id is not None
                and agent_id not in agent_ids
                and agent_id != room.chair_agent_id
            ):
                a = db.get(models.Agent, agent_id)
                if not a or a.user_id != user.id:
                    agent_id = default_agent_id

            human_id = _safe_int(item.get("human_id"))
            if human_id is not None and human_id not in human_ids:
                h = db.get(models.Human, human_id)
                if not h or h.owner_user_id != user.id:
                    human_id = None

            assignee_type = (item.get("assignee_type") or "").strip().lower() or None
            if not assignee_type:
                if human_id:
                    assignee_type = "human"
                elif agent_id:
                    assignee_type = "agent"
                else:
                    assignee_type = "unassigned"

            pri = (item.get("priority") or "medium").strip().lower()
            if pri not in ("low", "medium", "high", "urgent"):
                pri = "medium"

            resolved_agent_id = agent_id if assignee_type != "human" else None
            agent_row = (
                db.get(models.Agent, resolved_agent_id) if resolved_agent_id else None
            )
            status = initial_task_status(
                agent=agent_row,
                human_id=human_id if assignee_type == "human" else None,
                assignee_type=assignee_type,
                run_now=True,
            )
            title = (item.get("title") or "Meeting task").strip()[:200] or "Meeting task"

            t = models.Task(
                user_id=user.id,
                project_id=room.project_id,
                company_id=room.company_id,
                agent_id=resolved_agent_id,
                human_id=human_id if assignee_type == "human" else None,
                assignee_type=assignee_type,
                parent_task_id=room.task_id,
                meeting_id=room.id,
                title=title,
                description=(
                    item.get("description") or f"From meeting: {room.title}"
                ).strip()[:8000],
                status=status,
                priority=pri,
                labels="meeting,extracted",
                created_at=now,
                updated_at=now,
            )
            db.add(t)
            db.flush()
            created.append(_task_row_out(t))
            _add_system_message(
                db,
                room.id,
                f'Task created: "{t.title}" (#{t.id}, status={t.status})',
                msg_type="task_created",
                meta={
                    "event": "task_created",
                    "task_id": t.id,
                    "status": t.status,
                    "source": source,
                },
            )
        db.commit()

        await emit_ops(
            user.id,
            kind="action",
            status="done",
            title=f"Extracted {len(created)} tasks from meeting",
            detail=room.title or "",
            task_id=room.task_id,
            db=db,
            payload={
                "meeting_id": room.id,
                "task_ids": [c["id"] for c in created],
                "source": source,
            },
        )
    else:
        created = extracted

    return {
        "ok": True,
        "room_id": room.id,
        "created": bool(body.create),
        "tasks": created,
        "count": len(created),
        "source": source,
        "llm_error": llm_error,
    }


@router.post("/{room_id}/close")
async def close_meeting(
    room_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    room = _get_room(db, room_id, user)
    if room.status == "closed":
        return {
            "ok": True,
            "already_closed": True,
            "meeting": _room_out(room, db, with_participants=True, with_messages=False),
        }
    room.status = "closed"
    room.closed_at = datetime.utcnow()
    _add_system_message(
        db,
        room.id,
        f'Meeting "{room.title}" closed.',
        meta={"event": "closed"},
    )
    db.commit()
    db.refresh(room)

    await emit_ops(
        user.id,
        kind="system",
        status="done",
        title=f"Meeting closed: {room.title}",
        detail=room.summary_text[:200] if room.summary_text else "",
        task_id=room.task_id,
        db=db,
        payload={"meeting_id": room.id},
    )
    return {
        "ok": True,
        "already_closed": False,
        "meeting": _room_out(room, db, with_participants=True, with_messages=False),
    }
