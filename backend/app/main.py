import asyncio
import json
import os
import random
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine, SessionLocal
from . import models, config
from .auth_utils import hash_password, get_current_user
from .ws import manager
from .routers import (
    auth, templates, agents, chat, billing, dashboard, admin, org, keys,
    integrations, training, humans, ops, business, devices, marketplace,
)
from .seed_templates import SEED_TEMPLATES, NOTIFY_FIELDS

IDLE_WORK = [
    ("thinking", "Scanning inbox for new enquiries"),
    ("action", "Refreshing lead list and prioritising follow-ups"),
    ("thinking", "Reviewing yesterday's conversations for missed actions"),
    ("action", "Drafting follow-up messages for pending contacts"),
    ("email", "Queued a scheduled follow-up email"),
    ("thinking", "Checking open tasks and prioritising by impact"),
    ("action", "Drafting code review notes for pending PRs"),
    ("thinking", "Scanning logs for recurring errors"),
]


def seed_db():
    db = SessionLocal()
    try:
        # Upsert templates by name so new catalog entries appear on restart
        existing = {t.name: t for t in db.query(models.AgentTemplate).all()}
        for name, type_, desc, fields, cost in SEED_TEMPLATES:
            full_fields = fields + list(NOTIFY_FIELDS)
            payload = {
                "type": type_,
                "description": desc,
                "unique_fields": json.dumps(full_fields),
                "est_cost": cost,
            }
            if name in existing:
                t = existing[name]
                for k, v in payload.items():
                    setattr(t, k, v)
            else:
                db.add(models.AgentTemplate(name=name, **payload))
        db.commit()
        # Never seed weak demo admin in production
        allow_demo = not config.IS_PRODUCTION and os.getenv("SEED_DEMO_ADMIN", "1") not in ("0", "false", "no")
        admin = db.query(models.User).filter_by(email="admin@local").first()
        if allow_demo and not admin:
            u = models.User(
                email="admin@local", name="Staff Admin",
                password_hash=hash_password("admin123"), role="admin",
                plan="business", subscription_active=True,
                email_verified=True,
            )
            db.add(u)
            db.commit()
            db.refresh(u)
            db.add(models.Balance(
                user_id=u.id, credits=100.0,
                tokens_included=40_000_000, tokens_used_period=0,
            ))
            db.add(models.Company(owner_user_id=u.id, name="Demo Company", industry="Technology"))
            db.commit()
        elif admin and not config.IS_PRODUCTION:
            # Dev only: keep legacy admin usable
            if admin.role == "admin":
                admin.subscription_active = True
                admin.plan = "business"
                admin.email_verified = True
                bal = db.query(models.Balance).filter_by(user_id=admin.id).first()
                if bal:
                    bal.tokens_included = 40_000_000
                if db.query(models.Company).filter_by(owner_user_id=admin.id).count() == 0:
                    db.add(models.Company(owner_user_id=admin.id, name="Demo Company", industry="Technology"))
                db.commit()
        # Admins are always treated as verified (staff accounts)
        for admin_u in db.query(models.User).filter_by(role="admin").all():
            if not getattr(admin_u, "email_verified", False):
                admin_u.email_verified = True
        # Backfill balances only (do not auto-activate paid plans in production)
        from .plans import plan_limits
        for u in db.query(models.User).all():
            bal = db.query(models.Balance).filter_by(user_id=u.id).first()
            if not bal:
                bal = models.Balance(user_id=u.id, credits=0.0 if config.IS_PRODUCTION else 5.0)
                db.add(bal)
                db.flush()
            if config.IS_PRODUCTION:
                continue  # never mass-activate subscriptions in production
            if u.plan and u.plan not in ("none", ""):
                u.subscription_active = True
                lim = plan_limits(u.plan)
                if not bal.tokens_included:
                    bal.tokens_included = int(lim.get("tokens_included") or 0)
            if u.plan in ("pay_as_you_go",) or (u.role != "admin" and not u.plan):
                if not u.plan or u.plan == "":
                    u.plan = "pay_as_you_go"
                u.subscription_active = True
        db.commit()
    finally:
        db.close()


