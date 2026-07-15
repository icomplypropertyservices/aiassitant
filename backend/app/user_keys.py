"""Load and resolve subscriber API keys (decrypted only in-process)."""
from sqlalchemy.orm import Session
from . import models
from .crypto import decrypt_secret

# Canonical provider ids used in vault + LLM router
PROVIDERS = {
    "anthropic": {
        "label": "Anthropic (Claude)",
        "placeholder": "sk-ant-…",
        "help": "Used for Premium Claude models",
    },
    "xai": {
        "label": "xAI (Grok)",
        "placeholder": "xai-…",
        "help": "Used for Premium Grok models",
    },
    "openai": {
        "label": "OpenAI",
        "placeholder": "sk-…",
        "help": "Optional — for future OpenAI models",
    },
    "google": {
        "label": "Google AI (Gemini)",
        "placeholder": "AIza…",
        "help": "Optional — for future Gemini models",
    },
    "resend": {
        "label": "Resend (email)",
        "placeholder": "re_…",
        "help": "Send agent emails from your own Resend account",
    },
    "twilio_sid": {
        "label": "Twilio Account SID",
        "placeholder": "AC…",
        "help": "SMS / voice from your Twilio account",
    },
    "twilio_token": {
        "label": "Twilio Auth Token",
        "placeholder": "your auth token",
        "help": "Paired with Twilio Account SID",
    },
    "twilio_from": {
        "label": "Twilio From number",
        "placeholder": "+447…",
        "help": "E.164 number on your Twilio account",
    },
}


def get_decrypted_key(db: Session, user_id: int, provider: str) -> str | None:
    row = (
        db.query(models.UserApiKey)
        .filter_by(user_id=user_id, provider=provider, is_active=True)
        .order_by(models.UserApiKey.id.desc())
        .first()
    )
    if not row or not row.encrypted_value:
        return None
    try:
        val = decrypt_secret(row.encrypted_value)
        return val or None
    except Exception:
        return None


def credentials_for_user(db: Session, user_id: int) -> dict:
    """Map of provider → plaintext key for in-process use only."""
    out = {}
    rows = (
        db.query(models.UserApiKey)
        .filter_by(user_id=user_id, is_active=True)
        .all()
    )
    for row in rows:
        try:
            val = decrypt_secret(row.encrypted_value)
            if val:
                out[row.provider] = val
        except Exception:
            continue
    return out
