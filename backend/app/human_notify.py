"""
Always notify humans via short phone (SMS) + email when agents escalate / update.

Rules:
  - Target human must be status=active (or account owner treated as active if verified)
  - Email requires SMTP (or Resend as hosted SMTP path) configured
  - SMS requires Twilio configured
  - Message is a short cut: title + 1-line body + deep link into the app
  - Email/HTML includes product favicon + logo and a correct clickable link
  - Optional: push to registered mobile devices with same link + icon
"""
from __future__ import annotations

import html as html_lib
import logging
from typing import Any
from urllib.parse import urljoin, urlparse

from sqlalchemy.orm import Session

from . import models, config
from . import channels
from .user_keys import credentials_for_user

log = logging.getLogger("app.human_notify")

# Canonical production origin (www avoids apex redirect issues for POSTs/links)
_PROD_ORIGIN = "https://www.aibusinessagent.xyz"
_PROD_APP = f"{_PROD_ORIGIN}/agents"
_FAVICON = f"{_PROD_ORIGIN}/agents/favicon-32.png"
_LOGO = f"{_PROD_ORIGIN}/agents/logo-256.png"
_ICON_192 = f"{_PROD_ORIGIN}/agents/icons/icon-192.png"


def public_origin() -> str:
    """https://www.aibusinessagent.xyz (or local origin)."""
    fu = (getattr(config, "FRONTEND_URL", None) or "").strip().rstrip("/")
    if fu:
        # Normalize apex → www for production links
        if "aibusinessagent.xyz" in fu and "www." not in fu:
            fu = fu.replace("://aibusinessagent.xyz", "://www.aibusinessagent.xyz")
        try:
            p = urlparse(fu)
            if p.scheme and p.netloc:
                return f"{p.scheme}://{p.netloc}"
        except Exception:
            pass
    if getattr(config, "IS_PRODUCTION", False):
        return _PROD_ORIGIN
    # Local dev
    if fu.startswith("http"):
        try:
            p = urlparse(fu)
            return f"{p.scheme}://{p.netloc}"
        except Exception:
            pass
    return "http://localhost:5173"


def _app_base() -> str:
    """SPA base ending with /agents (no trailing slash beyond that)."""
    base = (getattr(config, "FRONTEND_URL", None) or "").strip().rstrip("/")
    if not base:
        return _PROD_APP if getattr(config, "IS_PRODUCTION", False) else "http://localhost:5173"
    # Normalize production domain to www
    if "aibusinessagent.xyz" in base and "www." not in base:
        base = base.replace("://aibusinessagent.xyz", "://www.aibusinessagent.xyz")
    if base.endswith("/agents"):
        return base
    if "aibusinessagent" in base or getattr(config, "IS_PRODUCTION", False):
        return f"{base}/agents"
    return base


def asset_url(path: str) -> str:
    """Absolute URL for a public SPA asset (favicon, logo)."""
    origin = public_origin()
    p = path if path.startswith("/") else f"/{path}"
    # Assets live under /agents/ on production web
    if "aibusinessagent" in origin:
        if not p.startswith("/agents/"):
            p = f"/agents{p}" if p.startswith("/") else f"/agents/{p}"
        return f"{origin}{p}"
    # Local vite: public/ at root
    return f"{origin}{p}"


def notification_icon_url() -> str:
    return asset_url("/favicon-32.png")


def notification_logo_url() -> str:
    return asset_url("/logo-256.png")


def _normalize_app_path(path: str) -> str:
    """Path relative to SPA root, e.g. /tasks or /meetings/3."""
    p = (path or "/tasks").strip() or "/tasks"
    if not p.startswith("/"):
        p = f"/{p}"
    # Strip accidental full URLs
    if p.startswith("http"):
        try:
            u = urlparse(p)
            p = u.path or "/tasks"
            if u.query:
                p = f"{p}?{u.query}"
        except Exception:
            p = "/tasks"
    # Remove /agents prefix so we can re-join cleanly
    if p.startswith("/agents/"):
        p = p[len("/agents") :] or "/"
    elif p == "/agents":
        p = "/"
    return p


def shortcut_url(path: str = "/tasks") -> str:
    """Full clickable URL into the private app (correct for email/SMS/push)."""
    base = _app_base()
    p = _normalize_app_path(path)
    if p == "/":
        return base if base.endswith("/agents") else f"{base}/"
    return f"{base}{p}"


