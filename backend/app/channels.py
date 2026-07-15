"""Multi-channel service: Email (Resend) + SMS/Voice (Twilio).
Every function returns (sent: bool, detail: str) so agent terminals can log
exactly what happened. With no keys configured, actions are logged, not sent.

BYOK: pass credentials from user_keys (resend, twilio_sid, twilio_token, twilio_from).
User keys are preferred over platform config.* env; RESEND_FROM still comes from config.
"""
import httpx
from . import config


def _resolve_channel_creds(credentials: dict | None = None, **kwargs):
    """Merge explicit kwargs over credentials dict over platform config."""
    creds = dict(credentials or {})
    for k, v in kwargs.items():
        if v:
            creds[k] = v
    resend = creds.get("resend") or config.RESEND_API_KEY
    twilio_sid = creds.get("twilio_sid") or config.TWILIO_ACCOUNT_SID
    twilio_token = creds.get("twilio_token") or config.TWILIO_AUTH_TOKEN
    twilio_from = creds.get("twilio_from") or config.TWILIO_FROM_NUMBER
    return resend, twilio_sid, twilio_token, twilio_from


async def send_email(to: str, subject: str, body: str, credentials: dict | None = None, **kwargs):
    resend_key, _, _, _ = _resolve_channel_creds(credentials, **kwargs)
    if not resend_key:
        return False, f"Email drafted for {to} (not sent — RESEND_API_KEY not configured)"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_key}"},
                json={"from": config.RESEND_FROM, "to": [to], "subject": subject, "text": body},
            )
        if r.status_code in (200, 201):
            return True, f"Email sent to {to}: “{subject}”"
        return False, f"Email to {to} failed ({r.status_code}): {r.text[:120]}"
    except Exception as e:
        return False, f"Email to {to} failed: {e}"


async def send_sms(to: str, body: str, credentials: dict | None = None, **kwargs):
    _, sid, token, from_num = _resolve_channel_creds(credentials, **kwargs)
    if not (sid and token and from_num):
        return False, f"SMS drafted for {to} (not sent — Twilio not configured)"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                auth=(sid, token),
                data={"To": to, "From": from_num, "Body": body[:1500]},
            )
        if r.status_code in (200, 201):
            return True, f"SMS sent to {to}"
        return False, f"SMS to {to} failed ({r.status_code}): {r.text[:120]}"
    except Exception as e:
        return False, f"SMS to {to} failed: {e}"


async def make_call(to: str, message: str, credentials: dict | None = None, **kwargs):
    _, sid, token, from_num = _resolve_channel_creds(credentials, **kwargs)
    if not (sid and token and from_num):
        return False, f"Call scripted for {to} (not placed — Twilio not configured)"
    try:
        twiml = f"<Response><Say>{message[:800]}</Say></Response>"
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json",
                auth=(sid, token),
                data={"To": to, "From": from_num, "Twiml": twiml},
            )
        if r.status_code in (200, 201):
            return True, f"Voice call placed to {to}"
        return False, f"Call to {to} failed ({r.status_code}): {r.text[:120]}"
    except Exception as e:
        return False, f"Call to {to} failed: {e}"
