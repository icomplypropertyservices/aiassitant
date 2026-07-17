"""Execute actions against connected apps (OAuth tokens / API keys)."""
from __future__ import annotations

import base64
import json
from email.mime.text import MIMEText
from typing import Any
from urllib.parse import quote

import httpx

from . import models
from .integrations_service import secrets_from_row, meta_from_row


async def run_app_action(
    conn: models.IntegrationConnection,
    action: str,
    payload: dict | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    secrets = secrets_from_row(conn)
    meta = meta_from_row(conn)
    app_id = conn.app_id
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
            "ok": True,
            "message": f"App '{app_id}' connected — action '{action}' recorded (generic).",
            "simulated": True,
            "payload": payload,
            "connection_status": conn.status,
        }
    try:
        return await fn(action, secrets, meta, payload)
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


async def _gmail(action, secrets, meta, payload):
    token = secrets.get("access_token")
    if not token:
        return {"ok": False, "error": "Gmail OAuth access_token missing — reconnect Google/Gmail"}
    if action in ("status", "test"):
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:300]}
            return {"ok": True, "message": f"Gmail {r.json().get('emailAddress')}", "data": r.json()}
    if action in ("send", "draft_send"):
        to = payload.get("to") or payload.get("email")
        subject = payload.get("subject") or "Message from AI Assistant"
        body = payload.get("body") or payload.get("text") or ""
        if not to:
            return {"ok": False, "error": "payload.to required"}
        mime = MIMEText(body, "plain", "utf-8")
        mime["to"] = to
        mime["subject"] = subject
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"raw": raw},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:400]}
            return {"ok": True, "message": f"Email sent to {to}", "data": r.json()}
    if action in ("list", "inbox"):
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={"maxResults": int(payload.get("limit") or 5)},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:300]}
            return {"ok": True, "message": "Inbox listed", "data": r.json()}
    return {"ok": False, "error": f"Unknown gmail action '{action}'"}


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


async def _shopify(action, secrets, meta, payload):
    shop = meta.get("shop_domain") or secrets.get("shop_domain")
    token = secrets.get("access_token")
    if not shop or not token:
        return {"ok": False, "error": "Shopify shop_domain + access_token required"}
    ver = secrets.get("api_version") or meta.get("api_version") or "2024-10"
    base = f"https://{shop}/admin/api/{ver}"
    path = {
        "status": "/shop.json",
        "test": "/shop.json",
        "orders": "/orders.json?limit=5&status=any",
        "products": "/products.json?limit=5",
        "customers": "/customers.json?limit=5",
    }.get(action, "/shop.json")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(base + path, headers={"X-Shopify-Access-Token": token})
        if r.status_code >= 400:
            return {"ok": False, "error": r.text[:300]}
        return {"ok": True, "message": f"Shopify {action}", "data": r.json()}


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
    if not url:
        return {"ok": False, "error": "webhook_url missing"}
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
        # Simplified UGC post requires author URN — return guidance if missing
        author = payload.get("author") or meta.get("person_urn")
        text = payload.get("text") or payload.get("message")
        if not author or not text:
            return {
                "ok": False,
                "error": "LinkedIn post needs payload.author (urn:li:person:…) and payload.text",
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
            return {"ok": True, "message": "Instagram token present — set ig_user_id in meta for posting"}
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
        "error": "Instagram publishing requires media container flow — use status/test or Media API from dashboard",
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
