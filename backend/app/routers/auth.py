"""Auth routes: register/login, email verify, password reset, profile, GDPR export/delete."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
import secrets
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, config
from ..auth_utils import (
    hash_password,
    verify_password,
    create_token,
    get_current_user,
    hash_reset_token,
)
from ..usage_billing import meter_snapshot
from ..rate_limit import check_rate_limit, client_ip
from ..channels import send_email

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("auth")

_PASSWORD_LETTER_RE = re.compile(r"[A-Za-z]")
_PASSWORD_DIGIT_RE = re.compile(r"[0-9]")

_EMAIL_TOKEN_TTL = timedelta(hours=48)
_RESET_TOKEN_TTL = timedelta(hours=1)


def _validate_password(password: str) -> None:
    """Enforce min length 8 and at least one letter and one number. Raises HTTP 400."""
    if not password or len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if not _PASSWORD_LETTER_RE.search(password):
        raise HTTPException(400, "Password must contain at least one letter")
    if not _PASSWORD_DIGIT_RE.search(password):
        raise HTTPException(400, "Password must contain at least one number")


def _hash_email_token(raw: str) -> str:
    return hash_reset_token(raw)


def _issue_email_token(
    db: Session,
    user: models.User,
    purpose: str = "verify",
    ttl: timedelta | None = None,
) -> str:
    """Create a one-time EmailToken; returns raw token for email / dev logs."""
    now = datetime.utcnow()
    for old in (
        db.query(models.EmailToken)
        .filter_by(user_id=user.id, purpose=purpose)
        .filter(models.EmailToken.used_at.is_(None))
        .all()
    ):
        old.used_at = now
    raw = secrets.token_urlsafe(32)
    row = models.EmailToken(
        user_id=user.id,
        purpose=purpose,
        token_hash=_hash_email_token(raw),
        expires_at=now + (ttl or _EMAIL_TOKEN_TTL),
    )
    db.add(row)
    db.commit()
    return raw


def _bump_token_version(u: models.User) -> None:
    u.token_version = int(getattr(u, "token_version", None) or 0) + 1


def _issue_session(user: models.User) -> str:
    return create_token(
        user.id,
        user.role,
        token_version=int(getattr(user, "token_version", None) or 0),
    )


def _frontend_base() -> str:
    return (config.FRONTEND_URL or "http://localhost:5173").rstrip("/")


def _verification_link(raw_token: str) -> str:
    return f"{_frontend_base()}/verify-email?token={raw_token}"


def _reset_link(raw_token: str) -> str:
    return f"{_frontend_base()}/reset-password?token={raw_token}"


async def _send_verification_email(user: models.User, raw_token: str) -> tuple[bool, str]:
    link = _verification_link(raw_token)
    name = (user.name or "").strip() or "there"
    subject = "Verify your email — AI Business Assistant"
    body = (
        f"Hi {name},\n\n"
        f"Please verify your email address by opening this link:\n\n"
        f"{link}\n\n"
        f"This link expires in 48 hours. If you did not create an account, ignore this message.\n"
    )
    return await send_email(user.email, subject, body)


async def _send_reset_email(user: models.User, raw_token: str) -> tuple[bool, str]:
    link = _reset_link(raw_token)
    name = (user.name or "").strip() or "there"
    subject = "Reset your password — AI Business Assistant"
    body = (
        f"Hi {name},\n\n"
        f"We received a request to reset the password for {user.email}.\n\n"
        f"Open this link to choose a new password (expires in 1 hour):\n\n"
        f"{link}\n\n"
        f"If you did not request this, you can ignore this email.\n"
    )
    return await send_email(user.email, subject, body)


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=8)
    name: str = ""
    company_name: str = ""


class LoginIn(BaseModel):
    email: str
    password: str


class ProfileIn(BaseModel):
    name: str | None = None
    password: str | None = Field(default=None, min_length=8)


class VerifyEmailIn(BaseModel):
    token: str


class ForgotPasswordIn(BaseModel):
    email: str


class ResetPasswordIn(BaseModel):
    token: str
    password: str = Field(min_length=8)


class DeleteAccountIn(BaseModel):
    password: str


def _subscription_live(u: models.User) -> bool:
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
    verified = bool(getattr(u, "email_verified", False))
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "plan": u.plan if live or u.role == "admin" else (u.plan or "none"),
        "subscription_active": live,
        "subscription_expires_at": exp.isoformat() + "Z" if exp else None,
        "needs_subscription": u.role != "admin" and not live,
        "email_verified": verified,
        "needs_email_verification": u.role != "admin" and not verified,
    }


def _is_deleted_user(u: models.User) -> bool:
    email = (u.email or "").lower()
    return email.startswith("deleted+") and email.endswith("@invalid.local")


@router.post("/register")
async def register(data: RegisterIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    check_rate_limit(f"register:{ip}", limit=5, window_sec=300)
    email = data.email.strip().lower()
    check_rate_limit(f"register-email:{email}", limit=5, window_sec=3600)
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Enter a valid email address")
    if db.query(models.User).filter_by(email=email).first():
        raise HTTPException(400, "An account with that email already exists")
    _validate_password(data.password)
    user = models.User(
        email=email,
        name=data.name.strip(),
        password_hash=hash_password(data.password),
        plan="none",
        subscription_active=False,
        email_verified=False,
        token_version=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(
        models.Balance(
            user_id=user.id, credits=0.0, tokens_included=0, tokens_used_period=0
        )
    )
    db.commit()

    raw_token = _issue_email_token(db, user, purpose="verify")
    sent, detail = await _send_verification_email(user, raw_token)

    out = {
        "token": _issue_session(user),
        "user": user_out(user),
        "preferred_company_name": data.company_name.strip() or None,
        "verification_email_sent": sent,
        "verification_detail": detail,
    }
    if not sent and not config.IS_PRODUCTION:
        out["dev_verification_token"] = raw_token
        out["dev_verification_link"] = _verification_link(raw_token)
    return out


@router.post("/login")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    check_rate_limit(f"login:{ip}", limit=20, window_sec=60)
    email = (data.email or "").strip().lower()
    password = data.password or ""
    if not email or not password:
        raise HTTPException(400, "Email and password are required")
    check_rate_limit(f"login-email:{email}", limit=10, window_sec=300)
    try:
        user = db.query(models.User).filter_by(email=email).first()
    except Exception as e:
        raise HTTPException(
            503,
            f"Database unavailable. Ensure DATABASE_URL is set and the app finished startup. ({type(e).__name__})",
        ) from e
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    if _is_deleted_user(user):
        raise HTTPException(401, "This account has been deleted")
    try:
        token = _issue_session(user)
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
def update_me(
    data: ProfileIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    u = db.get(models.User, user.id)
    if data.name is not None:
        u.name = data.name.strip()
    if data.password:
        _validate_password(data.password)
        u.password_hash = hash_password(data.password)
        _bump_token_version(u)
    db.commit()
    db.refresh(u)
    if data.password:
        # Fresh JWT; prior sessions fail token_version check
        return {**user_out(u), "token": _issue_session(u)}
    return user_out(u)


@router.post("/forgot-password")
async def forgot_password(
    data: ForgotPasswordIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Always returns {ok: true} (no email enumeration).
    If account exists: create EmailToken purpose=reset, email link via Resend when configured.
    Non-production without Resend: log token and include dev_reset_token in response.
    """
    ip = client_ip(request)
    check_rate_limit(f"forgot-password:{ip}", limit=5, window_sec=900)

    email = (data.email or "").strip().lower()
    ok_body: dict = {
        "ok": True,
        "message": "If an account exists for that email, password reset instructions have been sent.",
    }
    if not email or "@" not in email:
        return ok_body

    check_rate_limit(f"forgot-password-email:{email}", limit=3, window_sec=3600)

    try:
        user = db.query(models.User).filter_by(email=email).first()
    except Exception as e:
        log.warning("forgot-password db error: %s", type(e).__name__)
        return ok_body

    if not user or _is_deleted_user(user):
        return ok_body

    raw = _issue_email_token(db, user, purpose="reset", ttl=_RESET_TOKEN_TTL)
    sent, detail = False, ""
    try:
        sent, detail = await _send_reset_email(user, raw)
    except Exception as e:
        detail = str(e)
        log.warning("forgot-password email error: %s", e)

    if not sent:
        if not config.IS_PRODUCTION:
            log.warning(
                "password-reset token for %s (not emailed): %s | detail=%s",
                email,
                raw,
                detail,
            )
            return {
                **ok_body,
                "dev_reset_token": raw,
                "dev_reset_link": _reset_link(raw),
                "email_sent": False,
                "email_detail": detail,
            }
        log.error("password-reset email failed for user_id=%s: %s", user.id, detail)

    return {**ok_body, "email_sent": sent}


