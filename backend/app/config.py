import hashlib
import json
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


def _jwt_from_env() -> str | None:
    """JWT from env (for Vercel / servers that cannot read ~/.grok/auth.json)."""
    for k in ("GROK_SESSION_TOKEN", "GROK_JWT", "MANAGED_BACKEND_TOKEN", "XAI_JWT"):
        v = (os.getenv(k) or "").strip()
        if v.startswith("eyJ"):
            return v
    return None


def _load_jwt_from_auth_json() -> str | None:
    """
    INTERNAL ONLY — Grok Super / CLI OIDC session JWT from ~/.grok/auth.json.
    Reloaded on each call so login refreshes are picked up. Never returned to clients.
    """
    candidates = []
    explicit = os.getenv("MANAGED_BACKEND_TOKEN_PATH", "").strip()
    if explicit:
        candidates.append(Path(explicit))
    try:
        candidates.append(Path.home() / ".grok" / "auth.json")
    except Exception:
        pass
    if os.name == "nt":
        up = os.getenv("USERPROFILE")
        if up:
            candidates.append(Path(up) / ".grok" / "auth.json")
        la = os.getenv("LOCALAPPDATA")
        if la:
            candidates.append(Path(la) / "grok" / "auth.json")

    for p in candidates:
        try:
            if not p or not p.exists():
                continue
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            # Prefer most recently expiring / any valid JWT under OIDC entries
            best = None
            for entry in data.values():
                if not isinstance(entry, dict):
                    continue
                tok = entry.get("key") or entry.get("token") or entry.get("access_token")
                if tok and isinstance(tok, str) and tok.startswith("eyJ"):
                    best = tok
                    # Prefer auth_mode oidc / entries with refresh_token
                    if entry.get("auth_mode") == "oidc" or entry.get("refresh_token"):
                        return tok
            if best:
                return best
            tok = data.get("key") or data.get("token") or data.get("access_token")
            if tok and isinstance(tok, str) and tok.startswith("eyJ"):
                return tok
        except Exception:
            continue
    return None


def _load_managed_backend_token() -> str | None:
    """JWT only: env first (deploy), then ~/.grok/auth.json (local Super)."""
    return _jwt_from_env() or _load_jwt_from_auth_json()

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

