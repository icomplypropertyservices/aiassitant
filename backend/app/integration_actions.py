"""Execute actions against connected apps (OAuth tokens / API keys)."""
from __future__ import annotations

import base64
import ipaddress
import json
import re
from email.mime.text import MIMEText
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from .shopify_actions import shopify_action as _shopify

# Note: do not import integrations_service at module top - circular with integration_probes.
# secrets_from_row / meta_from_row / set_secrets are imported lazily in run_app_action.

# Hostnames / patterns blocked for user-supplied webhook URLs (SSRF).
_BLOCKED_WEBHOOK_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "169.254.169.254",
        "metadata.google.internal",
        "metadata",
    }
)
_PRIVATE_IP_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),  # 172.16-31.*
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def validate_webhook_url(url: str | None) -> str | None:
    """Return an error message if *url* is unsafe for server-side fetch, else None.

    Rejects non-http(s) schemes and hosts that resolve to loopback, link-local,
    private ranges, cloud metadata, or well-known internal names.
    """
    if not url or not str(url).strip():
        return "webhook_url missing"
    raw = str(url).strip()
    try:
        parsed = urlparse(raw)
    except Exception:
        return "Invalid webhook_url"
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return "webhook_url must use http or https"
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return "webhook_url missing host"
    # Strip trailing dots / brackets noise
    host = host.rstrip(".")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if host in _BLOCKED_WEBHOOK_HOSTS:
        return "webhook_url host is not allowed"
    if host.endswith(".localhost") or host.endswith(".local"):
        return "webhook_url host is not allowed"
    # Literal IP address
    try:
        ip = ipaddress.ip_address(host)
        for net in _PRIVATE_IP_NETWORKS:
            if ip in net:
                return "webhook_url must not target private or link-local addresses"
        if ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved or ip.is_multicast:
            return "webhook_url must not target private or link-local addresses"
    except ValueError:
        # Hostname: block obvious private-range dotted patterns if mis-parsed as host
        if re.match(r"^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$", host):
            return "webhook_url must not target private or link-local addresses"
        if re.match(r"^192\.168\.\d{1,3}\.\d{1,3}$", host):
            return "webhook_url must not target private or link-local addresses"
        m = re.match(r"^172\.(\d{1,3})\.\d{1,3}\.\d{1,3}$", host)
        if m and 16 <= int(m.group(1)) <= 31:
            return "webhook_url must not target private or link-local addresses"
        if host == "169.254.169.254" or host.startswith("169.254."):
            return "webhook_url must not target private or link-local addresses"
    return None


async def run_app_action(
    conn,  # models.IntegrationConnection
    action: str,
    payload: dict | None = None,
    *,
    app_id: str | None = None,
) -> dict[str, Any]:
    """Dispatch to an app handler. app_id overrides conn.app_id (e.g. google token -> gmail actions)."""
    from .integrations_service import secrets_from_row, meta_from_row, set_secrets

    payload = payload or {}
    secrets = secrets_from_row(conn)
    meta = meta_from_row(conn)
    app_id = (app_id or conn.app_id or "").strip().lower()
    action = (action or "status").lower()

    handlers = {
        "slack": _slack,
        "gmail": _gmail,
        "google": _google,
        "google_sheets": _sheets,
        "shopify": _shopify,
        "hubspot": _hubspot,
        "notion": _notion,
        "zapier": _zapier,
        "x": _x_twitter,
        "twitter": _x_twitter,
        "linkedin": _linkedin,
        "meta": _meta,
        "facebook": _meta,
        "instagram": _instagram,
        "youtube": _youtube,
        "discord": _discord,
        "microsoft": _microsoft,
        "mailchimp": _mailchimp,
        "woocommerce": _woocommerce,
        "dropbox": _dropbox,
    }
    fn = handlers.get(app_id)
    if not fn:
        return {
            "ok": False,
            "error": (
                f"No handler for app '{app_id}' action '{action}'. "
                "Connect a supported app or use a wired integration skill."
            ),
            "app_id": app_id,
            "action": action,
            "connection_status": getattr(conn, "status", None),
        }
    try:
        result = await fn(action, secrets, meta, payload)
        # Persist refreshed OAuth tokens when handlers return them
        if isinstance(result, dict) and result.get("refreshed_secrets"):
            try:
                set_secrets(conn, result.pop("refreshed_secrets"))
                result["token_refreshed"] = True
            except Exception:
                result.pop("refreshed_secrets", None)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e), "app_id": app_id, "action": action}


