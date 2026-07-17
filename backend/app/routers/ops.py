"""Live ops feed + visual snapshot + WebSocket."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..auth_utils import get_current_user, user_from_ws_token
from ..live_ops import list_ops, ops_snapshot, emit_ops
from ..ws import manager
from .. import models

router = APIRouter(prefix="/ops", tags=["ops"])


class PlanIn(BaseModel):
    title: str
    steps: list[str] = Field(default_factory=list)
    agent_id: int | None = None


@router.get("/live")
def live_feed(
    limit: int = Query(50, ge=1, le=200),
    plan_id: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return {
        "events": list_ops(db, user.id, limit=limit, plan_id=plan_id),
        "snapshot": ops_snapshot(db, user.id),
    }


@router.get("/visual")
def visual(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return ops_snapshot(db, user.id)


@router.post("/plan")
async def publish_plan(data: PlanIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import execute_skill

    agent = None
    if data.agent_id:
        agent = db.get(models.Agent, data.agent_id)
        if not agent or agent.user_id != user.id:
            agent = None
    if not agent:
        agent = (
            db.query(models.Agent)
            .filter_by(user_id=user.id, hierarchy_role="orchestrator")
            .first()
        )
    if not agent:
        agent = db.query(models.Agent).filter_by(user_id=user.id).first()
    if not agent:
        # synthetic announce without agent skill
        import uuid
        plan_id = f"plan-{uuid.uuid4().hex[:10]}"
        await emit_ops(
            user.id, kind="plan", status="running", title=data.title,
            detail=f"{len(data.steps)} steps", plan_id=plan_id, db=db,
        )
        for i, step in enumerate(data.steps[:20], 1):
            await emit_ops(
                user.id, kind="step", status="queued", title=f"Step {i}",
                detail=step, plan_id=plan_id, db=db,
            )
        return {"ok": True, "plan_id": plan_id}
    return await execute_skill(
        db, agent, user, "announce_plan",
        {"title": data.title, "steps": data.steps},
    )


@router.websocket("/ws")
async def ops_ws(ws: WebSocket, token: str = Query("")):
    db = SessionLocal()
    user = user_from_ws_token(token, db)
    if not user:
        db.close()
        await ws.close(code=4401)
        return
    user_id = user.id
    # Send snapshot first
    snap = ops_snapshot(db, user_id)
    db.close()
    await manager.connect(f"ops:{user_id}", ws)
    try:
        await ws.send_json({"event": "snapshot", "snapshot": snap})
        while True:
            # Keepalive / client pings
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(f"ops:{user_id}", ws)
    except Exception:
        manager.disconnect(f"ops:{user_id}", ws)
