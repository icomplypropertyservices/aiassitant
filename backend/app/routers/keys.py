"""Subscriber API key vault — encrypted at rest, masked on read."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import get_current_user
from ..crypto import encrypt_secret, decrypt_secret, mask_secret
from ..user_keys import PROVIDERS, SMTP_PRESETS, email_channel_status, credentials_for_user
from .. import channels

router = APIRouter(prefix="/keys", tags=["keys"])

_SMTP_FIELD_KEYS = (
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
    "smtp_from",
    "smtp_tls",
)


class KeyIn(BaseModel):
    provider: str
    value: str = Field(min_length=1)
    label: str = ""


class KeyUpdate(BaseModel):
    value: str | None = None
    label: str | None = None
    is_active: bool | None = None


class SmtpSetupIn(BaseModel):
    """Full SMTP profile for Namecheap / Gmail / Outlook / custom."""
    preset: str | None = None  # namecheap | gmail | outlook | yahoo | custom
    smtp_host: str
    smtp_port: int | str = 587
    smtp_user: str
    smtp_password: str | None = None  # omit to keep existing
    smtp_from: str | None = None
    smtp_tls: bool | str = True
    test_to: str | None = None  # optional: send test after save


class SmtpTestIn(BaseModel):
    to: str | None = None


def _key_out(row: models.UserApiKey, include_mask: bool = True) -> dict:
    meta = PROVIDERS.get(row.provider, {})
    secret = meta.get("secret", True)
    return {
        "id": row.id,
        "provider": row.provider,
        "provider_label": meta.get("label", row.provider),
        "label": row.label or "",
        "hint": row.hint or "",
        "masked": (
            (row.hint if not secret else f"{'•' * 12}{row.hint}")
            if row.hint
            else ("••••••••" if secret else None)
        ),
        "is_active": bool(row.is_active),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "encrypted": True,
        "secret": secret,
    }


def _upsert_plain(db: Session, user_id: int, provider: str, value: str, label: str = "") -> models.UserApiKey:
    value = (value or "").strip()
    if not value:
        raise HTTPException(400, f"{provider} value required")
    try:
        encrypted = encrypt_secret(value)
    except Exception as e:
        raise HTTPException(500, f"Encryption failed: {e}") from e
    hint = value[-4:] if len(value) >= 4 else value
    # Non-secret fields can show more context (host, email)
    meta = PROVIDERS.get(provider) or {}
    if meta.get("secret") is False:
        hint = value[:48]
    row = (
        db.query(models.UserApiKey)
        .filter_by(user_id=user_id, provider=provider)
        .first()
    )
    if row:
        row.encrypted_value = encrypted
        row.hint = hint
        if label:
            row.label = label.strip()
        row.is_active = True
        row.updated_at = datetime.utcnow()
    else:
        row = models.UserApiKey(
            user_id=user_id,
            provider=provider,
            label=(label or "").strip(),
            encrypted_value=encrypted,
            hint=hint,
            is_active=True,
        )
        db.add(row)
    return row


@router.get("/providers")
def list_providers(user=Depends(get_current_user)):
    return [
        {"id": k, **v}
        for k, v in PROVIDERS.items()
    ]


@router.get("")
def list_keys(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = (
        db.query(models.UserApiKey)
        .filter_by(user_id=user.id)
        .order_by(models.UserApiKey.provider)
        .all()
    )
    by_provider = {r.provider: _key_out(r) for r in rows}
    # Return one row per known provider + any extras
    catalog = []
    for pid, meta in PROVIDERS.items():
        if pid in by_provider:
            catalog.append(by_provider.pop(pid))
        else:
            catalog.append({
                "id": None,
                "provider": pid,
                "provider_label": meta["label"],
                "label": "",
                "hint": "",
                "masked": None,
                "is_active": False,
                "created_at": None,
                "updated_at": None,
                "encrypted": True,
                "configured": False,
                "status": meta.get("status"),
                "help": meta.get("help"),
            })
    for extra in by_provider.values():
        extra["configured"] = True
        catalog.append(extra)
    for c in catalog:
        meta = PROVIDERS.get(c.get("provider") or "", {})
        if meta:
            c.setdefault("status", meta.get("status"))
            c.setdefault("help", meta.get("help"))
            c.setdefault("provider_label", meta.get("label", c.get("provider")))
        if c.get("id"):
            c["configured"] = True
    return {"keys": catalog, "encryption": "fernet-aes", "note": "Plaintext keys are never returned after save."}


@router.get("/email/status")
def email_status(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """SMTP / Resend readiness + Namecheap-style presets for Settings UI."""
    st = email_channel_status(db, user.id)
    # Non-secret current values for form prefill
    creds = credentials_for_user(db, user.id)
    st["form"] = {
        "smtp_host": creds.get("smtp_host") or "",
        "smtp_port": creds.get("smtp_port") or "587",
        "smtp_user": creds.get("smtp_user") or "",
        "smtp_from": creds.get("smtp_from") or "",
        "smtp_tls": (creds.get("smtp_tls") or "1") not in ("0", "false", "no"),
        "smtp_password_set": bool(creds.get("smtp_password")),
        "resend_set": bool(creds.get("resend")),
    }
    return st


@router.get("/email/presets")
def email_presets(user=Depends(get_current_user)):
    return {"presets": list(SMTP_PRESETS.values())}


@router.put("/email/smtp")
async def save_smtp(
    data: SmtpSetupIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Save full SMTP config (Namecheap Private Email, Gmail SMTP, custom, …)."""
    host = (data.smtp_host or "").strip()
    user_name = (data.smtp_user or "").strip()
    if not host or not user_name:
        raise HTTPException(400, "SMTP host and username are required")
    port = str(data.smtp_port or 587).strip() or "587"
    tls_val = data.smtp_tls
    if isinstance(tls_val, bool):
        tls_s = "1" if tls_val else "0"
    else:
        tls_s = "0" if str(tls_val).lower() in ("0", "false", "no") else "1"
    from_addr = (data.smtp_from or "").strip() or user_name

    # Apply preset host defaults if host empty (already required) — still record preset label
    preset = (data.preset or "").strip().lower()
    if preset in SMTP_PRESETS and not host:
        host = SMTP_PRESETS[preset]["smtp_host"]

    fields = {
        "smtp_host": host,
        "smtp_port": port,
        "smtp_user": user_name,
        "smtp_from": from_addr,
        "smtp_tls": tls_s,
    }
    if data.smtp_password is not None and str(data.smtp_password).strip():
        fields["smtp_password"] = str(data.smtp_password).strip()
    else:
        # Require password on first setup
        existing = credentials_for_user(db, user.id)
        if not existing.get("smtp_password"):
            raise HTTPException(400, "SMTP password is required")

    label = SMTP_PRESETS.get(preset, {}).get("label") or "SMTP"
    for k, v in fields.items():
        _upsert_plain(db, user.id, k, v, label=label if k == "smtp_host" else "")
    db.commit()

    out = {
        "ok": True,
        "message": f"SMTP saved ({host})",
        "status": email_channel_status(db, user.id),
    }
    if data.test_to:
        creds = credentials_for_user(db, user.id)
        to = (data.test_to or user.email or "").strip()
        sent, detail = await channels.send_email(
            to,
            "AI Business Assistant — SMTP test",
            f"This is a test message from your workspace SMTP settings ({host}).\n\nIf you received this, outbound email is working.",
            credentials=creds,
        )
        out["test"] = {"ok": sent, "detail": detail, "to": to}
        if not sent:
            out["message"] = f"SMTP saved but test failed: {detail}"
    return out


