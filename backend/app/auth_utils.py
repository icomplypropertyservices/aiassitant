"""
Site-wide authentication via API keys (not JWT sessions).

Clients send either:
  Authorization: Bearer aba_<secret>
  X-API-Key: aba_<secret>

Login/register returns the raw key once; only a hash is stored.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .database import get_db
from . import models, config

bearer = HTTPBearer(auto_error=False)

# Public session keys for the main product (agents app + bay SSO)
API_KEY_PREFIX = "aba_"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${h}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$")
    except ValueError:
        return False
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex() == h


def hash_reset_token(token: str) -> str:
    """SHA-256 hex digest of a password-reset secret (never store the raw token)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Returns (full_key, prefix_for_display, hash). Prefix aba_…"""
    raw = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    prefix = raw[:16]
    return raw, prefix, hash_api_key(raw)


def issue_session_api_key(db: Session, user: models.User) -> str:
    """Create a new session API key for the user (invalidates previous)."""
    raw, prefix, h = generate_api_key()
    user.api_key_hash = h
    user.api_key_prefix = prefix
    # Bump token_version so any legacy JWTs stop working
    user.token_version = int(getattr(user, "token_version", None) or 0) + 1
    db.commit()
    return raw


def get_user_from_api_key(raw: str, db: Session) -> models.User | None:
    if not raw:
        return None
    key = raw.strip()
    # Accept bare key or accidental "Bearer " prefix
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    if not key.startswith(API_KEY_PREFIX):
        return None
    prefix = key[:16]
    h = hash_api_key(key)
    user = (
        db.query(models.User)
        .filter(
            models.User.api_key_prefix == prefix,
            models.User.api_key_hash == h,
        )
        .first()
    )
    if not user:
        # Prefix may have drifted; scan by hash only (indexed)
        user = db.query(models.User).filter_by(api_key_hash=h).first()
    if user and not _is_deleted(user):
        return user
    return None


def _is_deleted(u: models.User) -> bool:
    email = (u.email or "").lower()
    return email.startswith("deleted+") and email.endswith("@invalid.local")


def _extract_key(
    creds: HTTPAuthorizationCredentials | None,
    x_api_key: str | None,
) -> str | None:
    if x_api_key and str(x_api_key).strip():
        return str(x_api_key).strip()
    if creds and creds.credentials:
        return creds.credentials.strip()
    return None


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> models.User:
    raw = _extract_key(creds, x_api_key)
    if not raw:
        raise HTTPException(401, "Not authenticated — send X-API-Key or Authorization: Bearer aba_…")
    user = get_user_from_api_key(raw, db)
    if not user:
        raise HTTPException(401, "Invalid API key")
    return user


def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != "admin":
        raise HTTPException(403, "Admin access required")
    return user


def user_from_ws_token(token: str, db: Session):
    """WebSocket auth: API key in first message or query (same as HTTP)."""
    return get_user_from_api_key(token or "", db)


async def accept_and_authenticate_ws(ws, token: str, db: Session):
    """
    Accept WebSocket then authenticate with API key.

    Preferred: first text frame {"type":"auth","api_key":"aba_…"} or {"type":"auth","token":"aba_…"}.
    Legacy: ?token=aba_… query param.
    """
    await ws.accept()
    raw = (token or "").strip()
    if not raw:
        try:
            msg = await ws.receive_text()
            import json as _json

            data = _json.loads(msg) if msg else {}
            if isinstance(data, dict) and data.get("type") == "auth":
                raw = (data.get("api_key") or data.get("token") or "").strip()
        except Exception:
            raw = ""
    user = user_from_ws_token(raw, db) if raw else None
    if not user:
        try:
            await ws.close(code=4401)
        except Exception:
            pass
        return None
    if not (token or "").strip():
        try:
            await ws.send_text('{"type":"auth_ok"}')
        except Exception:
            pass
    return user


def ensure_credits(db: Session, user_id: int, min_credits: float | None = None) -> float:
    """Allow usage if monthly included tokens remain OR wallet has credits."""
    from .usage_billing import ensure_period

    user = db.get(models.User, user_id)
    if user and user.role == "admin":
        return 999.0
    if user:
        if not user.subscription_active or user.plan in (None, "", "none"):
            raise HTTPException(402, "Choose a subscription plan to continue.")
        exp = getattr(user, "subscription_expires_at", None)
        if exp is not None and exp < datetime.utcnow():
            raise HTTPException(402, "Your access period has ended. Renew on Billing to continue.")
    bal = db.query(models.Balance).filter_by(user_id=user_id).first()
    if not bal:
        # Active subscribers must be able to spawn agents even if Balance row
        # was never created (race on register / plan change). Create a zero
        # wallet + plan token pool so spawn/create is not a dead end.
        from .plans import plan_limits
        tokens = 0
        try:
            tokens = int(plan_limits(user.plan if user else "none").get("tokens_included") or 0)
        except Exception:
            tokens = 0
        bal = models.Balance(
            user_id=user_id,
            credits=0.0,
            tokens_included=tokens,
            tokens_used_period=0,
        )
        db.add(bal)
        try:
            db.commit()
            db.refresh(bal)
        except Exception:
            db.rollback()
            bal = db.query(models.Balance).filter_by(user_id=user_id).first()
            if not bal:
                raise HTTPException(402, "No billing account. Choose a plan or top up credits.")
    if user:
        ensure_period(bal, user)
        db.commit()
    included = int(bal.tokens_included or 0)
    used = int(bal.tokens_used_period or 0)
    if included > 0 and used < included:
        return float(bal.credits or 0)
    need = config.MIN_CREDITS if min_credits is None else min_credits
    credits = bal.credits if bal else 0.0
    if credits < need:
        raise HTTPException(
            402,
            "Included tokens used up and wallet is empty. Top up on Billing to continue.",
        )
    return credits


# --- Deprecated JWT helpers (kept only if something still imports create_token) ---

def create_token(user_id: int, role: str, token_version: int = 0) -> str:
    """Deprecated: sessions use API keys. Raises if called in production."""
    raise RuntimeError(
        "JWT sessions removed. Use issue_session_api_key() / API key auth."
    )


def decode_token(token: str):
    return None
