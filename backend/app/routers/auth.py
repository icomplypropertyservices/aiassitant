"""Auth routes: register/login, email verify, password reset, profile, GDPR export/delete."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
import os
import secrets
import re
import time
from urllib.parse import urlencode, quote

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, config
from ..auth_utils import (
    hash_password,
    verify_password,
    get_current_user,
    hash_reset_token,
    issue_session_api_key,
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
_OTP_TTL = timedelta(minutes=10)


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


def _issue_session(db: Session, user: models.User) -> str:
    """Issue session API key (aba_…). Returned once; stored hashed."""
    return issue_session_api_key(db, user)


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


async def _send_reset_email(
    user: models.User,
    raw_token: str,
    otp_code: str | None = None,
) -> tuple[bool, str]:
    link = _reset_link(raw_token)
    name = (user.name or "").strip() or "there"
    subject = "Reset your password — AI Business Assistant"
    code_block = ""
    if otp_code:
        code_block = (
            f"Or enter this verification code on the reset page (expires in 10 minutes):\n\n"
            f"    {otp_code}\n\n"
        )
    body = (
        f"Hi {name},\n\n"
        f"We received a request to reset the password for {user.email}.\n\n"
        f"Open this link to choose a new password (expires in 1 hour):\n\n"
        f"{link}\n\n"
        f"{code_block}"
        f"If you did not request this, you can ignore this email.\n"
    )
    return await send_email(user.email, subject, body)


def _otp_hash(user_id: int, purpose: str, code: str) -> str:
    return _hash_email_token(f"{user_id}:{purpose}:{code.strip()}")


def _issue_otp(
    db: Session,
    user: models.User,
    purpose: str,
    ttl: timedelta | None = None,
) -> str:
    """Issue a 6-digit email OTP. Returns the raw code (send via email once)."""
    now = datetime.utcnow()
    for old in (
        db.query(models.EmailToken)
        .filter_by(user_id=user.id, purpose=purpose)
        .filter(models.EmailToken.used_at.is_(None))
        .all()
    ):
        old.used_at = now
    code = f"{secrets.randbelow(1_000_000):06d}"
    row = models.EmailToken(
        user_id=user.id,
        purpose=purpose,
        token_hash=_otp_hash(user.id, purpose, code),
        expires_at=now + (ttl or _OTP_TTL),
    )
    db.add(row)
    db.commit()
    return code


def _consume_otp(
    db: Session,
    user: models.User,
    purpose: str,
    code: str,
) -> bool:
    """Validate and consume a 6-digit OTP. Returns True if ok."""
    raw = (code or "").strip().replace(" ", "")
    if not raw or not raw.isdigit() or len(raw) != 6:
        return False
    th = _otp_hash(user.id, purpose, raw)
    now = datetime.utcnow()
    row = (
        db.query(models.EmailToken)
        .filter_by(user_id=user.id, purpose=purpose, token_hash=th)
        .filter(models.EmailToken.used_at.is_(None))
        .first()
    )
    if not row or row.expires_at < now:
        return False
    row.used_at = now
    for other in (
        db.query(models.EmailToken)
        .filter_by(user_id=user.id, purpose=purpose)
        .filter(models.EmailToken.used_at.is_(None))
        .filter(models.EmailToken.id != row.id)
        .all()
    ):
        other.used_at = now
    db.flush()
    return True


async def _send_otp_email(
    user: models.User,
    code: str,
    *,
    subject: str,
    reason: str,
) -> tuple[bool, str]:
    name = (user.name or "").strip() or "there"
    body = (
        f"Hi {name},\n\n"
        f"{reason}\n\n"
        f"Your verification code is:\n\n"
        f"    {code}\n\n"
        f"This code expires in 10 minutes. If you did not request this, "
        f"secure your account and ignore this email.\n"
    )
    return await send_email(user.email, subject, body)


def _email_hint(email: str) -> str:
    email = (email or "").strip()
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        masked = local[:1] + "***"
    else:
        masked = local[:2] + "***"
    return f"{masked}@{domain}"


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
    # Password change without email OTP is rejected when twofa_enabled or always prefer OTP path
    password: str | None = Field(default=None, min_length=8)
    current_password: str | None = None
    otp_code: str | None = None


class VerifyEmailIn(BaseModel):
    token: str


class ForgotPasswordIn(BaseModel):
    email: str


class ResetPasswordIn(BaseModel):
    token: str | None = None  # link token OR omit when using email+code
    email: str | None = None
    code: str | None = None  # 6-digit email verification code
    password: str = Field(min_length=8)


class TwoFaCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)
    email: str | None = None  # required for login challenge


class TwoFaLoginIn(BaseModel):
    email: str
    code: str = Field(min_length=6, max_length=8)


class PasswordChangeStartIn(BaseModel):
    current_password: str


class PasswordChangeIn(BaseModel):
    current_password: str
    password: str = Field(min_length=8)
    code: str = Field(min_length=6, max_length=8)


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
    twofa = bool(getattr(u, "twofa_enabled", False))
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
        "twofa_enabled": twofa,
        "twofa_method": "email" if twofa else None,
        "has_api_key": bool(getattr(u, "api_key_hash", None)),
        "api_key_prefix": getattr(u, "api_key_prefix", None),
        "auth_type": "api_key",
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
    # Create account, then auto-activate Free trial so first login can create agents
    # (ensure-orchestrator / chat / meetings) without a separate Billing click.
    # Limits: plans.PLANS["trial"] — 10 agents, 2 companies, 50k tokens, 14 days (one-shot).
    # Paid plans are NOT granted here; Stripe/crypto still required via /billing/plan.
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

    # Shared path with POST /billing/plan: plan=trial, expires_at, token pool, company.
    # Production never mints free wallet credits (see billing._activate_plan).
    company_name = (data.company_name or "").strip() or None
    trial_started = False
    try:
        from .billing import _activate_plan
        from ..plans import TRIAL_DAYS, TRIAL_TOKENS_INCLUDED, plan_limits

        user = _activate_plan(db, user, "trial", company_name)
        db.refresh(user)
        trial_started = bool(
            user.subscription_active and (user.plan or "") == "trial"
        )
        # Inline fallback if activate returned without applying trial (should not happen)
        if not trial_started:
            limits = plan_limits("trial")
            user.plan = "trial"
            user.subscription_active = True
            if not getattr(user, "subscription_expires_at", None):
                user.subscription_expires_at = datetime.utcnow() + timedelta(days=TRIAL_DAYS)
            bal = db.query(models.Balance).filter_by(user_id=user.id).first()
            if not bal:
                bal = models.Balance(user_id=user.id, credits=0.0)
                db.add(bal)
                db.flush()
            bal.tokens_included = int(limits.get("tokens_included") or TRIAL_TOKENS_INCLUDED)
            bal.tokens_used_period = 0
            bal.period_start = datetime.utcnow().replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            db.commit()
            db.refresh(user)
            trial_started = True
    except Exception as e:
        # Keep the account; attempt minimal inline trial so first login is usable.
        # User can still POST /billing/plan {"plan":"trial"} if this also fails.
        log.warning(
            "register trial activation failed for user_id=%s: %s: %s",
            user.id,
            type(e).__name__,
            e,
            exc_info=True,
        )
        try:
            from ..plans import TRIAL_DAYS, TRIAL_TOKENS_INCLUDED, plan_limits

            limits = plan_limits("trial")
            user.plan = "trial"
            user.subscription_active = True
            if not getattr(user, "subscription_expires_at", None):
                user.subscription_expires_at = datetime.utcnow() + timedelta(days=TRIAL_DAYS)
            bal = db.query(models.Balance).filter_by(user_id=user.id).first()
            if not bal:
                bal = models.Balance(user_id=user.id, credits=0.0)
                db.add(bal)
                db.flush()
            if int(bal.tokens_included or 0) <= 0:
                bal.tokens_included = int(limits.get("tokens_included") or TRIAL_TOKENS_INCLUDED)
                bal.tokens_used_period = 0
                bal.period_start = datetime.utcnow().replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                )
            db.commit()
            db.refresh(user)
            trial_started = bool(
                user.subscription_active and (user.plan or "") == "trial"
            )
        except Exception as e2:
            log.warning(
                "register inline trial fallback failed for user_id=%s: %s: %s",
                user.id,
                type(e2).__name__,
                e2,
                exc_info=True,
            )
            bal = db.query(models.Balance).filter_by(user_id=user.id).first()
            if not bal:
                db.add(
                    models.Balance(
                        user_id=user.id,
                        credits=0.0,
                        tokens_included=0,
                        tokens_used_period=0,
                    )
                )
                db.commit()

    # Every account gets a primary "My Human" for human task delegation with agents
    try:
        from ..human_service import ensure_my_human
        ensure_my_human(db, user)
        db.commit()
    except Exception as e:
        log.warning("ensure_my_human failed for user_id=%s: %s", user.id, e)

    # Fresh accounts: Main AI Orchestrator only (no shared/demo team data).
    # Users hire extra agents later via spawn / Core Team ensure / seed-starter-team.
    try:
        if user.subscription_active or user.role == "admin":
            from ..agent_hierarchy import ensure_main_orchestrator
            ensure_main_orchestrator(db, user)
    except Exception as e:
        log.warning("ensure_main_orchestrator failed for user_id=%s: %s", user.id, e)

    raw_token = _issue_email_token(db, user, purpose="verify")
    sent, detail = await _send_verification_email(user, raw_token)

    api_key = _issue_session(db, user)
    out = {
        "token": api_key,  # legacy field name — value is session API key (aba_…)
        "api_key": api_key,
        "auth_type": "api_key",
        "user": user_out(user),
        "preferred_company_name": company_name,
        "verification_email_sent": sent,
        "verification_detail": detail,
        "trial_started": trial_started,
    }
    if not sent and not config.IS_PRODUCTION:
        out["dev_verification_token"] = raw_token
        out["dev_verification_link"] = _verification_link(raw_token)
    return out


@router.post("/login")
async def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    check_rate_limit(f"login:{ip}", limit=20, window_sec=60)
    email = (data.email or "").strip().lower()
    password = data.password or ""
    if not email or not password:
        raise HTTPException(400, "Email and password are required")
    # Shared demo/e2e accounts + multi-tab clients need more than 10/5m without blocking legit use
    check_rate_limit(f"login-email:{email}", limit=40, window_sec=300)
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

    # Email 2FA: password OK → send OTP, do not issue session yet
    if bool(getattr(user, "twofa_enabled", False)):
        check_rate_limit(f"2fa-login-send:{user.id}", limit=5, window_sec=900)
        code = _issue_otp(db, user, purpose="2fa_login", ttl=_OTP_TTL)
        sent, detail = False, ""
        try:
            sent, detail = await _send_otp_email(
                user,
                code,
                subject="Your sign-in code — AI Business Assistant",
                reason="Someone is signing in to your AI Business Assistant account. Enter this code to continue.",
            )
        except Exception as e:
            detail = str(e)
            log.warning("2fa login email error: %s", e)
        out = {
            "ok": True,
            "requires_2fa": True,
            "twofa_method": "email",
            "email_hint": _email_hint(user.email),
            "message": "We sent a 6-digit verification code to your email. Enter it to finish signing in.",
            "email_sent": sent,
            "expires_in_sec": int(_OTP_TTL.total_seconds()),
        }
        if not sent and not config.IS_PRODUCTION:
            out["dev_otp_code"] = code
            out["email_detail"] = detail
        return out

    try:
        api_key = _issue_session(db, user)
    except Exception as e:
        raise HTTPException(500, f"Could not issue API key: {type(e).__name__}") from e
    return {
        "token": api_key,
        "api_key": api_key,
        "auth_type": "api_key",
        "requires_2fa": False,
        "user": user_out(user),
    }


# ── Google Sign-in / Sign-up (OIDC via OAuth 2.0) ─────────────────────────

_GOOGLE_AUTH_SCOPES = "openid email profile"
_GOOGLE_AUTH_STATE_TTL = 15 * 60  # seconds


def _google_oauth_credentials() -> tuple[str, str]:
    cid = (os.getenv("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    csec = (os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()
    return cid, csec


def _google_auth_redirect_uri() -> str:
    """Must be listed in Google Cloud Console → Authorized redirect URIs."""
    explicit = (os.getenv("GOOGLE_AUTH_REDIRECT_URI") or "").strip().rstrip("/")
    if explicit:
        # Prefer apex when product host is used
        if "://www.aibusinessagent.xyz/" in explicit:
            explicit = explicit.replace(
                "://www.aibusinessagent.xyz/", "://aibusinessagent.xyz/"
            )
        return explicit
    # Prefer production apex pin
    if getattr(config, "IS_PRODUCTION", False) or "aibusinessagent.xyz" in (
        (config.API_PUBLIC_URL or "") + (config.FRONTEND_URL or "")
    ):
        return "https://aibusinessagent.xyz/api/auth/google/callback"
    api = (config.API_PUBLIC_URL or "").rstrip("/")
    # Local SPA (Vite :5173) is not the API host — FastAPI defaults to :8000
    if api and "localhost:5173" not in api and "127.0.0.1:5173" not in api:
        if api.endswith("/api"):
            return f"{api}/auth/google/callback"
        return f"{api}/api/auth/google/callback"
    return "http://localhost:8000/auth/google/callback"


def _encode_google_auth_state(intent: str, next_path: str | None = None) -> str:
    payload = {
        "purpose": "google_auth",
        "intent": intent if intent in ("login", "register") else "login",
        "nonce": secrets.token_hex(8),
        "exp": int(time.time()) + _GOOGLE_AUTH_STATE_TTL,
    }
    if next_path:
        payload["next"] = str(next_path)[:200]
    token = jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")
    if isinstance(token, bytes):
        return token.decode("utf-8")
    return str(token)


def _decode_google_auth_state(state: str) -> dict:
    try:
        data = jwt.decode(state, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(400, f"Invalid or expired OAuth state: {e}") from e
    if data.get("purpose") != "google_auth":
        raise HTTPException(400, "Invalid OAuth state purpose")
    return data


async def _bootstrap_new_user(
    db: Session,
    user: models.User,
    *,
    company_name: str | None = None,
) -> None:
    """Trial + My Human + Main Orchestrator only for newly created Google accounts."""
    try:
        from .billing import _activate_plan

        _activate_plan(db, user, "trial", company_name)
        db.refresh(user)
    except Exception as e:
        log.warning("google_auth trial activate failed user_id=%s: %s", user.id, e)
        try:
            from ..plans import TRIAL_DAYS, TRIAL_TOKENS_INCLUDED, plan_limits

            limits = plan_limits("trial")
            user.plan = "trial"
            user.subscription_active = True
            user.subscription_expires_at = datetime.utcnow() + timedelta(days=TRIAL_DAYS)
            bal = db.query(models.Balance).filter_by(user_id=user.id).first()
            if not bal:
                bal = models.Balance(user_id=user.id, credits=0.0)
                db.add(bal)
                db.flush()
            bal.tokens_included = int(limits.get("tokens_included") or TRIAL_TOKENS_INCLUDED)
            bal.tokens_used_period = 0
            bal.period_start = datetime.utcnow().replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            db.commit()
            db.refresh(user)
        except Exception as e2:
            log.warning("google_auth trial fallback failed user_id=%s: %s", user.id, e2)
    try:
        from ..human_service import ensure_my_human
        ensure_my_human(db, user)
        db.commit()
    except Exception as e:
        log.warning("google_auth ensure_my_human failed: %s", e)
    # Orchestrator only — do not seed a full shared-looking core team
    try:
        if user.subscription_active or user.role == "admin":
            from ..agent_hierarchy import ensure_main_orchestrator
            ensure_main_orchestrator(db, user)
    except Exception as e:
        log.warning("google_auth ensure_main_orchestrator failed: %s", e)


@router.get("/oauth/providers")
def oauth_providers():
    """Public: which social auth providers are configured (no secrets)."""
    g_id, g_sec = _google_oauth_credentials()
    return {
        "google": {
            "enabled": bool(g_id and g_sec),
            "redirect_uri": _google_auth_redirect_uri() if (g_id and g_sec) else None,
            "console_hint": (
                "Add this Authorized redirect URI in Google Cloud Console → "
                f"{_google_auth_redirect_uri()}"
            ),
        },
        "x": {
            "enabled": bool(
                (os.getenv("X_CLIENT_ID") or "").strip()
                and (os.getenv("X_CLIENT_SECRET") or "").strip()
            ),
            "note": "X is for Connected apps (posting), not account login yet.",
        },
    }


@router.get("/google/start")
def google_auth_start(
    request: Request,
    intent: str = Query("login", description="login | register"),
    next: str | None = Query(None, description="Frontend path after success"),
):
    """Begin Google sign-in / sign-up. Returns authorize_url for the SPA to redirect."""
    ip = client_ip(request)
    check_rate_limit(f"google-auth-start:{ip}", limit=30, window_sec=60)
    client_id, client_secret = _google_oauth_credentials()
    if not client_id or not client_secret:
        raise HTTPException(
            503,
            "Google sign-in is not configured. Set GOOGLE_OAUTH_CLIENT_ID and "
            "GOOGLE_OAUTH_CLIENT_SECRET on the server.",
        )
    intent = (intent or "login").strip().lower()
    if intent not in ("login", "register"):
        intent = "login"
    redirect_uri = _google_auth_redirect_uri()
    state = _encode_google_auth_state(intent, next)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _GOOGLE_AUTH_SCOPES,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    authorize_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        + urlencode(params)
    )
    return {
        "ok": True,
        "provider": "google",
        "intent": intent,
        "authorize_url": authorize_url,
        "redirect_uri": redirect_uri,
        "hint": (
            "If Google shows redirect_uri_mismatch, add this exact URI under "
            f"Authorized redirect URIs: {redirect_uri}"
        ),
    }


@router.get("/google/callback")
async def google_auth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: Session = Depends(get_db),
):
    """Google redirects here after consent. Creates/logs in user and sends SPA a session key."""
    frontend = _frontend_base()
    # SPA login lives at /login under /agents in production
    login_path = f"{frontend}/login"

    def _fail(msg: str):
        return RedirectResponse(
            f"{login_path}?oauth=error&provider=google&message={quote(str(msg)[:300])}",
            status_code=302,
        )

    if error:
        return _fail(error_description or error)
    if not code or not state:
        return _fail("missing_code_or_state")

    try:
        st = _decode_google_auth_state(state)
    except HTTPException as e:
        return _fail(str(e.detail))

    intent = st.get("intent") or "login"
    client_id, client_secret = _google_oauth_credentials()
    if not client_id or not client_secret:
        return _fail("server_missing_google_credentials")
    redirect_uri = _google_auth_redirect_uri()

    # Exchange code → tokens
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            tr = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            tokens = tr.json() if tr.content else {}
            if tr.status_code >= 400 or not tokens.get("access_token"):
                err = (
                    tokens.get("error_description")
                    or tokens.get("error")
                    or tr.text[:200]
                )
                log.warning("google_auth token_exchange failed: %s", err)
                return _fail(f"token_exchange_failed:{err}")

            ur = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            info = ur.json() if ur.content else {}
            if ur.status_code >= 400:
                return _fail("userinfo_failed")
    except Exception as e:
        log.exception("google_auth callback error")
        return _fail(f"oauth_error:{e}")

    email = (info.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return _fail("google_account_missing_email")
    if info.get("email_verified") is False:
        return _fail("google_email_not_verified")

    name = (info.get("name") or info.get("given_name") or "").strip()
    picture = (info.get("picture") or "").strip()
    google_sub = (info.get("sub") or "").strip()

    user = db.query(models.User).filter_by(email=email).first()
    is_new = False
    if user:
        if _is_deleted_user(user):
            return _fail("account_deleted")
        # Mark verified (Google confirmed ownership)
        if not getattr(user, "email_verified", False):
            user.email_verified = True
            db.commit()
        # Optional: skip 2FA for Google OAuth (passwordless identity already proven)
        # Still enforce 2FA for security if enabled — issue session only after...
        # For UX, Google login bypasses email OTP when 2FA is on (identity is Google's).
    else:
        # Sign-up via Google (also allowed from login intent — first-time Google users)
        is_new = True
        user = models.User(
            email=email,
            name=name or email.split("@")[0],
            # Unusable random password — account uses Google / password-reset only
            password_hash=hash_password(secrets.token_urlsafe(32)),
            plan="none",
            subscription_active=False,
            email_verified=True,
            token_version=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        await _bootstrap_new_user(db, user)
        db.refresh(user)

    # Store light Google meta on workspace settings if available (non-fatal)
    try:
        if picture or google_sub:
            ws = (
                db.query(models.WorkspaceSettings)
                .filter_by(user_id=user.id)
                .first()
            )
            if ws is not None and hasattr(ws, "meta_json"):
                pass  # no meta_json on WorkspaceSettings in current schema
    except Exception:
        pass

    try:
        api_key = _issue_session(db, user)
    except Exception as e:
        return _fail(f"session_issue_failed:{e}")

    next_path = (st.get("next") or "").strip()
    if next_path and next_path.startswith("/") and not next_path.startswith("//"):
        dest = f"{frontend}{next_path}" if not next_path.startswith(frontend) else next_path
        # Prefer SPA login handoff so setAuth runs; include next for post-login nav
        q = urlencode({
            "oauth": "success",
            "provider": "google",
            "api_key": api_key,
            "is_new": "1" if is_new else "0",
            "next": next_path,
        })
        return RedirectResponse(f"{login_path}?{q}", status_code=302)

    q = urlencode({
        "oauth": "success",
        "provider": "google",
        "api_key": api_key,
        "is_new": "1" if is_new else "0",
    })
    log.info(
        "google_auth ok user_id=%s is_new=%s intent=%s",
        user.id,
        is_new,
        intent,
    )
    return RedirectResponse(f"{login_path}?{q}", status_code=302)


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
        # Password changes require email OTP (+ current password when 2FA on)
        raise HTTPException(
            400,
            "To change your password, use Settings → Security: request an email code "
            "(POST /auth/password/change/start) then POST /auth/password/change with the code.",
        )
    db.commit()
    db.refresh(u)
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
    otp = _issue_otp(db, user, purpose="reset_code", ttl=_OTP_TTL)
    sent, detail = False, ""
    try:
        sent, detail = await _send_reset_email(user, raw, otp_code=otp)
    except Exception as e:
        detail = str(e)
        log.warning("forgot-password email error: %s", e)

    if not sent:
        if not config.IS_PRODUCTION:
            log.warning(
                "password-reset token for %s (not emailed): %s code=%s | detail=%s",
                email,
                raw,
                otp,
                detail,
            )
            return {
                **ok_body,
                "dev_reset_token": raw,
                "dev_reset_link": _reset_link(raw),
                "dev_otp_code": otp,
                "email_sent": False,
                "email_detail": detail,
            }
        log.error("password-reset email failed for user_id=%s: %s", user.id, detail)

    return {
        **ok_body,
        "email_sent": sent,
        "email_hint": _email_hint(email),
        "message": (
            "If an account exists for that email, we sent a reset link and a 6-digit "
            "verification code. Use either to set a new password."
        ),
    }


@router.post("/reset-password")
def reset_password(
    data: ResetPasswordIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Set a new password using either:
    - one-time link token (from email), or
    - email + 6-digit verification code from the same email.
    """
    ip = client_ip(request)
    check_rate_limit(f"reset-password:{ip}", limit=10, window_sec=300)

    _validate_password(data.password)
    now = datetime.utcnow()
    user = None
    row = None

    raw = (data.token or "").strip()
    code = (data.code or "").strip().replace(" ", "")
    email = (data.email or "").strip().lower()

    if raw and len(raw) >= 16:
        th = _hash_email_token(raw)
        row = (
            db.query(models.EmailToken)
            .filter_by(token_hash=th, purpose="reset")
            .first()
        )
        if not row or row.used_at is not None or row.expires_at < now:
            raise HTTPException(400, "Invalid or expired reset link")
        user = db.get(models.User, row.user_id)
    elif code and email and "@" in email:
        user = db.query(models.User).filter_by(email=email).first()
        if not user or _is_deleted_user(user):
            raise HTTPException(400, "Invalid or expired verification code")
        if not _consume_otp(db, user, "reset_code", code):
            raise HTTPException(400, "Invalid or expired verification code")
        # Invalidate link tokens too
        for other in (
            db.query(models.EmailToken)
            .filter_by(user_id=user.id, purpose="reset")
            .filter(models.EmailToken.used_at.is_(None))
            .all()
        ):
            other.used_at = now
    else:
        raise HTTPException(
            400,
            "Provide the reset link token, or your email plus the 6-digit code from the email.",
        )

    if not user or _is_deleted_user(user):
        raise HTTPException(400, "Invalid or expired reset link")

    user.password_hash = hash_password(data.password)
    user.email_verified = True  # proved inbox ownership via reset email
    _bump_token_version(user)
    if row is not None:
        row.used_at = now
        for other in (
            db.query(models.EmailToken)
            .filter_by(user_id=user.id, purpose="reset")
            .filter(models.EmailToken.used_at.is_(None))
            .filter(models.EmailToken.id != row.id)
            .all()
        ):
            other.used_at = now
        for other in (
            db.query(models.EmailToken)
            .filter_by(user_id=user.id, purpose="reset_code")
            .filter(models.EmailToken.used_at.is_(None))
            .all()
        ):
            other.used_at = now

    db.commit()
    db.refresh(user)

    api_key = _issue_session(db, user)
    return {
        "ok": True,
        "message": "Password updated. You can sign in with your new password.",
        "token": api_key,
        "api_key": api_key,
        "auth_type": "api_key",
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


# ── Email 2FA ───────────────────────────────────────────────────────────────


@router.get("/2fa/status")
def twofa_status(user: models.User = Depends(get_current_user)):
    return {
        "twofa_enabled": bool(getattr(user, "twofa_enabled", False)),
        "twofa_method": "email" if getattr(user, "twofa_enabled", False) else None,
        "email_hint": _email_hint(user.email),
        "email_verified": bool(getattr(user, "email_verified", False)),
    }


@router.post("/2fa/enable/start")
async def twofa_enable_start(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Send email OTP to enable 2FA on this account."""
    ip = client_ip(request)
    check_rate_limit(f"2fa-enable:{ip}", limit=8, window_sec=900)
    check_rate_limit(f"2fa-enable-user:{user.id}", limit=5, window_sec=3600)
    u = db.get(models.User, user.id)
    if not u:
        raise HTTPException(401, "Not authenticated")
    if getattr(u, "twofa_enabled", False):
        return {"ok": True, "already_enabled": True, "message": "2FA is already on"}
    code = _issue_otp(db, u, purpose="2fa_enable", ttl=_OTP_TTL)
    sent, detail = await _send_otp_email(
        u,
        code,
        subject="Enable 2FA — AI Business Assistant",
        reason="Confirm this code to turn on email two-factor authentication for your account.",
    )
    out = {
        "ok": True,
        "email_sent": sent,
        "email_hint": _email_hint(u.email),
        "message": "We sent a 6-digit code to your email. Enter it to enable 2FA.",
        "expires_in_sec": int(_OTP_TTL.total_seconds()),
    }
    if not sent and not config.IS_PRODUCTION:
        out["dev_otp_code"] = code
        out["email_detail"] = detail
    return out


@router.post("/2fa/enable/confirm")
def twofa_enable_confirm(
    data: TwoFaCodeIn,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    ip = client_ip(request)
    check_rate_limit(f"2fa-enable-confirm:{ip}", limit=15, window_sec=300)
    u = db.get(models.User, user.id)
    if not u:
        raise HTTPException(401, "Not authenticated")
    if not _consume_otp(db, u, "2fa_enable", data.code):
        raise HTTPException(400, "Invalid or expired verification code")
    u.twofa_enabled = True
    u.email_verified = True
    db.commit()
    db.refresh(u)
    return {
        "ok": True,
        "twofa_enabled": True,
        "message": "Email 2FA is now enabled. You will need a code from your email when signing in.",
        "user": user_out(u),
    }


@router.post("/2fa/disable/start")
async def twofa_disable_start(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    ip = client_ip(request)
    check_rate_limit(f"2fa-disable:{user.id}", limit=5, window_sec=900)
    u = db.get(models.User, user.id)
    if not u:
        raise HTTPException(401, "Not authenticated")
    if not getattr(u, "twofa_enabled", False):
        return {"ok": True, "already_disabled": True, "message": "2FA is already off"}
    code = _issue_otp(db, u, purpose="2fa_disable", ttl=_OTP_TTL)
    sent, detail = await _send_otp_email(
        u,
        code,
        subject="Disable 2FA — AI Business Assistant",
        reason="Confirm this code to turn off email two-factor authentication.",
    )
    out = {
        "ok": True,
        "email_sent": sent,
        "email_hint": _email_hint(u.email),
        "message": "We sent a code to your email. Enter it to disable 2FA.",
    }
    if not sent and not config.IS_PRODUCTION:
        out["dev_otp_code"] = code
        out["email_detail"] = detail
    return out


@router.post("/2fa/disable/confirm")
def twofa_disable_confirm(
    data: TwoFaCodeIn,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    ip = client_ip(request)
    check_rate_limit(f"2fa-disable-confirm:{ip}", limit=15, window_sec=300)
    u = db.get(models.User, user.id)
    if not u:
        raise HTTPException(401, "Not authenticated")
    if not _consume_otp(db, u, "2fa_disable", data.code):
        raise HTTPException(400, "Invalid or expired verification code")
    u.twofa_enabled = False
    db.commit()
    db.refresh(u)
    return {
        "ok": True,
        "twofa_enabled": False,
        "message": "Email 2FA has been turned off.",
        "user": user_out(u),
    }


@router.post("/2fa/login/verify")
def twofa_login_verify(
    data: TwoFaLoginIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Complete login after password step when 2FA is enabled."""
    ip = client_ip(request)
    check_rate_limit(f"2fa-login-verify:{ip}", limit=20, window_sec=300)
    email = (data.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Email is required")
    check_rate_limit(f"2fa-login-verify-email:{email}", limit=10, window_sec=300)
    user = db.query(models.User).filter_by(email=email).first()
    if not user or _is_deleted_user(user):
        raise HTTPException(401, "Invalid verification code")
    if not getattr(user, "twofa_enabled", False):
        raise HTTPException(400, "2FA is not enabled for this account")
    if not _consume_otp(db, user, "2fa_login", data.code):
        raise HTTPException(401, "Invalid or expired verification code")
    user.email_verified = True
    db.commit()
    api_key = _issue_session(db, user)
    return {
        "ok": True,
        "token": api_key,
        "api_key": api_key,
        "auth_type": "api_key",
        "requires_2fa": False,
        "user": user_out(user),
    }


@router.post("/2fa/login/resend")
async def twofa_login_resend(
    data: ForgotPasswordIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Resend login OTP (rate limited). Does not confirm password again."""
    ip = client_ip(request)
    check_rate_limit(f"2fa-resend:{ip}", limit=5, window_sec=900)
    email = (data.email or "").strip().lower()
    ok = {
        "ok": True,
        "message": "If 2FA is pending for this account, a new code was sent.",
    }
    if not email or "@" not in email:
        return ok
    user = db.query(models.User).filter_by(email=email).first()
    if not user or not getattr(user, "twofa_enabled", False):
        return ok
    check_rate_limit(f"2fa-resend-user:{user.id}", limit=3, window_sec=900)
    code = _issue_otp(db, user, purpose="2fa_login", ttl=_OTP_TTL)
    sent, detail = await _send_otp_email(
        user,
        code,
        subject="Your sign-in code — AI Business Assistant",
        reason="Here is a new sign-in verification code for your account.",
    )
    out = {**ok, "email_sent": sent, "email_hint": _email_hint(email)}
    if not sent and not config.IS_PRODUCTION:
        out["dev_otp_code"] = code
        out["email_detail"] = detail
    return out


# ── Password change (authenticated, email-verified via OTP) ─────────────────


@router.post("/password/change/start")
async def password_change_start(
    data: PasswordChangeStartIn,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Send email OTP before allowing password change."""
    ip = client_ip(request)
    check_rate_limit(f"pw-change-start:{user.id}", limit=5, window_sec=900)
    u = db.get(models.User, user.id)
    if not u:
        raise HTTPException(401, "Not authenticated")
    if not verify_password(data.current_password or "", u.password_hash):
        raise HTTPException(401, "Current password is incorrect")
    code = _issue_otp(db, u, purpose="password_change", ttl=_OTP_TTL)
    sent, detail = await _send_otp_email(
        u,
        code,
        subject="Confirm password change — AI Business Assistant",
        reason="Enter this code to confirm changing the password on your AI Business Assistant account.",
    )
    out = {
        "ok": True,
        "email_sent": sent,
        "email_hint": _email_hint(u.email),
        "message": "We sent a verification code to your email. Enter it with your new password.",
        "expires_in_sec": int(_OTP_TTL.total_seconds()),
    }
    if not sent and not config.IS_PRODUCTION:
        out["dev_otp_code"] = code
        out["email_detail"] = detail
    return out


@router.post("/password/change")
def password_change(
    data: PasswordChangeIn,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Change password after email OTP verification."""
    ip = client_ip(request)
    check_rate_limit(f"pw-change:{ip}", limit=10, window_sec=300)
    u = db.get(models.User, user.id)
    if not u:
        raise HTTPException(401, "Not authenticated")
    if not verify_password(data.current_password or "", u.password_hash):
        raise HTTPException(401, "Current password is incorrect")
    _validate_password(data.password)
    if not _consume_otp(db, u, "password_change", data.code):
        raise HTTPException(400, "Invalid or expired verification code")
    u.password_hash = hash_password(data.password)
    u.email_verified = True
    _bump_token_version(u)
    db.commit()
    db.refresh(u)
    api_key = _issue_session(db, u)
    return {
        "ok": True,
        "message": "Password updated. Other sessions were signed out.",
        "token": api_key,
        "api_key": api_key,
        "auth_type": "api_key",
        "user": user_out(u),
    }


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
