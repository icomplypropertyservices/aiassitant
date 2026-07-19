"""Load and resolve subscriber API keys (decrypted only in-process)."""
from sqlalchemy.orm import Session
from . import models
from .crypto import decrypt_secret

# Canonical provider ids used in vault + LLM router
PROVIDERS = {
    "anthropic": {
        "label": "Anthropic (Claude) — Coming soon",
        "placeholder": "sk-ant-…",
        "help": "Coming soon — Claude models are not live yet.",
        "category": "llm",
        "status": "coming_soon",
    },
    "xai": {
        "label": "xAI (Grok) — API only",
        "placeholder": "xai-…",
        "help": "Grok works via API only (your xAI key or platform key). Not available on VPS.",
        "category": "llm",
        "status": "api_only",
    },
    "openai": {
        "label": "OpenAI",
        "placeholder": "sk-…",
        "help": "Optional — for OpenAI-compatible models",
        "category": "llm",
    },
    "google": {
        "label": "Google AI (Gemini)",
        "placeholder": "AIza…",
        "help": "Gemini API key (also add Google apps under Connected apps)",
        "category": "llm",
    },
    "resend": {
        "label": "Resend (email API)",
        "placeholder": "re_…",
        "help": "Send agent emails via Resend API (alternative to SMTP)",
        "category": "channels",
    },
    # Classic SMTP (Namecheap Private Email, Google Workspace SMTP, Outlook, custom)
    "smtp_host": {
        "label": "SMTP host",
        "placeholder": "mail.privateemail.com",
        "help": "e.g. Namecheap: mail.privateemail.com · Gmail: smtp.gmail.com",
        "category": "channels",
        "secret": False,
    },
    "smtp_port": {
        "label": "SMTP port",
        "placeholder": "587",
        "help": "Usually 587 (STARTTLS) or 465 (SSL)",
        "category": "channels",
        "secret": False,
    },
    "smtp_user": {
        "label": "SMTP username",
        "placeholder": "you@yourdomain.com",
        "help": "Full email address for most hosts (Namecheap, Gmail app password user)",
        "category": "channels",
        "secret": False,
    },
    "smtp_password": {
        "label": "SMTP password",
        "placeholder": "mailbox or app password",
        "help": "Mailbox password or app-specific password",
        "category": "channels",
    },
    "smtp_from": {
        "label": "From address",
        "placeholder": "you@yourdomain.com",
        "help": "From: header (defaults to SMTP username if blank)",
        "category": "channels",
        "secret": False,
    },
    "smtp_tls": {
        "label": "SMTP TLS",
        "placeholder": "1",
        "help": "1 = STARTTLS (port 587). 0 = SSL/plain (often port 465 uses SSL path when TLS off)",
        "category": "channels",
        "secret": False,
    },
    "twilio_sid": {
        "label": "Twilio Account SID",
        "placeholder": "AC…",
        "help": "SMS / voice from your Twilio account",
        "category": "channels",
    },
    "twilio_token": {
        "label": "Twilio Auth Token",
        "placeholder": "your auth token",
        "help": "Paired with Twilio Account SID",
        "category": "channels",
    },
    "twilio_from": {
        "label": "Twilio From number",
        "placeholder": "+447…",
        "help": "E.164 number on your Twilio account",
        "category": "channels",
    },
}

# One-click SMTP presets for the Settings UI
SMTP_PRESETS = {
    "namecheap": {
        "id": "namecheap",
        "label": "Namecheap Private Email",
        "blurb": "Private Email / namecheap.com mailboxes",
        "smtp_host": "mail.privateemail.com",
        "smtp_port": "587",
        "smtp_tls": "1",
        "docs": "https://www.namecheap.com/support/knowledgebase/article.aspx/1195/2176/namecheap-private-email-settings-for-mail-clients-and-mobile-devices/",
        "hints": [
            "SMTP host: mail.privateemail.com",
            "Port: 587 with TLS (or 465 with SSL)",
            "Username: full email address",
            "Password: your mailbox password",
        ],
    },
    "gmail": {
        "id": "gmail",
        "label": "Gmail / Google Workspace (SMTP)",
        "blurb": "Requires an App Password if 2FA is on",
        "smtp_host": "smtp.gmail.com",
        "smtp_port": "587",
        "smtp_tls": "1",
        "docs": "https://support.google.com/accounts/answer/185833",
        "hints": [
            "Enable 2-Step Verification, then create an App Password",
            "Username: your full Gmail address",
            "Prefer Gmail OAuth under Connected apps when possible",
        ],
    },
    "outlook": {
        "id": "outlook",
        "label": "Outlook / Microsoft 365",
        "blurb": "outlook.com or Microsoft 365 SMTP",
        "smtp_host": "smtp.office365.com",
        "smtp_port": "587",
        "smtp_tls": "1",
        "docs": "https://support.microsoft.com/office",
        "hints": [
            "Host: smtp.office365.com · Port 587 · STARTTLS",
            "Username: full email address",
        ],
    },
    "yahoo": {
        "id": "yahoo",
        "label": "Yahoo Mail",
        "blurb": "Yahoo SMTP with app password",
        "smtp_host": "smtp.mail.yahoo.com",
        "smtp_port": "587",
        "smtp_tls": "1",
        "docs": "https://help.yahoo.com/",
        "hints": ["Use an app password if account security is enabled"],
    },
    "custom": {
        "id": "custom",
        "label": "Custom SMTP",
        "blurb": "Any host: cPanel, Zoho, SendGrid SMTP, etc.",
        "smtp_host": "",
        "smtp_port": "587",
        "smtp_tls": "1",
        "docs": "",
        "hints": ["Ask your host for outgoing SMTP host, port, and TLS settings"],
    },
}