@router.post("/reset-password")
def reset_password(
    data: ResetPasswordIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Validate one-time reset token, set password, mark token used, bump token_version."""
    ip = client_ip(request)
    check_rate_limit(f"reset-password:{ip}", limit=10, window_sec=300)

    raw = (data.token or "").strip()
    if not raw or len(raw) < 16:
        raise HTTPException(400, "Invalid or expired reset link")

    _validate_password(data.password)
    th = _hash_email_token(raw)
    now = datetime.utcnow()

    row = (
        db.query(models.EmailToken)
        .filter_by(token_hash=th, purpose="reset")
        .first()
    )
    if not row or row.used_at is not None or row.expires_at < now:
        raise HTTPException(400, "Invalid or expired reset link")

    user = db.get(models.User, row.user_id)
    if not user or _is_deleted_user(user):
        raise HTTPException(400, "Invalid or expired reset link")

    user.password_hash = hash_password(data.password)
    _bump_token_version(user)
    row.used_at = now
    for other in (
        db.query(models.EmailToken)
        .filter_by(user_id=user.id, purpose="reset")
        .filter(models.EmailToken.used_at.is_(None))
        .filter(models.EmailToken.id != row.id)
        .all()
    ):
        other.used_at = now

    db.commit()
    db.refresh(user)

    return {
        "ok": True,
        "message": "Password updated. You can sign in with your new password.",
        "token": _issue_session(user),
        "user": user_out(user),
    }


@router.post("/verify-email")
def verify_email(data: VerifyEmailIn, request: Request, db: Session = Depends(get_db)):
    """Consume a one-time verification token and mark the user email as verified."""
    ip = client_ip(request)
    check_rate_limit(f"verify-email:{ip}", limit=30, window_sec=300)
    raw = (data.token or "").strip()
    if not raw:
        raise HTTPException(400, "Verification token is required")
    th = _hash_email_token(raw)
    row = (
        db.query(models.EmailToken)
        .filter_by(token_hash=th, purpose="verify")
        .first()
    )
    if not row:
        raise HTTPException(400, "Invalid or expired verification link")
    if row.used_at is not None:
        raise HTTPException(400, "This verification link was already used")
    if row.expires_at < datetime.utcnow():
        raise HTTPException(400, "This verification link has expired — request a new one")
    user = db.get(models.User, row.user_id)
    if not user:
        raise HTTPException(400, "Invalid or expired verification link")
    row.used_at = datetime.utcnow()
    user.email_verified = True
    for other in (
        db.query(models.EmailToken)
        .filter_by(user_id=user.id, purpose="verify")
        .filter(models.EmailToken.used_at.is_(None))
        .filter(models.EmailToken.id != row.id)
        .all()
    ):
        other.used_at = row.used_at
    db.commit()
    db.refresh(user)
    return {"ok": True, "user": user_out(user)}


@router.post("/resend-verification")
async def resend_verification(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Auth-required: issue a new verification email for the current user."""
    ip = client_ip(request)
    check_rate_limit(f"resend-verify:{ip}", limit=5, window_sec=300)
    check_rate_limit(f"resend-verify-user:{user.id}", limit=3, window_sec=3600)
    u = db.get(models.User, user.id)
    if not u:
        raise HTTPException(401, "Not authenticated")
    if getattr(u, "email_verified", False):
        return {
            "ok": True,
            "already_verified": True,
            "user": user_out(u),
            "message": "Email is already verified",
        }
    raw_token = _issue_email_token(db, u, purpose="verify")
    sent, detail = await _send_verification_email(u, raw_token)
    out = {
        "ok": True,
        "already_verified": False,
        "verification_email_sent": sent,
        "verification_detail": detail,
        "user": user_out(u),
    }
    if not sent and not config.IS_PRODUCTION:
        out["dev_verification_token"] = raw_token
        out["dev_verification_link"] = _verification_link(raw_token)
    return out


@router.get("/export")
@router.post("/export-data")
def export_my_data(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """GDPR-style JSON export of the caller's own profile and workspace summary.

    GET /auth/export is canonical; POST /auth/export-data is a compatibility alias.
    """
    if _is_deleted_user(user):
        raise HTTPException(410, "Account has been deleted")

    companies = (
        db.query(models.Company)
        .filter(models.Company.owner_user_id == user.id)
        .all()
    )
    agents = db.query(models.Agent).filter(models.Agent.user_id == user.id).all()
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    usage_rows = (
        db.query(models.TokenUsage)
        .filter(models.TokenUsage.user_id == user.id)
        .order_by(models.TokenUsage.created_at.desc())
        .limit(500)
        .all()
    )
    total_in = sum(int(r.input_tokens or 0) for r in usage_rows)
    total_out = sum(int(r.output_tokens or 0) for r in usage_rows)
    total_cost = round(sum(float(r.cost or 0) for r in usage_rows), 6)
    by_model: dict[str, dict] = {}
    for r in usage_rows:
        m = r.model or "unknown"
        slot = by_model.setdefault(
            m, {"input_tokens": 0, "output_tokens": 0, "cost": 0.0, "events": 0}
        )
        slot["input_tokens"] += int(r.input_tokens or 0)
        slot["output_tokens"] += int(r.output_tokens or 0)
        slot["cost"] = round(slot["cost"] + float(r.cost or 0), 6)
        slot["events"] += 1

    meter = None
    try:
        meter = meter_snapshot(db, user)
    except Exception:
        meter = None

    return {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "profile": {
            "id": user.id,
            "email": user.email,
            "name": user.name or "",
            "role": user.role,
            "plan": user.plan,
            "subscription_active": bool(user.subscription_active),
            "subscription_expires_at": (
                user.subscription_expires_at.isoformat() + "Z"
                if getattr(user, "subscription_expires_at", None)
                else None
            ),
            "created_at": (
                user.created_at.isoformat() + "Z" if user.created_at else None
            ),
            "email_verified": bool(getattr(user, "email_verified", False)),
        },
        "companies": [
            {
                "id": c.id,
                "name": c.name,
                "industry": c.industry or "",
                "notes": c.notes or "",
                "created_at": c.created_at.isoformat() + "Z" if c.created_at else None,
            }
            for c in companies
        ],
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "template_type": a.template_type,
                "hierarchy_role": getattr(a, "hierarchy_role", None),
                "status": a.status,
                "company_id": a.company_id,
            }
            for a in agents
        ],
        "usage_summary": {
            "balance": {
                "credits": float(bal.credits or 0) if bal else 0.0,
                "tokens_included": int(bal.tokens_included or 0) if bal else 0,
                "tokens_used_period": int(bal.tokens_used_period or 0) if bal else 0,
                "period_start": (
                    bal.period_start.isoformat() + "Z"
                    if bal and bal.period_start
                    else None
                ),
            },
            "meter": meter,
            "recent_usage_events_capped": len(usage_rows),
            "totals_from_recent_events": {
                "input_tokens": total_in,
                "output_tokens": total_out,
                "cost_usd": total_cost,
            },
            "by_model": by_model,
        },
    }