async def idle_activity_loop():
    """Never-be-idle logic: active never_idle agents get cosmetic activity ticks."""
    while True:
        await asyncio.sleep(30)
        db = SessionLocal()
        try:
            busy = db.query(models.Agent).filter_by(status="active", idle_mode="never_idle").all()
            for a in busy:
                type_, msg = random.choice(IDLE_WORK)
                log = models.ActivityLog(agent_id=a.id, type=type_, message=msg)
                db.add(log)
                db.commit()
                await manager.broadcast(f"agents:{a.user_id}", {
                    "event": "activity", "agent_id": a.id,
                    "entry": {"id": log.id, "type": type_, "message": msg, "created_at": log.created_at},
                })
        except Exception:
            pass
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Never let startup kill the whole serverless function hard
    try:
        from .schema_migrate import ensure_schema
        report = ensure_schema(engine)
        if report.get("added"):
            print(f"[startup] schema columns added: {report['added']}")
        if report.get("errors"):
            print(f"[startup] schema warnings: {report['errors']}")
    except Exception as e:
        print(f"[startup] ensure_schema failed: {e}")
        try:
            Base.metadata.create_all(bind=engine)
        except Exception as e2:
            print(f"[startup] create_all failed: {e2}")
    try:
        seed_db()
    except Exception as e:
        print(f"[startup] seed_db failed: {e}")
    # Background loops: cosmetic idle ticks + full autonomy engine (local only)
    from .async_jobs import is_serverless
    from .autonomy import autonomy_background_loop
    orch_task = None
    autonomy_task = None
    if not is_serverless():
        orch_task = asyncio.create_task(idle_activity_loop())
        autonomy_task = asyncio.create_task(autonomy_background_loop())
    yield
    for t in (orch_task, autonomy_task):
        if not t:
            continue
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="AI Business Assistant API",
    version="1.4.0",
    lifespan=lifespan,
    docs_url=None if config.IS_PRODUCTION else "/docs",
    redoc_url=None if config.IS_PRODUCTION else "/redoc",
    openapi_url=None if config.IS_PRODUCTION else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS if config.CORS_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
from .routers import media as media_router
from .routers import permissions_api as permissions_router
for r in (
    auth.router, templates.router, agents.router, chat.router,
    billing.router, dashboard.router, admin.router, org.router, keys.router,
    integrations.router, training.router, humans.router, ops.router, business.router,
    media_router.router, permissions_router.router, devices.router, marketplace.router,
):
    app.include_router(r)


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "ai-business-assistant",
        "version": "1.4.0",
        "environment": config.APP_ENV,
        "serverless": bool(__import__("os").getenv("VERCEL")),
        # Non-secret readiness flags (no secret values)
        "billing_free_grants": False if config.IS_PRODUCTION else True,
        "docs_enabled": not config.IS_PRODUCTION,
        "cron_secret_configured": bool(config.CRON_SECRET),
        "path_frontend_hint": config.FRONTEND_URL,
    }


@app.get("/system/status")
def system_status(user=Depends(get_current_user)):
    """Authenticated: which integrations are live vs dev fallback.
    Internal details (which exact token or session is used for Grok) are not exposed to clients.
    """
    st = config.integration_status()
    # Remove any internal auth source details before returning to clients
    llm = st.get("llm", {})
    llm.pop("grok_auth_source", None)
    llm.pop("xai_via_super_session", None)
    llm.pop("xai_auth_source", None)
    llm.pop("using_super_session", None)
    # Only expose high-level "is configured" booleans
    return st


@app.get("/system/models")
def system_models():
    """
    Returns ONLY neutral model names to clients.
    Never exposes RunPod, Grok, Claude, Ollama, etc.
    """
    from .pricing import MODEL_CATALOG, PRICING

    out = []
    for m in MODEL_CATALOG:
        out.append({
            "id": m["id"],
            "value": m["id"],
            "label": m["label"],
            "group": m.get("group", "managed"),
            "group_label": m.get("group_label", "Managed"),
            "provider": "managed",           # always hide the real provider
            "rate_per_1m": PRICING.get(m["id"], 2.0),
            "configured": True,
        })

    return {
        "models": out,
        "groups": [{"id": "managed", "label": "Managed"}],
        "count": len(out),
    }
