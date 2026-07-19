"""Created-skill factory, AgentBay publish, and catalog deliverable handlers."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..usage_billing import bill_llm_turn
from .bridge import (
    get_enabled_skill_ids,
    set_enabled_skills,
)


async def _skill_catalog_deliverable(
    db: Session,
    agent: models.Agent,
    user: models.User,
    skill_id: str,
    meta: dict,
    args: dict,
) -> dict:
    """
    Generic path for catalog skills without a dedicated side-effect handler.

    Marks the skill as accepted and gives the model a concrete deliverable brief
    so agents never hit hard "not implemented" for sales/HR/code/content skills.
    Optionally runs a short LLM completion when a model is available.
    """
    name = (meta or {}).get("name") or skill_id
    desc = (meta or {}).get("description") or ""
    brief = {
        "skill": skill_id,
        "name": name,
        "description": desc,
        "args": args or {},
        "agent": getattr(agent, "name", None),
        "role": getattr(agent, "hierarchy_role", None) or getattr(agent, "template_type", None),
    }
    instruction = (
        f"You are executing skill '{name}' ({skill_id}).\n"
        f"Goal: {desc}\n"
        f"Arguments: {json.dumps(args or {}, default=str)[:2000]}\n"
        "Produce a complete, usable deliverable (not a plan to do it later)."
    )
    content = ""
    try:
        from ..llm import complete
        from ..agent_scaffold import resolve_runtime

        rt = resolve_runtime(agent)
        model = getattr(rt, "model", None) or agent.model or "vps-fast"
        # Prefer a quality text model when on VPS placeholder ids
        messages = [
            {
                "role": "system",
                "content": f"You are {agent.name}, a business AI agent. Output only the deliverable.",
            },
            {"role": "user", "content": instruction},
        ]
        content = await complete(
            messages,
            model=model,
            mode=getattr(rt, "mode_hint", None) or "general",
        )
        content = (content or "").strip()
        # Always meter tokens for catalog deliverables (draft skills)
        if content:
            try:
                usage = bill_llm_turn(db, user, model, messages, content)
                brief["usage"] = usage
            except Exception as bill_e:
                brief["usage_error"] = str(bill_e)[:160]
    except Exception as e:
        # Still ok — caller LLM can finish from the brief
        content = ""
        brief["llm_error"] = str(e)[:200]

    # Persist short memory so later turns can reuse
    try:
        title = f"Skill: {name}"
        body = content[:3500] if content else instruction[:1500]
        db.add(
            models.AgentMemory(
                agent_id=agent.id,
                user_id=user.id,
                kind="deliverable",
                title=title[:200],
                content=body,
                tags=skill_id,
            )
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    out = {
        "ok": True,
        "mode": "catalog_deliverable",
        "skill": skill_id,
        "name": name,
        "brief": brief,
        "content": content or None,
        "message": (
            f"Skill '{name}' completed."
            if content
            else f"Skill '{name}' accepted — produce the deliverable from the brief."
        ),
        "instruction": instruction,
    }
    if brief.get("usage"):
        out["usage"] = brief["usage"]
    return out

def _slug_skill_key(name: str, agent_id: int, row_id: int | None = None) -> str:
    import re
    base = re.sub(r"[^a-z0-9]+", "_", (name or "skill").lower()).strip("_")[:40] or "skill"
    suffix = f"_{row_id}" if row_id else ""
    return f"custom_{agent_id}_{base}{suffix}"[:80]

async def _skill_create_skill(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Agent invents a new skill; optional share + AgentBay listing."""
    name = (args.get("name") or "").strip()[:120]
    if not name:
        return {"ok": False, "error": "name is required"}
    description = (args.get("description") or "").strip()[:2000]
    instructions = (args.get("instructions") or args.get("prompt") or "").strip()[:8000]
    if not instructions:
        instructions = (
            f"Execute the skill '{name}'. {description}\n"
            "Produce a complete, usable deliverable from the given arguments."
        )
    raw_args = args.get("args") or args.get("arg_names") or ["context", "goal"]
    if isinstance(raw_args, str):
        arg_list = [a.strip() for a in raw_args.replace(";", ",").split(",") if a.strip()]
    elif isinstance(raw_args, list):
        arg_list = [str(a).strip() for a in raw_args if str(a).strip()]
    else:
        arg_list = ["context", "goal"]
    category = (args.get("category") or "custom").strip()[:40] or "custom"
    share = args.get("share")
    if share is None:
        share = True
    share = bool(share) if not isinstance(share, str) else share.lower() not in ("0", "false", "no")
    list_on_bay = args.get("list_on_bay") or args.get("sell") or args.get("publish")
    if isinstance(list_on_bay, str):
        list_on_bay = list_on_bay.lower() in ("1", "true", "yes", "sell", "publish")
    list_on_bay = bool(list_on_bay)
    try:
        price = float(args.get("price") if args.get("price") is not None else 29.0)
    except Exception:
        price = 29.0
    price = max(0.0, min(price, 10_000.0))

    # Provisional key then finalize with id
    temp_key = _slug_skill_key(name, agent.id)
    row = models.CreatedSkill(
        user_id=user.id,
        agent_id=agent.id,
        skill_key=temp_key + f"_{int(datetime.utcnow().timestamp()) % 100000}",
        name=name,
        description=description,
        args_json=json.dumps(arg_list),
        instructions=instructions,
        category=category,
        status="active",
        shared=share,
        listed_on_bay=False,
        list_price=price,
    )
    db.add(row)
    db.flush()
    row.skill_key = _slug_skill_key(name, agent.id, row.id)
    db.commit()
    db.refresh(row)

    # Auto-enable on creator
    try:
        cur = get_enabled_skill_ids(agent, db)
        set_enabled_skills(db, agent, list(cur | {row.skill_key, "create_skill", "list_created_skills", "publish_skill_to_bay"}))
    except Exception:
        pass

    bay = None
    if list_on_bay:
        bay = await _skill_publish_skill_to_bay(
            db, agent, user,
            {"skill_key": row.skill_key, "price": price, "title": name},
        )

    return {
        "ok": True,
        "message": f"Created skill “{name}” ({row.skill_key})",
        "skill": {
            "id": row.id,
            "skill_key": row.skill_key,
            "name": row.name,
            "description": row.description,
            "args": arg_list,
            "category": row.category,
            "shared": row.shared,
            "listed_on_bay": bool(row.listed_on_bay or (bay or {}).get("ok")),
            "list_price": row.list_price,
            "bay": bay if isinstance(bay, dict) else None,
        },
        "how_to_run": f"Use skill block with id {row.skill_key} and args {arg_list}",
        "how_to_sell": "Call publish_skill_to_bay with skill_key if not already listed.",
    }

