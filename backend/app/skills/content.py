"""Content generation / research / time skill handlers."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..live_ops import emit_ops
from .bridge import (
    get_skill_catalog,
    charge_premium,
)


async def _skill_generate_image(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    prompt = (args.get("prompt") or "").strip()
    if len(prompt) < 3:
        return {"ok": False, "error": "prompt is required"}
    meta = next((s for s in get_skill_catalog() if s["id"] == "generate_image"), {})
    # If execute_skill already charged premium, avoid double-charge when called via run
    # Skills run path charges once here when not charged upstream — check cost_credits flag
    if not args.get("_billed"):
        charge_premium(db, user, meta, 0.06, text=prompt)

    from ..routers.media import _svg_placeholder
    url = _svg_placeholder(prompt, "image")
    # Try live image API when available
    try:
        from .. import config
        import httpx
        key = config.get_grok_token() or ""
        if key:
            async with httpx.AsyncClient(timeout=90) as client:
                r = await client.post(
                    "https://api.x.ai/v1/images/generations",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model": "grok-imagine-image", "prompt": prompt, "n": 1},
                )
                if r.status_code < 400:
                    body = r.json()
                    u = (body.get("data") or [{}])[0].get("url")
                    if u:
                        url = u
    except Exception:
        pass

    await emit_ops(
        user.id, kind="action", status="done",
        title="Image generated", detail=prompt[:120], agent_id=agent.id, db=db,
    )
    return {"ok": True, "url": url, "prompt": prompt, "style": args.get("style"), "size": args.get("size")}

async def _skill_generate_video(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    prompt = (args.get("prompt") or "").strip()
    if len(prompt) < 3:
        return {"ok": False, "error": "prompt is required"}
    meta = next((s for s in get_skill_catalog() if s["id"] == "generate_video"), {})
    if not args.get("_billed"):
        charge_premium(db, user, meta, 0.25, text=prompt)

    from ..routers.media import _svg_placeholder
    poster = _svg_placeholder(prompt, "video")
    await emit_ops(
        user.id, kind="action", status="done",
        title="Video job created", detail=prompt[:120], agent_id=agent.id, db=db,
    )
    return {
        "ok": True,
        "poster_url": poster,
        "video_url": None,
        "prompt": prompt,
        "duration_sec": args.get("duration_sec") or 4,
        "note": "Poster ready. Full video URL when media worker is configured.",
    }

async def _skill_generate_content(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    ctype = args.get("type") or args.get("format") or "email"
    topic = (args.get("topic") or args.get("subject") or args.get("prompt") or "").strip()
    if not topic:
        return {"ok": False, "error": "topic is required"}
    audience = args.get("audience") or ""
    tone = args.get("tone") or "professional"
    length = args.get("length") or "medium"
    keywords = args.get("keywords") or ""
    brief = (
        f"Write {ctype} content.\n"
        f"Topic: {topic}\n"
        f"Audience: {audience or 'general'}\n"
        f"Tone: {tone}\n"
        f"Length: {length}\n"
        f"Keywords: {keywords or 'n/a'}\n"
        "Produce the full deliverable, not an outline."
    )
    return {
        "ok": True,
        "request": {
            "type": ctype,
            "topic": topic,
            "audience": audience,
            "tone": tone,
            "length": length,
            "keywords": keywords,
        },
        "message": f"Content brief ready ({ctype}): {topic[:80]}",
        "brief": brief,
    }

async def _skill_research(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    query = (args.get("query") or args.get("topic") or args.get("q") or "").strip()
    if not query:
        return {"ok": False, "error": "query or topic is required"}
    depth = args.get("depth") or "normal"
    focus = args.get("focus") or ""
    # Structure a research brief; catalog_deliverable path used for mega packs.
    # Core research skill returns a structured request the chat loop can expand.
    return {
        "ok": True,
        "request": {"query": query, "depth": depth, "focus": focus},
        "message": f"Research brief prepared for: {query[:120]}",
        "brief": (
            f"Research topic: {query}\n"
            f"Depth: {depth}\n"
            f"Focus: {focus or 'general'}\n"
            "Produce findings with sources, risks, and next actions."
        ),
    }

async def _skill_summarize(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    text = (
        args.get("text")
        or args.get("content")
        or args.get("body")
        or args.get("source")
        or ""
    )
    text = str(text).strip()
    if not text:
        return {"ok": False, "error": "text is required to summarize"}
    style = args.get("style") or args.get("format") or "bullets"
    try:
        max_points = min(20, max(3, int(args.get("max_points") or 8)))
    except (TypeError, ValueError):
        max_points = 8
    return {
        "ok": True,
        "request": {
            "text_preview": text[:400],
            "text_len": len(text),
            "format": style,
            "max_points": max_points,
        },
        "message": f"Summarize ({style}, up to {max_points} points)",
        "brief": (
            f"Summarize the following as {style} (max {max_points} points):\n\n{text[:6000]}"
        ),
    }

async def _skill_get_time(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from datetime import datetime, timezone
    tz = args.get("timezone") or "UTC"
    now = datetime.now(timezone.utc)
    return {"ok": True, "iso": now.isoformat(), "timezone": tz, "note": "Use for scheduling logic."}

async def _skill_suggest_times(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    return {"ok": True, "suggestions": ["Tomorrow 10:00", "Tomorrow 14:30", "Friday 09:00"], "duration_minutes": args.get("duration_minutes", 30)}

async def _skill_create_invoice_draft(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    return {"ok": True, "draft": True, "customer_id": args.get("customer_id"), "items": args.get("items", []), "message": "Invoice draft prepared."}


__all__ = [
    '_skill_generate_image',
    '_skill_generate_video',
    '_skill_generate_content',
    '_skill_research',
    '_skill_summarize',
    '_skill_get_time',
    '_skill_suggest_times',
    '_skill_create_invoice_draft',
]
