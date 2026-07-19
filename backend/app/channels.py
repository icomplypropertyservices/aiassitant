"""Multi-channel service: Email (Resend) + SMS/Voice (Twilio).
Every function returns (sent: bool, detail: str) so agent terminals can log
exactly what happened. With no keys configured, actions are logged, not sent.

BYOK: pass credentials from user_keys (resend, twilio_sid, twilio_token, twilio_from).
User keys are preferred over platform config.* env; RESEND_FROM still comes from config.

Email also supports optional cc / bcc lists.
"""
import re
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


def _e164(phone: str) -> str:
    """Normalize to E.164-ish (+digits). Leaves whatsapp: prefix intact."""
    p = (phone or "").strip()
    if p.lower().startswith("whatsapp:"):
        rest = _e164(p.split(":", 1)[1])
        return f"whatsapp:{rest}" if rest else p
    digits = re.sub(r"[^\d+]", "", p)
    if digits and not digits.startswith("+"):
        # Assume already international if long enough; otherwise leave as-is for Twilio to reject clearly
        if len(digits) >= 10:
            digits = "+" + digits
    return digits or p


def _addr_list(val) -> list[str]:
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        return [str(x).strip() for x in val if str(x).strip()]
    s = str(val).strip()
    if not s:
        return []
    return [p.strip() for p in s.split(",") if p.strip()]


def smtp_or_resend_configured(credentials: dict | None = None) -> bool:
    """True if classic SMTP or Resend API can send mail."""
    creds = dict(credentials or {})
    if creds.get("resend") or config.RESEND_API_KEY:
        return True
    host = creds.get("smtp_host") or getattr(config, "SMTP_HOST", "") or ""
    user = creds.get("smtp_user") or getattr(config, "SMTP_USER", "") or ""
    password = creds.get("smtp_password") or getattr(config, "SMTP_PASSWORD", "") or ""
    return bool(host and user and password)


def _smtp_settings(credentials: dict | None = None) -> dict:
    creds = dict(credentials or {})
    return {
        "host": (creds.get("smtp_host") or getattr(config, "SMTP_HOST", "") or "").strip(),
        "port": int(creds.get("smtp_port") or getattr(config, "SMTP_PORT", 587) or 587),
        "user": (creds.get("smtp_user") or getattr(config, "SMTP_USER", "") or "").strip(),
        "password": (creds.get("smtp_password") or getattr(config, "SMTP_PASSWORD", "") or "").strip(),
        "from_addr": (
            creds.get("smtp_from")
            or getattr(config, "SMTP_FROM", "")
            or config.RESEND_FROM
            or ""
        ).strip(),
        "tls": str(creds.get("smtp_tls") if creds.get("smtp_tls") is not None else getattr(config, "SMTP_TLS", True)).lower()
        not in ("0", "false", "no"),
    }


