"""Connected apps: OAuth + API keys + agent allocation."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode, quote

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..ownership import require_owned
from .. import models, config
from ..auth_utils import get_current_user
from ..integrations_catalog import (
    INTEGRATION_APPS,
    get_app,
    public_app,
    list_apps,
    one_click_oauth_list,
    OAUTH_ONE_CLICK_ORDER,
    GOOGLE_FAMILY,
)
from ..integrations_service import (
    connection_out,
    set_secrets,
    set_meta,
    meta_from_row,
    secrets_from_row,
    set_agent_links,
    probe_connection,
    oauth_env_ready,
    mark_connected,
    integrations_context_for_agent,
)

log = logging.getLogger("app.integrations")

router = APIRouter(prefix="/integrations", tags=["integrations"])

OAUTH_STATE_TTL_MIN = 20
GOOGLE_APP_IDS = frozenset(GOOGLE_FAMILY) | frozenset(
    {"google", "gmail", "google_sheets", "google_business", "youtube"}
)


class ConnectIn(BaseModel):
    """API-key / manual credential connect."""
    credentials: dict = Field(default_factory=dict)
    display_name: str = ""
    agent_ids: list[int] = Field(default_factory=list)
    test: bool = True


class ConnectionAgentsIn(BaseModel):
    """Assign agents to a connection."""
    agent_ids: list[int] = Field(default_factory=list)
    permission: str = "full"


class AgentConnectionsIn(BaseModel):
    """Assign connections (apps) to an agent."""
    connection_ids: list[int] = Field(default_factory=list)
    # Deprecated alias — do not use; kept so old clients do not 422
    agent_ids: list[int] | None = None
    permission: str = "full"


class OAuthStartIn(BaseModel):
    shop_domain: str | None = None  # Shopify
    redirect_after: str | None = None  # frontend path after success


def _encode_oauth_state(user_id: int, app_id: str, extra: dict | None = None) -> str:
    # Use numeric exp — some JWT libs mishandle datetime objects
    payload = {
        "uid": int(user_id),
        "app": app_id,
        "nonce": secrets.token_hex(8),
        "exp": int(time.time()) + OAUTH_STATE_TTL_MIN * 60,
        **(extra or {}),
    }
    token = jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")
    # PyJWT <2 returned bytes
    if isinstance(token, bytes):
        return token.decode("utf-8")
    return str(token)


def _decode_oauth_state(state: str) -> dict:
    try:
        return jwt.decode(state, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(400, f"Invalid or expired OAuth state: {e}") from e


def _canonicalize_oauth_redirect(uri: str) -> str:
    """Stable production redirect_uri for aibusinessagent.xyz (apex).

    Google Error 400 redirect_uri_mismatch is almost always www vs apex,
    trailing slash, or /agents/api/... wrong path.
    """
    u = (uri or "").strip().rstrip("/")
    if not u:
        return u
    # Never allow SPA-prefixed API paths
    u = u.replace("/agents/api/", "/api/")
    # Pin our product domain to one canonical host (apex)
    if "aibusinessagent.xyz" in u:
        u = u.replace("://www.aibusinessagent.xyz", "://aibusinessagent.xyz")
        # Prefer configured canonical when env/request drifts
        if u.endswith("/api/integrations/oauth/callback"):
            return getattr(config, "PROD_OAUTH_REDIRECT_URI", None) or (
                "https://aibusinessagent.xyz/api/integrations/oauth/callback"
            )
    return u


def _oauth_redirect_uri(request: Request | None = None) -> str:
    """Exact redirect_uri for authorize + token exchange.

    Google returns Error 400 redirect_uri_mismatch when this does not match
    Authorized redirect URIs in Cloud Console **exactly**.

    Canonical production value (add this in Google Console):
      https://aibusinessagent.xyz/api/integrations/oauth/callback

    Also whitelist www during transition (optional, we send apex):
      https://www.aibusinessagent.xyz/api/integrations/oauth/callback

    Never use FRONTEND_URL + /api/... when FRONTEND is .../agents.
    """
    # 1) Explicit config / env (highest priority)
    explicit = (
        (getattr(config, "OAUTH_REDIRECT_URI", None) or "").strip()
        or os.getenv("OAUTH_REDIRECT_URI", "").strip()
    )
    if explicit:
        return _canonicalize_oauth_redirect(explicit)

    # Production product domain: always pin (do not use ephemeral Vercel host)
    if getattr(config, "IS_PRODUCTION", False):
        fu = (getattr(config, "FRONTEND_URL", None) or "") + (
            getattr(config, "API_PUBLIC_URL", None) or ""
        )
        if "aibusinessagent.xyz" in fu or not fu:
            return getattr(
                config,
                "PROD_OAUTH_REDIRECT_URI",
                "https://aibusinessagent.xyz/api/integrations/oauth/callback",
            )

    # 2) API_PUBLIC_URL from config / env
    api_public = (
        (getattr(config, "API_PUBLIC_URL", None) or "").strip().rstrip("/")
        or os.getenv("API_PUBLIC_URL", "").strip().rstrip("/")
    )
    if api_public:
        if api_public.endswith("/api"):
            return _canonicalize_oauth_redirect(f"{api_public}/integrations/oauth/callback")
        return _canonicalize_oauth_redirect(f"{api_public}/api/integrations/oauth/callback")

    # 3) Derive from request host (local / custom domains)
    if request is not None:
        try:
            proto = (
                request.headers.get("x-forwarded-proto")
                or request.url.scheme
                or "https"
            ).split(",")[0].strip()
            host = (
                request.headers.get("x-forwarded-host")
                or request.headers.get("host")
                or request.url.netloc
            )
            host = (host or "").split(",")[0].strip()
            if host and "localhost" not in host and "127.0.0.1" not in host:
                # Never use *.vercel.app for Google — Console won't match unless
                # every preview is added. Fall back to product canonical in prod.
                if host.endswith(".vercel.app") and getattr(config, "IS_PRODUCTION", False):
                    return getattr(
                        config,
                        "PROD_OAUTH_REDIRECT_URI",
                        "https://aibusinessagent.xyz/api/integrations/oauth/callback",
                    )
                return _canonicalize_oauth_redirect(
                    f"{proto}://{host}/api/integrations/oauth/callback"
                )
            if host:
                return f"{proto}://{host}/integrations/oauth/callback"
        except Exception:
            pass

    # 4) FRONTEND_URL — strip SPA path prefixes carefully
    base = (config.FRONTEND_URL or "").rstrip("/")
    if base:
        if base.endswith("/agents"):
            origin = base[: -len("/agents")]
            return _canonicalize_oauth_redirect(f"{origin}/api/integrations/oauth/callback")
        from urllib.parse import urlparse
        p = urlparse(base)
        if p.scheme and p.netloc:
            return _canonicalize_oauth_redirect(
                f"{p.scheme}://{p.netloc}/api/integrations/oauth/callback"
            )

    # 5) Local default
    return "http://localhost:8000/integrations/oauth/callback"


def _is_google_app(app: dict) -> bool:
    aid = (app.get("id") or "").lower()
    return aid in GOOGLE_APP_IDS or app.get("family") == "google" or aid.startswith("google")


def _normalize_scopes(scopes: str | list | None, *, google: bool) -> str:
    if not scopes:
        return ""
    if isinstance(scopes, (list, tuple)):
        parts = [str(s).strip() for s in scopes if str(s).strip()]
    else:
        raw = str(scopes).replace(",", " ")
        parts = [p.strip() for p in raw.split() if p.strip()]
    # Google wants space-separated scopes
    if google:
        return " ".join(parts)
    return " ".join(parts)


@router.get("/catalog")
def catalog(user=Depends(get_current_user)):
    apps = list_apps(oauth_ready_fn=lambda a: oauth_env_ready(a) if a.get("oauth") else False)
    one_click = one_click_oauth_list(
        oauth_ready_fn=lambda a: oauth_env_ready(a) if a.get("oauth") else False
    )
    categories = sorted({a["category"] for a in apps})
    google_ready = all(a.get("oauth_ready") for a in one_click) if one_click else False
    return {
        "apps": apps,
        "one_click_oauth": one_click,
        "one_click_order": list(OAUTH_ONE_CLICK_ORDER),
        "google_family": list(GOOGLE_FAMILY),
        "google_oauth_configured": google_ready,
        "categories": categories,
        "count": len(apps),
        "live_count": sum(1 for a in apps if not a.get("coming_soon")),
        "coming_soon_count": sum(1 for a in apps if a.get("coming_soon")),
    }


@router.get("/oauth/google-status")
def google_oauth_status(request: Request, user=Depends(get_current_user)):
    """Verify Google OAuth client env is present for all Google apps."""
    cid = (os.getenv("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    csec = (os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()
    redirect = _oauth_redirect_uri(request)
    apps = []
    for aid in OAUTH_ONE_CLICK_ORDER:
        app = get_app(aid)
        if not app:
            continue
        apps.append({
            "id": aid,
            "name": app.get("name"),
            "scopes": (app.get("oauth") or {}).get("scopes"),
            "oauth_ready": bool(cid and csec),
            "coming_soon": bool(app.get("coming_soon")),
        })
    www_alt = getattr(config, "PROD_OAUTH_REDIRECT_URI_WWW", None) or (
        "https://www.aibusinessagent.xyz/api/integrations/oauth/callback"
    )
    return {
        "ok": bool(cid and csec and redirect),
        "client_id_set": bool(cid),
        "client_secret_set": bool(csec),
        "client_id_preview": (cid[:12] + "…") if len(cid) > 12 else (cid or None),
        "redirect_uri": redirect,
        "redirect_uri_alternates": [www_alt] if redirect != www_alt else [],
        "api_public_url": getattr(config, "API_PUBLIC_URL", None) or os.getenv("API_PUBLIC_URL") or None,
        "frontend_url": getattr(config, "FRONTEND_URL", None),
        "apps": apps,
        "console_steps": [
            "Open Google Cloud Console → APIs & Services → Credentials",
            "OAuth 2.0 Client IDs → Web application client (not iOS/Android)",
            f"Authorized redirect URIs → ADD EXACTLY (copy-paste): {redirect}",
            f"Also add (optional www transition): {www_alt}",
            "Authorized JavaScript origins → https://aibusinessagent.xyz and https://www.aibusinessagent.xyz",
            "OAuth consent screen → Publishing status Testing → Test users → Add the Google email you will use",
            "Error 403 access_denied = email not in Test users (or app not published)",
            "Enable APIs: Gmail, Sheets, Calendar, Drive, YouTube Data (as needed)",
            "Save, wait ~1 minute, then Connect with that same Google account",
        ],
        "note": (
            "Error 400 redirect_uri_mismatch: add redirect_uri under Authorized redirect URIs. "
            "Error 403 access_denied / verification message: add your email under OAuth consent "
            "screen → Test users (while status is Testing)."
        ),
        "error_help": {
            "redirect_uri_mismatch": (
                f"Add this exact URI in Google Cloud Console: {redirect}"
            ),
            "access_denied": (
                "OAuth consent screen is in Testing. Add your Google account under "
                "Test users, or publish the app (In production)."
            ),
        },
    }


@router.get("/connections")
def list_connections(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = (
        db.query(models.IntegrationConnection)
        .filter_by(user_id=user.id)
        .order_by(models.IntegrationConnection.updated_at.desc())
        .all()
    )
    return {
        "connections": [connection_out(r, db) for r in rows],
        "connected_count": sum(1 for r in rows if r.status == "connected"),
    }


@router.get("/connections/{connection_id}")
def get_connection(connection_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = require_owned(
        db, models.IntegrationConnection, connection_id, user,
        user_field='user_id', not_found="Connection not found",
    )
    return connection_out(row, db)


@router.post("/{app_id}/connect")
async def connect_with_credentials(
    app_id: str,
    data: ConnectIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    app = get_app(app_id)
    if not app:
        raise HTTPException(404, "Unknown app")
    if "api_key" not in (app.get("auth_modes") or []) and not data.credentials:
        # still allow if they paste oauth tokens into fields
        pass

    creds = {k: str(v).strip() for k, v in (data.credentials or {}).items() if v is not None and str(v).strip()}

    # Upsert one connection per user+app (latest wins) unless display_name distinguishes
    row = (
        db.query(models.IntegrationConnection)
        .filter_by(user_id=user.id, app_id=app["id"])
        .order_by(models.IntegrationConnection.id.desc())
        .first()
    )
    if not row:
        row = models.IntegrationConnection(user_id=user.id, app_id=app["id"])
        db.add(row)
        db.flush()

    # Merge secrets (keep old if not re-sent)
    existing = secrets_from_row(row)

    # Validate required fields only when creating first secrets (updates may omit secrets)
    if not existing:
        for f in app.get("fields") or []:
            if f.get("required") and f["name"] not in creds:
                if "api_key" in (app.get("auth_modes") or []):
                    raise HTTPException(400, f"Missing required field: {f['label']}")

    # Split secret vs meta
    secret_names = {f["name"] for f in (app.get("fields") or []) if f.get("secret")}
    secrets_blob = {}
    meta = {}
    for k, v in creds.items():
        if k in secret_names or any(s in k.lower() for s in ("token", "secret", "key", "password", "private")):
            secrets_blob[k] = v
        else:
            meta[k] = v

    existing.update(secrets_blob)
    set_secrets(row, existing)
    old_meta = meta_from_row(row)
    old_meta.update(meta)
    set_meta(row, old_meta)
    row.display_name = (data.display_name or row.display_name or app["name"]).strip()
    row.auth_mode = "api_key"
    row.status = "pending"
    row.updated_at = datetime.utcnow()

    probe = {"ok": True, "message": "Saved"}
    if data.test:
        probe = await probe_connection(app["id"], existing, old_meta)
        if probe.get("ok"):
            mark_connected(row, probe.get("message") or "Connected")
            if probe.get("shop_name"):
                old_meta["shop_name"] = probe["shop_name"]
                set_meta(row, old_meta)
        else:
            row.status = "error"
            row.last_error = probe.get("message") or "Connection test failed"
    else:
        mark_connected(row, "Saved without live test")

    if data.agent_ids is not None:
        set_agent_links(db, row, data.agent_ids, user)

    # Twilio: also mirror into Settings → API keys so SMS/voice channels work
    if app["id"] == "twilio" and row.status == "connected":
        try:
            from ..routers.keys import _upsert_plain
            merged = secrets_from_row(row)
            meta = meta_from_row(row)
            sid = (merged.get("twilio_sid") or meta.get("twilio_sid") or "").strip()
            tok = (merged.get("twilio_token") or meta.get("twilio_token") or "").strip()
            fr = (merged.get("twilio_from") or meta.get("twilio_from") or "").strip()
            if sid:
                _upsert_plain(db, user.id, "twilio_sid", sid, label="Twilio SID (from Apps)")
            if tok:
                _upsert_plain(db, user.id, "twilio_token", tok, label="Twilio token (from Apps)")
            if fr:
                _upsert_plain(db, user.id, "twilio_from", fr, label="Twilio From (from Apps)")
        except Exception:
            pass

    db.commit()
    db.refresh(row)
    out = connection_out(row, db)
    out["probe"] = probe
    return out


@router.put("/connections/{connection_id}/agents")
def allocate_agents(
    connection_id: int,
    data: ConnectionAgentsIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = require_owned(
        db, models.IntegrationConnection, connection_id, user,
        user_field='user_id', not_found="Connection not found",
    )
    if data.permission not in ("read", "write", "full"):
        raise HTTPException(400, "permission must be read, write, or full")
    linked = set_agent_links(db, row, data.agent_ids, user, permission=data.permission)
    db.commit()
    db.refresh(row)
    return {
        **connection_out(row, db),
        "allocated": len(linked),
        "message": f"Allocated to {len(linked)} agent(s)",
    }


@router.post("/connections/{connection_id}/test")
async def test_connection(connection_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = require_owned(
        db, models.IntegrationConnection, connection_id, user,
        user_field='user_id', not_found="Connection not found",
    )
    secrets = secrets_from_row(row)
    meta = meta_from_row(row)
    probe = await probe_connection(row.app_id, secrets, meta)
    if probe.get("ok"):
        mark_connected(row, probe.get("message") or "OK")
        if probe.get("shop_name"):
            meta["shop_name"] = probe["shop_name"]
            set_meta(row, meta)
    else:
        row.status = "error"
        row.last_error = probe.get("message") or "Test failed"
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"probe": probe, "connection": connection_out(row, db)}


class ActionIn(BaseModel):
    action: str = "status"
    payload: dict = Field(default_factory=dict)


@router.post("/connections/{connection_id}/action")
async def run_connection_action(
    connection_id: int,
    data: ActionIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Execute a live action against a connected app (fully wired handlers)."""
    from ..integration_actions import run_app_action
    from ..live_ops import emit_ops

    row = require_owned(
        db, models.IntegrationConnection, connection_id, user,
        user_field='user_id', not_found="Connection not found",
    )
    result = await run_app_action(row, data.action, data.payload or {})
    await emit_ops(
        user.id,
        kind="app",
        status="done" if result.get("ok") else "failed",
        title=f"{row.app_id}:{data.action}",
        detail=result.get("message") or result.get("error") or "",
        payload={"connection_id": row.id, "result": result},
        db=db,
    )
    return result