async def _skill_list_created_skills(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        limit = min(100, int(args.get("limit") or 40))
    except Exception:
        limit = 40
    mine_only = args.get("mine_only")
    if isinstance(mine_only, str):
        mine_only = mine_only.lower() in ("1", "true", "yes")
    listed_only = args.get("listed_only")
    if isinstance(listed_only, str):
        listed_only = listed_only.lower() in ("1", "true", "yes")
    q = db.query(models.CreatedSkill).filter_by(user_id=user.id).filter(models.CreatedSkill.status != "archived")
    if mine_only:
        q = q.filter_by(agent_id=agent.id)
    if listed_only:
        q = q.filter_by(listed_on_bay=True)
    rows = q.order_by(models.CreatedSkill.id.desc()).limit(limit).all()
    return {
        "ok": True,
        "count": len(rows),
        "skills": [
            {
                "id": r.id,
                "skill_key": r.skill_key,
                "name": r.name,
                "description": (r.description or "")[:300],
                "category": r.category,
                "shared": r.shared,
                "listed_on_bay": r.listed_on_bay,
                "list_price": r.list_price,
                "bay_listing_id": r.bay_listing_id,
                "bay_url": r.bay_url,
                "creator_agent_id": r.agent_id,
                "use_count": r.use_count,
            }
            for r in rows
        ],
    }

def _resolve_created_skill(db: Session, user_id: int, args: dict) -> models.CreatedSkill | None:
    key = (args.get("skill_key") or args.get("skill_id") or args.get("id") or "").strip()
    if not key:
        return None
    row = db.query(models.CreatedSkill).filter_by(user_id=user_id, skill_key=key).first()
    if row:
        return row
    try:
        rid = int(key)
        return db.query(models.CreatedSkill).filter_by(user_id=user_id, id=rid).first()
    except Exception:
        return None

async def _skill_publish_skill_to_bay(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    row = _resolve_created_skill(db, user.id, args)
    if not row:
        return {"ok": False, "error": "skill not found (skill_key or skill_id)"}
    try:
        price = float(args.get("price") if args.get("price") is not None else row.list_price or 29.0)
    except Exception:
        price = float(row.list_price or 29.0)
    title = (args.get("title") or row.name or "Custom skill").strip()[:200]
    try:
        qty = int(args.get("quantity") or 100)
    except Exception:
        qty = 100

    from ..agentbay_bridge import publish_created_skill, enabled as bay_enabled
    if not bay_enabled():
        # Still mark as listed locally so UI shows intent; bridge may be offline
        row.listed_on_bay = True
        row.list_price = price
        row.updated_at = datetime.utcnow()
        db.commit()
        return {
            "ok": True,
            "warning": "AgentBay bridge not configured — skill marked listed locally only",
            "skill_key": row.skill_key,
            "price": price,
            "hint": "Set AGENTBAY_URL + AGENTBAY_BRIDGE_SECRET to push live listings to /bay",
        }

    result = await publish_created_skill(
        db, user, agent, row,
        price=price,
        title=title,
        quantity=qty,
    )
    # Always record sell intent + price; remote listing when bridge is up
    row.listed_on_bay = True
    row.list_price = price
    row.updated_at = datetime.utcnow()
    if result.get("ok"):
        lid = (result.get("listing") or {}).get("id") or result.get("listing_id")
        if lid:
            try:
                row.bay_listing_id = int(lid)
            except Exception:
                pass
        row.bay_external_id = result.get("external_id") or row.bay_external_id or f"skill:{row.id}"
        row.bay_url = result.get("url") or row.bay_url or ""
        db.commit()
        return {
            "ok": True,
            "message": result.get("message") or f"Listed “{row.name}” on AgentBay at ${price:.2f}",
            "skill_key": row.skill_key,
            "price": price,
            "agentbay": result,
        }
    db.commit()
    return {
        "ok": True,
        "warning": result.get("error") or "AgentBay unreachable",
        "message": (
            f"Skill “{row.name}” marked for sale at ${price:.2f}. "
            "AgentBay sync failed — retry publish_skill_to_bay when /bay is up."
        ),
        "skill_key": row.skill_key,
        "price": price,
        "agentbay": result,
        "listed_locally": True,
    }

async def _skill_unpublish_skill_from_bay(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    row = _resolve_created_skill(db, user.id, args)
    if not row:
        return {"ok": False, "error": "skill not found"}
    row.listed_on_bay = False
    row.updated_at = datetime.utcnow()
    db.commit()
    # Best-effort remote pause
    try:
        from ..agentbay_bridge import unpublish_created_skill
        await unpublish_created_skill(row)
    except Exception:
        pass
    return {"ok": True, "message": f"Unlisted {row.skill_key} from AgentBay (local skill kept)"}

async def _skill_share_skill(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    row = _resolve_created_skill(db, user.id, args)
    if not row:
        return {"ok": False, "error": "skill not found"}
    shared = args.get("shared")
    if shared is None:
        shared = True
    if isinstance(shared, str):
        shared = shared.lower() not in ("0", "false", "no")
    row.shared = bool(shared)
    row.updated_at = datetime.utcnow()
    db.commit()
    return {
        "ok": True,
        "skill_key": row.skill_key,
        "shared": row.shared,
        "message": f"Skill is {'shared with workspace' if row.shared else 'private to creator agent'}",
    }

async def _skill_run_created(
    db: Session,
    agent: models.Agent,
    user: models.User,
    skill_id: str,
    meta: dict,
    args: dict,
    custom_row: models.CreatedSkill | None,
) -> dict:
    """Run a user/agent-created skill via deliverable path + stored instructions."""
    instructions = ""
    if custom_row:
        instructions = custom_row.instructions or ""
        try:
            custom_row.use_count = int(custom_row.use_count or 0) + 1
            db.commit()
        except Exception:
            pass
    else:
        instructions = (meta or {}).get("instructions") or ""
    # Fold instructions into args for catalog deliverable
    enriched = {
        **(args or {}),
        "_skill_instructions": instructions,
        "_created_skill": True,
    }
    meta2 = dict(meta or {})
    if instructions:
        meta2["description"] = (
            f"{meta2.get('description') or ''}\n\nSkill instructions:\n{instructions}"
        ).strip()
    return await _skill_catalog_deliverable(db, agent, user, skill_id, meta2, enriched)


__all__ = [
    '_skill_catalog_deliverable',
    '_slug_skill_key',
    '_skill_create_skill',
    '_skill_list_created_skills',
    '_resolve_created_skill',
    '_skill_publish_skill_to_bay',
    '_skill_unpublish_skill_from_bay',
    '_skill_share_skill',
    '_skill_run_created',
]
