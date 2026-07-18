import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Load local .env if present
_env = BASE_DIR / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and (os.environ.get(k) is None or str(os.environ.get(k)).strip() == ""):
                os.environ[k] = v

# production | staging  (no demo mode)
APP_ENV = (os.getenv("APP_ENV") or "production").strip().lower()
IS_PRODUCTION = APP_ENV in ("production", "prod", "live")

# Prefer dedicated marketplace DB; bay_* tables can also live on shared Postgres
DB_PATH = os.getenv("MARKETPLACE_DB", str(BASE_DIR / "marketplace.db"))
DATABASE_URL = (
    os.getenv("AGENTBAY_DATABASE_URL")
    or os.getenv("MARKETPLACE_DATABASE_URL")
    or os.getenv("DATABASE_URL")
    or f"sqlite:///{DB_PATH}"
)

_raw_jwt = (os.getenv("JWT_SECRET") or "").strip()
_WEAK_JWT = {"", "dev-marketplace-secret-change-me", "change-me", "secret", "changeme"}
if _raw_jwt in _WEAK_JWT:
    if IS_PRODUCTION:
        JWT_SECRET = ""  # invalid until set — auth will fail closed
    else:
        JWT_SECRET = secrets.token_hex(32)
        print("[config] JWT_SECRET not set — using ephemeral secret (sessions reset on restart)")
else:
    JWT_SECRET = _raw_jwt

JWT_ALG = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "168"))

# Default production domain: aibusinessagent.xyz (path prefixes /bay + /bay/api)
_DEFAULT_CORS = (
    "https://aibusinessagent.xyz,https://www.aibusinessagent.xyz"
    if IS_PRODUCTION
    else "http://localhost:5173,http://127.0.0.1:5173"
)
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", _DEFAULT_CORS).split(",")
    if o.strip()
]

APP_NAME = "AgentBay Marketplace"
APP_VERSION = "1.2.0"

_DEFAULT_APP = (
    "https://aibusinessagent.xyz/bay"
    if IS_PRODUCTION
    else "http://127.0.0.1:5173"
)
_DEFAULT_API = (
    "https://aibusinessagent.xyz/bay/api"
    if IS_PRODUCTION
    else "http://127.0.0.1:8000"
)
PUBLIC_APP_URL = os.getenv("PUBLIC_APP_URL", _DEFAULT_APP).rstrip("/")
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", _DEFAULT_API).rstrip("/")

# Stripe required for all purchases (no free/demo checkout)
STRIPE_SECRET_KEY = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
STRIPE_WEBHOOK_SECRET = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()
STRIPE_CURRENCY = (os.getenv("STRIPE_CURRENCY") or "usd").lower()

# Bridge secret for ABA → AgentBay (must be set for bridge)
BRIDGE_SECRET = (os.getenv("BRIDGE_SECRET") or "").strip()
_WEAK_BRIDGE = {"", "dev-bridge-secret-change-me", "change-me", "changeme"}

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
UPLOAD_MAX_MB = int(os.getenv("UPLOAD_MAX_MB", "8"))
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def stripe_enabled() -> bool:
    return bool(STRIPE_SECRET_KEY) and STRIPE_SECRET_KEY.startswith(("sk_test", "sk_live"))


def stripe_live() -> bool:
    return bool(STRIPE_SECRET_KEY) and STRIPE_SECRET_KEY.startswith("sk_live")


def bridge_configured() -> bool:
    return BRIDGE_SECRET not in _WEAK_BRIDGE


def config_issues() -> list[str]:
    """Production readiness issues (non-empty = not fully ready)."""
    issues: list[str] = []
    if not JWT_SECRET or JWT_SECRET in _WEAK_JWT:
        issues.append("JWT_SECRET missing or weak — set a long random secret")
    if not stripe_enabled():
        issues.append("STRIPE_SECRET_KEY missing — purchases disabled until set")
    if IS_PRODUCTION and stripe_enabled() and not stripe_live():
        issues.append("Production requires STRIPE_SECRET_KEY=sk_live_… (not sk_test)")
    if not STRIPE_WEBHOOK_SECRET:
        issues.append("STRIPE_WEBHOOK_SECRET missing — webhooks will reject")
    if not bridge_configured():
        issues.append("BRIDGE_SECRET missing or weak — agent bridge disabled")
    if IS_PRODUCTION and ("127.0.0.1" in PUBLIC_APP_URL or "localhost" in PUBLIC_APP_URL):
        issues.append("PUBLIC_APP_URL should be public HTTPS in production")
    return issues


def require_payments():
    from fastapi import HTTPException

    if not stripe_enabled():
        raise HTTPException(
            503,
            "Payments not configured. Set STRIPE_SECRET_KEY (and webhook secret) to enable checkout.",
        )
    if IS_PRODUCTION and not stripe_live():
        raise HTTPException(
            503,
            "Production requires live Stripe keys (sk_live_…).",
        )