def _send_via_smtp(
    to_list: list[str],
    subject: str,
    body: str,
    *,
    cc_list: list[str] | None = None,
    bcc_list: list[str] | None = None,
    html: str | None = None,
    credentials: dict | None = None,
) -> tuple[bool, str]:
    """Send with stdlib smtplib (STARTTLS by default)."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    cfg = _smtp_settings(credentials)
    if not (cfg["host"] and cfg["user"] and cfg["password"]):
        return False, "SMTP not configured (SMTP_HOST / SMTP_USER / SMTP_PASSWORD)"
    if not to_list:
        return False, "Email failed: no recipients"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"] or cfg["user"]
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg.attach(MIMEText(body or "", "plain", "utf-8"))
    if html:
        msg.attach(MIMEText(html, "html", "utf-8"))
    recipients = list(to_list) + list(cc_list or []) + list(bcc_list or [])
    try:
        if cfg["tls"]:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(cfg["user"], cfg["password"])
                server.sendmail(msg["From"], recipients, msg.as_string())
        else:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=20) as server:
                server.login(cfg["user"], cfg["password"])
                server.sendmail(msg["From"], recipients, msg.as_string())
        return True, f"Email sent via SMTP to {','.join(to_list)}: “{subject}”"
    except Exception as e:
        return False, f"SMTP email failed: {e}"


async def send_email(
    to: str,
    subject: str,
    body: str,
    credentials: dict | None = None,
    *,
    cc: str | list | None = None,
    bcc: str | list | None = None,
    html: str | None = None,
    **kwargs,
):
    """Send via SMTP if configured, else Resend. Supports to + optional cc/bcc."""
    resend_key, _, _, _ = _resolve_channel_creds(credentials, **kwargs)
    to_list = _addr_list(to)
    cc_list = _addr_list(cc if cc is not None else kwargs.get("cc"))
    bcc_list = _addr_list(bcc if bcc is not None else kwargs.get("bcc"))
    if not to_list:
        return False, "Email failed: no recipients"

    # Prefer classic SMTP when fully set (user asked for SMTP notify path)
    smtp_cfg = _smtp_settings(credentials)
    if smtp_cfg["host"] and smtp_cfg["user"] and smtp_cfg["password"]:
        return _send_via_smtp(
            to_list, subject, body or "",
            cc_list=cc_list, bcc_list=bcc_list, html=html, credentials=credentials,
        )

    if not resend_key:
        return False, (
            f"Email drafted for {to} (not sent — set SMTP_HOST/SMTP_USER/SMTP_PASSWORD "
            "or RESEND_API_KEY; connect Gmail for OAuth mail)"
        )
    payload = {
        "from": config.RESEND_FROM,
        "to": to_list,
        "subject": subject,
        "text": body or "",
    }
    if html:
        payload["html"] = html
    if cc_list:
        payload["cc"] = cc_list
    if bcc_list:
        payload["bcc"] = bcc_list
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_key}"},
                json=payload,
            )
        if r.status_code in (200, 201):
            extra = ""
            if cc_list:
                extra += f" cc={','.join(cc_list)}"
            return True, f"Email sent to {','.join(to_list)}{extra}: “{subject}”"
        return False, f"Email to {','.join(to_list)} failed ({r.status_code}): {r.text[:200]}"
    except Exception as e:
        return False, f"Email to {to} failed: {e}"


async def send_transactional_email(to: str, subject: str, html_body: str) -> dict:
    """Platform transactional mail (auth verify/reset/2FA).

    Prefer platform SMTP when set (Namecheap etc. via env), else Resend API.
    Returns a dict suitable for auth routes:
      {ok: True, id?: str} on success
      {ok: False, dev: True, detail: str} when nothing configured (safe for local/dev)
      {ok: False, error: str} on API/network failure
    """
    # 1) Platform SMTP (works with Namecheap Private Email, etc.)
    smtp_cfg = _smtp_settings(None)
    if smtp_cfg["host"] and smtp_cfg["user"] and smtp_cfg["password"]:
        # Convert simple HTML to plain fallback
        plain = (html_body or "").replace("<br>", "\n").replace("<br/>", "\n")
        import re
        plain = re.sub(r"<[^>]+>", "", plain)
        ok, detail = _send_via_smtp(
            [to], subject, plain or subject, html=html_body, credentials=None,
        )
        if ok:
            return {"ok": True, "to": to, "subject": subject, "provider": "smtp", "detail": detail}
        return {"ok": False, "error": detail, "provider": "smtp"}

    # 2) Resend
    api_key = (config.RESEND_API_KEY or "").strip()
    from_addr = (config.RESEND_FROM or "").strip() or "assistant@yourdomain.com"
    if not api_key:
        return {
            "ok": False,
            "dev": True,
            "detail": (
                f"Email not sent (dev) — set SMTP_HOST/SMTP_USER/SMTP_PASSWORD "
                f"(e.g. Namecheap mail.privateemail.com) or RESEND_API_KEY; "
                f"would send to {to}: {subject}"
            ),
        }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "from": from_addr,
                    "to": [to],
                    "subject": subject,
                    "html": html_body,
                },
            )
        if r.status_code in (200, 201):
            data = {}
            try:
                data = r.json() or {}
            except Exception:
                pass
            return {"ok": True, "id": data.get("id"), "to": to, "subject": subject, "provider": "resend"}
        return {
            "ok": False,
            "error": f"Resend {r.status_code}: {r.text[:200]}",
            "provider": "resend",
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "provider": "resend"}


def _xml_escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def build_say_twiml(
    message: str,
    *,
    voice: str = "alice",
    language: str = "en-US",
    loop: int = 1,
) -> str:
    """Build TwiML so Twilio speaks the message on answer (text-to-speech)."""
    text = (message or "Hello. This is an automated call from your AI business assistant.").strip()
    # Twilio Say is happiest under ~4k chars; chunk long scripts
    chunks = []
    max_chunk = 900
    remaining = text
    while remaining:
        chunks.append(remaining[:max_chunk])
        remaining = remaining[max_chunk:]
    if not chunks:
        chunks = ["Hello."]
    voice = (voice or "alice").strip() or "alice"
    language = (language or "en-US").strip() or "en-US"
    try:
        loop_n = max(1, min(3, int(loop or 1)))
    except (TypeError, ValueError):
        loop_n = 1
    parts = ["<Response>"]
    for _ in range(loop_n):
        for i, chunk in enumerate(chunks):
            safe = _xml_escape(chunk)
            parts.append(
                f'<Say voice="{_xml_escape(voice)}" language="{_xml_escape(language)}">{safe}</Say>'
            )
            if i < len(chunks) - 1:
                parts.append("<Pause length=\"1\"/>")
        if loop_n > 1:
            parts.append("<Pause length=\"1\"/>")
    parts.append("</Response>")
    return "".join(parts)


async def send_sms(to: str, body: str, credentials: dict | None = None, **kwargs):
    """
    Initiate outbound SMS via Twilio.
    Returns (ok: bool, detail: str). On success detail includes Twilio Message SID.
    """
    _, sid, token, from_num = _resolve_channel_creds(credentials, **kwargs)
    if not (sid and token and from_num):
        return False, (
            f"SMS drafted for {to} (not sent — Twilio not configured. "
            "Add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER "
            "or save Twilio keys under Settings → API keys: twilio_sid, twilio_token, twilio_from)"
        )
    to_n = _e164(to)
    from_n = _e164(from_num)
    if not to_n or len(re.sub(r"\D", "", to_n)) < 8:
        return False, f"SMS failed: invalid To number '{to}' (use E.164 e.g. +15551234567)"
    text = (body or "").strip()
    if not text:
        return False, "SMS failed: empty body"
    # SMS segment safety — Twilio allows longer via concatenated SMS
    text = text[:1600]
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                auth=(sid, token),
                data={"To": to_n, "From": from_n, "Body": text},
            )
        data = {}
        try:
            data = r.json() or {}
        except Exception:
            pass
        if r.status_code in (200, 201):
            msg_sid = data.get("sid") or ""
            status = data.get("status") or "queued"
            return True, f"SMS queued to {to_n} status={status}" + (f" sid={msg_sid}" if msg_sid else "")
        err = data.get("message") or data.get("error_message") or r.text[:200]
        code = data.get("code") or r.status_code
        return False, f"SMS to {to_n} failed ({code}): {err}"
    except Exception as e:
        return False, f"SMS to {to} failed: {e}"


async def make_call(
    to: str,
    message: str,
    credentials: dict | None = None,
    *,
    voice: str = "alice",
    language: str = "en-US",
    loop: int = 1,
    **kwargs,
):
    """
    Initiate outbound phone call via Twilio and speak `message` (TTS speech).

    Uses inline TwiML <Say> so no public webhook URL is required.
    Optional kwargs: voice (alice|man|woman|Polly.*), language (en-US), loop (1-3).
    Returns (ok: bool, detail: str) with Call SID on success.
    """
    _, sid, token, from_num = _resolve_channel_creds(credentials, **kwargs)
    if not (sid and token and from_num):
        return False, (
            f"Call scripted for {to} (not placed — Twilio not configured. "
            "Add TWILIO_* env or Settings → API keys twilio_sid / twilio_token / twilio_from)"
        )
    to_n = _e164(to)
    from_n = _e164(from_num)
    if not to_n or len(re.sub(r"\D", "", to_n)) < 8:
        return False, f"Call failed: invalid To number '{to}' (use E.164 e.g. +15551234567)"
    voice = kwargs.get("voice") or voice or "alice"
    language = kwargs.get("language") or language or "en-US"
    loop = kwargs.get("loop") if kwargs.get("loop") is not None else loop
    twiml = build_say_twiml(message, voice=str(voice), language=str(language), loop=loop)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json",
                auth=(sid, token),
                data={
                    "To": to_n,
                    "From": from_n,
                    "Twiml": twiml,
                    # Machine detection optional — keep simple for agent-initiated calls
                },
            )
        data = {}
        try:
            data = r.json() or {}
        except Exception:
            pass
        if r.status_code in (200, 201):
            call_sid = data.get("sid") or ""
            status = data.get("status") or "queued"
            preview = (message or "")[:80].replace("\n", " ")
            return (
                True,
                f"Voice call initiated to {to_n} status={status}"
                + (f" sid={call_sid}" if call_sid else "")
                + f' speech="{preview}{"…" if len(message or "") > 80 else ""}"',
            )
        err = data.get("message") or data.get("error_message") or r.text[:200]
        code = data.get("code") or r.status_code
        return False, f"Call to {to_n} failed ({code}): {err}"
    except Exception as e:
        return False, f"Call to {to} failed: {e}"


async def send_whatsapp(to: str, body: str, credentials: dict | None = None, **kwargs):
    """Send WhatsApp text via Twilio (Sandbox or approved sender)."""
    _, sid, token, from_num = _resolve_channel_creds(credentials, **kwargs)
    wa_from_override = (credentials or {}).get("twilio_whatsapp_from") or kwargs.get("twilio_whatsapp_from")
    if wa_from_override:
        from_num = wa_from_override
    if not (sid and token and from_num):
        return False, f"WhatsApp drafted for {to} (not sent — Twilio not configured)"

    to_n = _e164(to)
    from_n = _e164(from_num)
    wa_to = to_n if to_n.startswith("whatsapp:") else f"whatsapp:{to_n}"
    wa_from = from_n if from_n.startswith("whatsapp:") else f"whatsapp:{from_n}"
    text = (body or "").strip()[:1600]
    if not text:
        return False, "WhatsApp failed: empty body"

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                auth=(sid, token),
                data={"To": wa_to, "From": wa_from, "Body": text},
            )
        data = {}
        try:
            data = r.json() or {}
        except Exception:
            pass
        if r.status_code in (200, 201):
            msg_sid = data.get("sid") or ""
            return True, f"WhatsApp queued to {to_n}" + (f" sid={msg_sid}" if msg_sid else "")
        err = data.get("message") or r.text[:200]
        return False, f"WhatsApp to {to_n} failed ({r.status_code}): {err}"
    except Exception as e:
        return False, f"WhatsApp to {to} failed: {e}"


def twilio_configured(credentials: dict | None = None) -> bool:
    _, sid, token, from_num = _resolve_channel_creds(credentials)
    return bool(sid and token and from_num)


async def twilio_account_status(credentials: dict | None = None) -> dict:
    """Probe Twilio credentials (GET Account). Used by health/skills diagnostics."""
    _, sid, token, from_num = _resolve_channel_creds(credentials)
    if not (sid and token):
        return {
            "ok": False,
            "configured": False,
            "error": "Missing TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN (or user twilio_sid / twilio_token)",
        }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
                auth=(sid, token),
            )
        data = {}
        try:
            data = r.json() or {}
        except Exception:
            pass
        if r.status_code in (200, 201):
            return {
                "ok": True,
                "configured": True,
                "account_sid": sid[:6] + "…" + sid[-4:] if len(sid) > 12 else sid,
                "friendly_name": data.get("friendly_name"),
                "status": data.get("status"),
                "from_number": from_num or None,
                "sms": bool(from_num),
                "voice": bool(from_num),
            }
        return {
            "ok": False,
            "configured": True,
            "error": data.get("message") or r.text[:200],
            "status_code": r.status_code,
        }
    except Exception as e:
        return {"ok": False, "configured": True, "error": str(e)}
