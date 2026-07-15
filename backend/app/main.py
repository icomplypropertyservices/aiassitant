import asyncio
import json
import random
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine, SessionLocal
from . import models, config
from .auth_utils import hash_password, get_current_user
from .ws import manager
from .routers import auth, templates, agents, chat, billing, dashboard, admin, org, keys
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
        admin = db.query(models.User).filter_by(email="admin@local").first()
        if not admin:
            u = models.User(
                email="admin@local", name="Staff Admin",
                password_hash=hash_password("admin123"), role="admin",
                plan="business", subscription_active=True,
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
        else:
            # Ensure legacy admin can use the app without re-subscribing
            if admin.role == "admin":
                admin.subscription_active = True
                admin.plan = "business"
                bal = db.query(models.Balance).filter_by(user_id=admin.id).first()
                if bal:
                    bal.tokens_included = 40_000_000
                if db.query(models.Company).filter_by(owner_user_id=admin.id).count() == 0:
                    db.add(models.Company(owner_user_id=admin.id, name="Demo Company", industry="Technology"))
                db.commit()
            # Backfill subscription flags / balance for existing users
            from .plans import plan_limits
            for u in db.query(models.User).all():
                bal = db.query(models.Balance).filter_by(user_id=u.id).first()
                if not bal:
                    bal = models.Balance(user_id=u.id, credits=5.0)
                    db.add(bal)
                    db.flush()
                if u.plan and u.plan not in ("none", ""):
                    u.subscription_active = True
                    lim = plan_limits(u.plan)
                    if not bal.tokens_included:
                        bal.tokens_included = int(lim.get("tokens_included") or 0)
                # Legacy free-credit users without plan → treat as pay_as_you_go
                if u.plan in ("pay_as_you_go",) or (u.role != "admin" and not u.plan):
                    if not u.plan or u.plan == "":
                        u.plan = "pay_as_you_go"
                    u.subscription_active = True
            db.commit()
    finally:
        db.close()


async def orchestrator():
    """Never-be-idle logic: active never_idle agents get work assigned automatically."""
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
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"[startup] create_all failed: {e}")
    # Light migrations for existing SQLite DBs
    try:
        db_url = str(engine.url)
        if db_url.startswith("sqlite"):
            with engine.begin() as conn:
                def cols(table):
                    return [r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()]

                def add(table, col, decl):
                    if col not in cols(table):
                        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

                if "tasks" in [r[0] for r in conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()]:
                    add("tasks", "result", "TEXT DEFAULT ''")
                    add("tasks", "completed_at", "DATETIME")
                    add("tasks", "project_id", "INTEGER")
                    add("tasks", "company_id", "INTEGER")
                    add("tasks", "title", "TEXT DEFAULT ''")
                    add("tasks", "tokens_used", "INTEGER DEFAULT 0")
                    add("tasks", "cost", "FLOAT DEFAULT 0")
                    add("tasks", "priority", "TEXT DEFAULT 'medium'")
                    add("tasks", "labels", "TEXT DEFAULT ''")
                    add("tasks", "updated_at", "DATETIME")
                add("users", "subscription_active", "BOOLEAN DEFAULT 0")
                add("balances", "tokens_included", "INTEGER DEFAULT 0")
                add("balances", "tokens_used_period", "INTEGER DEFAULT 0")
                add("balances", "period_start", "DATETIME")
                add("agents", "company_id", "INTEGER")
                add("agents", "project_id", "INTEGER")
                add("agents", "parent_id", "INTEGER")
                add("agents", "hierarchy_role", "TEXT DEFAULT 'member'")
                add("agents", "is_lead", "BOOLEAN DEFAULT 0")
                add("token_usage", "company_id", "INTEGER")
                add("token_usage", "project_id", "INTEGER")
                add("token_usage", "bill_source", "TEXT DEFAULT 'included'")
                add("conversations", "project_id", "INTEGER")
    except Exception as e:
        print(f"[startup] migrations failed: {e}")
    try:
        seed_db()
    except Exception as e:
        print(f"[startup] seed_db failed: {e}")
    # Background idle loop is not useful on Vercel serverless cold starts
    from .async_jobs import is_serverless
    orch_task = None
    if not is_serverless():
        orch_task = asyncio.create_task(orchestrator())
    yield
    if orch_task:
        orch_task.cancel()
        try:
            await orch_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="AI Business Assistant API",
    version="1.4.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS if config.CORS_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (
    auth.router, templates.router, agents.router, chat.router,
    billing.router, dashboard.router, admin.router, org.router, keys.router,
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
    }


@app.get("/system/status")
def system_status(user=Depends(get_current_user)):
    """Authenticated: which integrations are live vs dev fallback."""
    return config.integration_status()


@app.get("/system/models")
def system_models():
    """Full model catalog for every picker (public — needed on login screens too)."""
    from .pricing import MODEL_CATALOG, PRICING, MODEL_GROUPS
    status = config.integration_status()["llm"]
    out = []
    for m in MODEL_CATALOG:
        live = True
        if m["provider"] == "anthropic":
            live = bool(status.get("anthropic"))
        elif m["provider"] == "xai":
            live = bool(status.get("xai"))
        out.append({
            **m,
            "rate_per_1m": PRICING.get(m["id"], 0.80),
            "configured": live if m["provider"] != "ollama" else True,
            "value": m["id"],  # ant Select option shape
        })
    return {
        "models": out,
        "groups": [{"id": g, "label": lab} for g, lab in MODEL_GROUPS],
        "count": len(out),
    }