@router.delete("/connections/{connection_id}")
def delete_connection(connection_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = require_owned(
        db, models.IntegrationConnection, connection_id, user,
        user_field='user_id', not_found="Connection not found",
    )
    db.query(models.AgentIntegration).filter_by(connection_id=row.id).delete()
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/agents/{agent_id}")
def agent_integrations(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = require_owned(
        db, models.Agent, agent_id, user,
        user_field='user_id', not_found="Agent not found",
    )
    links = db.query(models.AgentIntegration).filter_by(agent_id=agent_id).all()
    conns = []
    for link in links:
        c = db.get(models.IntegrationConnection, link.connection_id)
        if c:
            out = connection_out(c, db)
            out["permission"] = link.permission
            conns.append(out)
    return {
        "agent_id": agent_id,
        "connections": conns,
        "context_preview": integrations_context_for_agent(db, agent_id),
    }


@router.put("/agents/{agent_id}")
def set_agent_integrations(
    agent_id: int,
    data: AgentConnectionsIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Allocate connected apps to this agent. Body: { connection_ids, permission }."""
    a = require_owned(
        db, models.Agent, agent_id, user,
        user_field='user_id', not_found="Agent not found",
    )
    connection_ids = list(data.connection_ids or [])
    if not connection_ids and data.agent_ids:
        connection_ids = [int(x) for x in data.agent_ids]
    db.query(models.AgentIntegration).filter_by(agent_id=agent_id).delete()
    linked = 0
    for cid in connection_ids:
        c = db.get(models.IntegrationConnection, int(cid))
        if not c or c.user_id != user.id:
            continue
        if c.status not in ("connected", "pending", "error"):
            continue
        db.add(models.AgentIntegration(
            connection_id=c.id,
            agent_id=agent_id,
            permission=data.permission or "full",
        ))
        linked += 1
    db.commit()
    links = db.query(models.AgentIntegration).filter_by(agent_id=agent_id).all()
    conns = []
    for link in links:
        c = db.get(models.IntegrationConnection, link.connection_id)
        if c:
            out = connection_out(c, db)
            out["permission"] = link.permission
            conns.append(out)
    return {
        "agent_id": agent_id,
        "allocated": linked,
        "context_preview": integrations_context_for_agent(db, agent_id),
        "connections": conns,
    }


@router.post("/{app_id}/oauth/start")
def oauth_start(
    app_id: str,
    request: Request,
    data: OAuthStartIn | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Begin OAuth. Returns authorize_url when platform OAuth apps are configured."""
    data = data or OAuthStartIn()
    app = get_app(app_id)
    if not app:
        raise HTTPException(404, "Unknown app")
    oauth = app.get("oauth")
    if not oauth:
        raise HTTPException(400, "This app does not support OAuth — use API credentials instead")

    # Any app with OAuth block can start when platform client env is set.
    # Explicit coming_soon with no credentials still returns a helpful message.
    ready = oauth_env_ready(app)
    if app.get("coming_soon") and not ready:
        raise HTTPException(
            503,
            f"{app.get('name') or app_id} is not available for OAuth yet. "
            "Use Connect with API keys if this app supports them.",
        )
    if not ready:
        return {
            "ok": False,
            "mode": "credentials",
            "message": (
                f"OAuth app credentials not configured on the server "
                f"({oauth.get('client_id_env')} / {oauth.get('client_secret_env')}). "
                f"Set those env vars on Vercel and redeploy, or use Connect with API keys."
            ),
            "fields": public_app(app)["fields"],
            "oauth_ready": False,
            "redirect_uri": _oauth_redirect_uri(request),
            "supports_api_key": "api_key" in (app.get("auth_modes") or []),
        }

    client_id = os.getenv(oauth["client_id_env"], "").strip()
    if not client_id:
        raise HTTPException(503, f"Missing {oauth.get('client_id_env')} on server")

    redirect_uri = _oauth_redirect_uri(request)
    is_google = _is_google_app(app)
    extra = {
        # Persist exact redirect_uri so token exchange matches authorize request
        "ru": redirect_uri,
    }
    if data.redirect_after:
        extra["next"] = data.redirect_after[:200]

    shop = None
    if oauth.get("needs_shop"):
        shop = (data.shop_domain or "").strip().replace("https://", "").replace("http://", "").split("/")[0]
        if not shop:
            raise HTTPException(400, "shop_domain is required for Shopify OAuth (e.g. store.myshopify.com)")
        extra["shop"] = shop

    state = _encode_oauth_state(user.id, app["id"], extra)

    # Create pending connection row
    row = (
        db.query(models.IntegrationConnection)
        .filter_by(user_id=user.id, app_id=app["id"])
        .order_by(models.IntegrationConnection.id.desc())
        .first()
    )
    if not row:
        row = models.IntegrationConnection(user_id=user.id, app_id=app["id"])
        db.add(row)
    row.status = "pending"
    row.auth_mode = "oauth"
    row.display_name = row.display_name or app["name"]
    meta = meta_from_row(row)
    if shop:
        meta["shop_domain"] = shop
    meta["oauth_state_nonce"] = "pending"
    meta["oauth_redirect_uri"] = redirect_uri
    set_meta(row, meta)
    db.commit()

    scopes = _normalize_scopes(oauth.get("scopes"), google=is_google)
    auth_base = oauth["authorize_url"]
    if "{shop}" in auth_base:
        auth_base = auth_base.format(shop=shop)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
    }
    if scopes:
        params["scope"] = scopes

    # Google / YouTube — offline refresh + consent for refresh_token
    if is_google:
        params["access_type"] = oauth.get("access_type") or "offline"
        params["prompt"] = oauth.get("prompt") or "consent"
        # Never send include_granted_scopes — causes invalid_request with
        # mixed / restricted Google scopes across Gmail/Calendar/Sheets family.

    # Notion
    if app["id"] == "notion":
        params["owner"] = "user"
    # Microsoft
    if app["id"] == "microsoft":
        params["response_mode"] = "query"
    # LinkedIn
    if app["id"] == "linkedin":
        params["response_type"] = "code"
    # Meta / Instagram
    if app["id"] in ("meta", "instagram"):
        params["client_id"] = client_id
    # X (Twitter) OAuth 2.0 with PKCE (S256) — required by X API v2
    if app["id"] == "x":
        # 43–128 char verifier; store in state for token exchange
        code_verifier = secrets.token_urlsafe(64)[:96]
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        extra["cv"] = code_verifier
        # Re-encode state with verifier
        state = _encode_oauth_state(user.id, app["id"], extra)
        params["state"] = state
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
        if scopes:
            params["scope"] = scopes

    # Slack uses scope without response_type in some flows
    if app["id"] == "slack":
        params.pop("response_type", None)
        if scopes:
            params["scope"] = scopes.replace(" ", ",")

    # doseq=False; safe encode for Google
    authorize_url = f"{auth_base}?{urlencode(params, quote_via=quote)}"
    log.info(
        "oauth_start app=%s redirect_uri=%s client_id_prefix=%s",
        app["id"],
        redirect_uri,
        client_id[:12] if client_id else "",
    )
    return {
        "ok": True,
        "mode": "oauth",
        "authorize_url": authorize_url,
        "redirect_uri": redirect_uri,
        "oauth_ready": True,
        "connection_id": row.id,
        "hint": (
            "If Google shows 'request is invalid', add this exact redirect_uri "
            "under OAuth client → Authorized redirect URIs."
        ),
    }


@router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    shop: str | None = None,
    db: Session = Depends(get_db),
):
    """OAuth provider redirects here. Stores tokens and sends user back to Settings."""
    frontend = (config.FRONTEND_URL or "http://localhost:5173").rstrip("/")
    fail_url = f"{frontend}/settings?tab=apps&oauth=error"

    def _fail(msg: str):
        msg = quote(str(msg or "oauth_error")[:300], safe="")
        return RedirectResponse(f"{fail_url}&message={msg}", status_code=302)

    if error:
        detail = error_description or error
        log.warning("oauth_callback provider_error=%s desc=%s", error, error_description)
        return _fail(detail)
    if not code or not state:
        return _fail("missing_code_or_state")

    try:
        payload = _decode_oauth_state(state)
    except HTTPException as e:
        return _fail(f"bad_state:{e.detail}")

    user_id = int(payload["uid"])
    app_id = payload["app"]
    app = get_app(app_id)
    if not app or not app.get("oauth"):
        return _fail("unknown_app")

    oauth = app["oauth"]
    client_id = os.getenv(oauth["client_id_env"], "").strip()
    client_secret = os.getenv(oauth["client_secret_env"], "").strip()
    # Must match authorize request exactly
    redirect_uri = (
        (payload.get("ru") or "").strip()
        or _oauth_redirect_uri(request)
    )
    shop_domain = payload.get("shop") or shop
    is_google = _is_google_app(app)

    if not client_id or not client_secret:
        return _fail("server_missing_oauth_credentials")

    token_url = oauth["token_url"]
    if "{shop}" in token_url:
        token_url = token_url.format(shop=shop_domain)

    tokens: dict = {}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if app_id == "shopify":
                r = await client.post(
                    token_url,
                    json={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code": code,
                    },
                )
            elif app_id == "notion":
                import base64
                basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
                r = await client.post(
                    token_url,
                    headers={
                        "Authorization": f"Basic {basic}",
                        "Content-Type": "application/json",
                    },
                    json={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
                )
            elif app_id == "slack":
                r = await client.post(
                    token_url,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                )
            elif app_id == "x":
                code_verifier = (payload.get("cv") or "").strip() or "challenge"
                basic = base64.b64encode(
                    f"{client_id}:{client_secret}".encode("utf-8")
                ).decode("ascii")
                r = await client.post(
                    token_url,
                    data={
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": redirect_uri,
                        "code_verifier": code_verifier,
                        "client_id": client_id,
                    },
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Authorization": f"Basic {basic}",
                    },
                )
            else:
                # Google, HubSpot, LinkedIn, Meta, Microsoft, etc.
                # Google requires application/x-www-form-urlencoded body
                form = {
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                }
                r = await client.post(
                    token_url,
                    data=form,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            data = r.json() if r.content else {}
            if r.status_code >= 400:
                err = (
                    data.get("error_description")
                    or data.get("error")
                    or r.text[:200]
                )
                log.warning(
                    "oauth_token_exchange_failed app=%s status=%s err=%s redirect=%s",
                    app_id,
                    r.status_code,
                    err,
                    redirect_uri,
                )
                raise RuntimeError(str(err))
            if is_google and not data.get("access_token"):
                raise RuntimeError(data.get("error_description") or data.get("error") or "no_access_token")
            tokens = data
    except Exception as e:
        row = (
            db.query(models.IntegrationConnection)
            .filter_by(user_id=user_id, app_id=app_id)
            .order_by(models.IntegrationConnection.id.desc())
            .first()
        )
        if row:
            row.status = "error"
            row.last_error = str(e)[:500]
            db.commit()
        return _fail(f"token_exchange_failed:{e}")

    # Normalize tokens into secrets
    secrets_blob = {}
    meta = {}
    if app_id == "shopify":
        secrets_blob["access_token"] = tokens.get("access_token") or ""
        meta["shop_domain"] = shop_domain
        meta["scope"] = tokens.get("scope")
    elif app_id == "slack":
        secrets_blob["bot_token"] = (tokens.get("access_token") or tokens.get("authed_user", {}).get("access_token") or "")
        if tokens.get("incoming_webhook"):
            meta["default_channel"] = tokens["incoming_webhook"].get("channel")
        meta["team"] = (tokens.get("team") or {}).get("name")
    elif app_id == "notion":
        secrets_blob["integration_token"] = tokens.get("access_token") or ""
        meta["workspace_name"] = tokens.get("workspace_name")
    else:
        secrets_blob["access_token"] = tokens.get("access_token") or ""
        if tokens.get("refresh_token"):
            secrets_blob["refresh_token"] = tokens["refresh_token"]
        meta["scope"] = tokens.get("scope")
        meta["token_type"] = tokens.get("token_type")
        if tokens.get("expires_in"):
            try:
                meta["expires_at"] = (
                    datetime.utcnow() + timedelta(seconds=int(tokens["expires_in"]))
                ).isoformat() + "Z"
            except Exception:
                pass
        if tokens.get("id_token"):
            meta["has_id_token"] = True

    row = (
        db.query(models.IntegrationConnection)
        .filter_by(user_id=user_id, app_id=app_id)
        .order_by(models.IntegrationConnection.id.desc())
        .first()
    )
    if not row:
        row = models.IntegrationConnection(user_id=user_id, app_id=app_id)
        db.add(row)
        db.flush()

    existing = secrets_from_row(row)
    existing.update({k: v for k, v in secrets_blob.items() if v})
    set_secrets(row, existing)
    old_meta = meta_from_row(row)
    old_meta.update({k: v for k, v in meta.items() if v is not None})
    old_meta["oauth_redirect_uri"] = redirect_uri

    # Best-effort identity / probe so UI shows Connected with email
    status_msg = "OAuth connected"
    try:
        probe = await probe_connection(app_id, existing, old_meta)
        if probe.get("ok") and probe.get("message"):
            status_msg = probe["message"]
            if "Google identity:" in status_msg:
                email = status_msg.split("Google identity:", 1)[-1].strip()
                if email and email != "ok":
                    row.display_name = f"{app['name']} ({email})"
                    old_meta["email"] = email
    except Exception as probe_err:
        log.warning("oauth_probe_after_connect app=%s err=%s", app_id, probe_err)

    set_meta(row, old_meta)
    row.auth_mode = "oauth"
    row.display_name = row.display_name or app["name"]
    mark_connected(row, status_msg)
    row.updated_at = datetime.utcnow()
    db.commit()
    log.info("oauth_connected app=%s user=%s", app_id, user_id)

    next_path = payload.get("next") or "/settings?tab=apps&oauth=success"
    if not str(next_path).startswith("/"):
        next_path = "/settings?tab=apps&oauth=success"
    if "oauth=" not in next_path:
        sep = "&" if "?" in next_path else "?"
        next_path = f"{next_path}{sep}oauth=success"
    return RedirectResponse(f"{frontend}{next_path}", status_code=302)


@router.get("/oauth/callback/page")
def oauth_callback_page():
    """HTML helper if popup flow is used."""
    return HTMLResponse(
        "<html><body><script>"
        "if(window.opener){window.opener.postMessage({type:'oauth_done'},'*');window.close();}"
        "else{location.href='/settings?tab=apps';}"
        "</script><p>You can close this window.</p></body></html>"
    )
