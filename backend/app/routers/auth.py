from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..auth_utils import hash_password, verify_password, create_token, get_current_user
from ..usage_billing import meter_snapshot
from ..rate_limit import check_rate_limit, client_ip

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=6)
    name: str = ""
    company_name: str = ""


class LoginIn(BaseModel):
    email: str
    password: str


class ProfileIn(BaseModel):
    name: str | None = None
    password: str | None = None


def _subscription_live(u: models.User) -> bool:
    """True when plan is active and not past subscription_expires_at."""
    if u.role == "admin":
        return True
    if not u.subscription_active or u.plan in (None, "", "none"):
        return False
    exp = getattr(u, "subscription_expires_at", None)
    if exp is not None and exp < datetime.utcnow():
        return False
    return True


def user_out(u: models.User):
    live = _subscription_live(u)
    exp = getattr(u, "subscription_expires_at", None)
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "plan": u.plan if live or u.role == "admin" else (u.plan or "none"),
        "subscription_active": live,
        "subscription_expires_at": exp.isoformat() + "Z" if exp else None,
        "needs_subscription": u.role != "admin" and not live,
    }


@router.post("/register")
def register(data: RegisterIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    check_rate_limit(f"register:{ip}", limit=10, window_sec=300)
    email = data.email.strip().lower()
    check_rate_limit(f"register-email:{email}", limit=5, window_sec=3600)
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Enter a valid email address")
    if db.query(models.User).filter_by(email=email).first():
        raise HTTPException(400, "An account with that email already exists")
    if len(data.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    user = models.User(
        email=email,
        name=data.name.strip(),
        password_hash=hash_password(data.password),
        plan="none",
        subscription_active=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(models.Balance(user_id=user.id, credits=0.0, tokens_included=0, tokens_used_period=0))
    # Stash preferred company name on a draft company only after plan pick —
    # store as a pending name in notes via lightweight placeholder is overkill;
    # frontend sends company_name again on /billing/plan.
    db.commit()
    return {
        "token": create_token(user.id, user.role),
        "user": user_out(user),
        "preferred_company_name": data.company_name.strip() or None,
    }


@router.post("/login")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    check_rate_limit(f"login:{ip}", limit=30, window_sec=60)
    email = (data.email or "").strip().lower()
    password = data.password or ""
    if not email or not password:
        raise HTTPException(400, "Email and password are required")
    check_rate_limit(f"login-email:{email}", limit=15, window_sec=300)
    try:
        user = db.query(models.User).filter_by(email=email).first()
    except Exception as e:
        # e.g. missing tables / DB unreachable on cold start
        raise HTTPException(
            503,
            f"Database unavailable. Ensure DATABASE_URL is set and the app finished startup. ({type(e).__name__})",
        ) from e
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    try:
        token = create_token(user.id, user.role)
    except Exception as e:
        raise HTTPException(500, f"Could not issue session token: {type(e).__name__}") from e
    return {"token": token, "user": user_out(user)}


@router.get("/me")
def me(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    out = user_out(user)
    try:
        out["meter"] = meter_snapshot(db, user)
    except Exception:
        out["meter"] = None
    return out


@router.patch("/me")
def update_me(data: ProfileIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    u = db.get(models.User, user.id)
    if data.name is not None:
        u.name = data.name.strip()
    if data.password:
        if len(data.password) < 6:
            raise HTTPException(400, "Password must be at least 6 characters")
        u.password_hash = hash_password(data.password)
    db.commit()
    db.refresh(u)
    return user_out(u)