async def _slack(action, secrets, meta, payload):
    token = secrets.get("bot_token") or secrets.get("access_token")
    if not token:
        return {"ok": False, "error": "Missing Slack bot token"}
    channel = payload.get("channel") or meta.get("default_channel") or "#general"
    text = payload.get("text") or payload.get("message") or "Update from AI Business Assistant"
    if action in ("status", "test"):
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {token}"},
            )
            data = r.json()
            return {"ok": bool(data.get("ok")), "message": data.get("error") or f"Slack team {data.get('team')}", "data": data}
    if action in ("post", "send", "message", "notify"):
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"channel": channel, "text": text},
            )
            data = r.json()
            return {"ok": bool(data.get("ok")), "message": data.get("error") or "Posted to Slack", "data": data}
    return {"ok": False, "error": f"Unknown slack action '{action}'"}


def _gmail_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _addr_list(val) -> str:
    """Normalize to/cc/bcc into a comma-separated header string."""
    if val is None:
        return ""
    if isinstance(val, (list, tuple)):
        return ", ".join(str(x).strip() for x in val if str(x).strip())
    return str(val).strip()


def _build_mime_message(
    *,
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    html: bool = False,
    reply_to: str = "",
    in_reply_to: str = "",
    references: str = "",
    from_email: str = "",
) -> str:
    """Build RFC 2822 message and return Gmail API raw (urlsafe base64)."""
    subtype = "html" if html else "plain"
    mime = MIMEText(body or "", subtype, "utf-8")
    if to:
        mime["To"] = to
    if cc:
        mime["Cc"] = cc
    if bcc:
        mime["Bcc"] = bcc
    mime["Subject"] = subject or "(no subject)"
    if from_email:
        mime["From"] = from_email
    if reply_to:
        mime["Reply-To"] = reply_to
    if in_reply_to:
        mime["In-Reply-To"] = in_reply_to
    if references:
        mime["References"] = references
    return base64.urlsafe_b64encode(mime.as_bytes()).decode().rstrip("=")


def _header_map(payload: dict) -> dict[str, str]:
    headers = {}
    for h in (payload or {}).get("headers") or []:
        name = (h.get("name") or "").lower()
        if name:
            headers[name] = h.get("value") or ""
    return headers


def _extract_body_text(payload: dict | None, depth: int = 0) -> str:
    """Best-effort plain text from Gmail message payload."""
    if not payload or depth > 8:
        return ""
    mime = (payload.get("mimeType") or "").lower()
    body = payload.get("body") or {}
    data = body.get("data")
    if data and mime in ("text/plain", "text/html", ""):
        try:
            raw = base64.urlsafe_b64decode(data + "===")
            text = raw.decode("utf-8", errors="replace")
            if mime == "text/html":
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
            return text
        except Exception:
            pass
    parts = payload.get("parts") or []
    plain = ""
    html = ""
    for part in parts:
        t = _extract_body_text(part, depth + 1)
        pm = (part.get("mimeType") or "").lower()
        if pm == "text/plain" and t and not plain:
            plain = t
        elif pm == "text/html" and t and not html:
            html = t
        elif t and not plain:
            plain = t
    return plain or html


async def _gmail_refresh_token(secrets: dict) -> dict | None:
    """Refresh Google access_token using refresh_token. Returns new secrets or None."""
    refresh = (secrets or {}).get("refresh_token")
    if not refresh:
        return None
    from . import config as app_config
    client_id = (getattr(app_config, "GOOGLE_OAUTH_CLIENT_ID", None) or "").strip()
    client_secret = (getattr(app_config, "GOOGLE_OAUTH_CLIENT_SECRET", None) or "").strip()
    import os
    client_id = client_id or os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = client_secret or os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh,
                    "grant_type": "refresh_token",
                },
            )
        if r.status_code >= 400:
            return None
        data = r.json() or {}
        access = data.get("access_token")
        if not access:
            return None
        out = dict(secrets)
        out["access_token"] = access
        if data.get("refresh_token"):
            out["refresh_token"] = data["refresh_token"]
        return out
    except Exception:
        return None


