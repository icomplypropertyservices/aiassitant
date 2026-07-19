from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import (
    hash_password,
    verify_password,
    get_current_user,
    generate_api_key,
    issue_bay_session_key,
    user_me,
    user_public,
)
from ..sso import login_via_main_credentials

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: str
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=8)
    display_name: str = ""
    account_type: str = "human"
    bio: str = ""


class LoginIn(BaseModel):
    email: str
    password: str


class ProfileUpdate(BaseModel):
    display_name: str | None = None
    bio: str | None = None
    location: str | None = None
    avatar_url: str | None = None


@router.post("/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    username = data.username.strip().lower().replace(" ", "_")
    if data.account_type not in ("human", "agent"):
        raise HTTPException(400, "account_type must be human or agent")
    if db.query(models.User).filter_by(email=email).first():
        raise HTTPException(400, "Email already registered — use main app login")
    if db.query(models.User).filter_by(username=username).first():
        raise HTTPException(400, "Username taken")

    user = models.User(
        email=email,
        username=username,
        display_name=data.display_name or username,
        password_hash=hash_password(data.password),
        account_type=data.account_type,
        bio=data.bio or "",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    api_key = issue_bay_session_key(db, user)
    out = {
        "token": api_key,
        "api_key": api_key,
        "auth_type": "api_key",
        "user": user_me(user),
        "sso": False,
    }
    return out


@router.post("/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    """
    Unified login (API keys only):
    1) Main app email/password → aba_ key + linked bay profile
    2) Bay-local password → abm_ key
    """
    email = data.email.strip().lower()

    # Prefer main product credentials
    linked = login_via_main_credentials(db, email, data.password)
    if linked:
        bay, api_key = linked
        return {
            "token": api_key,
            "api_key": api_key,
            "auth_type": "api_key",
            "user": user_me(bay),
            "sso": True,
            "source": "ai-business-assistant",
        }

    user = db.query(models.User).filter_by(email=email).first()
    if user and verify_password(data.password, user.password_hash):
        if not user.is_active:
            raise HTTPException(403, "Account disabled")
        api_key = issue_bay_session_key(db, user)
        return {
            "token": api_key,
            "api_key": api_key,
            "auth_type": "api_key",
            "user": user_me(user),
            "sso": False,
        }

    raise HTTPException(401, "Invalid email or password")


@router.post("/sso")
def sso_from_api_key(user=Depends(get_current_user)):
    """Confirm marketplace profile for current X-API-Key (aba_ or abm_)."""
    return {
        "ok": True,
        "user": user_me(user),
        "auth_type": "api_key",
        "sso": bool(user.main_user_id or (user.source_system == "ai-business-assistant")),
    }


@router.get("/me")
def me(user=Depends(get_current_user)):
    return user_me(user)


@router.patch("/me")
def update_me(data: ProfileUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if data.display_name is not None:
        user.display_name = data.display_name
    if data.bio is not None:
        user.bio = data.bio
    if data.location is not None:
        user.location = data.location
    if data.avatar_url is not None:
        user.avatar_url = data.avatar_url
    db.commit()
    db.refresh(user)
    return user_me(user)


@router.post("/api-key/rotate")
def rotate_api_key(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Rotate AgentBay marketplace key (abm_). Main aba_ keys rotate via main app login."""
    raw, prefix, h = generate_api_key()
    user.api_key_hash = h
    user.api_key_prefix = prefix
    db.commit()
    return {
        "api_key": raw,
        "token": raw,
        "prefix": prefix,
        "auth_type": "api_key",
        "note": "Save this API key now — it will not be shown again.",
    }


@router.get("/users/{username}")
def public_profile(username: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter_by(username=username.lower()).first()
    if not user or not user.is_active:
        raise HTTPException(404, "User not found")
    return user_public(user)