def email_channel_status(db: Session, user_id: int) -> dict:
    """Whether this user can send mail via BYOK SMTP/Resend (or platform fallback)."""
    creds = credentials_for_user(db, user_id)
    from . import config
    from . import channels

    user_smtp = bool(
        (creds.get("smtp_host") or "").strip()
        and (creds.get("smtp_user") or "").strip()
        and (creds.get("smtp_password") or "").strip()
    )
    user_resend = bool((creds.get("resend") or "").strip())
    platform_smtp = bool(
        getattr(config, "SMTP_HOST", "")
        and getattr(config, "SMTP_USER", "")
        and getattr(config, "SMTP_PASSWORD", "")
    )
    platform_resend = bool(getattr(config, "RESEND_API_KEY", ""))
    serverless = bool(getattr(config, "IS_VERCEL", False) or getattr(config, "IS_PRODUCTION", False) and bool(
        __import__("os").getenv("VERCEL")
    ))
    # More accurate: use channels helper
    try:
        serverless = channels._is_serverless_host()
    except Exception:
        pass
    ready = channels.smtp_or_resend_configured(creds) or platform_smtp or platform_resend
    warnings = []
    if user_smtp and serverless and not (user_resend or platform_resend):
        warnings.append(
            "Raw SMTP often fails on Vercel (outbound ports blocked). "
            "Add a Resend API key or connect Gmail for reliable production email."
        )
    if not ready:
        warnings.append(
            "No email channel configured. Save SMTP or Resend under Settings → API keys."
        )
    return {
        "ok": ready,
        "user_smtp": user_smtp,
        "user_resend": user_resend,
        "platform_smtp": platform_smtp,
        "platform_resend": platform_resend,
        "smtp_host": (creds.get("smtp_host") or "")[:80] or None,
        "smtp_from": (creds.get("smtp_from") or creds.get("smtp_user") or "")[:120] or None,
        "serverless_host": serverless,
        "smtp_blocked_risk": bool(serverless and user_smtp and not (user_resend or platform_resend)),
        "recommended": (
            "resend_or_gmail"
            if serverless
            else ("smtp_or_resend" if not ready else "ok")
        ),
        "warnings": warnings,
        "presets": list(SMTP_PRESETS.values()),
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
    """Map of provider → plaintext key for in-process use only.

    Merges Settings → API keys with Connected apps (e.g. Twilio connection).
    Explicit API keys win over connection secrets.
    """
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

    # Connected apps → channel credentials (Twilio, etc.)
    try:
        from .integrations_service import secrets_from_row, meta_from_row

        conn = (
            db.query(models.IntegrationConnection)
            .filter_by(user_id=user_id, app_id="twilio", status="connected")
            .order_by(models.IntegrationConnection.id.desc())
            .first()
        )
        if conn:
            sec = secrets_from_row(conn) or {}
            meta = meta_from_row(conn) or {}
            for key in (
                "twilio_sid",
                "twilio_token",
                "twilio_from",
                "twilio_whatsapp_from",
                "account_sid",
                "auth_token",
                "from_number",
            ):
                val = (sec.get(key) or meta.get(key) or "").strip()
                if not val:
                    continue
                # Normalize aliases into channel credential names
                if key in ("account_sid",):
                    out.setdefault("twilio_sid", val)
                elif key in ("auth_token",):
                    out.setdefault("twilio_token", val)
                elif key in ("from_number",):
                    out.setdefault("twilio_from", val)
                else:
                    out.setdefault(key, val)
    except Exception:
        pass

    return out
