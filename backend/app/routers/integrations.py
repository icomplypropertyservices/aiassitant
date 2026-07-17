"""Connected apps: OAuth + API keys + agent allocation."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, config
from ..auth_utils import get_current_user
from ..integrations_catalog import INTEGRATION_APPS, get_app, public_app, list_apps
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

router = APIRouter(prefix="/integrations", tags=["integrations"])

OAUTH_STATE_TTL_MIN = 20


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
    payload = {
        "uid": user_id,
        "app": app_id,
        "nonce": secrets.token_hex(8),
        "exp": datetime.utcnow() + timedelta(minutes=OAUTH_STATE_TTL_MIN),
        **(extra or {}),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


def _decode_oauth_state(state: str) -> dict:
    try:
        return jwt.decode(state, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(400, f"Invalid or expired OAuth state: {e}") from e


def _oauth_redirect_uri() -> str:
    # Prefer API base derived from FRONTEND or explicit env
    explicit = os.getenv("OAUTH_REDIRECT_URI", "").strip()
    if explicit:
        return explicit
    # Same-origin on Vercel: FRONTEND_URL + /api/integrations/oauth/callback
    base = (config.FRONTEND_URL or "").rstrip("/")
    if base:
        # If frontend is separate, API may be FRONTEND/api or a dedicated host
        api_public = os.getenv("API_PUBLIC_URL", "").rstrip("/")
        if api_public:
            return f"{api_public}/integrations/oauth/callback"
        return f"{base}/api/integrations/oauth/callback"
    return "http://localhost:8000/integrations/oauth/callback"


@router.get("/catalog")
def catalog(user=Depends(get_current_user)):
    apps = []
    for app in INTEGRATION_APPS.values():
        entry = public_app(app, oauth_ready=oauth_env_ready(app) if app.get("oauth") else False)
        apps.append(entry)
    categories = sorted({a["category"] for a in apps})
    return {"apps": apps, "categories": categories, "count": len(apps)}


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
    row = db.get(models.IntegrationConnection, connection_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Connection not found")
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
    row = db.get(models.IntegrationConnection, connection_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Connection not found")
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
    row = db.get(models.IntegrationConnection, connection_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Connection not found")
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

    row = db.get(models.IntegrationConnection, connection_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Connection not found")
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
    row = db.get(models.IntegrationConnection, connection_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Connection not found")
    db.query(models.AgentIntegration).filter_by(connection_id=row.id).delete()
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/agents/{agent_id}")
def agent_integrations(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = db.get(models.Agent, agent_id)
    if not a or (a.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Agent not found")
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
    a = db.get(models.Agent, agent_id)
    if not a or (a.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Agent not found")
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

    if not oauth_env_ready(app):
        return {
            "ok": False,
            "mode": "credentials",
            "message": (
                f"OAuth app credentials not configured on the server "
                f"({oauth.get('client_id_env')}). Use Connect with API keys, "
                f"or set those env vars and redeploy."
            ),
            "fields": public_app(app)["fields"],
            "oauth_ready": False,
        }

    client_id = os.getenv(oauth["client_id_env"], "").strip()
    redirect_uri = _oauth_redirect_uri()
    extra = {}
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
    set_meta(row, meta)
    db.commit()

    scopes = oauth.get("scopes") or ""
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
    # Google / YouTube extras
    if app["id"] in (
        "gmail", "google_sheets", "google_business", "google", "youtube",
    ) or "google" in app["id"]:
        params["access_type"] = "offline"
        params["prompt"] = "consent"
        params["include_granted_scopes"] = "true"
    # Notion
    if app["id"] == "notion":
        params["owner"] = "user"
    # Microsoft
    if app["id"] == "microsoft":
        params["response_mode"] = "query"
    # LinkedIn
    if app["id"] == "linkedin":
        params["response_type"] = "code"
    # Meta / Instagram use client_id as app id
    if app["id"] in ("meta", "instagram"):
        params["client_id"] = client_id
    # X (Twitter) OAuth 2.0 with PKCE-ish: still send standard code flow when confidential client
    if app["id"] == "x":
        params["code_challenge"] = "challenge"
        params["code_challenge_method"] = "plain"
        params["scope"] = scopes.replace(",", " ") if scopes else params.get("scope")

    # Slack uses scope differently (user vs bot) — keep simple
    if app["id"] == "slack":
        params.pop("response_type", None)
        params["scope"] = scopes

    authorize_url = f"{auth_base}?{urlencode(params)}"
    return {
        "ok": True,
        "mode": "oauth",
        "authorize_url": authorize_url,
        "redirect_uri": redirect_uri,
        "oauth_ready": True,
        "connection_id": row.id,
    }


@router.get("/oauth/callback")
async def oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    shop: str | None = None,
    db: Session = Depends(get_db),
):
    """OAuth provider redirects here. Stores tokens and sends user back to Settings."""
    frontend = (config.FRONTEND_URL or "http://localhost:5173").rstrip("/")
    fail_url = f"{frontend}/settings?tab=apps&oauth=error"

    if error:
        return RedirectResponse(f"{fail_url}&message={error}", status_code=302)
    if not code or not state:
        return RedirectResponse(f"{fail_url}&message=missing_code", status_code=302)

    try:
        payload = _decode_oauth_state(state)
    except HTTPException:
        return RedirectResponse(f"{fail_url}&message=bad_state", status_code=302)

    user_id = int(payload["uid"])
    app_id = payload["app"]
    app = get_app(app_id)
    if not app or not app.get("oauth"):
        return RedirectResponse(f"{fail_url}&message=unknown_app", status_code=302)

    oauth = app["oauth"]
    client_id = os.getenv(oauth["client_id_env"], "").strip()
    client_secret = os.getenv(oauth["client_secret_env"], "").strip()
    redirect_uri = _oauth_redirect_uri()
    shop_domain = payload.get("shop") or shop

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
                r = await client.post(
                    token_url,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code": code,
                        "redirect_uri": redirect_uri,
                        "grant_type": "authorization_code",
                        "code_verifier": "challenge",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            else:
                # Google, HubSpot, LinkedIn, Meta, Microsoft, etc. — form token exchange
                r = await client.post(
                    token_url,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code": code,
                        "redirect_uri": redirect_uri,
                        "grant_type": "authorization_code",
                    },
                )
            data = r.json() if r.content else {}
            if r.status_code >= 400:
                raise RuntimeError(data.get("error_description") or data.get("error") or r.text[:200])
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
        return RedirectResponse(f"{fail_url}&message=token_exchange_failed", status_code=302)

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
    set_meta(row, old_meta)
    row.auth_mode = "oauth"
    row.display_name = row.display_name or app["name"]
    mark_connected(row, "OAuth connected")
    row.updated_at = datetime.utcnow()
    db.commit()

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
