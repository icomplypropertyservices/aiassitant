import hashlib
import os
import secrets
from pathlib import Path

# Load .env sitting next to the backend folder (no external dep needed).
# Process / platform env (Vercel) always wins — only fill missing or empty keys.
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if not k:
                continue
            existing = os.environ.get(k)
            if existing is None or str(existing).strip() == "":
                os.environ[k] = v

# Prefer explicit APP_ENV; on Vercel production deploys default to production.
_raw_env = (os.getenv("APP_ENV") or "").strip().lower()
if not _raw_env and (os.getenv("VERCEL_ENV") or "").lower() == "production":
    _raw_env = "production"
APP_ENV = _raw_env or "development"  # development | production
IS_PRODUCTION = APP_ENV == "production"
# Vercel sets VERCEL=1
IS_VERCEL = bool(os.getenv("VERCEL") or os.getenv("VERCEL_ENV"))

_jwt = os.getenv("JWT_SECRET", "").strip()
_WEAK_JWT = ("", "generate-a-long-random-string", "change-me-in-production", "change-me")
if not _jwt or _jwt in _WEAK_JWT or len(_jwt) < 32:
    if IS_PRODUCTION:
        # Production (including Vercel) must set an explicit long secret — no commit-hash fallback.
        raise RuntimeError(
            "JWT_SECRET must be set in production to a random string ≥32 characters. "
            "Set it in Vercel Environment Variables or backend/.env "
            "(e.g. openssl rand -hex 32)."
        )
    # Development only: ephemeral secret (sessions reset on restart if not in .env)
    if IS_VERCEL:
        # Preview without production flag — still prefer env, else deploy-stable derive
        seed = os.getenv("VERCEL_GIT_COMMIT_SHA") or os.getenv("VERCEL_URL") or "vercel-dev"
        JWT_SECRET = "vercel-dev-" + hashlib.sha256(seed.encode()).hexdigest()
    else:
        JWT_SECRET = secrets.token_hex(32)
else:
    JWT_SECRET = _jwt

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
XAI_MODEL_FAST = os.getenv("XAI_MODEL_FAST", "grok-3-mini")
XAI_MODEL_QUALITY = os.getenv("XAI_MODEL_QUALITY", "grok-3")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL_FAST = os.getenv("OLLAMA_MODEL_FAST", "llama3.2")
OLLAMA_MODEL_QUALITY = os.getenv("OLLAMA_MODEL_QUALITY", "llama3.1:8b")
# Qwen fleet on VPS — set these to whatever you `ollama pull` on the box
OLLAMA_MODEL_QWEN_FAST = os.getenv("OLLAMA_MODEL_QWEN_FAST", "qwen2.5:7b")
OLLAMA_MODEL_QWEN_7B = os.getenv("OLLAMA_MODEL_QWEN_7B", "qwen2.5:7b")
OLLAMA_MODEL_QWEN_14B = os.getenv("OLLAMA_MODEL_QWEN_14B", "qwen2.5:14b")
OLLAMA_MODEL_QWEN_32B = os.getenv("OLLAMA_MODEL_QWEN_32B", "qwen2.5:32b")
OLLAMA_MODEL_QWEN_CODER = os.getenv("OLLAMA_MODEL_QWEN_CODER", "qwen2.5-coder:32b")
OLLAMA_MODEL_QWEN_CODER_7B = os.getenv("OLLAMA_MODEL_QWEN_CODER_7B", "qwen2.5-coder:7b")
OLLAMA_MODEL_QWEN_CODER_14B = os.getenv("OLLAMA_MODEL_QWEN_CODER_14B", "qwen2.5-coder:14b")
OLLAMA_MODEL_QWEN_CODER_32B = os.getenv("OLLAMA_MODEL_QWEN_CODER_32B", "qwen2.5-coder:32b")
OLLAMA_MODEL_QWEN_LARGE = os.getenv("OLLAMA_MODEL_QWEN_LARGE", "qwen2.5:72b")
OLLAMA_MODEL_QWEN_72B = os.getenv("OLLAMA_MODEL_QWEN_72B", "qwen2.5:72b")
# xAI API model names (override if xAI renames)
XAI_MODEL_GROK2 = os.getenv("XAI_MODEL_GROK2", "grok-2")
XAI_MODEL_GROK3 = os.getenv("XAI_MODEL_GROK3", "grok-3")
XAI_MODEL_GROK4 = os.getenv("XAI_MODEL_GROK4", "grok-4")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_STARTER = os.getenv("STRIPE_PRICE_STARTER", "")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_BUSINESS = os.getenv("STRIPE_PRICE_BUSINESS", "")

