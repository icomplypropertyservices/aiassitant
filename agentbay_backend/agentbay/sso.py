"""
Unified login with AI Business Assistant via API keys (no JWT).

Main app session key: aba_…
AgentBay accepts X-API-Key / Bearer aba_… and links bay_users to main users.
"""
from __future__ import annotations

import re
import secrets
from typing import Any, Optional

from sqlalchemy.orm import Session

from . import models
from .auth_utils import hash_password


SOURCE = "ai-business-assistant"
MAIN_KEY_PREFIX = "aba_"


def _slug_username(email: str, name: str, main_id: int) -> str:
    base = (name or email.split("@")[0] or "user").lower()
    base = re.sub(r"[^a-z0-9_]+", "_", base).strip("_")[:24] or "user"
    return f"{base}_{main_id}"[:40]


def lookup_main_user_by_api_key(raw_key: str) -> Optional[Any]:
    """Resolve main app user from aba_ API key (monorepo shared process)."""
    if not raw_key or not str(raw_key).strip().startswith(MAIN_KEY_PREFIX):
        return None
    try:
        from app.auth_utils import get_user_from_api_key  # type: ignore
        from app.database import SessionLocal as MainSession  # type: ignore
    except Exception:
        return None
    db = MainSession()
    try:
        return get_user_from_api_key(str(raw_key).strip(), db)
    except Exception:
        return None
    finally:
        db.close()


def fetch_main_user(main_user_id: int) -> Optional[Any]:
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


def issue_main_api_key(main_user, main_db=None) -> Optional[str]:
    """Issue/rotate main session API key (login on bay with main password)."""
    try:
        from app.auth_utils import issue_session_api_key  # type: ignore
        from app.database import SessionLocal as MainSession  # type: ignore
    except Exception:
        return None
    own = main_db is None
    db = main_db or MainSession()
    try:
        # re-load attached instance
        from app.models import User as MainUser  # type: ignore

        u = db.get(MainUser, main_user.id)
        if not u:
            return None
        return issue_session_api_key(db, u)
    except Exception:
        return None
    finally:
        if own:
            db.close()


def ensure_bay_user_from_main(db: Session, main_user) -> models.User:
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

    if db.query(models.User).filter_by(username=username).first():
        username = f"user_{main_user.id}"
    if db.query(models.User).filter_by(email=email).first():
        email = f"main_{main_user.id}@sso.agentbay.local"

    bay = models.User(
        email=email,
        username=username,
        display_name=display,
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


def resolve_user_from_credential(db: Session, raw: str) -> Optional[models.User]:
    """
    Auth material:
    - Main app API key aba_… → SSO link
    - AgentBay marketplace key abm_… (handled elsewhere)
    """
    key = (raw or "").strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()

    # Main product API key
    if key.startswith(MAIN_KEY_PREFIX):
        main_user = lookup_main_user_by_api_key(key)
        if main_user:
            return ensure_bay_user_from_main(db, main_user)
        return None

    return None


def login_via_main_credentials(
    db: Session, email: str, password: str
) -> Optional[tuple[models.User, str]]:
    """Email/password against main app; returns (bay_user, main_api_key)."""
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
        api_key = issue_main_api_key(main_user, mdb)
        if not api_key:
            return None
        bay = ensure_bay_user_from_main(db, main_user)
        return bay, api_key
    finally:
        mdb.close()
