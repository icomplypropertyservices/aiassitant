"""Email / SMS / WhatsApp / voice / unified messaging skill handlers."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from .. import channels
from ..live_ops import emit_ops
from .bridge import (
    get_skill_catalog,
    charge_premium,
)


async def _skill_draft_email(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    to = (args.get("to") or "").strip()
    subject = (args.get("subject") or "Follow-up").strip()
    body = (args.get("body") or "").strip()
    tone = args.get("tone") or "professional"
    if not to:
        return {"ok": False, "error": "to (email address) is required"}
    if not body:
        body = f"Hi,\n\nI wanted to follow up regarding our conversation.\n\nBest regards,\n{agent.name}"
    return {
        "ok": True,
        "draft": True,
        "to": to,
        "subject": subject,
        "body": body,
        "tone": tone,
        "note": "This is a draft. Call send_email (premium) to actually deliver it."
    }

async def _skill_send_email(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    to = (args.get("to") or "").strip()
    subject = (args.get("subject") or "Message from " + agent.name).strip()
    body = (args.get("body") or "").strip()
    cc = args.get("cc")
    bcc = args.get("bcc")
    if not to or not body:
        return {"ok": False, "error": "to and body are required"}

    if not args.get("_billed"):
        from .integrations import _run_app
        meta = next((s for s in get_skill_catalog() if s["id"] == "send_email"), {})
        charge_premium(db, user, meta, 0.02, text=body)

    # Prefer connected Gmail (Google Cloud OAuth) when available
    gmail_try = await _run_app(db, agent, user, "gmail", "send", {
        "to": to, "subject": subject, "body": body, "cc": cc, "bcc": bcc,
        "html": args.get("html"),
    })
    if gmail_try.get("ok"):
        await emit_ops(
            user.id, kind="action", status="done",
            title="Email sent via Gmail", detail=to, agent_id=agent.id, db=db,
        )
        return {**gmail_try, "provider": "gmail"}

    # Fallback: Resend platform / BYOK
    from ..user_keys import credentials_for_user
    creds = credentials_for_user(db, user.id)
    sent, detail = await channels.send_email(
        to, subject, body, credentials=creds, cc=cc, bcc=bcc, html=args.get("html"),
    )
    await emit_ops(user.id, kind="action", status="done" if sent else "failed",
                   title=f"Email {'sent' if sent else 'drafted'}", detail=to, agent_id=agent.id, db=db)
    out = {"ok": sent, "to": to, "subject": subject, "detail": detail, "provider": "resend"}
    if not sent and not gmail_try.get("ok"):
        out["gmail_error"] = gmail_try.get("error")
        out["hint"] = "Connect Gmail under Settings → Connected apps, or add Resend API key"
    return out

async def _skill_draft_sms(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    to = (args.get("to") or "").strip()
    body = (args.get("body") or "").strip()
    if not to:
        return {"ok": False, "error": "to (phone number) is required"}
    return {"ok": True, "draft": True, "to": to, "body": body, "note": "Draft only. Use send_sms to actually deliver (premium)."}

async def _skill_send_sms(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    to = (args.get("to") or "").strip()
    body = (args.get("body") or "").strip()
    if not to or not body:
        return {"ok": False, "error": "to (E.164 phone) and body are required"}

    if not args.get("_billed"):
        meta = next((s for s in get_skill_catalog() if s["id"] == "send_sms"), {})
        charge_premium(db, user, meta, 0.015, text=body)

    from ..user_keys import credentials_for_user
    creds = credentials_for_user(db, user.id)
    sent, detail = await channels.send_sms(to, body, credentials=creds)
    await emit_ops(user.id, kind="action", status="done" if sent else "failed",
                   title=f"SMS {'sent' if sent else 'drafted'}", detail=to, agent_id=agent.id, db=db)
    out = {"ok": sent, "to": to, "detail": detail, "provider": "twilio"}
    if not sent:
        out["hint"] = (
            "Configure Twilio: Settings → Connected apps → Twilio, "
            "or Settings → API keys (twilio_sid, twilio_token, twilio_from), "
            "or platform env TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER"
        )
    return out

async def _skill_send_whatsapp(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    to = (args.get("to") or "").strip()
    body = (args.get("body") or "").strip()
    if not to or not body:
        return {"ok": False, "error": "to (whatsapp:+number) and body are required"}

    if not args.get("_billed"):
        meta = next((s for s in get_skill_catalog() if s["id"] == "send_whatsapp"), {})
        charge_premium(db, user, meta, 0.02, text=body)

    from ..user_keys import credentials_for_user
    creds = credentials_for_user(db, user.id)
    sent, detail = await channels.send_whatsapp(to, body, credentials=creds)
    await emit_ops(user.id, kind="action", status="done" if sent else "failed",
                   title=f"WhatsApp {'sent' if sent else 'drafted'}", detail=to, agent_id=agent.id, db=db)
    return {"ok": sent, "to": to, "detail": detail}

async def _skill_make_voice_call(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Initiate Twilio outbound call; recipient hears spoken TTS message."""
    to = (args.get("to") or args.get("phone") or "").strip()
    message = (
        args.get("message")
        or args.get("speech")
        or args.get("text")
        or args.get("body")
        or f"Hello from {agent.name}. This is an automated call with an important update."
    ).strip()
    if not to:
        return {"ok": False, "error": "to (E.164 phone e.g. +15551234567) is required"}
    if not message:
        return {"ok": False, "error": "message (speech script) is required"}

    if not args.get("_billed"):
        meta = next((s for s in get_skill_catalog() if s["id"] == "make_voice_call"), {})
        charge_premium(db, user, meta, 0.08, text=message)

    from ..user_keys import credentials_for_user
    creds = credentials_for_user(db, user.id)
    voice = (args.get("voice") or "alice").strip()
    language = (args.get("language") or "en-US").strip()
    try:
        loop = int(args.get("loop") or 1)
    except (TypeError, ValueError):
        loop = 1
    sent, detail = await channels.make_call(
        to, message, credentials=creds, voice=voice, language=language, loop=loop,
    )
    await emit_ops(
        user.id,
        kind="action",
        status="done" if sent else "failed",
        title=f"Phone call {'initiated' if sent else 'failed'}",
        detail=f"{to}: {(message or '')[:120]}",
        agent_id=agent.id,
        db=db,
    )
    out = {
        "ok": sent,
        "to": to,
        "detail": detail,
        "provider": "twilio",
        "channel": "voice",
        "speech_preview": message[:160],
        "voice": voice,
        "language": language,
    }
    if not sent:
        out["hint"] = (
            "Configure Twilio: Settings → Connected apps → Twilio, "
            "or API keys / platform TWILIO_* env. "
            "From number must support Voice."
        )
    return out

