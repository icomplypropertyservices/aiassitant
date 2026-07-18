"""Staff admin: users, fleet monitoring, wallet top-ups, model routing, WebUI."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import require_admin
from .. import config
from ..runpod_fleet import (
    probe_ollama,
    get_model_map,
    set_model_map,
    pull_model,
    delete_model,
    run_console,
    get_connection,
    set_connection,
    get_ops_log,
    test_generate,
    support_bundle,
    webui_url,
    RECOMMENDED_MODELS,
)
from ..admin_ops_team import (
    ensure_staff_ops_team,
    list_staff_ops_team,
    staff_ops_brief,
    STAFF_TEAM_SPEC,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
def users(db: Session = Depends(get_db), admin=Depends(require_admin)):
    out = []
    for u in db.query(models.User).all():
        bal = db.query(models.Balance).filter_by(user_id=u.id).first()
        agents = db.query(models.Agent).filter_by(user_id=u.id).count()
        usage = db.query(models.TokenUsage).filter_by(user_id=u.id).all()
        out.append({
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "role": u.role,
            "plan": u.plan,
            "credits": round(bal.credits, 4) if bal else 0,
            "tokens_used_period": int(getattr(bal, "tokens_used_period", 0) or 0) if bal else 0,
            "tokens_included": int(getattr(bal, "tokens_included", 0) or 0) if bal else 0,
            "agents": agents,
            "tokens": sum(r.input_tokens + r.output_tokens for r in usage),
            "spend": round(sum(r.cost for r in usage), 4),
            "created_at": u.created_at,
        })
    return out


@router.get("/stats")
def stats(db: Session = Depends(get_db), admin=Depends(require_admin)):
    usage = db.query(models.TokenUsage).all()
    low_credit = 0
    for u in db.query(models.User).all():
        bal = db.query(models.Balance).filter_by(user_id=u.id).first()
        if bal and (bal.credits or 0) < 1.0:
            low_credit += 1
    return {
        "users": db.query(models.User).count(),
        "agents": db.query(models.Agent).count(),
        "conversations": db.query(models.Conversation).count(),
        "total_tokens": sum(r.input_tokens + r.output_tokens for r in usage),
        "total_revenue": round(sum(r.cost for r in usage), 4),
        "low_credit_users": low_credit,
    }


@router.get("/agents")
def all_agents(db: Session = Depends(get_db), admin=Depends(require_admin)):
    out = []
    for a in db.query(models.Agent).all():
        owner = db.get(models.User, a.user_id)
        out.append({
            "id": a.id,
            "name": a.name,
            "owner": owner.email if owner else "?",
            "template_type": a.template_type,
            "model": a.model,
            "status": a.status,
            "idle_mode": a.idle_mode,
        })
    return out


# ─── Fleet / LLM control plane (admin only) ─────────────────────────────────

@router.get("/fleet/status")
async def fleet_status(admin=Depends(require_admin)):
    """Probe Ollama + connection + model map + recommended pulls + ops log."""
    probe = await probe_ollama()
    conn = get_connection(include_secrets=False)
    wu = webui_url() or conn.get("webui_url")
    return {
        "probe": probe,
        "model_map": get_model_map(),
        "recommended": RECOMMENDED_MODELS,
        "connection": conn,
        "webui_url": wu or None,
        "runpod_configured": bool(conn.get("ollama_url") or config.RUNPOD_OLLAMA_URL or config.RUNPOD_OPENAI_BASE_URL),
        "ops_log": get_ops_log(25),
        "console_help": (
            "list | pull <tag> | rm <tag> | show <tag> | test <tag> [prompt] | ps | help"
        ),
        "hardware_hint": {
            "tier_a": "1× RTX 4090 24GB or A40 48GB — Qwen 3B–32B + DeepSeek R1 8B–32B",
            "tier_b": "1× A100/H100 80GB — Qwen 72B + DeepSeek R1 70B",
            "docs": "backend/RUNPOD_CONNECT.md",
        },
    }


@router.get("/fleet/models")
async def fleet_models(admin=Depends(require_admin)):
    probe = await probe_ollama()
    return {
        "ok": probe.get("ok"),
        "models": probe.get("models") or [],
        "map": get_model_map(),
        "recommended": RECOMMENDED_MODELS,
    }


@router.get("/fleet/connection")
def fleet_connection_get(admin=Depends(require_admin)):
    return get_connection(include_secrets=False)


class ConnectionIn(BaseModel):
    ollama_url: str | None = None
    webui_url: str | None = None
    api_key: str | None = None
    openai_base_url: str | None = None
    support_notes: str | None = None
    agent_terminal_enabled: bool | None = None


@router.put("/fleet/connection")
def fleet_connection_put(data: ConnectionIn, admin=Depends(require_admin)):
    """Save RunPod/Ollama URLs without redeploying Vercel env."""
    payload = data.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(400, "no fields to update")
    who = getattr(admin, "email", None) or "admin"
    return {"ok": True, "connection": set_connection(payload, updated_by=str(who))}


@router.get("/fleet/support-bundle")
def fleet_support_bundle(admin=Depends(require_admin)):
    """Safe summary to paste into Grok chat for assisted setup."""
    return support_bundle()


class ModelMapIn(BaseModel):
    mapping: dict[str, str] = Field(default_factory=dict)


@router.put("/fleet/model-map")
def fleet_model_map(data: ModelMapIn, admin=Depends(require_admin)):
    """Change which Ollama tag backs Fast/Quality/Reasoning/etc. on demand."""
    if not data.mapping:
        raise HTTPException(400, "mapping required")
    who = getattr(admin, "email", None) or "admin"
    return {"ok": True, "map": set_model_map(data.mapping, updated_by=str(who))}


class PullIn(BaseModel):
    tag: str


@router.post("/fleet/pull")
async def fleet_pull(data: PullIn, admin=Depends(require_admin)):
    """Ask the Ollama host to pull a model (long-running on the pod)."""
    tag = (data.tag or "").strip()
    if not tag:
        raise HTTPException(400, "tag required")
    result = await pull_model(tag)
    if not result.get("ok"):
        raise HTTPException(502, result.get("error") or "pull failed")
    return result


class DeleteIn(BaseModel):
    tag: str


@router.post("/fleet/delete")
async def fleet_delete(data: DeleteIn, admin=Depends(require_admin)):
    tag = (data.tag or "").strip()
    if not tag:
        raise HTTPException(400, "tag required")
    result = await delete_model(tag)
    if not result.get("ok"):
        raise HTTPException(502, result.get("error") or "delete failed")
    return result


class TestIn(BaseModel):
    tag: str = "fast"
    prompt: str = "Say hello in one short sentence."


@router.post("/fleet/test")
async def fleet_test(data: TestIn, admin=Depends(require_admin)):
    result = await test_generate(data.tag, data.prompt)
    if not result.get("ok"):
        raise HTTPException(502, result.get("error") or "test failed")
    return result


class ConsoleIn(BaseModel):
    command: str = Field(..., min_length=1, max_length=500)


@router.post("/fleet/console")
async def fleet_console(data: ConsoleIn, admin=Depends(require_admin)):
    """
    Allowlisted fleet terminal (list / pull / rm / show / test / ps).
    No free shell — safe for staff and for guiding Grok through ops.
    """
    return await run_console(data.command)


@router.get("/fleet/ops-log")
def fleet_ops_log(limit: int = 40, admin=Depends(require_admin)):
    return get_ops_log(limit)


# ─── Staff Admin ops team (orchestrator + specialists) ──────────────────────

@router.get("/ops-team")
async def ops_team_status(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """List staff admin agents + fleet snapshot for Admin UI."""
    brief = staff_ops_brief(db, admin)
    probe = await probe_ollama()
    return {
        **brief,
        "probe": probe,
        "ready": len(brief.get("agents") or []) >= 1,
    }


@router.post("/ops-team/ensure")
def ops_team_ensure(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """
    Create / repair Staff Admin Orchestrator + specialists.
    Server Monitor → grok-max; all others → Qwen/DeepSeek tiers.
    """
    result = ensure_staff_ops_team(db, admin)
    if not result.get("ok"):
        raise HTTPException(403, result.get("error") or "failed")
    return result


@router.get("/ops-team/spec")
def ops_team_spec(admin=Depends(require_admin)):
    """Static team blueprint (models + roles)."""
    return {
        "team": [
            {
                "name": s["name"],
                "template_type": s["template_type"],
                "model": s["model"],
                "hierarchy_role": s["hierarchy_role"],
                "is_root": bool(s.get("is_root_staff")),
            }
            for s in STAFF_TEAM_SPEC
        ],
        "rules": {
            "server_monitor": "Highest Grok (grok-max → xAI)",
            "staff_orchestrator": "Day-to-day admin issues (Qwen quality on RunPod)",
            "others": "Qwen fast/quality or DeepSeek reasoning on RunPod",
        },
    }


# ─── Token / wallet control ─────────────────────────────────────────────────

class TopUpIn(BaseModel):
    user_id: int
    amount_usd: float = Field(..., gt=0, le=100_000)
    note: str = ""


@router.post("/wallet/topup")
def wallet_topup(data: TopUpIn, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Add wallet credits so a customer can keep using agents."""
    user = db.get(models.User, data.user_id)
    if not user:
        raise HTTPException(404, "user not found")
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal:
        bal = models.Balance(user_id=user.id, credits=0.0)
        db.add(bal)
        db.commit()
        db.refresh(bal)
    bal.credits = round((bal.credits or 0.0) + float(data.amount_usd), 4)
    db.commit()
    return {
        "ok": True,
        "user_id": user.id,
        "email": user.email,
        "credits": round(bal.credits, 4),
        "added": data.amount_usd,
        "note": data.note,
    }


