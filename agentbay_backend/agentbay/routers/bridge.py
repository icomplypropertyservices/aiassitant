"""
Bridge API for external systems (AI Business Assistant) to register agents
and auto-publish skill listings on AgentBay.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import config, models
from ..auth_utils import (
    generate_api_key,
    get_current_user,
    hash_password,
    user_public,
)
from ..database import get_db
from .listings import serialize_listing

router = APIRouter(prefix="/bridge", tags=["bridge"])


def _require_bridge(
    x_bridge_secret: str | None = Header(None, alias="X-Bridge-Secret"),
    user=None,
):
    if x_bridge_secret and x_bridge_secret == config.BRIDGE_SECRET:
        return "bridge"
    return None


class AgentSkillIn(BaseModel):
    title: str | None = None
    description: str | None = None
    price: float = Field(default=29.0, ge=0)
    quantity: int = Field(default=100, ge=0)
    tags: str = ""
    image_url: str = ""
    status: str = "active"


class BridgeAgentSync(BaseModel):
    """Upsert an agent account from AI Business Assistant and publish a skill listing."""

    external_id: str = Field(..., description="Stable id in source system, e.g. agent:42")
    source_system: str = "ai-business-assistant"
    name: str
    username: str | None = None
    email: str | None = None
    bio: str = ""
    template_type: str = ""
    personality: str = ""
    hierarchy_role: str = "member"
    company_name: str = ""
    skills: list[str] = []
    model: str = ""
    publish_listing: bool = True
    listing: AgentSkillIn | None = None
    # If set, reuse existing marketplace user by api key owner (optional)
    marketplace_api_key: str | None = None


class BridgeBulkSync(BaseModel):
    agents: list[BridgeAgentSync]


def _slug_username(name: str, external_id: str) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", (name or "agent").lower()).strip("_")[:24]
    suffix = re.sub(r"[^a-z0-9]", "", external_id.lower())[-6:] or "0"
    return f"{base}_{suffix}"[:40]


def _ensure_agent_user(db: Session, data: BridgeAgentSync) -> tuple[models.User, str | None]:
    """Return (user, new_api_key_if_created)."""
    existing = (
        db.query(models.User)
        .filter_by(source_system=data.source_system, external_id=data.external_id)
        .first()
    )
    if existing:
        existing.display_name = data.name or existing.display_name
        if data.bio:
            existing.bio = data.bio
        existing.account_type = "agent"
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        return existing, None

    username = (data.username or _slug_username(data.name, data.external_id)).lower()
    if db.query(models.User).filter_by(username=username).first():
        username = f"{username}_{data.external_id}"[:40].lower()

    email = (data.email or f"{username}@bridge.agentbay.local").lower()
    if db.query(models.User).filter_by(email=email).first():
        email = f"{data.source_system}.{data.external_id}@bridge.agentbay.local".lower()

    raw, prefix, h = generate_api_key()
    # Random password — agents use API key
    import secrets

    user = models.User(
        email=email,
        username=username,
        display_name=data.name,
        password_hash=hash_password(secrets.token_urlsafe(16)),
        account_type="agent",
        bio=data.bio
        or f"{data.template_type} agent from {data.source_system}. {data.personality}".strip(),
        source_system=data.source_system,
        external_id=data.external_id,
        api_key_hash=h,
        api_key_prefix=prefix,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, raw


def _publish_skill(db: Session, seller: models.User, data: BridgeAgentSync) -> models.Listing:
    listing_in = data.listing or AgentSkillIn()
    title = listing_in.title or f"{data.name} — {data.template_type or 'Agent skill'}"
    skills_txt = ", ".join(data.skills) if data.skills else ""
    desc_parts = [
        listing_in.description or "",
        data.personality and f"Personality: {data.personality}",
        data.hierarchy_role and f"Role: {data.hierarchy_role}",
        data.company_name and f"Company: {data.company_name}",
        data.model and f"Model: {data.model}",
        skills_txt and f"Skills: {skills_txt}",
        f"Synced from {data.source_system} ({data.external_id})",
    ]
    description = "\n".join(p for p in desc_parts if p)

    cat = db.query(models.Category).filter_by(slug="agent-skills").first()
    tags = listing_in.tags or ",".join(
        filter(None, [data.template_type, "agent", "bridge", *data.skills[:5]])
    )

    existing = (
        db.query(models.Listing)
        .filter_by(
            seller_id=seller.id,
            source_system=data.source_system,
            external_id=data.external_id,
        )
        .first()
    )
    meta = {
        "template_type": data.template_type,
        "hierarchy_role": data.hierarchy_role,
        "skills": data.skills,
        "model": data.model,
        "company_name": data.company_name,
    }
    if existing:
        existing.title = title[:200]
        existing.description = description
        existing.price = listing_in.price
        existing.quantity = listing_in.quantity
        existing.tags = tags
        existing.status = listing_in.status
        if listing_in.image_url:
            existing.image_url = listing_in.image_url
        existing.external_meta = json.dumps(meta)
        existing.updated_at = datetime.utcnow()
        existing.kind = "agent_skill"
        if cat:
            existing.category_id = cat.id
        db.commit()
        db.refresh(existing)
        return existing

    L = models.Listing(
        seller_id=seller.id,
        category_id=cat.id if cat else None,
        title=title[:200],
        description=description,
        kind="agent_skill",
        price=listing_in.price,
        quantity=listing_in.quantity,
        status=listing_in.status,
        condition="n/a",
        image_url=listing_in.image_url or "",
        tags=tags,
        sale_type="buy_now",
        source_system=data.source_system,
        external_id=data.external_id,
        external_meta=json.dumps(meta),
    )
    db.add(L)
    db.commit()
    db.refresh(L)
    return L


@router.get("/status")
def bridge_status():
    return {
        "ok": True,
        "bridge": "agentbay",
        "auth": "X-Bridge-Secret header or agent JWT / X-API-Key",
        "endpoints": [
            "POST /api/bridge/agent-sync",
            "POST /api/bridge/agents/bulk-sync",
            "GET /api/bridge/agents/{source}/{external_id}",
        ],
    }


def _check_bridge_secret(x_bridge_secret: str | None):
    if not config.bridge_configured():
        raise HTTPException(503, "Bridge not configured — set BRIDGE_SECRET")
    if not x_bridge_secret or x_bridge_secret != config.BRIDGE_SECRET:
        raise HTTPException(401, "Invalid or missing X-Bridge-Secret")


@router.post("/agent-sync")
def agent_sync(
    data: BridgeAgentSync,
    db: Session = Depends(get_db),
    x_bridge_secret: str | None = Header(None, alias="X-Bridge-Secret"),
):
    _check_bridge_secret(x_bridge_secret)

    user, new_key = _ensure_agent_user(db, data)
    listing = None
    if data.publish_listing:
        listing = _publish_skill(db, user, data)

    out = {
        "user": user_public(user),
        "listing": serialize_listing(listing, user) if listing else None,
        "created_api_key": new_key,
        "api_key_note": "Save created_api_key if present — shown only on first sync."
        if new_key
        else None,
    }
    return out


@router.post("/agents/bulk-sync")
def bulk_sync(
    data: BridgeBulkSync,
    db: Session = Depends(get_db),
    x_bridge_secret: str | None = Header(None, alias="X-Bridge-Secret"),
):
    _check_bridge_secret(x_bridge_secret)
    results = []
    for agent in data.agents:
        try:
            results.append(agent_sync(agent, db, x_bridge_secret))
        except Exception as e:
            results.append({"error": str(e), "external_id": agent.external_id})
    return {"items": results, "count": len(results)}


@router.get("/agents/{source_system}/{external_id}")
def get_bridged_agent(
    source_system: str,
    external_id: str,
    db: Session = Depends(get_db),
    x_bridge_secret: str | None = Header(None, alias="X-Bridge-Secret"),
):
    _check_bridge_secret(x_bridge_secret)
    user = (
        db.query(models.User)
        .filter_by(source_system=source_system, external_id=external_id)
        .first()
    )
    if not user:
        raise HTTPException(404, "Not found")
    listings = (
        db.query(models.Listing)
        .filter_by(seller_id=user.id, source_system=source_system)
        .all()
    )
    return {
        "user": user_public(user),
        "listings": [serialize_listing(L, user) for L in listings],
    }


@router.post("/publish-my-skill")
def publish_my_skill(
    data: AgentSkillIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Logged-in agent publishes/updates their own skill listing."""
    if user.account_type not in ("agent", "admin", "human"):
        raise HTTPException(403, "Forbidden")
    sync = BridgeAgentSync(
        external_id=user.external_id or f"user:{user.id}",
        source_system=user.source_system or "agentbay",
        name=user.display_name or user.username,
        bio=user.bio or "",
        publish_listing=True,
        listing=data,
    )
    # Don't create new user — use current
    L = _publish_skill(db, user, sync)
    return serialize_listing(L, user)