async def _gmail_request(
    method: str,
    path: str,
    secrets: dict,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
) -> tuple[int, Any, dict]:
    """HTTP to Gmail API; retries once after token refresh. Returns (status, data, secrets)."""
    token = (secrets or {}).get("access_token")
    if not token:
        return 401, {"error": "missing access_token"}, secrets
    url = path if path.startswith("http") else f"https://gmail.googleapis.com/gmail/v1/users/me{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.request(
            method,
            url,
            headers=_gmail_headers(token),
            params=params,
            json=json_body,
        )
        if r.status_code in (401, 403) and secrets.get("refresh_token"):
            refreshed = await _gmail_refresh_token(secrets)
            if refreshed and refreshed.get("access_token"):
                secrets = refreshed
                r = await client.request(
                    method,
                    url,
                    headers=_gmail_headers(secrets["access_token"]),
                    params=params,
                    json=json_body,
                )
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text[:500]}
        return r.status_code, data, secrets


async def _gmail_summarize_message(msg: dict) -> dict:
    payload = msg.get("payload") or {}
    headers = _header_map(payload)
    return {
        "id": msg.get("id"),
        "thread_id": msg.get("threadId"),
        "snippet": msg.get("snippet") or "",
        "label_ids": msg.get("labelIds") or [],
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "cc": headers.get("cc", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "message_id_header": headers.get("message-id", ""),
        "body_preview": (_extract_body_text(payload) or msg.get("snippet") or "")[:2000],
    }


async def _gmail(action, secrets, meta, payload):
    """
    Full Gmail actions for connected Google Cloud OAuth:
      status/test, send, reply, draft, list/inbox, search, get/get_message,
      get_thread, archive, read
    Supports To, Cc, Bcc on send/draft/reply.
    """
    payload = payload or {}
    secrets = dict(secrets or {})
    token = secrets.get("access_token")
    if not token:
        return {"ok": False, "error": "Gmail OAuth access_token missing - reconnect Google/Gmail in Settings -> Connected apps"}

    action = (action or "status").lower().replace("-", "_")

    if action in ("status", "test"):
        code, data, secrets = await _gmail_request("GET", "/profile", secrets)
        if code >= 400:
            return {"ok": False, "error": str(data)[:300], "refreshed_secrets": secrets if secrets.get("access_token") != token else None}
        return {
            "ok": True,
            "message": f"Gmail {data.get('emailAddress')}",
            "data": data,
            "refreshed_secrets": secrets if secrets.get("access_token") != token else None,
        }

    if action in ("send", "draft_send", "email_send"):
        to = _addr_list(payload.get("to") or payload.get("email"))
        cc = _addr_list(payload.get("cc") or payload.get("Cc"))
        bcc = _addr_list(payload.get("bcc") or payload.get("Bcc"))
        subject = (payload.get("subject") or "Message from AI Assistant").strip()
        body = payload.get("body") or payload.get("text") or payload.get("html") or ""
        html = bool(payload.get("html") is True or payload.get("is_html") or (payload.get("body_type") or "").lower() == "html")
        if not to:
            return {"ok": False, "error": "to (recipient email) is required"}
        if not body:
            return {"ok": False, "error": "body is required"}
        from_email = (payload.get("from") or payload.get("from_email") or meta.get("from_email") or "").strip()
        raw = _build_mime_message(
            to=to, subject=subject, body=body, cc=cc, bcc=bcc, html=html,
            reply_to=_addr_list(payload.get("reply_to")),
            from_email=from_email,
        )
        send_body: dict[str, Any] = {"raw": raw}
        if payload.get("thread_id"):
            send_body["threadId"] = str(payload["thread_id"])
        code, data, secrets = await _gmail_request("POST", "/messages/send", secrets, json_body=send_body)
        if code >= 400:
            return {"ok": False, "error": str(data)[:500], "refreshed_secrets": secrets if secrets.get("access_token") != token else None}
        return {
            "ok": True,
            "message": f"Email sent to {to}" + (f" (cc {cc})" if cc else ""),
            "data": data,
            "to": to,
            "cc": cc or None,
            "bcc": bcc or None,
            "subject": subject,
            "refreshed_secrets": secrets if secrets.get("access_token") != token else None,
        }

    if action in ("reply", "reply_all"):
        body = payload.get("body") or payload.get("text") or ""
        if not body:
            return {"ok": False, "error": "body is required for reply"}
        thread_id = payload.get("thread_id") or payload.get("threadId")
        message_id = payload.get("message_id") or payload.get("messageId")
        # Load original message for headers
        orig = None
        if message_id:
            code, orig, secrets = await _gmail_request(
                "GET", f"/messages/{message_id}", secrets,
                params={"format": "metadata", "metadataHeaders": ["From", "To", "Cc", "Subject", "Message-ID", "References"]},
            )
            if code >= 400:
                return {"ok": False, "error": f"Could not load message: {orig}"[:400]}
            thread_id = thread_id or orig.get("threadId")
        elif thread_id:
            code, thr, secrets = await _gmail_request("GET", f"/threads/{thread_id}", secrets, params={"format": "metadata"})
            if code >= 400:
                return {"ok": False, "error": f"Could not load thread: {thr}"[:400]}
            msgs = thr.get("messages") or []
            if not msgs:
                return {"ok": False, "error": "Thread has no messages"}
            orig = msgs[-1]
            message_id = orig.get("id")
        else:
            return {"ok": False, "error": "thread_id or message_id required for reply"}

        headers = _header_map((orig or {}).get("payload") or {})
        to = _addr_list(payload.get("to") or headers.get("from") or "")
        if action == "reply_all":
            # include original To + Cc minus ourselves if possible
            extras = []
            for part in (headers.get("to", ""), headers.get("cc", "")):
                extras.extend([p.strip() for p in part.split(",") if p.strip()])
            existing = {x.lower() for x in to.split(",") if x}
            for e in extras:
                if e.lower() not in existing:
                    to = f"{to}, {e}" if to else e
        cc = _addr_list(payload.get("cc") or (headers.get("cc") if action == "reply_all" else ""))
        subj = (payload.get("subject") or headers.get("subject") or "").strip()
        if subj and not subj.lower().startswith("re:"):
            subj = f"Re: {subj}"
        in_reply = headers.get("message-id") or ""
        refs = headers.get("references") or ""
        if in_reply:
            refs = f"{refs} {in_reply}".strip() if refs else in_reply
        raw = _build_mime_message(
            to=to,
            subject=subj or "Re:",
            body=body,
            cc=cc,
            bcc=_addr_list(payload.get("bcc")),
            html=bool(payload.get("html")),
            in_reply_to=in_reply,
            references=refs,
        )
        send_body = {"raw": raw}
        if thread_id:
            send_body["threadId"] = str(thread_id)
        code, data, secrets = await _gmail_request("POST", "/messages/send", secrets, json_body=send_body)
        if code >= 400:
            return {"ok": False, "error": str(data)[:500]}
        return {
            "ok": True,
            "message": f"Replied to {to}",
            "data": data,
            "thread_id": thread_id,
            "to": to,
            "cc": cc or None,
            "refreshed_secrets": secrets if secrets.get("access_token") != token else None,
        }

    if action in ("draft", "create_draft"):
        to = _addr_list(payload.get("to") or payload.get("email"))
        cc = _addr_list(payload.get("cc"))
        bcc = _addr_list(payload.get("bcc"))
        subject = (payload.get("subject") or "").strip()
        body = payload.get("body") or payload.get("text") or ""
        raw = _build_mime_message(to=to, subject=subject, body=body, cc=cc, bcc=bcc, html=bool(payload.get("html")))
        draft_body: dict[str, Any] = {"message": {"raw": raw}}
        if payload.get("thread_id"):
            draft_body["message"]["threadId"] = str(payload["thread_id"])
        code, data, secrets = await _gmail_request("POST", "/drafts", secrets, json_body=draft_body)
        if code >= 400:
            return {"ok": False, "error": str(data)[:500]}
        return {
            "ok": True,
            "message": f"Draft created for {to or '(no to)'}",
            "data": data,
            "to": to,
            "cc": cc or None,
            "subject": subject,
            "refreshed_secrets": secrets if secrets.get("access_token") != token else None,
        }

    if action in ("list", "inbox", "read", "list_messages"):
        q = (payload.get("query") or payload.get("q") or payload.get("label") or "").strip()
        if payload.get("label") and "label:" not in q.lower() and q == (payload.get("label") or "").strip():
            q = f"label:{payload.get('label')}"
        if not q and action in ("inbox", "list", "list_messages", "read"):
            q = "in:inbox"
        limit = min(25, max(1, int(payload.get("limit") or 10)))
        params: dict[str, Any] = {"maxResults": limit}
        if q:
            params["q"] = q
        code, data, secrets = await _gmail_request("GET", "/messages", secrets, params=params)
        if code >= 400:
            return {"ok": False, "error": str(data)[:400]}
        messages = []
        for m in (data.get("messages") or [])[:limit]:
            mid = m.get("id")
            if not mid:
                continue
            c2, full, secrets = await _gmail_request(
                "GET", f"/messages/{mid}", secrets,
                params={"format": "full"},
            )
            if c2 < 400:
                messages.append(await _gmail_summarize_message(full))
            else:
                messages.append({"id": mid, "thread_id": m.get("threadId")})
        return {
            "ok": True,
            "message": f"Listed {len(messages)} messages",
            "count": len(messages),
            "messages": messages,
            "data": {"resultSizeEstimate": data.get("resultSizeEstimate"), "nextPageToken": data.get("nextPageToken")},
            "refreshed_secrets": secrets if secrets.get("access_token") != token else None,
        }

    if action in ("search",):
        q = (payload.get("query") or payload.get("q") or "").strip()
        if not q:
            return {"ok": False, "error": "query is required for search"}
        payload = {**payload, "query": q}
        return await _gmail("list", secrets, meta, payload)

    if action in ("get", "get_message", "read_message"):
        mid = payload.get("message_id") or payload.get("id") or payload.get("messageId")
        if not mid:
            return {"ok": False, "error": "message_id required"}
        code, full, secrets = await _gmail_request("GET", f"/messages/{mid}", secrets, params={"format": "full"})
        if code >= 400:
            return {"ok": False, "error": str(full)[:400]}
        summary = await _gmail_summarize_message(full)
        summary["body"] = _extract_body_text(full.get("payload") or {})
        return {"ok": True, "message": "Message loaded", "data": summary, "refreshed_secrets": secrets if secrets.get("access_token") != token else None}

    if action in ("get_thread", "thread"):
        tid = payload.get("thread_id") or payload.get("threadId") or payload.get("id")
        if not tid:
            return {"ok": False, "error": "thread_id required"}
        code, thr, secrets = await _gmail_request("GET", f"/threads/{tid}", secrets, params={"format": "full"})
        if code >= 400:
            return {"ok": False, "error": str(thr)[:400]}
        msgs = []
        for m in thr.get("messages") or []:
            msgs.append(await _gmail_summarize_message(m))
        return {
            "ok": True,
            "message": f"Thread {tid} ({len(msgs)} messages)",
            "thread_id": tid,
            "messages": msgs,
            "data": thr,
            "refreshed_secrets": secrets if secrets.get("access_token") != token else None,
        }

    if action in ("archive", "remove_inbox"):
        mid = payload.get("message_id") or payload.get("id")
        tid = payload.get("thread_id") or payload.get("threadId")
        if mid:
            code, data, secrets = await _gmail_request(
                "POST", f"/messages/{mid}/modify", secrets,
                json_body={"removeLabelIds": ["INBOX"]},
            )
            if code >= 400:
                return {"ok": False, "error": str(data)[:400]}
            return {"ok": True, "message": f"Archived message {mid}", "data": data}
        if tid:
            code, data, secrets = await _gmail_request(
                "POST", f"/threads/{tid}/modify", secrets,
                json_body={"removeLabelIds": ["INBOX"]},
            )
            if code >= 400:
                return {"ok": False, "error": str(data)[:400]}
            return {"ok": True, "message": f"Archived thread {tid}", "data": data}
        return {"ok": False, "error": "message_id or thread_id required"}

    return {
        "ok": False,
        "error": (
            f"Unknown gmail action '{action}'. "
            "Use: status, send, reply, reply_all, draft, list, search, get, get_thread, archive"
        ),
    }


async def _google(action, secrets, meta, payload):
    token = secrets.get("access_token")
    if action in ("status", "test") and token:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:300]}
            return {"ok": True, "message": f"Google user {r.json().get('email')}", "data": r.json()}
    if action in ("calendar", "events") and token:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {token}"},
                params={"maxResults": 5, "singleEvents": "true", "orderBy": "startTime"},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:300]}
            return {"ok": True, "message": "Calendar events", "data": r.json()}
    api_key = secrets.get("api_key")
    if api_key and action in ("status", "test"):
        return {"ok": True, "message": "Google API key on file", "has_api_key": True}
    return {"ok": False, "error": "Provide OAuth token or use a more specific Google app (gmail, google_sheets)"}


