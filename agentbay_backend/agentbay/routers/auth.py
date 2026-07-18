from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import (
    hash_password,
    verify_password,
    create_token,
    get_current_user,
    generate_api_key,
    user_me,
    user_public,
    decode_token,
    get_user_from_token,
)
from ..sso import login_via_main_credentials, resolve_user_from_jwt_payload

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: str
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=8)
    display_name: str = ""
    account_type: str = "human"  # human | agent
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
    """
    Optional bay-only register. Prefer signing up at /agents then using AgentBay SSO.
    """
    email = data.email.strip().lower()
    username = data.username.strip().lower().replace(" ", "_")
    if data.account_type not in ("human", "agent"):
        raise HTTPException(400, "account_type must be human or agent")
    if db.query(models.User).filter_by(email=email).first():
        raise HTTPException(400, "Email already registered — sign in with your main account")
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
    api_key_plain = None
    if data.account_type == "agent":
        raw, prefix, h = generate_api_key()
        user.api_key_hash = h
        user.api_key_prefix = prefix
        api_key_plain = raw

    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token(user.id, user.account_type)
    out = {"token": token, "user": user_me(user), "sso": False}
    if api_key_plain:
        out["api_key"] = api_key_plain
        out["api_key_note"] = "Save this API key now — it will not be shown again."
    return out


@router.post("/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    """
    Unified login:
    1) AgentBay local password
    2) AI Business Assistant account (same email/password) → SSO link
    """
    email = data.email.strip().lower()
    user = db.query(models.User).filter_by(email=email).first()
    if user and verify_password(data.password, user.password_hash):
        if not user.is_active:
            raise HTTPException(403, "Account disabled")
        return {
            "token": create_token(user.id, user.account_type),
            "user": user_me(user),
            "sso": bool(user.main_user_id),
        }

    # Main app credentials
    linked = login_via_main_credentials(db, email, data.password)
    if linked:
        bay, token = linked
        return {"token": token, "user": user_me(bay), "sso": True, "source": "ai-business-assistant"}

    raise HTTPException(401, "Invalid email or password")


@router.post("/sso")
def sso_from_main_token(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Confirm / refresh marketplace profile using the current Bearer token
    (main app JWT or bay JWT). Called automatically by the AgentBay UI.
    """
    return {
        "ok": True,
        "user": user_me(user),
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
    raw, prefix, h = generate_api_key()
    user.api_key_hash = h
    user.api_key_prefix = prefix
    db.commit()
    return {
        "api_key": raw,
        "prefix": prefix,
        "note": "Save this API key now — it will not be shown again.",
    }


@router.get("/users/{username}")
def public_profile(username: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter_by(username=username.lower()).first()
    if not user or not user.is_active:
        raise HTTPException(404, "User not found")
    return user_public(user)
