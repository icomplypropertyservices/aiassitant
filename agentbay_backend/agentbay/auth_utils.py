import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import JWT_SECRET, JWT_ALG, JWT_EXPIRE_HOURS
from .database import get_db
from . import models

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


def create_token(user_id: int, account_type: str = "human") -> str:
    if not JWT_SECRET:
        raise HTTPException(503, "Server misconfigured: JWT_SECRET is not set")
    payload = {
        "sub": str(user_id),
        "type": account_type,
        "aud": "agentbay",
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    if not JWT_SECRET:
        raise HTTPException(503, "Server misconfigured: JWT_SECRET is not set")
    try:
        # Main app tokens have no aud; bay tokens may set aud=agentbay
        return jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALG],
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Invalid token: {e}")


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    raw = f"abm_{secrets.token_urlsafe(32)}"
    prefix = raw[:12]
    return raw, prefix, hash_api_key(raw)


def get_user_from_token(token: str, db: Session) -> models.User:
    from .sso import resolve_user_from_jwt_payload

    data = decode_token(token)
    user = resolve_user_from_jwt_payload(db, data)
    if not user:
        raise HTTPException(
            401,
            "User not found. Sign in with your AI Business Assistant account.",
        )
    return user


def get_user_from_api_key(api_key: str, db: Session) -> Optional[models.User]:
    if not api_key or not api_key.startswith("abm_"):
        return None
    prefix = api_key[:12]
    h = hash_api_key(api_key)
    user = (
        db.query(models.User)
        .filter(models.User.api_key_prefix == prefix, models.User.api_key_hash == h)
        .first()
    )
    if user and user.is_active:
        return user
    return None


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> models.User:
    if x_api_key:
        user = get_user_from_api_key(x_api_key, db)
        if user:
            return user
        raise HTTPException(401, "Invalid API key")
    if creds and creds.credentials:
        return get_user_from_token(creds.credentials, db)
    raise HTTPException(401, "Authentication required — use your main app login")


async def get_optional_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> Optional[models.User]:
    try:
        if x_api_key:
            return get_user_from_api_key(x_api_key, db)
        if creds and creds.credentials:
            return get_user_from_token(creds.credentials, db)
    except HTTPException:
        return None
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
        "linked_main": bool(getattr(u, "main_user_id", None) or (
            u.source_system == "ai-business-assistant" and (u.external_id or "").startswith("user:")
        )),
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def user_me(u: models.User) -> dict:
    d = user_public(u)
    d["email"] = u.email
    d["has_api_key"] = bool(u.api_key_hash)
    d["api_key_prefix"] = u.api_key_prefix
    return d