class AdjustIncludedIn(BaseModel):
    user_id: int
    tokens_included: int = Field(..., ge=0)


@router.post("/wallet/set-included")
def set_included(data: AdjustIncludedIn, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Set monthly included token pool for a customer (on-demand supply)."""
    user = db.get(models.User, data.user_id)
    if not user:
        raise HTTPException(404, "user not found")
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal:
        bal = models.Balance(user_id=user.id, credits=0.0)
        db.add(bal)
        db.commit()
        db.refresh(bal)
    if hasattr(bal, "tokens_included"):
        bal.tokens_included = int(data.tokens_included)
    db.commit()
    return {
        "ok": True,
        "user_id": user.id,
        "tokens_included": getattr(bal, "tokens_included", data.tokens_included),
    }


@router.get("/usage/recent")
def usage_recent(limit: int = 100, db: Session = Depends(get_db), admin=Depends(require_admin)):
    rows = (
        db.query(models.TokenUsage)
        .order_by(models.TokenUsage.id.desc())
        .limit(min(limit, 500))
        .all()
    )
    out = []
    for r in rows:
        u = db.get(models.User, r.user_id)
        out.append({
            "id": r.id,
            "user": u.email if u else r.user_id,
            "model": r.model,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cost": r.cost,
            "created_at": getattr(r, "created_at", None),
        })
    return out


@router.get("/usage/by-model")
def usage_by_model(db: Session = Depends(get_db), admin=Depends(require_admin)):
    rows = db.query(models.TokenUsage).all()
    agg: dict[str, dict] = {}
    for r in rows:
        m = r.model or "unknown"
        if m not in agg:
            agg[m] = {"model": m, "tokens": 0, "cost": 0.0, "calls": 0}
        agg[m]["tokens"] += (r.input_tokens or 0) + (r.output_tokens or 0)
        agg[m]["cost"] += r.cost or 0
        agg[m]["calls"] += 1
    for v in agg.values():
        v["cost"] = round(v["cost"], 4)
    return sorted(agg.values(), key=lambda x: -x["tokens"])
