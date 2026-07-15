import os
import secrets
from pathlib import Path

# Load .env sitting next to the backend folder (no external dep needed).
# Non-empty .env values win over empty process env so local keys always apply.
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if not k:
                continue
            if v or k not in os.environ or not os.environ.get(k):
                os.environ[k] = v

APP_ENV = os.getenv("APP_ENV", "development").lower()  # development | production
IS_PRODUCTION = APP_ENV == "production"

_jwt = os.getenv("JWT_SECRET", "").strip()
if not _jwt or _jwt in ("generate-a-long-random-string", "change-me-in-production"):
    if IS_PRODUCTION:
        raise RuntimeError(
            "JWT_SECRET must be set to a long random string in production "
            "(at least 32 characters). Set it in backend/.env"
        )
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
            "stripe_webhook": bool(STRIPE_WEBHOOK_SECRET),
            "price_starter": bool(STRIPE_PRICE_STARTER),
            "price_pro": bool(STRIPE_PRICE_PRO),
            "price_business": bool(STRIPE_PRICE_BUSINESS),
        },
        "channels": {
            "email_resend": bool(RESEND_API_KEY),
            "resend_from": RESEND_FROM if RESEND_API_KEY else None,
            "sms_twilio": twilio_ok,
            "voice_twilio": twilio_ok,
        },
        "database": {
            "driver": "postgresql" if DATABASE_URL.startswith("postgres") else "sqlite",
            "configured": True,
        },
    }
