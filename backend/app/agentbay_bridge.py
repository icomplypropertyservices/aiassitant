"""
Push AI Business Assistant agents to the AgentBay marketplace as sellable skills.

Configure:
  AGENTBAY_URL=http://127.0.0.1:8000
  AGENTBAY_BRIDGE_SECRET=<same as AgentBay BRIDGE_SECRET>
  AGENTBAY_AUTO_PUBLISH=1
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from . import config, models

log = logging.getLogger("agentbay_bridge")


def enabled() -> bool:
    return bool(config.AGENTBAY_URL and config.AGENTBAY_BRIDGE_SECRET)


def _skills_from_agent(a: models.Agent) -> list[str]:
    skills: list[str] = []
    try:
        cfg = json.loads(a.config or "{}")
        if isinstance(cfg.get("skills"), list):
            skills = [str(s) for s in cfg["skills"][:20]]
        elif isinstance(cfg.get("skills"), str) and cfg["skills"]:
            skills = [s.strip() for s in cfg["skills"].split(",") if s.strip()][:20]
    except Exception:
        pass
    if a.template_type and a.template_type not in skills:
        skills.insert(0, a.template_type)
    return skills


def agent_payload(
    a: models.Agent,
    db: Session,
    *,
    price: float | None = None,
    publish_listing: bool = True,
    extra_listing: dict | None = None,
) -> dict[str, Any]:
    company_name = ""
    if a.company_id:
        c = db.get(models.Company, a.company_id)
        if c:
            company_name = c.name or ""
    listing = {
        "title": f"{a.name} — AI agent skill",
        "description": (
            f"Hire **{a.name}** from AI Business Assistant.\n\n"
            f"{a.personality or ''}\n\n"
            f"Template: {a.template_type or 'general'} · Role: {a.hierarchy_role or 'member'}"
        ),
        "price": float(price if price is not None else config.AGENTBAY_DEFAULT_PRICE),
        "quantity": 100,
        "tags": ",".join(_skills_from_agent(a)[:8]),
        "status": "active" if a.status == "active" else "paused",
    }
    if extra_listing:
        listing.update(extra_listing)
    return {
        "external_id": f"agent:{a.id}",
        "source_system": "ai-business-assistant",
        "name": a.name,
        "bio": (a.personality or "")[:500],
        "template_type": a.template_type or "",
        "personality": a.personality or "",
        "hierarchy_role": a.hierarchy_role or "member",
        "company_name": company_name,
        "skills": _skills_from_agent(a),
        "model": a.model or "",
        "publish_listing": publish_listing,
        "listing": listing,
    }


async def publish_agent(
    a: models.Agent,
    db: Session,
    *,
    price: float | None = None,
    publish_listing: bool = True,
    extra_listing: dict | None = None,
) -> dict[str, Any]:
    if not enabled():
        return {"ok": False, "error": "AgentBay bridge not configured"}

    body = agent_payload(
        a, db, price=price, publish_listing=publish_listing, extra_listing=extra_listing
    )
    # Production path: https://aibusinessagent.xyz/bay/api/bridge/agent-sync
    base = config.AGENTBAY_URL.rstrip("/")
    if base.endswith("/bay"):
        url = f"{base}/api/bridge/agent-sync"
    elif "/bay/api" in base:
        url = f"{base.rstrip('/')}/bridge/agent-sync"
    else:
        url = f"{base}/api/bridge/agent-sync"
    headers = {
        "X-Bridge-Secret": config.AGENTBAY_BRIDGE_SECRET,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=body, headers=headers)
            if r.status_code >= 400:
                log.warning("AgentBay sync failed %s: %s", r.status_code, r.text[:300])
                return {"ok": False, "status": r.status_code, "error": r.text[:500]}
            data = r.json()
            # Store marketplace refs on agent config for later
            try:
                cfg = json.loads(a.config or "{}")
            except Exception:
                cfg = {}
            cfg["agentbay"] = {
                "user_id": (data.get("user") or {}).get("id"),
                "username": (data.get("user") or {}).get("username"),
                "listing_id": (data.get("listing") or {}).get("id"),
                "url": config.AGENTBAY_URL,
            }
            if data.get("created_api_key"):
                cfg["agentbay"]["api_key"] = data["created_api_key"]
            a.config = json.dumps(cfg)
            db.commit()
            return {"ok": True, **data}
    except Exception as e:
        log.exception("AgentBay publish failed")
        return {"ok": False, "error": str(e)}


async def publish_all_user_agents(db: Session, user_id: int) -> dict[str, Any]:
    agents = db.query(models.Agent).filter_by(user_id=user_id).all()
    results = []
    for a in agents:
        results.append({"agent_id": a.id, "name": a.name, **(await publish_agent(a, db))})
    return {"items": results, "count": len(results)}


async def maybe_auto_publish(a: models.Agent, db: Session) -> None:
    if not config.AGENTBAY_AUTO_PUBLISH or not enabled():
        return
    try:
        await publish_agent(a, db)
    except Exception:
        log.exception("auto-publish skipped")


def _bridge_url(path: str = "agent-sync") -> str:
    base = config.AGENTBAY_URL.rstrip("/")
    if base.endswith("/bay"):
        return f"{base}/api/bridge/{path}"
    if "/bay/api" in base:
        return f"{base.rstrip('/')}/bridge/{path}"
    return f"{base}/api/bridge/{path}"


async def publish_created_skill(
    db: Session,
    user: models.User,
    agent: models.Agent,
    skill: models.CreatedSkill,
    *,
    price: float = 29.0,
    title: str | None = None,
    quantity: int = 100,
) -> dict[str, Any]:
    """
    List a workspace-created skill for sale on AgentBay.

    Uses the same bridge agent-sync endpoint with external_id skill:{id}
    so listings stay upsertable.
    """
    if not enabled():
        return {"ok": False, "error": "AgentBay bridge not configured"}

    external_id = f"skill:{skill.id}"
    list_title = (title or skill.name or "Custom skill").strip()[:200]
    desc = (
        f"{skill.description or ''}\n\n"
        f"**Skill key:** `{skill.skill_key}`\n"
        f"**Category:** {skill.category or 'custom'}\n"
        f"Created by agent **{agent.name}** (#{agent.id}) on AI Business Assistant.\n\n"
        f"Instructions (seller brief):\n{(skill.instructions or '')[:1500]}"
    ).strip()
    body = {
        "external_id": external_id,
        "source_system": "ai-business-assistant",
        "name": f"{agent.name} · {skill.name}"[:120],
        "bio": (skill.description or agent.personality or "")[:500],
        "template_type": "custom_skill",
        "personality": (agent.personality or "")[:400],
        "hierarchy_role": agent.hierarchy_role or "member",
        "company_name": "",
        "skills": [skill.skill_key, skill.category or "custom", "agent-created"],
        "model": agent.model or "",
        "publish_listing": True,
        "listing": {
            "title": list_title,
            "description": desc[:4000],
            "price": float(price),
            "quantity": max(1, int(quantity or 100)),
            "tags": f"skill,custom,{skill.category or 'custom'},agent-created",
            "status": "active",
        },
    }
    if skill.user_id:
        body["email"] = f"skill{skill.id}.u{skill.user_id}@bridge.agentbay.local"

    headers = {
        "X-Bridge-Secret": config.AGENTBAY_BRIDGE_SECRET,
        "Content-Type": "application/json",
    }
    url = _bridge_url("agent-sync")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=body, headers=headers)
            if r.status_code >= 400:
                log.warning("AgentBay skill publish failed %s: %s", r.status_code, r.text[:300])
                return {"ok": False, "status": r.status_code, "error": r.text[:500]}
            data = r.json() if r.content else {}
            listing = data.get("listing") or {}
            public = (config.AGENTBAY_PUBLIC_URL or config.AGENTBAY_URL or "").rstrip("/")
            listing_url = ""
            if listing.get("id"):
                listing_url = f"{public}/listing/{listing['id']}" if public else ""
            return {
                "ok": True,
                "external_id": external_id,
                "listing": listing,
                "listing_id": listing.get("id"),
                "url": listing_url or public,
                "user": data.get("user"),
                "message": f"Skill listed on AgentBay ({list_title})",
            }
    except Exception as e:
        log.exception("publish_created_skill failed")
        return {"ok": False, "error": str(e)}


async def unpublish_created_skill(skill: models.CreatedSkill) -> dict[str, Any]:
    """Best-effort: bridge has no delete API yet — no-op remote, local flag cleared by caller."""
    return {"ok": True, "note": "remote pause not implemented; listing may remain until edited in AgentBay"}
