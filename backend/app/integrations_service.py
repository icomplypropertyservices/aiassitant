"""Helpers for integration connections + agent allocation."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .crypto import encrypt_secret, decrypt_secret
from .integrations_catalog import INTEGRATION_APPS, get_app


def secrets_from_row(row: models.IntegrationConnection) -> dict:
    if not row.encrypted_secrets:
        return {}
    try:
        raw = decrypt_secret(row.encrypted_secrets)
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def meta_from_row(row: models.IntegrationConnection) -> dict:
    try:
        return json.loads(row.meta_json or "{}")
    except Exception:
        return {}


def set_secrets(row: models.IntegrationConnection, secrets: dict) -> None:
    clean = {k: v for k, v in (secrets or {}).items() if v is not None and str(v).strip() != ""}
    row.encrypted_secrets = encrypt_secret(json.dumps(clean)) if clean else ""


def set_meta(row: models.IntegrationConnection, meta: dict) -> None:
    row.meta_json = json.dumps(meta or {})


def connection_out(row: models.IntegrationConnection, db: Session) -> dict:
    app = get_app(row.app_id) or {"name": row.app_id, "category": "other", "color": None}
    links = (
        db.query(models.AgentIntegration)
        .filter_by(connection_id=row.id)
        .all()
    )
    agents = []
    for link in links:
        a = db.get(models.Agent, link.agent_id)
        if a:
            agents.append({
                "id": a.id,
                "name": a.name,
                "template_type": a.template_type,
                "status": a.status,
                "permission": link.permission or "full",
            })
    meta = meta_from_row(row)
    # Mask secret field names present
    secret_keys = []
    for f in (app.get("fields") or []) if isinstance(app, dict) else []:
        if f.get("secret"):
            secret_keys.append(f["name"])
    secrets = secrets_from_row(row)
    for k in secrets:
        if k not in secret_keys and any(s in k.lower() for s in ("token", "secret", "key", "password")):
            secret_keys.append(k)

    return {
        "id": row.id,
        "app_id": row.app_id,
        "app_name": app.get("name", row.app_id) if isinstance(app, dict) else row.app_id,
        "category": app.get("category") if isinstance(app, dict) else None,
        "color": app.get("color") if isinstance(app, dict) else None,
        "display_name": row.display_name or (app.get("name") if isinstance(app, dict) else row.app_id),
        "status": row.status,
        "auth_mode": row.auth_mode,
        "meta": {k: v for k, v in meta.items() if not str(k).startswith("_")},
        "has_secrets": bool(row.encrypted_secrets),
        "secret_fields_set": [k for k in secret_keys if secrets.get(k)],
        "last_error": row.last_error or "",
        "last_synced_at": row.last_synced_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "agents": agents,
        "agent_ids": [a["id"] for a in agents],
        "agent_count": len(agents),
    }


def set_agent_links(
    db: Session,
    connection: models.IntegrationConnection,
    agent_ids: list[int],
    user: models.User,
    permission: str = "full",
) -> list[models.Agent]:
    """Replace agent allocations for a connection. Returns linked agents."""
    # Clear existing
    db.query(models.AgentIntegration).filter_by(connection_id=connection.id).delete()
    linked = []
    seen = set()
    for aid in agent_ids or []:
        try:
            aid = int(aid)
        except (TypeError, ValueError):
            continue
        if aid in seen:
            continue
        seen.add(aid)
        a = db.get(models.Agent, aid)
        if not a or (a.user_id != user.id and user.role != "admin"):
            continue
        db.add(models.AgentIntegration(
            connection_id=connection.id,
            agent_id=a.id,
            permission=permission or "full",
        ))
        linked.append(a)
    return linked


def integrations_context_for_agent(db: Session, agent_id: int) -> str:
    """Text injected into agent prompts listing allocated apps (no secrets)."""
    links = (
        db.query(models.AgentIntegration)
        .filter_by(agent_id=agent_id)
        .all()
    )
    if not links:
        return "Connected apps: none allocated. User can assign apps in Settings → Connected apps."
    parts = []
    for link in links:
        conn = db.get(models.IntegrationConnection, link.connection_id)
        if not conn or conn.status != "connected":
            continue
        app = get_app(conn.app_id)
        name = conn.display_name or (app["name"] if app else conn.app_id)
        caps = ", ".join((app or {}).get("agent_capabilities") or []) or "general API access"
        meta = meta_from_row(conn)
        meta_bits = []
        for k in ("shop_domain", "store_url", "from_email", "default_channel", "portal_id", "account_id"):
            if meta.get(k):
                meta_bits.append(f"{k}={meta[k]}")
        extra = f" ({', '.join(meta_bits)})" if meta_bits else ""
        parts.append(f"- {name} [{conn.app_id}] permission={link.permission}{extra}: {caps}")
    if not parts:
        return "Connected apps: none currently in connected status."
    return (
        "You have access to these connected business apps (credentials are stored securely server-side; "
        "describe actions you would take with them and use deliverables accordingly):\n"
        + "\n".join(parts)
    )


def agent_connection_ids(db: Session, agent_id: int) -> list[int]:
    return [
        r.connection_id
        for r in db.query(models.AgentIntegration).filter_by(agent_id=agent_id).all()
    ]


# Re-export registry-based probes (keeps import path stable for routers)
from .integration_probes import probe_connection  # noqa: E402,F401


def oauth_env_ready(app: dict) -> bool:
    import os
    oauth = app.get("oauth") or {}
    cid = os.getenv(oauth.get("client_id_env") or "", "").strip()
    csec = os.getenv(oauth.get("client_secret_env") or "", "").strip()
    return bool(cid and csec)


def mark_connected(row: models.IntegrationConnection, message: str = "") -> None:
    row.status = "connected"
    row.last_error = ""
    row.last_synced_at = datetime.utcnow()
    if message:
        meta = meta_from_row(row)
        meta["status_message"] = message
        set_meta(row, meta)
