"""Real-time plan/action event bus for the live banner and ops visual."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .database import SessionLocal
from .ws import manager


def _payload(row: models.LiveOpsEvent) -> dict:
    try:
        extra = json.loads(row.payload_json or "{}")
    except Exception:
        extra = {}
    return {
        "id": row.id,
        "kind": row.kind,
        "status": row.status,
        "title": row.title,
        "detail": row.detail,
        "agent_id": row.agent_id,
        "human_id": row.human_id,
        "task_id": row.task_id,
        "plan_id": row.plan_id or "",
        "payload": extra,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
    }


async def emit_ops(
    user_id: int,
    *,
    kind: str = "action",
    status: str = "info",
    title: str = "",
    detail: str = "",
    agent_id: int | None = None,
    human_id: int | None = None,
    task_id: int | None = None,
    plan_id: str = "",
    payload: dict | None = None,
    db: Session | None = None,
) -> dict:
    """Persist + broadcast a live ops event."""
    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        row = models.LiveOpsEvent(
            user_id=user_id,
            kind=kind,
            status=status,
            title=(title or "")[:240],
            detail=(detail or "")[:4000],
            agent_id=agent_id,
            human_id=human_id,
            task_id=task_id,
            plan_id=plan_id or "",
            payload_json=json.dumps(payload or {}),
            created_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        data = _payload(row)
        await manager.broadcast(f"ops:{user_id}", {"event": "ops", "entry": data})
        # Also mirror into activity feed when agent-scoped
        if agent_id:
            try:
                log = models.ActivityLog(
                    agent_id=agent_id,
                    type=kind if kind in ("thinking", "action", "email", "sms", "call", "done", "info") else "action",
                    message=f"{title}: {detail}"[:500] if detail else title,
                )
                db.add(log)
                db.commit()
                await manager.broadcast(
                    f"agents:{user_id}",
                    {
                        "event": "activity",
                        "agent_id": agent_id,
                        "entry": {
                            "id": log.id,
                            "type": log.type,
                            "message": log.message,
                            "created_at": log.created_at,
                        },
                    },
                )
            except Exception:
                pass
        return data
    finally:
        if own_db:
            db.close()


def list_ops(db: Session, user_id: int, *, limit: int = 80, plan_id: str | None = None) -> list[dict]:
    q = db.query(models.LiveOpsEvent).filter_by(user_id=user_id)
    if plan_id:
        q = q.filter_by(plan_id=plan_id)
    rows = q.order_by(models.LiveOpsEvent.id.desc()).limit(limit).all()
    return [_payload(r) for r in rows]


def ops_snapshot(db: Session, user_id: int) -> dict[str, Any]:
    """Aggregate for the ops visual canvas."""
    events = list_ops(db, user_id, limit=100)
    agents = db.query(models.Agent).filter_by(user_id=user_id).all()
    humans = db.query(models.Human).filter_by(owner_user_id=user_id).all()
    open_tasks = (
        db.query(models.Task)
        .filter(
            models.Task.user_id == user_id,
            models.Task.status.in_(("todo", "queued", "in_progress", "review")),
        )
        .count()
    )
    running = [e for e in events if e.get("status") == "running"][:12]
    plans = {}
    for e in events:
        pid = e.get("plan_id") or ""
        if not pid:
            continue
        plans.setdefault(pid, []).append(e)
    active_plans = []
    for pid, steps in plans.items():
        statuses = {s.get("status") for s in steps}
        if "running" in statuses or "queued" in statuses:
            active_plans.append({
                "plan_id": pid,
                "title": next((s["title"] for s in steps if s.get("kind") == "plan"), pid),
                "steps": list(reversed(steps))[:20],
                "running": sum(1 for s in steps if s.get("status") == "running"),
                "done": sum(1 for s in steps if s.get("status") == "done"),
            })
    return {
        "events": events[:50],
        "running": running,
        "active_plans": active_plans[:8],
        "counts": {
            "agents": len(agents),
            "agents_active": sum(1 for a in agents if a.status == "active"),
            "humans": len(humans),
            "humans_active": sum(1 for h in humans if h.status == "active"),
            "open_tasks": open_tasks,
            "events_recent": len(events),
        },
        "nodes": {
            "agents": [
                {
                    "id": a.id,
                    "name": a.name,
                    "status": a.status,
                    "role": a.hierarchy_role,
                    "parent_id": a.parent_id,
                }
                for a in agents
            ],
            "humans": [
                {
                    "id": h.id,
                    "name": h.name,
                    "status": h.status,
                    "role_title": h.role_title,
                }
                for h in humans
            ],
        },
    }