def _short_body(title: str, details: str, link: str, *, max_sms: int = 280) -> str:
    title = (title or "Update").strip()[:80]
    details = (details or "").strip()
    one = details.replace("\n", " ")[:140]
    sms = f"{title}: {one}".strip() if one else title
    budget = max_sms - len(link) - 2
    if budget < 40:
        budget = 40
    if len(sms) > budget:
        sms = sms[: budget - 1] + "…"
    return f"{sms}\n{link}"


def _html_email(
    *,
    title: str,
    details: str,
    link: str,
    agent_name: str,
    recipient_name: str,
) -> str:
    """Branded HTML email with favicon/logo and primary CTA button."""
    title_e = html_lib.escape(title or "Update")
    details_e = html_lib.escape((details or "")[:2000]).replace("\n", "<br/>")
    agent_e = html_lib.escape(agent_name or "AI Agent")
    recip_e = html_lib.escape(recipient_name or "there")
    link_e = html_lib.escape(link)
    fav = html_lib.escape(notification_icon_url())
    logo = html_lib.escape(notification_logo_url())
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <link rel="icon" href="{fav}" type="image/png"/>
  <title>{title_e}</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Inter,Segoe UI,system-ui,sans-serif;color:#0f172a;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f1f5f9;padding:24px 12px;">
    <tr><td align="center">
      <table role="presentation" width="100%" style="max-width:560px;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;overflow:hidden;">
        <tr>
          <td style="padding:20px 24px;background:linear-gradient(135deg,#0b1f3a,#1668dc);">
            <img src="{logo}" alt="AI Business Agent" width="40" height="40"
                 style="display:block;border-radius:10px;background:#fff;"/>
            <div style="color:#fff;font-size:18px;font-weight:700;margin-top:12px;">AI Business Agent</div>
            <div style="color:rgba(255,255,255,0.85);font-size:13px;margin-top:4px;">Private workspace notification</div>
          </td>
        </tr>
        <tr>
          <td style="padding:24px;">
            <p style="margin:0 0 8px;font-size:13px;color:#64748b;">Hi {recip_e},</p>
            <h1 style="margin:0 0 12px;font-size:20px;line-height:1.3;">{title_e}</h1>
            <p style="margin:0 0 8px;font-size:13px;color:#64748b;">From <strong>{agent_e}</strong></p>
            <div style="margin:16px 0;padding:14px 16px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;font-size:14px;line-height:1.5;">
              {details_e or "You have a new update in your workspace."}
            </div>
            <table role="presentation" cellspacing="0" cellpadding="0" style="margin:20px 0 8px;">
              <tr>
                <td style="border-radius:8px;background:#1668dc;">
                  <a href="{link_e}"
                     style="display:inline-block;padding:12px 22px;color:#ffffff;text-decoration:none;font-weight:600;font-size:14px;">
                    Open notification →
                  </a>
                </td>
              </tr>
            </table>
            <p style="margin:16px 0 0;font-size:12px;color:#94a3b8;word-break:break-all;">
              Or open: <a href="{link_e}" style="color:#1668dc;">{link_e}</a>
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:14px 24px;border-top:1px solid #e2e8f0;font-size:11px;color:#94a3b8;">
            <img src="{fav}" width="16" height="16" alt="" style="vertical-align:middle;margin-right:6px;"/>
            AI Business Agent · Only you can see your private workspace
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def resolve_active_human(
    db: Session,
    user: models.User,
    *,
    human_id: int | None = None,
    prefer_owner: bool = True,
) -> dict[str, Any]:
    """
    Resolve who to notify.
    Returns dict with name, email, phone, kind ('human'|'owner'), human_id?, active, error?
    """
    if human_id:
        h = db.get(models.Human, int(human_id))
        if not h or h.owner_user_id != user.id:
            return {"error": "Human not found", "active": False}
        if (h.status or "").lower() != "active":
            return {
                "error": f"Human '{h.name}' is not active (status={h.status}). Only active humans receive notifications.",
                "active": False,
                "human_id": h.id,
                "name": h.name,
            }
        return {
            "active": True,
            "kind": "human",
            "human_id": h.id,
            "name": h.name,
            "email": (h.email or "").strip(),
            "phone": (getattr(h, "phone", None) or "").strip(),
        }

    h = (
        db.query(models.Human)
        .filter_by(owner_user_id=user.id, status="active")
        .order_by(models.Human.id)
        .first()
    )
    if h:
        return {
            "active": True,
            "kind": "human",
            "human_id": h.id,
            "name": h.name,
            "email": (h.email or "").strip(),
            "phone": (getattr(h, "phone", None) or "").strip(),
        }

    if prefer_owner:
        email = (user.email or "").strip()
        if not email or email.startswith("deleted+"):
            return {"error": "No active human and owner has no email", "active": False}
        verified = bool(getattr(user, "email_verified", False) or user.role == "admin")
        if config.IS_PRODUCTION and not verified and user.role != "admin":
            return {
                "error": "Owner email is not verified — verify email before notify-human delivery",
                "active": False,
                "email": email,
            }
        return {
            "active": True,
            "kind": "owner",
            "name": user.name or email,
            "email": email,
            "phone": "",
            "user_id": user.id,
        }

    return {"error": "No active human to notify", "active": False}