async def _sheets(action, secrets, meta, payload):
    token = secrets.get("access_token")
    sheet_id = payload.get("spreadsheet_id") or meta.get("spreadsheet_id")
    if not token:
        return {"ok": False, "error": "Sheets OAuth token missing"}
    if not sheet_id and action not in ("status", "test"):
        return {"ok": False, "error": "spreadsheet_id required"}
    if action in ("status", "test"):
        return {"ok": True, "message": "Google Sheets token present", "spreadsheet_id": sheet_id}
    if action in ("read", "values"):
        rng = payload.get("range") or "Sheet1!A1:D20"
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{quote(rng)}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:300]}
            return {"ok": True, "message": "Sheet values", "data": r.json()}
    if action in ("append", "write"):
        rng = payload.get("range") or "Sheet1!A1"
        values = payload.get("values") or [[payload.get("text") or ""]]
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{quote(rng)}:append",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                params={"valueInputOption": "USER_ENTERED"},
                json={"values": values},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:300]}
            return {"ok": True, "message": "Rows appended", "data": r.json()}
    return {"ok": False, "error": f"Unknown sheets action '{action}'"}



async def _hubspot(action, secrets, meta, payload):
    token = secrets.get("access_token")
    if not token:
        return {"ok": False, "error": "HubSpot token missing"}
    path = {
        "status": "/crm/v3/objects/contacts?limit=1",
        "test": "/crm/v3/objects/contacts?limit=1",
        "contacts": "/crm/v3/objects/contacts?limit=5",
        "deals": "/crm/v3/objects/deals?limit=5",
    }.get(action, "/crm/v3/objects/contacts?limit=5")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"https://api.hubapi.com{path}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code >= 400:
            return {"ok": False, "error": r.text[:300]}
        return {"ok": True, "message": f"HubSpot {action}", "data": r.json()}


