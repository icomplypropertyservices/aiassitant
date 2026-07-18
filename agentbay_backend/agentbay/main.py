from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import APP_NAME, APP_VERSION, CORS_ORIGINS, UPLOAD_DIR, config_issues, IS_PRODUCTION, APP_ENV
from .database import init_db
from .schema_migrate import migrate
from .seed import seed
from .routers import auth, listings, orders, chat, catalog, media, bridge


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    migrate()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    issues = config_issues()
    if issues:
        print(f"[startup] APP_ENV={APP_ENV} — configuration issues:")
        for i in issues:
            print(f"  - {i}")
    else:
        print(f"[startup] APP_ENV={APP_ENV} — production config OK")
    try:
        seed()
    except Exception as e:
        print(f"[startup] seed warning: {e}")
    yield


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)

# In production, do not blanket-allow all origins
_cors = CORS_ORIGINS if IS_PRODUCTION else list(set(CORS_ORIGINS + ["*"]))
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(listings.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")
app.include_router(media.router, prefix="/api")
app.include_router(bridge.router, prefix="/api")

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.get("/api/health")
def health():
    from . import config

    issues = config.config_issues()
    return {
        "ok": True,
        "app": APP_NAME,
        "version": APP_VERSION,
        "env": config.APP_ENV,
        "production": config.IS_PRODUCTION,
        "stripe": config.stripe_enabled(),
        "stripe_live": config.stripe_live(),
        "bridge": config.bridge_configured(),
        "demo": False,
        "ready": len(issues) == 0,
        "issues": issues,
    }