@router.post("/email/smtp/test")
async def test_smtp(
    data: SmtpTestIn | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    data = data or SmtpTestIn()
    creds = credentials_for_user(db, user.id)
    if not channels.smtp_or_resend_configured(creds):
        # platform fallback
        from .. import config
        if not (
            config.RESEND_API_KEY
            or (config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASSWORD)
        ):
            raise HTTPException(
                400,
                "No email channel configured. Save SMTP (Namecheap etc.) or Resend under Settings → API keys.",
            )
    to = (data.to or user.email or "").strip()
    if not to or "@" not in to:
        raise HTTPException(400, "Provide a valid test recipient email")
    sent, detail = await channels.send_email(
        to,
        "AI Business Assistant — email channel test",
        "SMTP / Resend test OK. Your workspace can send agent and notify emails.",
        credentials=creds,
    )
    return {"ok": sent, "detail": detail, "to": to, "status": email_channel_status(db, user.id)}


@router.delete("/email/smtp")
def clear_smtp(db: Session = Depends(get_db), user=Depends(get_current_user)):
    for k in _SMTP_FIELD_KEYS:
        row = (
            db.query(models.UserApiKey)
            .filter_by(user_id=user.id, provider=k)
            .first()
        )
        if row:
            db.delete(row)
    db.commit()
    return {"ok": True, "message": "SMTP settings cleared", "status": email_channel_status(db, user.id)}


@router.put("/{provider}")
def upsert_key(provider: str, data: KeyIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    provider = provider.strip().lower()
    if provider not in PROVIDERS and not provider.replace("_", "").isalnum():
        raise HTTPException(400, "Unknown provider")
    value = (data.value or "").strip()
    meta = PROVIDERS.get(provider) or {}
    min_len = 1 if meta.get("secret") is False or provider.startswith("smtp_") else 4
    if len(value) < min_len:
        raise HTTPException(400, "Key value is too short")
    # Reject accidental placeholder pastes
    if value in ("sk-…", "xai-…", "••••"):
        raise HTTPException(400, "Paste your real API key")

    row = _upsert_plain(db, user.id, provider, value, label=(data.label or "").strip())
    db.commit()
    db.refresh(row)
    return _key_out(row)


@router.delete("/{provider}")
def delete_key(provider: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    provider = provider.strip().lower()
    row = (
        db.query(models.UserApiKey)
        .filter_by(user_id=user.id, provider=provider)
        .first()
    )
    if not row:
        raise HTTPException(404, "No key stored for that provider")
    db.delete(row)
    db.commit()
    return {"ok": True, "provider": provider}


@router.post("/{provider}/verify")
def verify_key(provider: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Confirm a key exists and decrypts (does not call external APIs)."""
    row = (
        db.query(models.UserApiKey)
        .filter_by(user_id=user.id, provider=provider.strip().lower(), is_active=True)
        .first()
    )
    if not row:
        return {"ok": False, "configured": False}
    try:
        plain = decrypt_secret(row.encrypted_value)
        return {
            "ok": bool(plain),
            "configured": True,
            "masked": mask_secret(plain),
            "length": len(plain),
        }
    except Exception:
        return {"ok": False, "configured": True, "error": "decrypt_failed"}