async def _notion(action, secrets, meta, payload):
    token = secrets.get("integration_token") or secrets.get("access_token")
    if not token:
        return {"ok": False, "error": "Notion token missing"}
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    if action in ("status", "test", "search"):
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.notion.com/v1/search",
                headers=headers,
                json={"page_size": 5, "query": payload.get("query") or ""},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:300]}
            return {"ok": True, "message": "Notion search", "data": r.json()}
    return {"ok": False, "error": f"Unknown notion action '{action}'"}


async def _zapier(action, secrets, meta, payload):
    url = secrets.get("webhook_url")
    err = validate_webhook_url(url)
    if err:
        return {"ok": False, "error": err}
    body = payload or {"event": action or "agent_event"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, json=body)
        return {
            "ok": r.status_code < 400,
            "message": f"Webhook {r.status_code}",
            "status_code": r.status_code,
        }


async def _x_twitter(action, secrets, meta, payload):
    token = secrets.get("access_token") or secrets.get("bearer_token")
    if not token:
        return {"ok": False, "error": "X/Twitter bearer or OAuth access_token required"}
    if action in ("status", "test", "me"):
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://api.twitter.com/2/users/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:300]}
            return {"ok": True, "message": "X user", "data": r.json()}
    if action in ("post", "tweet"):
        text = payload.get("text") or payload.get("message")
        if not text:
            return {"ok": False, "error": "payload.text required"}
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.twitter.com/2/tweets",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"text": text},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:400]}
            return {"ok": True, "message": "Posted to X", "data": r.json()}
    return {"ok": False, "error": f"Unknown x action '{action}'"}