def _scrub_account(db: Session, u: models.User) -> None:
    """Deactivate and scrub PII. Prefer scrub over hard-delete: many FKs lack ON DELETE CASCADE."""
    uid = u.id
    u.email = f"deleted+{uid}@invalid.local"
    u.name = ""
    u.password_hash = hash_password(secrets.token_urlsafe(48))
    _bump_token_version(u)
    u.subscription_active = False
    u.plan = "none"
    u.subscription_expires_at = None
    if hasattr(u, "email_verified"):
        u.email_verified = False
    for a in db.query(models.Agent).filter(models.Agent.user_id == uid).all():
        a.status = "deleted"
    bal = db.query(models.Balance).filter_by(user_id=uid).first()
    if bal:
        bal.credits = 0.0
        bal.tokens_included = 0
        bal.tokens_used_period = 0
        bal.auto_topup_enabled = False
    if hasattr(models, "UserApiKey"):
        for k in db.query(models.UserApiKey).filter_by(user_id=uid).all():
            k.encrypted_value = ""
            if hasattr(k, "is_active"):
                k.is_active = False
            if hasattr(k, "hint"):
                k.hint = ""
    if hasattr(models, "IntegrationConnection"):
        for conn in db.query(models.IntegrationConnection).filter_by(user_id=uid).all():
            if hasattr(conn, "encrypted_secrets"):
                conn.encrypted_secrets = ""
            conn.status = "disconnected"
            if hasattr(conn, "meta_json"):
                conn.meta_json = "{}"
    now = datetime.utcnow()
    for t in (
        db.query(models.EmailToken)
        .filter_by(user_id=uid)
        .filter(models.EmailToken.used_at.is_(None))
        .all()
    ):
        t.used_at = now


@router.post("/delete-account")
def delete_account(
    data: DeleteAccountIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """GDPR-style account deletion: verify password, scrub identity, deactivate workspace."""
    if _is_deleted_user(user):
        raise HTTPException(410, "Account has already been deleted")
    if user.role == "admin":
        admin_count = db.query(models.User).filter(models.User.role == "admin").count()
        if admin_count <= 1:
            raise HTTPException(400, "Cannot delete the last admin account")
    if not verify_password(data.password or "", user.password_hash):
        raise HTTPException(401, "Incorrect password")
    u = db.get(models.User, user.id)
    _scrub_account(db, u)
    db.commit()
    return {
        "ok": True,
        "message": "Account deleted. Personal identifiers have been scrubbed.",
    }


@router.delete("/me")
def delete_me(
    data: DeleteAccountIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Alias for POST /auth/delete-account (password required in JSON body)."""
    return delete_account(data, db, user)