def _env_str(name: str, default: str = "") -> str:
    """Read env; treat blank / whitespace-only as unset (Vercel empty secrets break OAuth)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    val = str(raw).strip()
    return val if val else default


# Product UI path on aibusinessagent.xyz is /agents (not a subdomain).
# Stripe success/cancel URLs are built from FRONTEND_URL.
FRONTEND_URL = _env_str(
    "FRONTEND_URL",
    "http://localhost:5173" if not IS_PRODUCTION else "https://www.aibusinessagent.xyz/agents",
).rstrip("/")
# Prefer www on production so email/SMS/OAuth links don't bounce apex redirects
if IS_PRODUCTION and "aibusinessagent.xyz" in FRONTEND_URL and "www." not in FRONTEND_URL:
    FRONTEND_URL = FRONTEND_URL.replace("://aibusinessagent.xyz", "://www.aibusinessagent.xyz")
_default_cors = (
    "https://aibusinessagent.xyz,https://www.aibusinessagent.xyz"
    if IS_PRODUCTION
    else "*"
)
CORS_ORIGINS = [o.strip() for o in _env_str("CORS_ORIGINS", _default_cors).split(",") if o.strip()]
DATABASE_URL = _env_str("DATABASE_URL", "sqlite:///./app.db")
# AgentBay marketplace (same domain path /bay)
AGENTBAY_PUBLIC_URL = _env_str("AGENTBAY_PUBLIC_URL", "https://www.aibusinessagent.xyz/bay").rstrip("/")

# Canonical production OAuth callback (Google redirect_uri_mismatch if wrong host/path).
# Must match Google Cloud Console → Credentials → Web client → Authorized redirect URIs
# EXACTLY (https, no trailing slash). Prefer www to match FRONTEND_URL.
PROD_OAUTH_REDIRECT_URI = "https://www.aibusinessagent.xyz/api/integrations/oauth/callback"
PROD_OAUTH_REDIRECT_URI_APEX = "https://aibusinessagent.xyz/api/integrations/oauth/callback"

# Public API origin (no trailing slash). Used for OAuth redirect_uri.
# Production path deploy: https://www.aibusinessagent.xyz/api
_api_public_env = _env_str("API_PUBLIC_URL").rstrip("/")
_oauth_redirect_env = _env_str("OAUTH_REDIRECT_URI")
if _api_public_env:
    API_PUBLIC_URL = _api_public_env
else:
    # Derive from FRONTEND_URL: strip /agents (or trailing SPA path) → {origin}/api
    _fu = FRONTEND_URL or ""
    if _fu.endswith("/agents"):
        API_PUBLIC_URL = _fu[: -len("/agents")] + "/api"
    elif _fu:
        from urllib.parse import urlparse as _urlparse
        _p = _urlparse(_fu)
        if _p.scheme and _p.netloc:
            API_PUBLIC_URL = f"{_p.scheme}://{_p.netloc}/api"
        else:
            API_PUBLIC_URL = ""
    else:
        API_PUBLIC_URL = (
            "http://localhost:8000" if not IS_PRODUCTION else "https://www.aibusinessagent.xyz/api"
        )

# Exact callback Google/Slack/etc. must redirect to.
# Production always pins to canonical www URI unless OAUTH_REDIRECT_URI is set non-empty.
if IS_PRODUCTION and "aibusinessagent.xyz" in (API_PUBLIC_URL + FRONTEND_URL + _oauth_redirect_env):
    OAUTH_REDIRECT_URI = _oauth_redirect_env or PROD_OAUTH_REDIRECT_URI
else:
    OAUTH_REDIRECT_URI = (
        _oauth_redirect_env
        or (f"{API_PUBLIC_URL}/integrations/oauth/callback" if API_PUBLIC_URL else "")
    )
# Normalize accidental trailing slash (Google treats as different URI)
OAUTH_REDIRECT_URI = (OAUTH_REDIRECT_URI or "").rstrip("/")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# === RunPod fleet: Ollama (Qwen + DeepSeek) + Open WebUI ===
# Clients only see: Fast / Quality / Reasoning / Large / Small / Medium.
# Admin maps those to real Ollama tags and monitors tokens.

RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "")
# Ollama HTTP base on the pod (RunPod proxy), e.g. https://xxx-11434.proxy.runpod.net
RUNPOD_OLLAMA_URL = os.getenv("RUNPOD_OLLAMA_URL", "").rstrip("/")
# Open WebUI for admin embed, e.g. https://xxx-8080.proxy.runpod.net
RUNPOD_WEBUI_URL = os.getenv("RUNPOD_WEBUI_URL", "").rstrip("/")
# Optional OpenAI-compatible base (vLLM serverless)
RUNPOD_OPENAI_BASE_URL = os.getenv("RUNPOD_OPENAI_BASE_URL", os.getenv("RUNPOD_BASE_URL", "")).rstrip("/")
RUNPOD_BASE_URL = RUNPOD_OPENAI_BASE_URL  # alias used by older llm paths

_DEFAULT_FLEET_MAP = {
    "fast": "qwen2.5:7b",
    "quality": "qwen2.5:14b",
    "reasoning": "deepseek-r1:14b",
    "large": "qwen2.5:32b",
    "small": "qwen2.5:3b",
    "medium": "qwen2.5:7b",
}
RUNPOD_MODEL_MAP = {
    k: os.getenv(f"RUNPOD_MODEL_{k.upper()}", os.getenv("RUNPOD_MODEL", _DEFAULT_FLEET_MAP[k]))
    for k in _DEFAULT_FLEET_MAP
}

RUNPOD_ENABLED = bool(RUNPOD_OLLAMA_URL or RUNPOD_OPENAI_BASE_URL)

# GPU protection (RunPod / Ollama) — keep VRAM and queue under control
try:
    OLLAMA_MAX_CONCURRENT = max(1, int(os.getenv("OLLAMA_MAX_CONCURRENT", "1") or "1"))
except ValueError:
    OLLAMA_MAX_CONCURRENT = 1
# How long Ollama keeps a model loaded after a request (shorter = freer VRAM)
OLLAMA_KEEP_ALIVE = (os.getenv("OLLAMA_KEEP_ALIVE") or "2m").strip() or "2m"
try:
    OLLAMA_NUM_PREDICT = max(64, int(os.getenv("OLLAMA_NUM_PREDICT", "1024") or "1024"))
except ValueError:
    OLLAMA_NUM_PREDICT = 1024
try:
    OLLAMA_NUM_CTX = max(512, int(os.getenv("OLLAMA_NUM_CTX", "4096") or "4096"))
except ValueError:
    OLLAMA_NUM_CTX = 4096
# Autonomy / background ticks (default 3 so multi-step chains drain faster per tick)
try:
    AUTONOMY_MAX_TASKS_PER_TICK = max(1, int(os.getenv("AUTONOMY_MAX_TASKS_PER_TICK", "3") or "3"))
except ValueError:
    AUTONOMY_MAX_TASKS_PER_TICK = 3
try:
    AUTONOMY_MAX_IDLE_FEEDS = max(0, int(os.getenv("AUTONOMY_MAX_IDLE_FEEDS", "1") or "1"))
except ValueError:
    AUTONOMY_MAX_IDLE_FEEDS = 1
try:
    AUTONOMY_MIN_INTERVAL_SEC = max(30, int(os.getenv("AUTONOMY_MIN_INTERVAL_SEC", "300") or "300"))
except ValueError:
    AUTONOMY_MIN_INTERVAL_SEC = 300
# Force background autonomy tasks onto a small/fast tier (saves VRAM)
AUTONOMY_MODEL = (os.getenv("AUTONOMY_MODEL") or "small").strip().lower() or "small"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")


def _managed_ollama_url() -> str:
    """RunPod first; localhost Ollama only outside production/Vercel."""
    if RUNPOD_OLLAMA_URL:
        return RUNPOD_OLLAMA_URL
    local = (OLLAMA_URL or "").rstrip("/")
    if not local:
        return ""
    loopback = any(h in local for h in ("127.0.0.1", "localhost", "0.0.0.0", "[::1]"))
    if loopback and (IS_PRODUCTION or IS_VERCEL):
        return ""
    return local


MANAGED_OLLAMA_URL = _managed_ollama_url()

# Internal only — JWT from Super/CLI (re-read live via get_grok_token; this is boot snapshot)
GROK_SESSION_TOKEN = _load_managed_backend_token() or ""
# Developer API key — used for platform xAI when XAI_USE_JWT_ONLY is false (prod default)
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")

# Local Ollama defaults (also used if RunPod URL points at Ollama)
OLLAMA_MODEL_FAST = os.getenv("OLLAMA_MODEL_FAST", "qwen2.5:7b")
OLLAMA_MODEL_QUALITY = os.getenv("OLLAMA_MODEL_QUALITY", "qwen2.5:14b")
OLLAMA_MODEL_QWEN_FAST = os.getenv("OLLAMA_MODEL_QWEN_FAST", "qwen2.5:3b")
OLLAMA_MODEL_QWEN_7B = os.getenv("OLLAMA_MODEL_QWEN_7B", "qwen2.5:7b")
OLLAMA_MODEL_QWEN_14B = os.getenv("OLLAMA_MODEL_QWEN_14B", "qwen2.5:14b")
OLLAMA_MODEL_QWEN_32B = os.getenv("OLLAMA_MODEL_QWEN_32B", "qwen2.5:32b")
OLLAMA_MODEL_QWEN_CODER = os.getenv("OLLAMA_MODEL_QWEN_CODER", "qwen2.5-coder:7b")
OLLAMA_MODEL_QWEN_CODER_7B = os.getenv("OLLAMA_MODEL_QWEN_CODER_7B", "qwen2.5-coder:7b")
OLLAMA_MODEL_QWEN_CODER_14B = os.getenv("OLLAMA_MODEL_QWEN_CODER_14B", "qwen2.5-coder:14b")
OLLAMA_MODEL_QWEN_CODER_32B = os.getenv("OLLAMA_MODEL_QWEN_CODER_32B", "qwen3-coder:30b")
OLLAMA_MODEL_QWEN_LARGE = os.getenv("OLLAMA_MODEL_QWEN_LARGE", "qwen2.5:72b")
OLLAMA_MODEL_QWEN_72B = os.getenv("OLLAMA_MODEL_QWEN_72B", "qwen2.5:72b")
# xAI API model names (override if xAI renames)
XAI_MODEL_GROK2 = os.getenv("XAI_MODEL_GROK2", "grok-4.20-0309-non-reasoning")
XAI_MODEL_GROK3 = os.getenv("XAI_MODEL_GROK3", "grok-4.3")
XAI_MODEL_GROK4 = os.getenv("XAI_MODEL_GROK4", "grok-4.5")
# Neutral UI tiers → xAI Grok model ids (used when LLM_GROK_ONLY is on)
XAI_MODEL_FAST = os.getenv("XAI_MODEL_FAST", XAI_MODEL_GROK2 or "grok-4.20-0309-non-reasoning")
XAI_MODEL_QUALITY = os.getenv("XAI_MODEL_QUALITY", XAI_MODEL_GROK4 or "grok-4.5")
XAI_MODEL_REASONING = os.getenv("XAI_MODEL_REASONING", XAI_MODEL_GROK4 or "grok-4.5")

# Force all chat inference through xAI Grok (no RunPod/Ollama/Claude path).
# Default ON — set LLM_GROK_ONLY=false only if you intentionally re-enable fleet GPUs.
_raw_grok_only = os.getenv("LLM_GROK_ONLY")
if _raw_grok_only is None or str(_raw_grok_only).strip() == "":
    LLM_GROK_ONLY = True
else:
    LLM_GROK_ONLY = str(_raw_grok_only).strip().lower() in ("1", "true", "yes", "on")

# Default false in production (prefer XAI_API_KEY for multi-tenant); true in development (JWT Super).
_raw_xai_jwt_only = os.getenv("XAI_USE_JWT_ONLY")
if _raw_xai_jwt_only is None or str(_raw_xai_jwt_only).strip() == "":
    XAI_USE_JWT_ONLY = not IS_PRODUCTION
else:
    XAI_USE_JWT_ONLY = str(_raw_xai_jwt_only).strip().lower() in ("1", "true", "yes", "on")

# Legacy alias — JWT is always preferred
PREFER_GROK_SUPER = XAI_USE_JWT_ONLY or (
    (os.getenv("PREFER_GROK_SUPER", "true") or "true").strip().lower() in ("1", "true", "yes", "on")
)


def refresh_grok_session_token() -> str:
    """Re-read JWT from env / ~/.grok/auth.json (call on every xAI request)."""
    global GROK_SESSION_TOKEN
    tok = _load_managed_backend_token() or ""
    GROK_SESSION_TOKEN = tok
    return tok


def get_grok_token(user_key: str | None = None) -> str | None:
    """
    Resolve auth for ALL xAI calls (chat, images, video, staff Server Monitor).

    Production default (XAI_USE_JWT_ONLY=false): prefer business XAI_API_KEY.
    Development default (XAI_USE_JWT_ONLY=true): Super/CLI JWT for local work.

    Resolution:
      1. Explicit BYOK from Settings (user_key) — rare; still billed in-app
      2. If not JWT-only: XAI_API_KEY (multi-tenant safe)
      3. Live JWT from Super session / env
      4. XAI_API_KEY fallback if JWT-only is off and key present (already tried)
    """
    if user_key and str(user_key).strip():
        return str(user_key).strip()

    # Multi-tenant production path: business API key first
    if not XAI_USE_JWT_ONLY and XAI_API_KEY:
        return XAI_API_KEY

    jwt = refresh_grok_session_token()
    if jwt:
        return jwt

    if not XAI_USE_JWT_ONLY and XAI_API_KEY:
        return XAI_API_KEY

    return None


# Boot-time snapshot (prefer JWT)
EFFECTIVE_GROK_TOKEN = get_grok_token() or ""


def grok_auth_source() -> str:
    """Human readable source for logs / status (no secrets)."""
    jwt = refresh_grok_session_token()
    if jwt:
        if _jwt_from_env():
            return "Grok Super JWT (env GROK_SESSION_TOKEN / GROK_JWT)"
        return "Grok Super / CLI JWT (~/.grok/auth.json)"
    if not XAI_USE_JWT_ONLY and XAI_API_KEY:
        return "XAI_API_KEY (JWT missing; API key fallback enabled)"
    return "none — sign in with `grok` CLI or set GROK_SESSION_TOKEN"

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_STARTER = os.getenv("STRIPE_PRICE_STARTER", "")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_BUSINESS = os.getenv("STRIPE_PRICE_BUSINESS", "")

# AgentBay host (bridge posts to {AGENTBAY_URL}/api/bridge/...).
# Production path deploy: https://aibusinessagent.xyz/bay  → API at /bay/api/...
AGENTBAY_URL = (
    os.getenv("AGENTBAY_URL")
    or (AGENTBAY_PUBLIC_URL if IS_PRODUCTION else "http://127.0.0.1:8000")
).rstrip("/")
_WEAK_BRIDGE_SECRETS = ("", "dev-bridge-secret-change-me")
_raw_bridge_secret = (os.getenv("AGENTBAY_BRIDGE_SECRET") or "").strip()
if IS_PRODUCTION:
    # Weak/default secret disables the bridge in production (agentbay_bridge.enabled() → false).
    if not _raw_bridge_secret or _raw_bridge_secret in _WEAK_BRIDGE_SECRETS:
        if _raw_bridge_secret:
            print(
                "WARNING: AGENTBAY_BRIDGE_SECRET is missing or still the dev default; "
                "AgentBay bridge disabled in production. Set a strong shared secret."
            )
        AGENTBAY_BRIDGE_SECRET = ""
    else:
        AGENTBAY_BRIDGE_SECRET = _raw_bridge_secret
else:
    # Local dev: keep default so bridge works out of the box when AgentBay uses the same secret.
    AGENTBAY_BRIDGE_SECRET = _raw_bridge_secret or "dev-bridge-secret-change-me"
# When true, newly created agents are auto-published to AgentBay
AGENTBAY_AUTO_PUBLISH = (os.getenv("AGENTBAY_AUTO_PUBLISH") or "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Default skill listing price (USD) when auto-publishing
AGENTBAY_DEFAULT_PRICE = float(os.getenv("AGENTBAY_DEFAULT_PRICE") or "29")

# Crypto payments (self-custody receive addresses — never put private keys here)
CRYPTO_ETH_ADDRESS = os.getenv("CRYPTO_ETH_ADDRESS", "").strip()
CRYPTO_SOL_ADDRESS = os.getenv("CRYPTO_SOL_ADDRESS", "").strip()
CRYPTO_XRP_ADDRESS = os.getenv("CRYPTO_XRP_ADDRESS", "").strip()
CRYPTO_BTC_ADDRESS = os.getenv("CRYPTO_BTC_ADDRESS", "").strip()
# Optional public RPC / explorer APIs
CRYPTO_ETH_RPC = os.getenv("CRYPTO_ETH_RPC", "https://ethereum.publicnode.com").strip()
CRYPTO_SOL_RPC = os.getenv("CRYPTO_SOL_RPC", "https://api.mainnet-beta.solana.com").strip()
CRYPTO_XRP_RPC = os.getenv("CRYPTO_XRP_RPC", "https://xrplcluster.com").strip()
CRYPTO_BTC_API = os.getenv("CRYPTO_BTC_API", "https://blockstream.info/api").strip()
# Invoice lifetime minutes
CRYPTO_INVOICE_TTL_MIN = int(os.getenv("CRYPTO_INVOICE_TTL_MIN", "60") or "60")

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM = os.getenv("RESEND_FROM", "assistant@yourdomain.com")
# Optional classic SMTP (for notify-human email). Resend API is used when set instead.
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or "587")
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", "").strip() or RESEND_FROM
SMTP_TLS = os.getenv("SMTP_TLS", "1").strip().lower() not in ("0", "false", "no")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")

# Cron / automation secret for GET|POST /ops/autonomy/tick-all (Vercel Cron path:
# /api/ops/autonomy/tick-all — see root vercel.json). Set the same value in Vercel
# Project → Environment Variables as CRON_SECRET; Vercel then sends
# Authorization: Bearer <CRON_SECRET> on scheduled GETs. Manual callers may use
# header X-Cron-Secret: <value> instead.
CRON_SECRET = os.getenv("CRON_SECRET", "").strip()

# Minimum credits required to run LLM-backed actions
MIN_CREDITS = float(os.getenv("MIN_CREDITS", "0.001"))
# Optional dedicated key for encrypting subscriber API keys (Fernet or any long secret).
# If empty, derived from JWT_SECRET. Changing it invalidates stored keys.
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "").strip()


def has_managed_backend() -> bool:
    """Whether a managed inference backend (RunPod, etc.) is configured."""
    return bool(RUNPOD_API_KEY and RUNPOD_BASE_URL) or bool(OLLAMA_URL)  # extend as needed

def has_anthropic_auth() -> bool:
    return bool(ANTHROPIC_API_KEY)

def integration_status() -> dict:
    """Which third-party services are configured (not a live ping)."""
    twilio_ok = bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER)
    grok_via_super = bool(get_grok_token() and (
        (get_grok_token() or "").startswith("eyJ")
    ))
    oauth_apps = {
        "shopify": bool(os.getenv("SHOPIFY_CLIENT_ID") and os.getenv("SHOPIFY_CLIENT_SECRET")),
        "google": bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID") and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")),
        "gmail": bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID") and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")),
        "google_sheets": bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID") and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")),
        "google_business": bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID") and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")),
        "youtube": bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID") and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")),
        "slack": bool(os.getenv("SLACK_CLIENT_ID") and os.getenv("SLACK_CLIENT_SECRET")),
        "hubspot": bool(os.getenv("HUBSPOT_CLIENT_ID") and os.getenv("HUBSPOT_CLIENT_SECRET")),
        "notion": bool(os.getenv("NOTION_CLIENT_ID") and os.getenv("NOTION_CLIENT_SECRET")),
        "x": bool(os.getenv("X_CLIENT_ID") and os.getenv("X_CLIENT_SECRET")),
        "linkedin": bool(os.getenv("LINKEDIN_CLIENT_ID") and os.getenv("LINKEDIN_CLIENT_SECRET")),
        "meta": bool(os.getenv("META_APP_ID") and os.getenv("META_APP_SECRET")),
        "instagram": bool(os.getenv("META_APP_ID") and os.getenv("META_APP_SECRET")),
        "microsoft": bool(os.getenv("MICROSOFT_CLIENT_ID") and os.getenv("MICROSOFT_CLIENT_SECRET")),
        "dropbox": bool(os.getenv("DROPBOX_APP_KEY") and os.getenv("DROPBOX_APP_SECRET")),
        "tiktok": bool(os.getenv("TIKTOK_CLIENT_KEY") and os.getenv("TIKTOK_CLIENT_SECRET")),
    }
    return {
        "environment": APP_ENV,
        "llm": {
            "anthropic": bool(ANTHROPIC_API_KEY),
            "managed_ollama": bool(MANAGED_OLLAMA_URL),
            "runpod_ollama": bool(RUNPOD_OLLAMA_URL),
            "runpod_webui": bool(RUNPOD_WEBUI_URL),
            "ollama_url": "***" if RUNPOD_OLLAMA_URL else OLLAMA_URL,
            "model_map": RUNPOD_MODEL_MAP,
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
                "jwt-xai → ollama → mock"
                if (ANTHROPIC_API_KEY or get_grok_token())
                else "ollama → mock"
            ),
            "xai_auth": grok_auth_source(),
            "xai_jwt_only": XAI_USE_JWT_ONLY,
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
            "crypto": bool(
                CRYPTO_ETH_ADDRESS or CRYPTO_SOL_ADDRESS or CRYPTO_XRP_ADDRESS or CRYPTO_BTC_ADDRESS
            ),
            "crypto_chains": {
                "eth": bool(CRYPTO_ETH_ADDRESS),
                "sol": bool(CRYPTO_SOL_ADDRESS),
                "xrp": bool(CRYPTO_XRP_ADDRESS),
                "btc": bool(CRYPTO_BTC_ADDRESS),
            },
        },
        "channels": {
            "email_resend": bool(RESEND_API_KEY),
            "email_smtp": bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD),
            "resend_from": RESEND_FROM if RESEND_API_KEY else None,
            "smtp_from": SMTP_FROM if (SMTP_HOST and SMTP_USER) else None,
            "sms_twilio": twilio_ok,
            "voice_twilio": twilio_ok,
            "notify_human": bool(
                (RESEND_API_KEY or (SMTP_HOST and SMTP_USER and SMTP_PASSWORD)) and twilio_ok
            ),
        },
        "oauth": oauth_apps,
        "database": {
            "driver": "postgresql" if DATABASE_URL.startswith("postgres") else "sqlite",
            "configured": True,
        },
    }