# Crypto payments (self-custody receive addresses — never put private keys here)
CRYPTO_ETH_ADDRESS = os.getenv("CRYPTO_ETH_ADDRESS", "").strip()
CRYPTO_SOL_ADDRESS = os.getenv("CRYPTO_SOL_ADDRESS", "").strip()
CRYPTO_XRP_ADDRESS = os.getenv("CRYPTO_XRP_ADDRESS", "").strip()
# Optional public RPC overrides
CRYPTO_ETH_RPC = os.getenv("CRYPTO_ETH_RPC", "https://ethereum.publicnode.com").strip()
CRYPTO_SOL_RPC = os.getenv("CRYPTO_SOL_RPC", "https://api.mainnet-beta.solana.com").strip()
CRYPTO_XRP_RPC = os.getenv("CRYPTO_XRP_RPC", "https://xrplcluster.com").strip()
# Invoice lifetime minutes
CRYPTO_INVOICE_TTL_MIN = int(os.getenv("CRYPTO_INVOICE_TTL_MIN", "60") or "60")

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM = os.getenv("RESEND_FROM", "assistant@yourdomain.com")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")

# Minimum credits required to run LLM-backed actions
MIN_CREDITS = float(os.getenv("MIN_CREDITS", "0.001"))
# Optional dedicated key for encrypting subscriber API keys (Fernet or any long secret).
# If empty, derived from JWT_SECRET. Changing it invalidates stored keys.
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "").strip()


def integration_status() -> dict:
    """Which third-party services are configured (not a live ping)."""
    twilio_ok = bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER)
    oauth_apps = {
        "shopify": bool(os.getenv("SHOPIFY_CLIENT_ID") and os.getenv("SHOPIFY_CLIENT_SECRET")),
        "google": bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID") and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")),
        "slack": bool(os.getenv("SLACK_CLIENT_ID") and os.getenv("SLACK_CLIENT_SECRET")),
        "hubspot": bool(os.getenv("HUBSPOT_CLIENT_ID") and os.getenv("HUBSPOT_CLIENT_SECRET")),
        "notion": bool(os.getenv("NOTION_CLIENT_ID") and os.getenv("NOTION_CLIENT_SECRET")),
    }
    return {
        "environment": APP_ENV,
        "llm": {
            "anthropic": bool(ANTHROPIC_API_KEY),
            "xai": bool(XAI_API_KEY),
            "xai_models": {
                "fast": XAI_MODEL_FAST,
                "quality": XAI_MODEL_QUALITY,
            },
            "ollama_url": OLLAMA_URL,
            "ollama_models": {
                "fast": OLLAMA_MODEL_FAST,
                "quality": OLLAMA_MODEL_QUALITY,
                "qwen_fast": OLLAMA_MODEL_QWEN_FAST,
                "qwen_7b": OLLAMA_MODEL_QWEN_7B,
                "qwen_14b": OLLAMA_MODEL_QWEN_14B,
                "qwen_32b": OLLAMA_MODEL_QWEN_32B,
                "qwen_coder": OLLAMA_MODEL_QWEN_CODER,
                "qwen_coder_7b": OLLAMA_MODEL_QWEN_CODER_7B,
                "qwen_coder_14b": OLLAMA_MODEL_QWEN_CODER_14B,
                "qwen_coder_32b": OLLAMA_MODEL_QWEN_CODER_32B,
                "qwen_large": OLLAMA_MODEL_QWEN_LARGE,
                "qwen_72b": OLLAMA_MODEL_QWEN_72B,
            },
            "fallback": (
                "claude/xai → ollama → mock"
                if (ANTHROPIC_API_KEY or XAI_API_KEY)
                else "ollama → mock"
            ),
        },
        "billing": {
            "stripe": bool(STRIPE_SECRET_KEY),
            "stripe_mode": (
                "test" if (STRIPE_SECRET_KEY or "").startswith("sk_test")
                else ("live" if (STRIPE_SECRET_KEY or "").startswith("sk_live") else None)
            ),
            "stripe_sandbox": (STRIPE_SECRET_KEY or "").startswith("sk_test"),
            "stripe_webhook": bool(STRIPE_WEBHOOK_SECRET),
            "price_starter": bool(STRIPE_PRICE_STARTER),
            "price_pro": bool(STRIPE_PRICE_PRO),
            "price_business": bool(STRIPE_PRICE_BUSINESS),
            "crypto": bool(CRYPTO_ETH_ADDRESS or CRYPTO_SOL_ADDRESS or CRYPTO_XRP_ADDRESS),
            "crypto_chains": {
                "eth": bool(CRYPTO_ETH_ADDRESS),
                "sol": bool(CRYPTO_SOL_ADDRESS),
                "xrp": bool(CRYPTO_XRP_ADDRESS),
            },
        },
        "channels": {
            "email_resend": bool(RESEND_API_KEY),
            "resend_from": RESEND_FROM if RESEND_API_KEY else None,
            "sms_twilio": twilio_ok,
            "voice_twilio": twilio_ok,
        },
        "oauth": oauth_apps,
        "database": {
            "driver": "postgresql" if DATABASE_URL.startswith("postgres") else "sqlite",
            "configured": True,
        },
    }
