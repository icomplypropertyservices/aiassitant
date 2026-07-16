"""Hierarchy tree + ensure-orchestrator domain logic (reusable)."""
from __future__ import annotations

import json
from sqlalchemy.orm import Session

from . import models
from .agent_roles import (
    agent_sort_key,
    attach_orphan_leads_under,
    find_orchestrator,
    is_orchestrator,
    is_lead_agent,
    promote_orchestrator,
)
from .agent_serialize import agent_out, load_name_maps


def build_hierarchy_payload(db: Session, user_id: int) -> dict:
    agents = db.query(models.Agent).filter_by(user_id=user_id).all()
    company_names, project_names = load_name_maps(db, agents)

    by_parent: dict[int | None, list] = {}
    for a in agents:
        by_parent.setdefault(a.parent_id, []).append(a)
    for kids in by_parent.values():
        kids.sort(key=agent_sort_key)

    def node(a: models.Agent) -> dict:
        kids = by_parent.get(a.id, [])
        return {
            **agent_out(
                a, db,
                company_names=company_names,
                project_names=project_names,
            ),
            "children": [node(c) for c in kids],
        }

    roots = sorted(by_parent.get(None, []), key=agent_sort_key)
    tree = [node(a) for a in roots]
    flat_sorted = sorted(agents, key=agent_sort_key)
    flat = [
        agent_out(a, db, company_names=company_names, project_names=project_names)
        for a in flat_sorted
    ]
    # Prefer pre-serialized flat entries (one pass)
    by_id = {x["id"]: x for x in flat}
    orchestrators = [by_id[a.id] for a in flat_sorted if is_orchestrator(a)]
    leads = [
        by_id[a.id]
        for a in flat_sorted
        if is_lead_agent(a) or (a.hierarchy_role or "") in ("lead", "orchestrator") or by_parent.get(a.id)
    ]
    return {
        "tree": tree,
        "orchestrator": orchestrators[0] if orchestrators else None,
        "orchestrators": orchestrators,
        "leads": leads,
        "flat": flat,
        "total": len(agents),
    }


def ensure_main_orchestrator(db: Session, user: models.User) -> models.Agent:
    """Return existing or newly created Main AI Orchestrator for user."""
    existing = find_orchestrator(db, user.id)
    if existing:
        promote_orchestrator(db, existing)
        db.commit()
        db.refresh(existing)
        return existing

    a = models.Agent(
        user_id=user.id,
        name="Main AI Orchestrator",
        template_type="orchestrator",
        personality=(
            "Strategic, clear, and decisive. You sit above all other agents, "
            "route work to the right lead or project team, and keep the human owner informed."
        ),
        model="vps-quality",
        idle_mode="never_idle",
        config=json.dumps({"mission": "Coordinate all companies, projects, and agents"}),
        is_lead=True,
        hierarchy_role="orchestrator",
        parent_id=None,
    )
    db.add(a)
    db.flush()
    promote_orchestrator(db, a)
    attach_orphan_leads_under(db, a)
    db.commit()
    db.refresh(a)
    return a