async def _linkedin(action, secrets, meta, payload):
    token = secrets.get("access_token")
    if not token:
        return {"ok": False, "error": "LinkedIn access_token required"}
    if action in ("status", "test", "me"):
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code >= 400:
                # fallback legacy
                r2 = await client.get(
                    "https://api.linkedin.com/v2/me",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if r2.status_code >= 400:
                    return {"ok": False, "error": r.text[:300]}
                return {"ok": True, "message": "LinkedIn connected", "data": r2.json()}
            return {"ok": True, "message": "LinkedIn connected", "data": r.json()}
    if action in ("post", "share"):
        # Simplified UGC post requires author URN - return guidance if missing
        author = payload.get("author") or meta.get("person_urn")
        text = payload.get("text") or payload.get("message")
        if not author or not text:
            return {
                "ok": False,
                "error": "LinkedIn post needs payload.author (urn:li:person:) and payload.text",
            }
        body = {
            "author": author,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.linkedin.com/v2/ugcPosts",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "X-Restli-Protocol-Version": "2.0.0",
                },
                json=body,
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:400]}
            return {"ok": True, "message": "Posted to LinkedIn", "data": r.json()}
    return {"ok": False, "error": f"Unknown linkedin action '{action}'"}


async def _meta(action, secrets, meta, payload):
    token = secrets.get("access_token") or secrets.get("page_token")
    if not token:
        return {"ok": False, "error": "Meta access_token required"}
    page_id = payload.get("page_id") or meta.get("page_id")
    if action in ("status", "test", "me"):
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://graph.facebook.com/v19.0/me",
                params={"access_token": token, "fields": "id,name"},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:300]}
            return {"ok": True, "message": "Meta connected", "data": r.json()}
    if action in ("post", "page_post"):
        if not page_id:
            return {"ok": False, "error": "page_id required for page posts"}
        message = payload.get("message") or payload.get("text")
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"https://graph.facebook.com/v19.0/{page_id}/feed",
                data={"message": message, "access_token": token},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:400]}
            return {"ok": True, "message": "Posted to Facebook Page", "data": r.json()}
    return {"ok": False, "error": f"Unknown meta action '{action}'"}


