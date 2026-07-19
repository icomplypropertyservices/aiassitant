"""
Meeting room multi-agent turn runner.

Runs one discussion round: chair first, then other agent participants
(capped at MAX_AGENTS_PER_ROUND), each generating a short reply from a
compact prompt + transcript.

Public entry points
-------------------
run_meeting_round
  • Skill path:  (db, user, room_id, *, prompt=, max_agents=, chair_only=) → dict
  • Router path: (db, room_id, user_id) → list[MeetingMessage]

summarize_meeting
  • Skill path:  (db, user, room_id, *, agent=) → dict {ok, summary, …}
  • Simple path: (db, room_id, user_id) → str

_recent_transcript(db, room_id, limit=…) → str  (used by extract skills)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .agent_scaffold import map_model
from .live_ops import emit_ops
from .llm import complete
from .user_keys import credentials_for_user

log = logging.getLogger("app.meeting_runner")

MAX_AGENTS_PER_ROUND = 5
TRANSCRIPT_LIMIT = 20
REPLY_MAX_TOKENS = 600
TASK_EXCERPT_LEN = 500
CONTENT_MAX = 8000


def _user_id_of(user_or_id: models.User | int) -> int:
    if isinstance(user_or_id, int):
        return user_or_id
    return int(getattr(user_or_id, "id"))


def _is_user_obj(value: Any) -> bool:
    """True if value looks like a User ORM instance (has .id, not a bare int)."""
    return not isinstance(value, int) and hasattr(value, "id")


def _message_to_dict(msg: models.MeetingMessage) -> dict[str, Any]:
    return {
        "id": msg.id,
        "room_id": msg.room_id,
        "sender_kind": msg.sender_kind,
        "sender_user_id": msg.sender_user_id,
        "sender_agent_id": msg.sender_agent_id,
        "sender_human_id": msg.sender_human_id,
        "content": msg.content or "",
        "msg_type": msg.msg_type or "chat",
        "meta_json": msg.meta_json or "{}",
        "created_at": msg.created_at.isoformat() + "Z" if msg.created_at else None,
    }


def _task_excerpt(task: models.Task | None) -> str:
    if not task:
        return ""
    title = (task.title or "").strip()
    desc = (task.description or "").strip()
    body = f"{title}\n{desc}".strip() if title else desc
    if not body:
        return ""
    if len(body) > TASK_EXCERPT_LEN:
        return body[:TASK_EXCERPT_LEN] + "…"
    return body


def _format_transcript(
    messages: list[models.MeetingMessage],
    agent_names: dict[int, str],
) -> str:
    lines: list[str] = []
    for m in messages:
        kind = (m.sender_kind or "user").lower()
        if kind == "agent" and m.sender_agent_id:
            who = agent_names.get(m.sender_agent_id) or f"Agent#{m.sender_agent_id}"
        elif kind == "human" and m.sender_human_id:
            who = f"Human#{m.sender_human_id}"
        elif kind == "system":
            who = "System"
        else:
            who = "User"
        text = (m.content or "").strip()
        if not text:
            continue
        if len(text) > 600:
            text = text[:600] + "…"
        lines.append(f"{who}: {text}")
    return "\n".join(lines) if lines else "(no prior messages)"


def _recent_transcript(db: Session, room_id: int, limit: int = 50) -> str:
    """
    Plain-text transcript of recent meeting messages (for skills / extract).
    """
    rows = _last_messages(db, room_id, limit=limit)
    if not rows:
        return ""
    name_cache: dict[int, str] = {}
    for m in rows:
        if m.sender_kind == "agent" and m.sender_agent_id and m.sender_agent_id not in name_cache:
            ag = db.get(models.Agent, m.sender_agent_id)
            if ag:
                name_cache[ag.id] = ag.name or f"Agent#{ag.id}"
    text = _format_transcript(rows, name_cache)
    return "" if text == "(no prior messages)" else text


def _build_system_prompt(
    *,
    agent_name: str,
    purpose: str,
    room_title: str,
    room_type: str,
    task_excerpt: str,
    transcript: str,
    is_chair: bool,
    focus: str = "",
) -> str:
    role_line = (
        "You are the chair of this meeting. Facilitate briefly, then contribute."
        if is_chair
        else "You are a participant in this multi-agent meeting."
    )
    parts = [
        f"You are {agent_name}, an AI business teammate.",
        role_line,
        "Reply in 1–3 short paragraphs. Be concrete and collaborative.",
        "Do not repeat the whole transcript. Do not invent tool calls or JSON.",
        f"Meeting: {(room_title or 'Meeting').strip()}",
        f"Type: {(room_type or 'brainstorm').strip()}",
    ]
    purpose = (purpose or "").strip()
    if purpose:
        parts.append(f"Purpose: {purpose[:400]}")
    focus = (focus or "").strip()
    if focus:
        parts.append(f"Round focus: {focus[:400]}")
    if task_excerpt:
        parts.append(f"Linked task:\n{task_excerpt}")
    parts.append(f"Recent transcript:\n{transcript}")
    return "\n".join(parts)


def _load_agent_participants(
    db: Session,
    room: models.MeetingRoom,
) -> list[tuple[models.MeetingParticipant, models.Agent]]:
    """Agent participants ordered chair-first, then join order. Cap applied by caller."""
    rows = (
        db.query(models.MeetingParticipant)
        .filter(
            models.MeetingParticipant.room_id == room.id,
            models.MeetingParticipant.kind == "agent",
            models.MeetingParticipant.agent_id.isnot(None),
        )
        .order_by(models.MeetingParticipant.id.asc())
        .all()
    )
    out: list[tuple[models.MeetingParticipant, models.Agent]] = []
    seen: set[int] = set()
    for p in rows:
        aid = p.agent_id
        if not aid or aid in seen:
            continue
        agent = db.get(models.Agent, aid)
        if not agent or (agent.status or "").lower() in ("deleted", "archived"):
            continue
        seen.add(aid)
        out.append((p, agent))

    chair_id = room.chair_agent_id
    if chair_id:
        # Ensure chair is present even if not in participants table
        if chair_id not in seen:
            chair_agent = db.get(models.Agent, chair_id)
            if chair_agent and (chair_agent.status or "").lower() not in ("deleted", "archived"):
                synth = models.MeetingParticipant(
                    room_id=room.id,
                    kind="agent",
                    agent_id=chair_id,
                    role="chair",
                )
                out.insert(0, (synth, chair_agent))
                seen.add(chair_id)
        else:
            ordered: list[tuple[models.MeetingParticipant, models.Agent]] = []
            rest: list[tuple[models.MeetingParticipant, models.Agent]] = []
            for pair in out:
                if pair[1].id == chair_id or (pair[0].role or "").lower() == "chair":
                    ordered.append(pair)
                else:
                    rest.append(pair)
            out = ordered + rest
    else:
        ordered = []
        rest = []
        for pair in out:
            if (pair[0].role or "").lower() == "chair":
                ordered.append(pair)
            else:
                rest.append(pair)
        out = ordered + rest

    return out


def _last_messages(
    db: Session, room_id: int, limit: int = TRANSCRIPT_LIMIT
) -> list[models.MeetingMessage]:
    rows = (
        db.query(models.MeetingMessage)
        .filter(models.MeetingMessage.room_id == room_id)
        .order_by(models.MeetingMessage.id.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()
    return rows


def _cap_agents(requested: int | None) -> int:
    """Clamp agent count to [1, MAX_AGENTS_PER_ROUND]."""
    if requested is None:
        return MAX_AGENTS_PER_ROUND
    try:
        n = int(requested)
    except (TypeError, ValueError):
        return MAX_AGENTS_PER_ROUND
    if n < 1:
        return 1
    return min(n, MAX_AGENTS_PER_ROUND)


async def run_meeting_round(
    db: Session,
    user_or_room_id: models.User | int,
    room_or_user_id: int,
    *,
    prompt: str = "",
    max_agents: int | None = None,
    chair_only: bool = False,
) -> list[models.MeetingMessage] | dict[str, Any]:
    """
    Run one multi-agent discussion round in a meeting room.

    Call styles
    -----------
    Skill (agent_skills):
        await run_meeting_round(db, user, meeting_id, prompt=…, max_agents=…, chair_only=…)
        → dict {ok, meeting_id, count, message_ids, messages, …}

    Router (meetings.py):
        await run_meeting_round(db, room_id, user_id)
        → list[MeetingMessage]  (may be empty)

    Loads agent participants (chair first, capped), each replies via
    ``complete(messages, model, mode=…, credentials=…, max_tokens=…)``.
    New MeetingMessage rows are committed; emit_ops events fire per turn.
    """
    # Resolve dual positional signatures
    if _is_user_obj(user_or_room_id):
        user_id = _user_id_of(user_or_room_id)
        room_id = int(room_or_user_id)
        as_dict = True
    else:
        room_id = int(user_or_room_id)
        user_id = int(room_or_user_id)
        as_dict = False

    cap = _cap_agents(max_agents)
    focus = (prompt or "").strip()
    new_messages: list[models.MeetingMessage] = []

    def _result(
        *,
        ok: bool,
        error: str | None = None,
        extra: dict | None = None,
    ) -> list[models.MeetingMessage] | dict[str, Any]:
        if not as_dict:
            return new_messages
        payload: dict[str, Any] = {
            "ok": ok,
            "meeting_id": room_id,
            "count": len(new_messages),
            "message_ids": [m.id for m in new_messages],
            "messages": [_message_to_dict(m) for m in new_messages],
        }
        if error:
            payload["error"] = error
            payload["message"] = error
        else:
            payload["message"] = (
                f"Round complete: {len(new_messages)} turn(s)"
                if new_messages
                else "Round complete with no new messages"
            )
        if extra:
            payload.update(extra)
        return payload

    try:
        room = db.get(models.MeetingRoom, room_id)
    except Exception as e:
        log.warning("run_meeting_round load room failed: %s", e)
        return _result(ok=False, error=f"load room failed: {e}")

    if not room:
        log.info("run_meeting_round: room %s not found", room_id)
        return _result(ok=False, error="meeting not found")
    if room.user_id != user_id:
        log.info("run_meeting_round: room %s ownership mismatch", room_id)
        return _result(ok=False, error="meeting not found")
    if (room.status or "").lower() == "closed":
        log.info("run_meeting_round: room %s closed", room_id)
        return _result(ok=False, error="meeting is closed")

    try:
        await emit_ops(
            user_id,
            kind="action",
            status="info",
            title=f"Meeting round: {(room.title or 'Meeting')[:80]}",
            detail="Agents taking turns…",
            task_id=room.task_id,
            payload={"room_id": room_id, "phase": "start"},
            db=db,
        )
    except Exception as e:
        log.warning("emit_ops meeting start failed: %s", e)

    task: models.Task | None = None
    if room.task_id:
        try:
            task = db.get(models.Task, room.task_id)
        except Exception:
            task = None
    task_excerpt = _task_excerpt(task)

    try:
        agents = _load_agent_participants(db, room)
    except Exception as e:
        log.warning("load participants failed room=%s: %s", room_id, e)
        return _result(ok=False, error=f"load participants failed: {e}")

    if chair_only and agents:
        chair_id = room.chair_agent_id
        if chair_id:
            agents = [p for p in agents if p[1].id == chair_id]
        else:
            # First chair-role participant, else first agent only
            chair_pairs = [p for p in agents if (p[0].role or "").lower() == "chair"]
            agents = chair_pairs[:1] if chair_pairs else agents[:1]

    agents = agents[:cap]

    # Empty participants — no crash; ops note + empty result
    if not agents:
        log.info("run_meeting_round: no agent participants room=%s", room_id)
        try:
            await emit_ops(
                user_id,
                kind="action",
                status="info",
                title="Meeting round skipped",
                detail="No agent participants in room",
                task_id=room.task_id,
                payload={"room_id": room_id, "phase": "empty"},
                db=db,
            )
        except Exception:
            pass
        return _result(ok=False, error="No agent participants in room")

    agent_names = {a.id: (a.name or f"Agent#{a.id}") for _, a in agents}
    try:
        recent = _last_messages(db, room_id, TRANSCRIPT_LIMIT)
        for m in recent:
            if m.sender_kind == "agent" and m.sender_agent_id and m.sender_agent_id not in agent_names:
                ag = db.get(models.Agent, m.sender_agent_id)
                if ag:
                    agent_names[ag.id] = ag.name or f"Agent#{ag.id}"
    except Exception as e:
        log.warning("load transcript failed room=%s: %s", room_id, e)
        recent = []

    try:
        creds = credentials_for_user(db, user_id)
    except Exception as e:
        log.warning("credentials_for_user failed: %s", e)
        creds = {}

    working: list[models.MeetingMessage] = list(recent)
    chair_id = room.chair_agent_id

    # Skill path may pass a focus prompt that the router would have already posted.
    # Inject into agent prompts via `focus`; do not duplicate a DB message here.
    if (room.status or "").lower() == "open":
        try:
            room.status = "active"
            db.commit()
        except Exception:
            db.rollback()

    for part, agent in agents:
        name = agent.name or f"Agent#{agent.id}"
        is_chair = bool(
            (chair_id and agent.id == chair_id)
            or (part.role or "").lower() == "chair"
        )
        model = map_model(agent.model or "fast")
        transcript = _format_transcript(working[-TRANSCRIPT_LIMIT:], agent_names)
        system = _build_system_prompt(
            agent_name=name,
            purpose=room.purpose or "",
            room_title=room.title or "Meeting",
            room_type=room.room_type or "brainstorm",
            task_excerpt=task_excerpt,
            transcript=transcript,
            is_chair=is_chair,
            focus=focus,
        )
        user_line = (
            "As chair, open or advance the discussion with a clear point or question."
            if is_chair
            else "Contribute your perspective on the discussion so far."
        )
        if focus:
            user_line = f"{user_line}\nFocus for this round: {focus[:400]}"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_line},
        ]

        try:
            await emit_ops(
                user_id,
                kind="thinking",
                status="info",
                title=f"{name} speaking",
                detail=(room.title or "Meeting")[:120],
                agent_id=agent.id,
                task_id=room.task_id,
                payload={"room_id": room_id, "phase": "turn"},
                db=db,
            )
        except Exception as e:
            log.warning("emit_ops turn start failed: %s", e)

        try:
            # complete(messages, model, mode=…, credentials=…, *, max_tokens=…)
            reply = await complete(
                messages,
                model,
                mode="general",
                credentials=creds if creds else None,
                max_tokens=REPLY_MAX_TOKENS,
            )
        except Exception as e:
            log.warning("LLM failed for agent %s room %s: %s", agent.id, room_id, e)
            try:
                await emit_ops(
                    user_id,
                    kind="action",
                    status="failed",
                    title=f"{name} turn failed",
                    detail=str(e)[:300],
                    agent_id=agent.id,
                    task_id=room.task_id,
                    payload={"room_id": room_id},
                    db=db,
                )
            except Exception:
                pass
            continue

        text = (reply or "").strip()
        if not text:
            log.info("empty reply agent=%s room=%s", agent.id, room_id)
            continue
        if len(text) > CONTENT_MAX:
            text = text[:CONTENT_MAX] + "…"

        try:
            msg = models.MeetingMessage(
                room_id=room.id,
                sender_kind="agent",
                sender_agent_id=agent.id,
                content=text,
                msg_type="chat",
                meta_json=json.dumps({
                    "model": model,
                    "is_chair": is_chair,
                    "round": True,
                }),
                created_at=datetime.utcnow(),
            )
            db.add(msg)
            db.commit()
            db.refresh(msg)
        except Exception as e:
            log.warning("persist MeetingMessage failed agent=%s: %s", agent.id, e)
            try:
                db.rollback()
            except Exception:
                pass
            continue

        new_messages.append(msg)
        working.append(msg)
        agent_names[agent.id] = name

        try:
            await emit_ops(
                user_id,
                kind="action",
                status="done",
                title=f"{name} spoke",
                detail=text[:180],
                agent_id=agent.id,
                task_id=room.task_id,
                payload={
                    "room_id": room_id,
                    "message_id": msg.id,
                    "phase": "turn_done",
                },
                db=db,
            )
        except Exception as e:
            log.warning("emit_ops turn done failed: %s", e)

    try:
        await emit_ops(
            user_id,
            kind="action",
            status="done",
            title=f"Meeting round complete ({len(new_messages)} turns)",
            detail=(room.title or "Meeting")[:120],
            task_id=room.task_id,
            payload={
                "room_id": room_id,
                "message_ids": [m.id for m in new_messages],
                "phase": "end",
            },
            db=db,
        )
    except Exception as e:
        log.warning("emit_ops meeting end failed: %s", e)

    return _result(ok=True, extra={"agents_ran": len(agents), "cap": cap})


async def summarize_meeting(
    db: Session,
    user_or_room_id: models.User | int,
    room_or_user_id: int | None = None,
    *,
    agent: models.Agent | None = None,
    max_messages: int = 40,
) -> str | dict[str, Any]:
    """
    Produce a short meeting summary via LLM and store it on MeetingRoom.summary_text.

    Skill path:
        await summarize_meeting(db, user, room_id, agent=agent) → dict {ok, summary, …}
    Simple path:
        await summarize_meeting(db, room_id, user_id) → str (empty on failure)
    """
    if _is_user_obj(user_or_room_id):
        user_id = _user_id_of(user_or_room_id)
        room_id = int(room_or_user_id) if room_or_user_id is not None else 0
        as_dict = True
    else:
        room_id = int(user_or_room_id)
        user_id = int(room_or_user_id) if room_or_user_id is not None else 0
        as_dict = False

    def _out(summary: str, *, ok: bool = True, error: str | None = None) -> str | dict[str, Any]:
        if not as_dict:
            return summary or ""
        payload: dict[str, Any] = {
            "ok": ok and bool(summary),
            "summary": summary or "",
            "meeting_id": room_id,
        }
        if error:
            payload["error"] = error
            payload["ok"] = False
        if agent is not None:
            payload["agent_id"] = agent.id
        return payload

    try:
        room = db.get(models.MeetingRoom, room_id)
    except Exception as e:
        log.warning("summarize_meeting load failed: %s", e)
        return _out("", ok=False, error=str(e))

    if not room or room.user_id != user_id:
        return _out("", ok=False, error="meeting not found")

    try:
        rows = (
            db.query(models.MeetingMessage)
            .filter(models.MeetingMessage.room_id == room_id)
            .order_by(models.MeetingMessage.id.desc())
            .limit(max_messages)
            .all()
        )
        rows.reverse()
    except Exception as e:
        log.warning("summarize_meeting messages failed: %s", e)
        return _out(room.summary_text or "", ok=False, error=str(e))

    name_cache: dict[int, str] = {}
    for m in rows:
        if m.sender_kind == "agent" and m.sender_agent_id and m.sender_agent_id not in name_cache:
            ag = db.get(models.Agent, m.sender_agent_id)
            if ag:
                name_cache[ag.id] = ag.name or f"Agent#{ag.id}"

    transcript = _format_transcript(rows, name_cache)
    if transcript == "(no prior messages)":
        return _out(room.summary_text or "", ok=bool(room.summary_text))

    # Prefer chair / calling agent model
    model = "fast"
    if agent and getattr(agent, "model", None):
        model = map_model(agent.model or "fast")
    elif room.chair_agent_id:
        chair = db.get(models.Agent, room.chair_agent_id)
        if chair:
            model = map_model(chair.model or "fast")

    try:
        creds = credentials_for_user(db, user_id)
    except Exception:
        creds = {}

    prompt_msgs = [
        {
            "role": "system",
            "content": (
                "Summarize this meeting in 5–10 bullet points: decisions, open questions, "
                "action items (who/what). Be concise. Plain text only."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Meeting: {room.title or 'Meeting'}\n"
                f"Purpose: {(room.purpose or '')[:400]}\n\n"
                f"Transcript:\n{transcript}"
            ),
        },
    ]

    try:
        summary = await complete(
            prompt_msgs,
            model,
            mode="general",
            credentials=creds if creds else None,
            max_tokens=500,
        )
        summary = (summary or "").strip()
    except Exception as e:
        log.warning("summarize_meeting LLM failed room=%s: %s", room_id, e)
        return _out(room.summary_text or "", ok=False, error=str(e))

    if not summary:
        return _out(room.summary_text or "", ok=False, error="empty summary")

    try:
        room.summary_text = summary[:8000]
        db.commit()
    except Exception as e:
        log.warning("summarize_meeting save failed: %s", e)
        try:
            db.rollback()
        except Exception:
            pass

    try:
        await emit_ops(
            user_id,
            kind="action",
            status="done",
            title="Meeting summarized",
            detail=summary[:180],
            task_id=room.task_id,
            agent_id=(agent.id if agent is not None else room.chair_agent_id),
            payload={"room_id": room_id, "phase": "summary"},
            db=db,
        )
    except Exception:
        pass

    return _out(summary, ok=True)