async def _skill_log_communication(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    cid = args.get("customer_id")
    email = (args.get("email") or "").strip()
    kind = (args.get("kind") or "email").strip()
    to = (args.get("to") or "").strip()
    title = (args.get("subject_or_title") or "").strip()
    body = (args.get("body") or "").strip()

    cust = None
    if cid:
        try:
            cust = db.get(models.Customer, int(cid))
        except Exception:
            pass
    elif email:
        cust = db.query(models.Customer).filter_by(owner_user_id=user.id, email=email).first()

    if cust:
        db.add(models.CustomerActivity(
            customer_id=cust.id,
            owner_user_id=user.id,
            kind=kind,
            title=title or f"{kind.title()} sent",
            body=body[:500],
            agent_id=agent.id,
        ))
        cust.last_contacted_at = datetime.utcnow()
        db.commit()

    return {"ok": True, "logged": True, "kind": kind, "to": to or email, "customer_id": getattr(cust, 'id', None)}

async def _skill_send_message(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Smart unified communication skill.
    channel can be: email | sms | whatsapp | voice | auto (default)
    This is the single best skill for agents to use when they want to reach a human.
    """
    to = (args.get("to") or "").strip()
    body = (args.get("body") or args.get("message") or "").strip()
    subject = args.get("subject") or f"Update from {agent.name}"
    channel = (args.get("channel") or "auto").lower()
    cid = args.get("customer_id")

    if not to or not body:
        return {"ok": False, "error": "to and body are required"}

    # Try to resolve customer for logging
    cust = None
    if cid:
        try:
            cust = db.get(models.Customer, int(cid))
        except Exception:
            pass

    # Auto-detect channel from "to"
    if channel == "auto":
        if "@" in to:
            channel = "email"
        elif to.lower().startswith("whatsapp:") or "whatsapp" in to.lower():
            from .integrations import _run_app
            channel = "whatsapp"
        elif to.replace("+", "").replace("-", "").replace(" ", "").isdigit():
            channel = "sms"
        else:
            channel = "sms"

    result = {"ok": False}
    from ..user_keys import credentials_for_user
    creds = credentials_for_user(db, user.id)

    billed = bool(args.get("_billed"))
    if channel == "email":
        meta = next((s for s in get_skill_catalog() if s["id"] == "send_email"), {})
        charge_premium(db, user, meta, 0.02, text=body, already_billed=billed)
        gmail_try = await _run_app(db, agent, user, "gmail", "send", {
            "to": to, "subject": subject, "body": body,
            "cc": args.get("cc"), "bcc": args.get("bcc"),
        })
        if gmail_try.get("ok"):
            result = {**gmail_try, "channel": "email", "provider": "gmail"}
        else:
            sent, detail = await channels.send_email(
                to, subject, body, credentials=creds, cc=args.get("cc"), bcc=args.get("bcc"),
            )
            result = {"ok": sent, "channel": "email", "to": to, "detail": detail, "provider": "resend"}

    elif channel == "sms":
        meta = next((s for s in get_skill_catalog() if s["id"] == "send_sms"), {})
        charge_premium(db, user, meta, 0.015, text=body, already_billed=billed)
        sent, detail = await channels.send_sms(to, body, credentials=creds)
        result = {"ok": sent, "channel": "sms", "to": to, "detail": detail, "provider": "twilio"}

    elif channel == "whatsapp":
        meta = next((s for s in get_skill_catalog() if s["id"] == "send_whatsapp"), {})
        charge_premium(db, user, meta, 0.02, text=body, already_billed=billed)
        sent, detail = await channels.send_whatsapp(to, body, credentials=creds)
        result = {"ok": sent, "channel": "whatsapp", "to": to, "detail": detail, "provider": "twilio"}

    elif channel == "voice":
        meta = next((s for s in get_skill_catalog() if s["id"] == "make_voice_call"), {})
        charge_premium(db, user, meta, 0.08, text=body, already_billed=billed)
        sent, detail = await channels.make_call(to, body, credentials=creds)
        result = {"ok": sent, "channel": "voice", "to": to, "detail": detail, "provider": "twilio"}

    else:
        meta = next((s for s in get_skill_catalog() if s["id"] == "send_email"), {})
        charge_premium(db, user, meta, 0.02, text=body, already_billed=billed)
        gmail_try = await _run_app(db, agent, user, "gmail", "send", {
            "to": to, "subject": subject, "body": body, "cc": args.get("cc"), "bcc": args.get("bcc"),
        })
        if gmail_try.get("ok"):
            result = {**gmail_try, "channel": "email", "provider": "gmail"}
        else:
            sent, detail = await channels.send_email(
                to, subject, body, credentials=creds, cc=args.get("cc"), bcc=args.get("bcc"),
            )
            result = {"ok": sent, "channel": "email", "to": to, "detail": detail, "provider": "resend"}

    # Log to CRM if we have a customer
    if cust:
        db.add(models.CustomerActivity(
            customer_id=cust.id,
            owner_user_id=user.id,
            kind=channel if channel in ("email", "sms", "call") else "note",
            title=f"{channel.title()} via {agent.name}",
            body=body[:400],
            agent_id=agent.id,
        ))
        cust.last_contacted_at = datetime.utcnow()
        db.commit()

    await emit_ops(user.id, kind="action", status="done" if result.get("ok") else "failed",
                   title=f"Sent via {result.get('channel', channel)}", detail=to, agent_id=agent.id, db=db)

    return result


__all__ = [
    '_skill_draft_email',
    '_skill_send_email',
    '_skill_draft_sms',
    '_skill_send_sms',
    '_skill_send_whatsapp',
    '_skill_make_voice_call',
    '_skill_log_communication',
    '_skill_send_message',
]
