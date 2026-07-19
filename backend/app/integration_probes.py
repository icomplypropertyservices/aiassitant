"""Registry of live connection probes — one function per app family."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

import httpx

from .integration_actions import validate_webhook_url

ProbeFn = Callable[[dict, dict], Awaitable[dict[str, Any]]]


async def _probe_shopify(secrets: dict, meta: dict) -> dict[str, Any]:
    shop = (secrets.get("shop_domain") or meta.get("shop_domain") or "").strip()
    shop = shop.replace("https://", "").replace("http://", "").split("/")[0]
    token = (secrets.get("access_token") or "").strip()
    if not shop or not token:
        return {"ok": False, "message": "Shop domain and access token required"}
    ver = (secrets.get("api_version") or meta.get("api_version") or "2024-10").strip()
    url = f"https://{shop}/admin/api/{ver}/shop.json"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        r = await client.get(url, headers={"X-Shopify-Access-Token": token})
    if r.status_code == 200:
        name = (r.json().get("shop") or {}).get("name") or shop
        return {"ok": True, "message": f"Connected to {name}", "shop_name": name}
    if r.status_code in (401, 403, 404):
        return {
            "ok": False,
            "message": f"Shopify auth failed (HTTP {r.status_code}) — check domain and Admin API token",
        }
    return {"ok": False, "message": f"Shopify returned HTTP {r.status_code}"}


async def _probe_slack(secrets: dict, meta: dict) -> dict[str, Any]:
    token = (secrets.get("bot_token") or secrets.get("access_token") or "").strip()
    if not token:
        return {"ok": False, "message": "Bot token required"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
        )
    data = r.json() if "json" in (r.headers.get("content-type") or "") else {}
    if data.get("ok"):
        return {"ok": True, "message": f"Slack team: {data.get('team', 'ok')}"}
    return {"ok": False, "message": data.get("error") or f"HTTP {r.status_code}"}


async def _probe_hubspot(secrets: dict, meta: dict) -> dict[str, Any]:
    token = (secrets.get("access_token") or "").strip()
    if not token:
        return {"ok": False, "message": "Access token required"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://api.hubapi.com/crm/v3/objects/contacts?limit=1",
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code == 200:
        return {"ok": True, "message": "HubSpot API reachable"}
    return {"ok": False, "message": f"HubSpot HTTP {r.status_code}"}


async def _probe_stripe(secrets: dict, meta: dict) -> dict[str, Any]:
    key = (secrets.get("secret_key") or "").strip()
    if not key:
        return {"ok": False, "message": "Secret key required"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://api.stripe.com/v1/balance",
            headers={"Authorization": f"Bearer {key}"},
        )
    if r.status_code == 200:
        return {"ok": True, "message": "Stripe account reachable"}
    return {"ok": False, "message": f"Stripe HTTP {r.status_code}"}


async def _probe_woocommerce(secrets: dict, meta: dict) -> dict[str, Any]:
    store = (secrets.get("store_url") or meta.get("store_url") or "").rstrip("/")
    ck = secrets.get("consumer_key") or ""
    cs = secrets.get("consumer_secret") or ""
    if not store or not ck or not cs:
        return {"ok": False, "message": "Store URL and consumer keys required"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{store}/wp-json/wc/v3/system_status", auth=(ck, cs))
    if r.status_code == 200:
        return {"ok": True, "message": "WooCommerce API reachable"}
    if r.status_code in (401, 403):
        return {"ok": False, "message": f"WooCommerce auth failed (HTTP {r.status_code})"}
    return {"ok": False, "message": f"WooCommerce HTTP {r.status_code}"}


async def _probe_notion(secrets: dict, meta: dict) -> dict[str, Any]:
    token = (secrets.get("integration_token") or secrets.get("access_token") or "").strip()
    if not token:
        return {"ok": False, "message": "Integration token required"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://api.notion.com/v1/users/me",
            headers={"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28"},
        )
    if r.status_code == 200:
        return {"ok": True, "message": "Notion integration OK"}
    return {"ok": False, "message": f"Notion HTTP {r.status_code}"}


async def _probe_google(secrets: dict, meta: dict) -> dict[str, Any]:
    token = (secrets.get("access_token") or "").strip()
    api_key = (secrets.get("api_key") or "").strip()
    if token:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code == 200:
            email = r.json().get("email") or "ok"
            return {"ok": True, "message": f"Google identity: {email}"}
        return {"ok": False, "message": f"Google token check HTTP {r.status_code}"}
    if api_key:
        return {"ok": True, "message": "API key stored (live Google call skipped)"}
    if secrets.get("refresh_token") or secrets.get("private_key"):
        return {"ok": True, "message": "Credentials stored"}
    return {"ok": False, "message": "Provide OAuth tokens or an API key"}


async def _probe_mailchimp(secrets: dict, meta: dict) -> dict[str, Any]:
    key = (secrets.get("api_key") or "").strip()
    if not key or "-" not in key:
        return {"ok": False, "message": "Mailchimp API key (with dc suffix) required"}
    dc = secrets.get("server_prefix") or key.split("-")[-1]
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"https://{dc}.api.mailchimp.com/3.0/", auth=("anystring", key))
    if r.status_code == 200:
        return {"ok": True, "message": "Mailchimp account reachable"}
    return {"ok": False, "message": f"Mailchimp HTTP {r.status_code}"}


async def _probe_zapier(secrets: dict, meta: dict) -> dict[str, Any]:
    url = (secrets.get("webhook_url") or "").strip()
    err = validate_webhook_url(url)
    if err:
        return {"ok": False, "message": err}
    return {"ok": True, "message": "Webhook URL saved (will fire when agents use it)"}


async def _probe_dropbox(secrets: dict, meta: dict) -> dict[str, Any]:
    token = (secrets.get("access_token") or secrets.get("token") or "").strip()
    if not token:
        return {"ok": False, "message": "Dropbox access token required"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://api.dropboxapi.com/2/users/get_current_account",
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code == 200:
        name = (r.json().get("name") or {}).get("display_name") or "Dropbox"
        return {"ok": True, "message": f"Dropbox: {name}"}
    return {"ok": False, "message": f"Dropbox HTTP {r.status_code}"}


async def _probe_gcs(secrets: dict, meta: dict) -> dict[str, Any]:
    bucket = (secrets.get("bucket") or meta.get("bucket") or "").strip()
    if not bucket:
        return {"ok": False, "message": "GCS bucket name required"}
    token = (secrets.get("access_token") or "").strip()
    has_sa = bool(
        secrets.get("service_account_json")
        or (secrets.get("private_key") and secrets.get("client_email"))
    )
    if token or has_sa:
        return {"ok": True, "message": f"GCS bucket '{bucket}' credentials stored"}
    return {"ok": False, "message": "Provide access token or service account credentials"}


async def _probe_generic(secrets: dict, meta: dict) -> dict[str, Any]:
    if secrets:
        return {"ok": True, "message": "Credentials saved"}
    return {"ok": False, "message": "No credentials provided"}


async def _probe_twilio(secrets: dict, meta: dict) -> dict[str, Any]:
    """Validate Twilio Account SID + Auth Token (live ping)."""
    import os
    from . import config as app_config

    sid = (
        secrets.get("twilio_sid")
        or secrets.get("account_sid")
        or getattr(app_config, "TWILIO_ACCOUNT_SID", "")
        or os.getenv("TWILIO_ACCOUNT_SID", "")
    ).strip()
    token = (
        secrets.get("twilio_token")
        or secrets.get("auth_token")
        or getattr(app_config, "TWILIO_AUTH_TOKEN", "")
        or os.getenv("TWILIO_AUTH_TOKEN", "")
    ).strip()
    from_num = (
        secrets.get("twilio_from")
        or secrets.get("from_number")
        or getattr(app_config, "TWILIO_FROM_NUMBER", "")
        or os.getenv("TWILIO_FROM_NUMBER", "")
    ).strip()
    if not sid or not token:
        return {
            "ok": False,
            "message": "Account SID and Auth Token required (or set platform TWILIO_* env)",
        }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
            auth=(sid, token),
        )
    if r.status_code == 200:
        data = r.json() if r.content else {}
        friendly = data.get("friendly_name") or sid[:10]
        status = data.get("status") or "active"
        msg = f"Twilio account OK ({friendly}, {status})"
        if from_num:
            msg += f" · from {from_num}"
        return {"ok": True, "message": msg, "friendly_name": friendly}
    if r.status_code in (401, 403):
        return {"ok": False, "message": "Twilio auth failed — check Account SID and Auth Token"}
    return {"ok": False, "message": f"Twilio HTTP {r.status_code}"}


async def _probe_x(secrets: dict, meta: dict) -> dict[str, Any]:
    token = (
        secrets.get("access_token")
        or secrets.get("bearer_token")
        or ""
    ).strip()
    if not token:
        return {"ok": False, "message": "access_token or bearer_token required"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://api.twitter.com/2/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code == 200:
        data = r.json() if r.content else {}
        uname = ((data.get("data") or {}).get("username")) or "ok"
        return {"ok": True, "message": f"X account @{uname}"}
    return {"ok": False, "message": f"X API HTTP {r.status_code}"}


async def _probe_linkedin(secrets: dict, meta: dict) -> dict[str, Any]:
    token = (secrets.get("access_token") or "").strip()
    if not token:
        return {"ok": False, "message": "Access token required"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code == 200:
        data = r.json() if r.content else {}
        name = data.get("name") or data.get("email") or "ok"
        return {"ok": True, "message": f"LinkedIn: {name}"}
    # Fallback older endpoint
    if r.status_code in (401, 403, 404):
        async with httpx.AsyncClient(timeout=15) as client:
            r2 = await client.get(
                "https://api.linkedin.com/v2/me",
                headers={"Authorization": f"Bearer {token}"},
            )
        if r2.status_code == 200:
            return {"ok": True, "message": "LinkedIn token valid"}
    return {"ok": False, "message": f"LinkedIn HTTP {r.status_code}"}


async def _probe_meta(secrets: dict, meta: dict) -> dict[str, Any]:
    token = (secrets.get("access_token") or secrets.get("page_access_token") or "").strip()
    if not token:
        return {"ok": False, "message": "Page or user access token required"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://graph.facebook.com/v19.0/me",
            params={"access_token": token, "fields": "id,name"},
        )
    if r.status_code == 200:
        data = r.json() if r.content else {}
        return {"ok": True, "message": f"Meta: {data.get('name') or data.get('id') or 'ok'}"}
    return {"ok": False, "message": f"Meta Graph HTTP {r.status_code}"}


async def _probe_microsoft(secrets: dict, meta: dict) -> dict[str, Any]:
    token = (secrets.get("access_token") or "").strip()
    if not token:
        return {"ok": False, "message": "Access token required"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code == 200:
        data = r.json() if r.content else {}
        return {"ok": True, "message": f"Microsoft: {data.get('displayName') or data.get('mail') or 'ok'}"}
    return {"ok": False, "message": f"Microsoft Graph HTTP {r.status_code}"}


PROBES: dict[str, ProbeFn] = {
    "shopify": _probe_shopify,
    "slack": _probe_slack,
    "hubspot": _probe_hubspot,
    "stripe_connect": _probe_stripe,
    "woocommerce": _probe_woocommerce,
    "notion": _probe_notion,
    "google": _probe_google,
    "gmail": _probe_google,
    "google_sheets": _probe_google,
    "google_business": _probe_google,
    "youtube": _probe_google,
    "mailchimp": _probe_mailchimp,
    "zapier": _probe_zapier,
    "dropbox": _probe_dropbox,
    "google_cloud_storage": _probe_gcs,
    "gcs": _probe_gcs,
    "twilio": _probe_twilio,
    "x": _probe_x,
    "twitter": _probe_x,
    "linkedin": _probe_linkedin,
    "meta": _probe_meta,
    "instagram": _probe_meta,
    "facebook": _probe_meta,
    "microsoft": _probe_microsoft,
}


async def probe_connection(app_id: str, secrets: dict, meta: dict) -> dict[str, Any]:
    """Best-effort live check. Never raises; returns {ok, message}."""
    key = (app_id or "").lower().strip()
    fn = PROBES.get(key, _probe_generic)
    try:
        return await fn(secrets or {}, meta or {})
    except Exception as e:
        return {"ok": False, "message": f"Probe failed: {type(e).__name__}: {e}"}
