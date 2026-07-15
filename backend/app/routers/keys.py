"""Subscriber API key vault — encrypted at rest, masked on read."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import get_current_user
from ..crypto import encrypt_secret, decrypt_secret, mask_secret
from ..user_keys import PROVIDERS

router = APIRouter(prefix="/keys", tags=["keys"])


class KeyIn(BaseModel):
    provider: str
    value: str = Field(min_length=4)
    label: str = ""


class KeyUpdate(BaseModel):
    value: str | None = None
    label: str | None = None
    is_active: bool | None = None


def _key_out(row: models.UserApiKey, include_mask: bool = True) -> dict:
    meta = PROVIDERS.get(row.provider, {})
    return {
        "id": row.id,
        "provider": row.provider,
        "provider_label": meta.get("label", row.provider),
        "label": row.label or "",
        "hint": row.hint or "",
        "masked": f"{'•' * 12}{row.hint}" if row.hint else "••••••••",
        "is_active": bool(row.is_active),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "encrypted": True,
    }


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
            })
    for extra in by_provider.values():
        extra["configured"] = True
        catalog.append(extra)
    for c in catalog:
        if c.get("id"):
            c["configured"] = True
    return {"keys": catalog, "encryption": "fernet-aes", "note": "Plaintext keys are never returned after save."}


@router.put("/{provider}")
def upsert_key(provider: str, data: KeyIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    provider = provider.strip().lower()
    if provider not in PROVIDERS and not provider.replace("_", "").isalnum():
        raise HTTPException(400, "Unknown provider")
    value = (data.value or "").strip()
    if len(value) < 4:
        raise HTTPException(400, "Key value is too short")
    # Reject accidental placeholder pastes
    if value in ("sk-…", "xai-…", "••••"):
        raise HTTPException(400, "Paste your real API key")

    try:
        encrypted = encrypt_secret(value)
    except Exception as e:
        raise HTTPException(500, f"Encryption failed: {e}")

    hint = value[-4:] if len(value) >= 4 else value
    row = (
        db.query(models.UserApiKey)
        .filter_by(user_id=user.id, provider=provider)
        .first()
    )
    if row:
        row.encrypted_value = encrypted
        row.hint = hint
        row.label = (data.label or row.label or "").strip()
        row.is_active = True
        row.updated_at = datetime.utcnow()
    else:
        row = models.UserApiKey(
            user_id=user.id,
            provider=provider,
            label=(data.label or "").strip(),
            encrypted_value=encrypted,
            hint=hint,
            is_active=True,
        )
        db.add(row)
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
