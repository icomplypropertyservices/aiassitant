import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import get_db
from . import models

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)

# Marketplace-only keys (when not using main aba_ key)
BAY_KEY_PREFIX = "abm_"
MAIN_KEY_PREFIX = "aba_"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    raw = f"{BAY_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    prefix = raw[:12]
    return raw, prefix, hash_api_key(raw)


def issue_bay_session_key(db: Session, user: models.User) -> str:
    raw, prefix, h = generate_api_key()
    user.api_key_hash = h
    user.api_key_prefix = prefix
    db.commit()
    return raw


def get_user_from_api_key(api_key: str, db: Session) -> Optional[models.User]:
    if not api_key:
        return None
    key = api_key.strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()

    # Main app key → SSO
    if key.startswith(MAIN_KEY_PREFIX):
        from .sso import resolve_user_from_credential

        return resolve_user_from_credential(db, key)

    if not key.startswith(BAY_KEY_PREFIX):
        return None
    prefix = key[:12]
    h = hash_api_key(key)
    user = (
        db.query(models.User)
        .filter(models.User.api_key_prefix == prefix, models.User.api_key_hash == h)
        .first()
    )
    if user and user.is_active:
        return user
    user = db.query(models.User).filter_by(api_key_hash=h).first()
    if user and user.is_active:
        return user
    return None


def get_user_from_token(token: str, db: Session) -> models.User:
    """Name kept for call sites — credential is API key (aba_ or abm_)."""
    user = get_user_from_api_key(token, db)
    if not user:
        raise HTTPException(
            401,
            "Invalid API key. Sign in with your main account (aba_ key) or AgentBay key.",
        )
    return user


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> models.User:
    raw = None
    if x_api_key and str(x_api_key).strip():
        raw = str(x_api_key).strip()
    elif creds and creds.credentials:
        raw = creds.credentials.strip()
    if not raw:
        raise HTTPException(
            401,
            "Authentication required — send X-API-Key: aba_… (main login) or abm_…",
        )
    return get_user_from_token(raw, db)


async def get_optional_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> Optional[models.User]:
    try:
        return await get_current_user(creds, x_api_key, db)
    except HTTPException:
        return None


def user_public(u: models.User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name or u.username,
        "account_type": u.account_type,
        "bio": u.bio or "",
        "avatar_url": u.avatar_url or "",
        "location": u.location or "",
        "rating_avg": round(u.rating_avg or 0, 2),
        "rating_count": u.rating_count or 0,
        "main_user_id": getattr(u, "main_user_id", None),
        "linked_main": bool(
            getattr(u, "main_user_id", None)
            or (
                u.source_system == "ai-business-assistant"
                and (u.external_id or "").startswith("user:")
            )
        ),
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def user_me(u: models.User) -> dict:
    d = user_public(u)
    d["email"] = u.email
    d["has_api_key"] = bool(u.api_key_hash)
    d["api_key_prefix"] = u.api_key_prefix
    d["auth_type"] = "api_key"
    return d
