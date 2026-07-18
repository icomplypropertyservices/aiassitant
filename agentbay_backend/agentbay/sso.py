"""
Unified login with AI Business Assistant (aibusinessagent.xyz).

Same JWT_SECRET → main app tokens work on AgentBay.
Marketplace profile is auto-created/linked on first use.
"""
from __future__ import annotations

import re
import secrets
from typing import Any, Optional

from sqlalchemy.orm import Session

from . import models
from .auth_utils import hash_password


SOURCE = "ai-business-assistant"


def _slug_username(email: str, name: str, main_id: int) -> str:
    base = (name or email.split("@")[0] or "user").lower()
    base = re.sub(r"[^a-z0-9_]+", "_", base).strip("_")[:24] or "user"
    return f"{base}_{main_id}"[:40]


def fetch_main_user(main_user_id: int) -> Optional[Any]:
    """Load user from AI Business Assistant DB (same process / monorepo)."""
    try:
        from app.models import User as MainUser  # type: ignore
        from app.database import SessionLocal as MainSession  # type: ignore
    except Exception:
        return None
    db = MainSession()
    try:
        return db.get(MainUser, main_user_id)
    except Exception:
        return None
    finally:
        db.close()


def verify_main_password(password: str, password_hash: str) -> bool:
    try:
        from app.auth_utils import verify_password as main_verify  # type: ignore

        return bool(main_verify(password, password_hash))
    except Exception:
        return False


def issue_main_token(main_user) -> Optional[str]:
    try:
        from app.auth_utils import create_token  # type: ignore

        return create_token(
            main_user.id,
            getattr(main_user, "role", None) or "user",
            token_version=int(getattr(main_user, "token_version", None) or 0),
        )
    except Exception:
        return None


def ensure_bay_user_from_main(db: Session, main_user) -> models.User:
    """Upsert marketplace user linked to main app account."""
    ext = f"user:{main_user.id}"
    bay = (
        db.query(models.User)
        .filter_by(source_system=SOURCE, external_id=ext)
        .first()
    )
    if not bay and getattr(main_user, "email", None):
        bay = db.query(models.User).filter_by(email=main_user.email.lower()).first()

    email = (main_user.email or f"user{main_user.id}@aibusinessagent.xyz").lower()
    display = (getattr(main_user, "name", None) or "").strip() or email.split("@")[0]
    username = _slug_username(email, display, main_user.id)

    if bay:
        bay.email = email
        bay.display_name = display or bay.display_name
        bay.main_user_id = main_user.id
        bay.source_system = SOURCE
        bay.external_id = ext
        bay.is_active = True
        if not bay.username:
            bay.username = username
        db.commit()
        db.refresh(bay)
        return bay

    # Unique username
    if db.query(models.User).filter_by(username=username).first():
        username = f"user_{main_user.id}"
    if db.query(models.User).filter_by(email=email).first():
        email = f"main_{main_user.id}@sso.agentbay.local"

    bay = models.User(
        email=email,
        username=username,
        display_name=display,
        # Random — real login goes through main app / SSO
        password_hash=hash_password(secrets.token_urlsafe(24)),
        account_type="human",
        bio="Linked to AI Business Assistant account",
        source_system=SOURCE,
        external_id=ext,
        main_user_id=main_user.id,
    )
    db.add(bay)
    db.commit()
    db.refresh(bay)
    return bay


def resolve_user_from_jwt_payload(db: Session, payload: dict) -> Optional[models.User]:
    """
    Accept:
    - AgentBay tokens: { sub, type: human|agent }
    - Main app tokens: { sub, role, tv }
    """
    try:
        sub = int(payload.get("sub"))
    except (TypeError, ValueError):
        return None

    # Main app JWT (has role claim)
    if "role" in payload or "tv" in payload:
        # Already linked?
        bay = (
            db.query(models.User)
            .filter_by(source_system=SOURCE, external_id=f"user:{sub}")
            .first()
        )
        if bay and bay.is_active:
            return bay
        bay = db.query(models.User).filter_by(main_user_id=sub, is_active=True).first()
        if bay:
            return bay
        main_user = fetch_main_user(sub)
        if main_user:
            return ensure_bay_user_from_main(db, main_user)
        return None

    # AgentBay-native JWT (type claim)
    if payload.get("type") in ("human", "agent", "admin"):
        user = db.get(models.User, sub)
        if user and user.is_active:
            return user

    # Fallback: treat sub as bay user id
    user = db.get(models.User, sub)
    if user and user.is_active:
        return user
    return None


def login_via_main_credentials(db: Session, email: str, password: str) -> Optional[tuple[models.User, str]]:
    """Email/password against main app; returns (bay_user, main_jwt)."""
    try:
        from app.models import User as MainUser  # type: ignore
        from app.database import SessionLocal as MainSession  # type: ignore
    except Exception:
        return None

    mdb = MainSession()
    try:
        main_user = mdb.query(MainUser).filter_by(email=email.strip().lower()).first()
        if not main_user:
            return None
        if not verify_main_password(password, main_user.password_hash):
            return None
        token = issue_main_token(main_user)
        if not token:
            return None
        bay = ensure_bay_user_from_main(db, main_user)
        return bay, token
    finally:
        mdb.close()
