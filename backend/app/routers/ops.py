"""Live ops feed + visual snapshot + WebSocket + autonomy control."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..auth_utils import get_current_user, user_from_ws_token, accept_and_authenticate_ws
from ..live_ops import list_ops, ops_snapshot, emit_ops
from ..ws import manager
from .. import models
from ..permissions import catalog as permission_catalog
from ..autonomy import (
    get_or_create_settings,
    settings_out,
    run_user_cycle,
    run_global_tick,
)

router = APIRouter(prefix="/ops", tags=["ops"])


@router.post("/scaffold")
def scaffold_all_agents(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """
    Explicit one-shot REPAIR of the whole team (not run on every chat/tick).
    Sets never_idle, executable permissions, model maps, role skills, hierarchy.
    """
    from ..agent_scaffold import repair_workspace
    return repair_workspace(db, user.id)


class PlanIn(BaseModel):
    title: str
    steps: list[str] = Field(default_factory=list)
    agent_id: int | None = None


class AutonomySettingsIn(BaseModel):
    autonomy_enabled: bool | None = None
    autonomy_interval_sec: int | None = None
    task_stuck_minutes: int | None = None


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


@router.get("/permissions")
def permissions_catalog(user=Depends(get_current_user)):
    """Permission levels + escalate-when options for agents and humans."""
    return permission_catalog()


@router.get("/autonomy")
def get_autonomy(db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = get_or_create_settings(db, user.id)
    return {
        **settings_out(row),
        "permissions": permission_catalog(),
    }


@router.put("/autonomy")
def put_autonomy(data: AutonomySettingsIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = get_or_create_settings(db, user.id)
    if data.autonomy_enabled is not None:
        row.autonomy_enabled = bool(data.autonomy_enabled)
    if data.autonomy_interval_sec is not None:
        row.autonomy_interval_sec = max(15, min(3600, int(data.autonomy_interval_sec)))
    if data.task_stuck_minutes is not None:
        row.task_stuck_minutes = max(5, min(24 * 60, int(data.task_stuck_minutes)))
    db.commit()
    db.refresh(row)
    return settings_out(row)


@router.post("/autonomy/tick")
async def autonomy_tick(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Run one self-driving cycle for this workspace (also called by background loop)."""
    result = await run_user_cycle(db, user)
    return {"ok": True, "result": result}


def _optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db),
):
    """Like get_current_user but returns None instead of 401 (for cron + optional JWT)."""
    if not creds or not creds.credentials:
        return None
    from ..auth_utils import decode_token

    payload = decode_token(creds.credentials)
    if not payload:
        return None
    return db.get(models.User, int(payload["sub"]))


@router.post("/autonomy/tick-all")
async def autonomy_tick_all(
    db: Session = Depends(get_db),
    user=Depends(_optional_user),
    x_cron_secret: str | None = Header(default=None, alias="x-cron-secret"),
    authorization: str | None = Header(default=None),
):
    """Admin or cron only.

    Access when any of:
    - `X-Cron-Secret: <CRON_SECRET>` matches configured secret
    - `Authorization: Bearer <CRON_SECRET>` (Vercel Cron often sends this)
    - Authenticated JWT user with admin role (admin UI)
    """
    from fastapi import HTTPException
    from ..config import CRON_SECRET, IS_PRODUCTION

    bearer_token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization[7:].strip()

    is_valid_cron = bool(
        CRON_SECRET
        and (
            (x_cron_secret and x_cron_secret == CRON_SECRET)
            or (bearer_token and bearer_token == CRON_SECRET)
        )
    )
    is_admin = bool(user is not None and getattr(user, "role", None) == "admin")

    if not CRON_SECRET and IS_PRODUCTION and not is_admin:
        raise HTTPException(503, "CRON_SECRET not configured")

    if not (is_valid_cron or is_admin):
        raise HTTPException(
            403,
            "Admin role or valid cron secret required "
            "(X-Cron-Secret or Authorization: Bearer <CRON_SECRET>)",
        )

    result = await run_global_tick()
    return {
        "ok": True,
        "global": True,
        "via": "cron" if is_valid_cron else "admin",
        "result": result,
    }


@router.get("/escalations")
def list_escalations(
    limit: int = Query(40, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    rows = (
        db.query(models.EscalationLog)
        .filter_by(user_id=user.id)
        .order_by(models.EscalationLog.id.desc())
        .limit(limit)
        .all()
    )
    out = []
    for r in rows:
        fa = db.get(models.Agent, r.from_agent_id) if r.from_agent_id else None
        ta = db.get(models.Agent, r.to_agent_id) if r.to_agent_id else None
        fh = db.get(models.Human, r.from_human_id) if r.from_human_id else None
        th = db.get(models.Human, r.to_human_id) if r.to_human_id else None
        out.append({
            "id": r.id,
            "task_id": r.task_id,
            "reason_code": r.reason_code,
            "reason_text": r.reason_text,
            "status": r.status,
            "from_agent": fa.name if fa else None,
            "to_agent": ta.name if ta else None,
            "from_human": fh.name if fh else None,
            "to_human": th.name if th else None,
            "created_at": r.created_at,
        })
    return {"escalations": out}


@router.websocket("/ws")
async def ops_ws(ws: WebSocket, token: str = Query("")):
    """Live ops feed WS. Auth: ?token= (legacy/mobile) or first-message {"type":"auth","token":...}."""
    db = SessionLocal()
    user = await accept_and_authenticate_ws(ws, token, db)
    if not user:
        db.close()
        return
    user_id = user.id
    # Send snapshot first
    snap = ops_snapshot(db, user_id)
    db.close()
    manager.register(f"ops:{user_id}", ws)
    try:
        await ws.send_json({"event": "snapshot", "snapshot": snap})
        while True:
            # Keepalive / client pings
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(f"ops:{user_id}", ws)
    except Exception:
        manager.disconnect(f"ops:{user_id}", ws)