async def _send_push_to_user(
    db: Session,
    user_id: int,
    *,
    title: str,
    body: str,
    link: str,
    path: str,
) -> dict[str, Any]:
    """Best-effort FCM data+notification payload with icon and deep link."""
    import os
    import httpx

    rows = (
        db.query(models.DevicePushToken)
        .filter_by(user_id=user_id, enabled=True)
        .order_by(models.DevicePushToken.id.desc())
        .limit(20)
        .all()
    )
    if not rows:
        return {"ok": False, "error": "no_devices", "sent": 0}
    server_key = (
        os.getenv("FCM_SERVER_KEY")
        or os.getenv("FIREBASE_SERVER_KEY")
        or ""
    ).strip()
    if not server_key:
        return {"ok": False, "error": "fcm_not_configured", "devices": len(rows), "sent": 0}

    icon = notification_icon_url()
    logo = _ICON_192 if "aibusinessagent" in public_origin() else notification_logo_url()
    app_path = _normalize_app_path(path)
    sent = 0
    errors: list[str] = []
    for row in rows:
        # Legacy FCM HTTP API (widely used with server key)
        payload = {
            "to": row.token,
            "priority": "high",
            "notification": {
                "title": (title or "AI Business Agent")[:120],
                "body": (body or "")[:240],
                "icon": icon,
                "image": logo,
                "click_action": link,
                "sound": "default",
            },
            "data": {
                "title": title or "AI Business Agent",
                "body": body or "",
                "path": app_path,
                "url": link,
                "link": link,
                "icon": icon,
                "route": app_path,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.post(
                    "https://fcm.googleapis.com/fcm/send",
                    headers={
                        "Authorization": f"key={server_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if r.status_code in (200, 201):
                sent += 1
            else:
                errors.append(f"{r.status_code}:{r.text[:80]}")
        except Exception as e:
            errors.append(str(e)[:80])
    return {
        "ok": sent > 0,
        "sent": sent,
        "devices": len(rows),
        "errors": errors[:5],
        "icon": icon,
        "link": link,
    }


async def notify_human(
    db: Session,
    user: models.User,
    *,
    title: str,
    details: str = "",
    human_id: int | None = None,
    agent: models.Agent | None = None,
    force_email: bool = True,
    force_sms: bool = True,
    force_push: bool = True,
    link_path: str = "/tasks",
) -> dict[str, Any]:
    """
    Always attempt short SMS + branded HTML email (+ optional push) to an active human.
    Links open the correct SPA route with product favicon/logo in email and push.
    """
    target = resolve_active_human(db, user, human_id=human_id)
    if not target.get("active"):
        return {"ok": False, "error": target.get("error") or "No active human", "channels": {}}

    path = _normalize_app_path(link_path)
    link = shortcut_url(path)
    one = (details or "").replace("\n", " ")[:160]
    title_s = (title or "Update").strip()[:80]
    sms_body = _short_body(title_s, details, link)
    email_subject = f"[AI Business Agent] {title_s}"
    agent_name = agent.name if agent else "AI Agent"
    plain_body = (
        f"From: {agent_name}\n"
        f"To: {target.get('name')}\n\n"
        f"{title_s}\n\n"
        f"{(details or '')[:2000]}\n\n"
        f"Open notification: {link}\n"
    )
    html_body = _html_email(
        title=title_s,
        details=details or one,
        link=link,
        agent_name=agent_name,
        recipient_name=target.get("name") or "there",
    )

    import asyncio

    creds = credentials_for_user(db, user.id)
    channels_out: dict[str, Any] = {}
    errors: list[str] = []
    email = target.get("email") or ""
    phone = target.get("phone") or ""

    async def _do_email() -> dict[str, Any]:
        if not force_email:
            return {}
        if not email:
            errors.append("Human has no email — set email on active human (Users/Team)")
            return {"ok": False, "error": "no_email"}
        if not channels.smtp_or_resend_configured(creds):
            errors.append(
                "SMTP not configured. Set SMTP_HOST/SMTP_USER/SMTP_PASSWORD/SMTP_FROM "
                "or RESEND_API_KEY + RESEND_FROM (platform or Settings keys)."
            )
            return {"ok": False, "error": "smtp_not_configured"}
        sent, detail = await channels.send_email(
            email, email_subject, plain_body, credentials=creds, html=html_body,
        )
        if not sent:
            errors.append(detail)
        return {
            "ok": sent, "detail": detail, "to": email, "link": link,
            "favicon": notification_icon_url(),
        }

    async def _do_sms() -> dict[str, Any]:
        if not force_sms:
            return {}
        if not phone:
            errors.append("Human has no phone — set phone (E.164) on active human for SMS shortcuts")
            return {"ok": False, "error": "no_phone"}
        if not channels.twilio_configured(creds):
            errors.append("Twilio not configured for SMS. Set TWILIO_* env or Settings Twilio keys.")
            return {"ok": False, "error": "twilio_not_configured"}
        sent, detail = await channels.send_sms(phone, sms_body, credentials=creds)
        if not sent:
            errors.append(detail)
        return {"ok": sent, "detail": detail, "to": phone, "link": link}

    async def _do_push() -> dict[str, Any]:
        if not force_push:
            return {}
        return await _send_push_to_user(
            db, user.id, title=title_s, body=one or title_s, link=link, path=path,
        )

    # Independent channels — run in parallel
    email_r, sms_r, push_r = await asyncio.gather(_do_email(), _do_sms(), _do_push())
    if email_r:
        channels_out["email"] = email_r
    if sms_r:
        channels_out["sms"] = sms_r
    if push_r:
        channels_out["push"] = push_r
    any_ok = any(bool(channels_out.get(k, {}).get("ok")) for k in ("email", "sms", "push"))

    # Live ops banner
    try:
        from .live_ops import emit_ops
        await emit_ops(
            user.id,
            kind="human",
            status="done" if any_ok else "failed",
            title=f"Notify human: {title_s}"[:120],
            detail=(
                f"{target.get('name')}: email={channels_out.get('email', {}).get('ok')} "
                f"sms={channels_out.get('sms', {}).get('ok')} "
                f"push={channels_out.get('push', {}).get('ok')} link={link}"
            )[:400],
            agent_id=agent.id if agent else None,
            human_id=target.get("human_id"),
            db=db,
        )
    except Exception:
        pass

    email_ok = channels_out.get("email", {}).get("ok")
    sms_ok = channels_out.get("sms", {}).get("ok")
    push_ok = channels_out.get("push", {}).get("ok")
    ok = bool(any_ok)
    if email_ok and sms_ok:
        message = "Human notified by email + SMS shortcut"
    elif email_ok:
        message = "Human notified by email only (SMS missing/failed)"
    elif sms_ok:
        message = "Human notified by SMS only (email missing/failed)"
    elif push_ok:
        message = "Human notified by push only"
    else:
        message = "Notify failed — active human needs email+phone and SMTP+Twilio setup"

    return {
        "ok": ok,
        "message": message,
        "target": {
            "kind": target.get("kind"),
            "human_id": target.get("human_id"),
            "name": target.get("name"),
            "email": email or None,
            "phone": phone or None,
        },
        "shortcut": link,
        "path": path,
        "favicon": notification_icon_url(),
        "logo": notification_logo_url(),
        "channels": channels_out,
        "errors": errors,
        "requires": {
            "active_human": True,
            "smtp_or_resend": True,
            "twilio_for_sms": True,
        },
    }
