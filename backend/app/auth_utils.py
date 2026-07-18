import hashlib
import secrets
from datetime import datetime, timedelta

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .database import get_db
from . import models, config

SECRET = config.JWT_SECRET
ALGO = "HS256"
bearer = HTTPBearer(auto_error=False)


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


def create_token(user_id: int, role: str, token_version: int = 0) -> str:
    # Logout is client-side (discard token). Password change bumps token_version
    # so older JWTs fail in get_current_user / user_from_ws_token.
    payload = {
        "sub": str(user_id),
        "role": role,
        "tv": int(token_version or 0),
        "exp": datetime.utcnow() + timedelta(hours=48),
    }
    return jwt.encode(payload, SECRET, algorithm=ALGO)


def decode_token(token: str):
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGO])
    except jwt.PyJWTError:
        return None


def _token_version_ok(user: models.User, payload: dict) -> bool:
    """Reject JWTs issued before the last password change (missing tv treated as 0)."""
    claim = int(payload.get("tv") or 0)
    current = int(getattr(user, "token_version", None) or 0)
    return claim == current


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> models.User:
    if not creds:
        raise HTTPException(401, "Not authenticated")
    payload = decode_token(creds.credentials)
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    user = db.get(models.User, int(payload["sub"]))
    if not user:
        raise HTTPException(401, "User not found")
    if not _token_version_ok(user, payload):
        raise HTTPException(401, "Session expired. Please sign in again.")
    return user


def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != "admin":
        raise HTTPException(403, "Admin access required")
    return user


def user_from_ws_token(token: str, db: Session):
    payload = decode_token(token or "")
    if not payload:
        return None
    user = db.get(models.User, int(payload["sub"]))
    if not user or not _token_version_ok(user, payload):
        return None
    return user


async def accept_and_authenticate_ws(ws, token: str, db: Session):
    """
    Accept WebSocket then authenticate.

    Preferred (no JWT in URL): client connects without query token, then sends
    first text frame: {"type":"auth","token":"<jwt>"}. Server replies {"type":"auth_ok"}.

    Legacy/mobile fallback: ?token=<jwt> still works (no first-message required).

    Returns User on success, or None after closing the socket with code 4401.
    """
    await ws.accept()
    raw = (token or "").strip()
    if not raw:
        try:
            msg = await ws.receive_text()
            import json as _json
            data = _json.loads(msg) if msg else {}
            if isinstance(data, dict) and data.get("type") == "auth":
                raw = (data.get("token") or "").strip()
        except Exception:
            raw = ""
    user = user_from_ws_token(raw, db) if raw else None
    if not user:
        try:
            await ws.close(code=4401)
        except Exception:
            pass
        return None
    # If client used first-message auth, acknowledge (query-token path is silent)
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