async def _instagram(action, secrets, meta, payload):
    token = secrets.get("access_token")
    ig_user = payload.get("ig_user_id") or meta.get("ig_user_id")
    if not token:
        return {"ok": False, "error": "Instagram access_token required"}
    if action in ("status", "test"):
        if not ig_user:
            return {"ok": True, "message": "Instagram token present - set ig_user_id in meta for posting"}
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"https://graph.facebook.com/v19.0/{ig_user}",
                params={"fields": "id,username", "access_token": token},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:300]}
            return {"ok": True, "message": "Instagram account", "data": r.json()}
    return {
        "ok": False,
        "error": "Instagram publishing requires media container flow - use status/test or Media API from dashboard",
    }


async def _youtube(action, secrets, meta, payload):
    token = secrets.get("access_token")
    if not token:
        return {"ok": False, "error": "YouTube OAuth access_token required"}
    if action in ("status", "test", "channels"):
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://www.googleapis.com/youtube/v3/channels",
                headers={"Authorization": f"Bearer {token}"},
                params={"part": "snippet,statistics", "mine": "true"},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:300]}
            return {"ok": True, "message": "YouTube channels", "data": r.json()}
    return {"ok": False, "error": f"Unknown youtube action '{action}'"}


async def _discord(action, secrets, meta, payload):
    webhook = secrets.get("webhook_url")
    bot = secrets.get("bot_token")
    if action in ("post", "send", "notify") and webhook:
        err = validate_webhook_url(webhook)
        if err:
            return {"ok": False, "error": err}
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(webhook, json={"content": payload.get("text") or payload.get("message") or "Update"})
            return {"ok": r.status_code < 400, "message": f"Discord webhook {r.status_code}"}
    if bot and action in ("status", "test"):
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {bot}"},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:300]}
            return {"ok": True, "message": "Discord bot OK", "data": r.json()}
    return {"ok": False, "error": "Provide webhook_url or bot_token"}


