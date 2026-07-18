"""Mobile device push token registration."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import get_current_user

router = APIRouter(prefix="/devices", tags=["devices"])


class RegisterIn(BaseModel):
    token: str = Field(..., min_length=8, max_length=512)
    platform: str = Field(default="", max_length=32)
    device_label: str = Field(default="", max_length=120)
    enabled: bool = True


@router.post("/push/register")
def register_push(data: RegisterIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    tok = (data.token or "").strip()
    if not tok:
        raise HTTPException(400, "token required")
    row = (
        db.query(models.DevicePushToken)
        .filter_by(user_id=user.id, token=tok)
        .first()
    )
    now = datetime.utcnow()
    if row:
        row.platform = (data.platform or row.platform or "")[:32]
        row.device_label = (data.device_label or row.device_label or "")[:120]
        row.enabled = bool(data.enabled)
        row.last_seen_at = now
        row.updated_at = now
    else:
        row = models.DevicePushToken(
            user_id=user.id,
            token=tok,
            platform=(data.platform or "")[:32],
            device_label=(data.device_label or "")[:120],
            enabled=bool(data.enabled),
            last_seen_at=now,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "ok": True,
        "id": row.id,
        "platform": row.platform,
        "enabled": row.enabled,
    }


@router.post("/push/unregister")
def unregister_push(data: RegisterIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    tok = (data.token or "").strip()
    q = db.query(models.DevicePushToken).filter_by(user_id=user.id)
    if tok:
        q = q.filter_by(token=tok)
    n = 0
    for row in q.all():
        row.enabled = False
        row.updated_at = datetime.utcnow()
        n += 1
    db.commit()
    return {"ok": True, "disabled": n}


@router.get("/push")
def list_tokens(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = (
        db.query(models.DevicePushToken)
        .filter_by(user_id=user.id)
        .order_by(models.DevicePushToken.id.desc())
        .limit(20)
        .all()
    )
    return {
        "devices": [
            {
                "id": r.id,
                "platform": r.platform,
                "device_label": r.device_label,
                "enabled": r.enabled,
                "token_preview": (r.token[:12] + "…") if r.token else "",
                "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
            }
            for r in rows
        ]
    }


@router.get("/push/status")
def push_status(db: Session = Depends(get_db), user=Depends(get_current_user)):
    n = (
        db.query(models.DevicePushToken)
        .filter_by(user_id=user.id, enabled=True)
        .count()
    )
    return {
        "enabled_devices": n,
        "fcm_configured": bool(__import__("os").getenv("FCM_SERVER_KEY") or __import__("os").getenv("FIREBASE_SERVER_KEY")),
        "note": (
            "Tokens are stored when the mobile app registers. "
            "Remote delivery needs FCM/APNs credentials on the server (optional for v1)."
        ),
    }
