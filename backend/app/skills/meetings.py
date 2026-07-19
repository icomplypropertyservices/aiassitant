"""Meeting room skill handlers."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..live_ops import emit_ops


def _parse_meeting_id(args: dict) -> int | None:
    raw = args.get("meeting_id") or args.get("room_id") or args.get("id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None

def _parse_id_list(raw) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
        out = []
        for p in parts:
            try:
                out.append(int(p))
            except ValueError:
                continue
        return out
    if isinstance(raw, (list, tuple, set)):
        out = []
        for x in raw:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                continue
        return out
    try:
        return [int(raw)]
    except (TypeError, ValueError):
        return []

def _meeting_room(db: Session, user: models.User, meeting_id: int | None) -> models.MeetingRoom | None:
    if not meeting_id:
        return None
    room = db.get(models.MeetingRoom, meeting_id)
    if not room or room.user_id != user.id:
        return None
    return room

async def _skill_open_meeting(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    title = (args.get("title") or "Meeting").strip()[:200] or "Meeting"
    purpose = (args.get("purpose") or args.get("description") or "").strip()[:4000]
    room_type = (args.get("room_type") or "brainstorm").strip()[:40] or "brainstorm"
    if room_type not in ("brainstorm", "task_war_room", "standup", "review"):
        room_type = "brainstorm"

    task_id = project_id = company_id = None
    for key, attr in (("task_id", "task_id"), ("project_id", "project_id"), ("company_id", "company_id")):
        try:
            v = args.get(key)
            if v is not None and str(v).strip() != "":
                if attr == "task_id":
                    task_id = int(v)
                elif attr == "project_id":
                    project_id = int(v)
                else:
                    company_id = int(v)
        except (TypeError, ValueError):
            pass

    if project_id is None:
        project_id = agent.project_id
    if company_id is None:
        company_id = agent.company_id

    agent_ids = _parse_id_list(args.get("agent_ids") or args.get("agents") or args.get("participant_ids"))
    # Always include the opening agent as chair
    if agent.id not in agent_ids:
        agent_ids = [agent.id] + agent_ids

    # Dedupe preserve order
    seen: set[int] = set()
    ordered: list[int] = []
    for aid in agent_ids:
        if aid in seen:
            continue
        seen.add(aid)
        ordered.append(aid)

    room = models.MeetingRoom(
        user_id=user.id,
        company_id=company_id,
        project_id=project_id,
        task_id=task_id,
        title=title,
        purpose=purpose,
        room_type=room_type,
        status="open",
        chair_agent_id=agent.id,
        settings_json=json.dumps({"opened_by": agent.id}),
        summary_text="",
        created_at=datetime.utcnow(),
    )
    db.add(room)
    db.flush()

    participants_out = []
    for i, aid in enumerate(ordered):
        a = db.get(models.Agent, aid)
        if not a or a.user_id != user.id:
            continue
        role = "chair" if a.id == agent.id else "member"
        p = models.MeetingParticipant(
            room_id=room.id,
            kind="agent",
            agent_id=a.id,
            role=role,
            joined_at=datetime.utcnow(),
        )
        db.add(p)
        participants_out.append({"agent_id": a.id, "name": a.name, "role": role})

    # Owner user as observer so humans appear in the room
    db.add(models.MeetingParticipant(
        room_id=room.id,
        kind="user",
        user_id=user.id,
        role="observer",
        joined_at=datetime.utcnow(),
    ))

    # Opening system message
    db.add(models.MeetingMessage(
        room_id=room.id,
        sender_kind="system",
        content=f"Meeting opened by {agent.name}: {title}"
                + (f" — {purpose}" if purpose else ""),
        msg_type="system",
        meta_json=json.dumps({"skill": "open_meeting"}),
        created_at=datetime.utcnow(),
    ))

    db.commit()
    db.refresh(room)

    await emit_ops(
        user.id,
        kind="meeting",
        status="running",
        title=f"Opened meeting: {title}",
        detail=f"{len(participants_out)} agent participant(s)",
        agent_id=agent.id,
        task_id=task_id,
        payload={"meeting_id": room.id, "participants": participants_out},
        db=db,
    )

    return {
        "ok": True,
        "message": f"Meeting opened: {title}",
        "meeting_id": room.id,
        "status": room.status,
        "chair_agent_id": agent.id,
        "participants": participants_out,
    }

async def _skill_post_to_meeting(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    meeting_id = _parse_meeting_id(args)
    room = _meeting_room(db, user, meeting_id)
    if not room:
        return {"ok": False, "error": "meeting_id required or meeting not found"}
    if (room.status or "").lower() == "closed":
        return {"ok": False, "error": "meeting is closed"}

    content = (args.get("content") or args.get("message") or args.get("body") or "").strip()
    if not content:
        return {"ok": False, "error": "content required"}

    msg_type = (args.get("msg_type") or args.get("type") or "chat").strip()[:40] or "chat"
    if msg_type not in ("chat", "decision", "task_created", "system"):
        msg_type = "chat"

    # Ensure poster is a participant (auto-join as member if missing)
    part = (
        db.query(models.MeetingParticipant)
        .filter_by(room_id=room.id, kind="agent", agent_id=agent.id)
        .first()
    )
    if not part:
        db.add(models.MeetingParticipant(
            room_id=room.id,
            kind="agent",
            agent_id=agent.id,
            role="member",
            joined_at=datetime.utcnow(),
        ))

    if (room.status or "").lower() == "open":
        room.status = "active"

    msg = models.MeetingMessage(
        room_id=room.id,
        sender_kind="agent",
        sender_agent_id=agent.id,
        content=content[:20000],
        msg_type=msg_type,
        meta_json=json.dumps({"skill": "post_to_meeting"}),
        created_at=datetime.utcnow(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    return {
        "ok": True,
        "message": f"Posted to meeting #{room.id}",
        "meeting_id": room.id,
        "message_id": msg.id,
        "msg_type": msg_type,
    }

async def _skill_run_meeting_round(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Delegate to meeting_runner.run_meeting_round (skill path → dict result)."""
    meeting_id = _parse_meeting_id(args)
    if not meeting_id:
        return {"ok": False, "error": "meeting_id required"}
    room = _meeting_room(db, user, meeting_id)
    if not room:
        return {"ok": False, "error": "meeting not found"}
    if (room.status or "").lower() == "closed":
        return {"ok": False, "error": "meeting is closed"}

    from ..meeting_runner import run_meeting_round

    max_agents = args.get("max_agents")
    try:
        max_agents = int(max_agents) if max_agents is not None and str(max_agents).strip() != "" else None
    except (TypeError, ValueError):
        max_agents = None

    chair_only = bool(args.get("chair_only") in (True, "true", "1", 1, "yes"))
    prompt = (args.get("prompt") or args.get("focus") or args.get("instruction") or "").strip()

    # Skill path: (db, user, room_id, *, prompt, max_agents, chair_only) → dict
    result = await run_meeting_round(
        db,
        user,
        meeting_id,
        prompt=prompt,
        max_agents=max_agents,
        chair_only=chair_only,
    )
    if isinstance(result, dict):
        return result
    # Defensive: router-style list return should not happen on skill path
    msgs = result or []
    return {
        "ok": True,
        "message": f"Round complete: {len(msgs)} turn(s)",
        "meeting_id": meeting_id,
        "count": len(msgs),
        "message_ids": [m.id for m in msgs],
    }