async def _microsoft(action, secrets, meta, payload):
    token = secrets.get("access_token")
    if not token:
        return {"ok": False, "error": "Microsoft access_token required"}
    if action in ("status", "test", "me"):
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:300]}
            return {"ok": True, "message": "Microsoft Graph OK", "data": r.json()}
    if action in ("mail", "send_mail"):
        to = payload.get("to")
        subject = payload.get("subject") or "Message"
        body = payload.get("body") or payload.get("text") or ""
        if not to:
            return {"ok": False, "error": "payload.to required"}
        msg = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to}}],
            },
            "saveToSentItems": True,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://graph.microsoft.com/v1.0/me/sendMail",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=msg,
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:400]}
            return {"ok": True, "message": f"Mail sent to {to}"}
    return {"ok": False, "error": f"Unknown microsoft action '{action}'"}


async def _mailchimp(action, secrets, meta, payload):
    key = secrets.get("api_key") or ""
    if "-" not in key:
        return {"ok": False, "error": "Mailchimp api_key should look like xxxx-us21"}
    dc = secrets.get("server_prefix") or key.split("-")[-1]
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"https://{dc}.api.mailchimp.com/3.0/",
            auth=("any", key),
        )
        if r.status_code >= 400:
            return {"ok": False, "error": r.text[:300]}
        if action in ("lists", "audiences"):
            r2 = await client.get(
                f"https://{dc}.api.mailchimp.com/3.0/lists?count=5",
                auth=("any", key),
            )
            return {"ok": True, "message": "Mailchimp lists", "data": r2.json()}
        return {"ok": True, "message": "Mailchimp OK", "data": r.json()}


async def _woocommerce(action, secrets, meta, payload):
    store = (secrets.get("store_url") or meta.get("store_url") or "").rstrip("/")
    ck, cs = secrets.get("consumer_key"), secrets.get("consumer_secret")
    if not store or not ck or not cs:
        return {"ok": False, "error": "store_url, consumer_key, consumer_secret required"}
    path = "/wp-json/wc/v3/orders" if action in ("orders", "list") else "/wp-json/wc/v3/products"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{store}{path}", params={"consumer_key": ck, "consumer_secret": cs, "per_page": 5})
        if r.status_code >= 400:
            return {"ok": False, "error": r.text[:300]}
        return {"ok": True, "message": f"WooCommerce {action}", "data": r.json()}


async def _dropbox(action, secrets, meta, payload):
    token = secrets.get("access_token")
    if not token:
        return {"ok": False, "error": "Dropbox access_token required"}
    path = payload.get("path") or meta.get("root_path") or ""
    async with httpx.AsyncClient(timeout=20) as client:
        if action in ("status", "test"):
            r = await client.post(
                "https://api.dropboxapi.com/2/users/get_current_account",
                headers={"Authorization": f"Bearer {token}"},
            )
        else:
            r = await client.post(
                "https://api.dropboxapi.com/2/files/list_folder",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"path": path or ""},
            )
        if r.status_code >= 400:
            return {"ok": False, "error": r.text[:300]}
        return {"ok": True, "message": f"Dropbox {action}", "data": r.json()}