async def _skill_close_meeting(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Close room; optional summary via meeting_runner.summarize_meeting (skill path)."""
    meeting_id = _parse_meeting_id(args)
    room = _meeting_room(db, user, meeting_id)
    if not room:
        return {"ok": False, "error": "meeting_id required or meeting not found"}
    if (room.status or "").lower() == "closed":
        return {
            "ok": True,
            "already_closed": True,
            "message": f"Meeting #{room.id} already closed",
            "meeting_id": room.id,
            "status": "closed",
            "summary": room.summary_text or "",
        }

    summary = (args.get("summary") or "").strip()
    if not summary:
        from ..meeting_runner import summarize_meeting
        # Skill path: (db, user, room_id, agent=…) → dict {ok, summary, …}
        res = await summarize_meeting(db, user, room.id, agent=agent)
        if isinstance(res, dict):
            summary = (res.get("summary") or "").strip()
        else:
            summary = (res or "").strip()

    room.status = "closed"
    room.summary_text = summary[:20000] if summary else (room.summary_text or "")
    room.closed_at = datetime.utcnow()

    db.add(models.MeetingMessage(
        room_id=room.id,
        sender_kind="system",
        sender_agent_id=agent.id,
        content=f"Meeting closed by {agent.name}."
                + (f"\n\nSummary:\n{summary[:4000]}" if summary else ""),
        msg_type="system",
        meta_json=json.dumps({"skill": "close_meeting"}),
        created_at=datetime.utcnow(),
    ))
    db.commit()
    db.refresh(room)

    await emit_ops(
        user.id,
        kind="meeting",
        status="done",
        title=f"Closed meeting: {room.title or f'#{room.id}'}",
        detail=(summary or "")[:400],
        agent_id=agent.id,
        payload={"meeting_id": room.id, "status": "closed"},
        db=db,
    )

    return {
        "ok": True,
        "already_closed": False,
        "message": f"Meeting #{room.id} closed",
        "meeting_id": room.id,
        "status": "closed",
        "summary": room.summary_text or "",
    }

async def _skill_extract_meeting_tasks(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    meeting_id = _parse_meeting_id(args)
    room = _meeting_room(db, user, meeting_id)
    if not room:
        return {"ok": False, "error": "meeting_id required or meeting not found"}

    default_agent_id = args.get("agent_id") or room.chair_agent_id or agent.id
    try:
        default_agent_id = int(default_agent_id)
    except (TypeError, ValueError):
        default_agent_id = agent.id

    raw_tasks = args.get("tasks") or args.get("items") or args.get("action_items")
    task_specs: list[dict] = []

    if isinstance(raw_tasks, str):
        # newline or semicolon separated titles
        for line in raw_tasks.replace(";", "\n").split("\n"):
            line = line.strip().lstrip("-*• ").strip()
            if line:
                task_specs.append({"title": line[:200], "description": line})
    elif isinstance(raw_tasks, list):
        for item in raw_tasks:
            if isinstance(item, str) and item.strip():
                task_specs.append({"title": item.strip()[:200], "description": item.strip()})
            elif isinstance(item, dict):
                title = (item.get("title") or item.get("name") or item.get("description") or "").strip()
                if not title:
                    continue
                task_specs.append({
                    "title": title[:200],
                    "description": (item.get("description") or title).strip(),
                    "agent_id": item.get("agent_id") or item.get("assignee_id"),
                    "priority": item.get("priority") or "medium",
                })

    # If no explicit tasks: LLM extract (like meetings router), then heuristic fallback
    source = "explicit"
    if not task_specs:
        from ..meeting_runner import _recent_transcript
        from ..llm import complete
        from ..user_keys import credentials_for_user
        from ..agent_scaffold import map_model

        transcript = _recent_transcript(db, room.id, limit=50)
        summary_bit = (room.summary_text or "").strip()
        llm_error = None

        if transcript.strip() or summary_bit:
            source_text = transcript
            if summary_bit:
                source_text = (
                    f"Existing summary:\n{summary_bit}\n\nTranscript:\n{transcript}"
                )
            creds = credentials_for_user(db, user.id)
            prompt = (
                f"From this meeting transcript, extract concrete action items as a JSON array.\n"
                f"Meeting: {room.title}\nPurpose: {room.purpose or 'n/a'}\n\n"
                f"{source_text}\n\n"
                'Return ONLY a JSON array of objects: '
                '[{"title":"...","description":"...","priority":"medium"}] '
                "Max 8 items. No markdown fences."
            )
            try:
                text = await complete(
                    [{"role": "user", "content": prompt}],
                    map_model(agent.model or "fast"),
                    mode="general",
                    credentials=creds if creds else None,
                    max_tokens=900,
                )
                text = (text or "").strip()
                # Strip optional code fences
                if text.startswith("```"):
                    text = re.sub(r"^```(?:json)?\s*", "", text)
                    text = re.sub(r"\s*```$", "", text)
                parsed = json.loads(text)
                if isinstance(parsed, dict) and "tasks" in parsed:
                    parsed = parsed["tasks"]
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict):
                            title = (item.get("title") or item.get("description") or "").strip()
                            if title:
                                task_specs.append({
                                    "title": title[:200],
                                    "description": (item.get("description") or title).strip(),
                                    "priority": item.get("priority") or "medium",
                                })
                        elif isinstance(item, str) and item.strip():
                            task_specs.append({
                                "title": item.strip()[:200],
                                "description": item.strip(),
                            })
                if task_specs:
                    source = "llm"
            except Exception as e:
                llm_error = str(e)

        # Heuristic fallback — same helper as meetings router extract-tasks
        if not task_specs:
            from ..meeting_extract import extract_tasks_from_room

            result = extract_tasks_from_room(
                db, room, user, agent_id=default_agent_id, commit=True,
            )
            if not result.get("ok"):
                return {
                    "ok": False,
                    "error": result.get("error")
                    or llm_error
                    or "no messages in meeting to extract tasks from",
                    "meeting_id": room.id,
                    "llm_error": llm_error,
                }
            tasks_out = result.get("tasks") or []
            await emit_ops(
                user.id,
                kind="meeting",
                status="done",
                title=f"Extracted {len(tasks_out)} task(s) from meeting #{room.id}",
                detail=(room.title or "")[:400],
                agent_id=agent.id,
                payload={
                    "meeting_id": room.id,
                    "tasks": tasks_out,
                    "source": "heuristic",
                    "llm_error": llm_error,
                },
                db=db,
            )
            return {
                "ok": True,
                "message": f"Created {len(tasks_out)} task(s) from meeting #{room.id}",
                "meeting_id": room.id,
                "tasks": tasks_out,
                "source": result.get("source") or "heuristic",
                "llm_error": llm_error,
            }

    if not task_specs:
        return {"ok": False, "error": "no tasks to create", "meeting_id": room.id}

    created = []
    for spec in task_specs[:20]:
        aid = spec.get("agent_id") or default_agent_id
        try:
            aid = int(aid)
        except (TypeError, ValueError):
            aid = default_agent_id
        target = db.get(models.Agent, aid)
        if not target or target.user_id != user.id:
            target = agent
            aid = agent.id

        from ..task_status import initial_task_status

        t = models.Task(
            user_id=user.id,
            agent_id=aid,
            assignee_type="agent",
            company_id=room.company_id or target.company_id or agent.company_id,
            project_id=room.project_id or target.project_id or agent.project_id,
            meeting_id=room.id,
            parent_task_id=room.task_id,
            title=(spec.get("title") or "Meeting task")[:200],
            description=(spec.get("description") or spec.get("title") or "").strip(),
            status=initial_task_status(agent=target, assignee_type="agent", run_now=True),
            priority=(spec.get("priority") or "medium")[:20],
            labels="meeting,extracted",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(t)
        db.flush()
        created.append({"task_id": t.id, "title": t.title, "agent_id": aid, "status": t.status})

        db.add(models.MeetingMessage(
            room_id=room.id,
            sender_kind="system",
            sender_agent_id=agent.id,
            content=f"Task created: {t.title} (#{t.id})",
            msg_type="task_created",
            meta_json=json.dumps({
                "task_id": t.id,
                "skill": "extract_meeting_tasks",
                "source": source,
            }),
            created_at=datetime.utcnow(),
        ))

    db.commit()

    await emit_ops(
        user.id,
        kind="meeting",
        status="done",
        title=f"Extracted {len(created)} task(s) from meeting #{room.id}",
        detail=", ".join(c["title"] for c in created)[:400],
        agent_id=agent.id,
        payload={"meeting_id": room.id, "tasks": created, "source": source},
        db=db,
    )

    return {
        "ok": True,
        "message": f"Created {len(created)} task(s) from meeting #{room.id}",
        "meeting_id": room.id,
        "tasks": created,
        "source": source,
    }

async def _skill_list_meetings(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        limit = min(40, int(args.get("limit") or 20))
    except Exception:
        limit = 20
    status = (args.get("status") or "").strip() or None
    query = db.query(models.MeetingRoom).filter_by(user_id=user.id)
    if status:
        query = query.filter(models.MeetingRoom.status == status)
    rows = query.order_by(models.MeetingRoom.id.desc()).limit(limit).all()
    return {
        "ok": True,
        "count": len(rows),
        "meetings": [
            {
                "id": r.id,
                "title": r.title,
                "status": r.status,
                "room_type": r.room_type,
                "purpose": (r.purpose or "")[:200],
                "chair_agent_id": r.chair_agent_id,
                "task_id": r.task_id,
            }
            for r in rows
        ],
    }


__all__ = [
    '_parse_meeting_id',
    '_parse_id_list',
    '_meeting_room',
    '_skill_open_meeting',
    '_skill_post_to_meeting',
    '_skill_run_meeting_round',
    '_skill_close_meeting',
    '_skill_extract_meeting_tasks',
    '_skill_list_meetings',
]
