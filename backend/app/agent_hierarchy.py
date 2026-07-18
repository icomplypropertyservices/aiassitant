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
        # Light touch only: keep root identity. Full skill/model repair is POST /ops/scaffold.
        existing.hierarchy_role = "orchestrator"
        existing.is_lead = True
        existing.parent_id = None
        if not existing.permission_level or existing.permission_level == "viewer":
            existing.permission_level = "admin"
        if not existing.idle_mode:
            existing.idle_mode = "never_idle"
        db.commit()
        db.refresh(existing)
        return existing

    a = models.Agent(
        user_id=user.id,
        name="Main AI Orchestrator",
        template_type="orchestrator",
        personality=(
            "Strategic, clear, and decisive. You sit above all other agents, "
            "route work to the right lead or project team, and keep the human owner informed. "
            "You operate 100% autonomously: spawn, delegate, run skills, and recover from failures."
        ),
        model="quality",
        idle_mode="never_idle",
        config=json.dumps({"mission": "Coordinate all companies, projects, and agents", "autonomy": "full"}),
        is_lead=True,
        hierarchy_role="orchestrator",
        parent_id=None,
        permission_level="admin",
        status="active",
        escalate_when="on_failure",
        escalate_to="owner",
    )
    db.add(a)
    db.flush()
    promote_orchestrator(db, a)
    attach_orphan_leads_under(db, a)
    from .agent_scaffold import repair_agent
    repair_agent(db, a, force_never_idle=True, expand_skills=True)
    db.commit()
    db.refresh(a)
    return a


def find_designer(db: Session, user_id: int) -> models.Agent | None:
    return (
        db.query(models.Agent)
        .filter(
            models.Agent.user_id == user_id,
            models.Agent.template_type == "designer",
        )
        .order_by(models.Agent.id)
        .first()
    )


def ensure_master_designer(db: Session, user: models.User) -> models.Agent:
    """UI polish guardian agent — one per workspace."""
    existing = find_designer(db, user.id)
    if existing:
        existing.name = existing.name or "Master Designer"
        if not (existing.hierarchy_role or "").strip():
            existing.hierarchy_role = "specialist"
        existing.permission_level = getattr(existing, "permission_level", None) or "lead"
        existing.idle_mode = "never_idle"
        db.commit()
        db.refresh(existing)
        return existing

    orch = find_orchestrator(db, user.id)
    a = models.Agent(
        user_id=user.id,
        name="Master Designer",
        template_type="designer",
        personality=(
            "Exacting product designer. You judge UI polish for mobile and desktop: "
            "ChatGPT-like agent chat, touch targets, spacing, hierarchy, contrast, and clarity. "
            "You block ship until the experience feels premium and simple — one agent per page for chat."
        ),
        model="quality",
        idle_mode="never_idle",
        config=json.dumps({
            "brand": "AI Business Assistant",
            "mobile_first": True,
            "autonomy": "full",
            "gates": [
                "Agent chat is full-screen ChatGPT style",
                "One agent per chat page",
                "Touch targets ≥ 44px on mobile",
                "Bottom nav on phone for main areas",
                "Safe-area padding",
            ],
        }),
        is_lead=False,
        hierarchy_role="specialist",
        parent_id=orch.id if orch else None,
        permission_level="lead",
        status="active",
        escalate_when="on_failure",
        escalate_to="orchestrator",
        escalate_reason="UI polish not acceptable until designer gates pass",
    )
    db.add(a)
    db.flush()
    from .agent_scaffold import repair_agent
    repair_agent(db, a, force_never_idle=True, expand_skills=True)
    db.commit()
    db.refresh(a)
    return a


def polish_checklist() -> list[dict]:
    """Static product polish gates the Master Designer enforces."""
    return [
        {"id": "agent_chat_fullscreen", "label": "Agent chat is full-screen, one agent per page", "route": "/agents/:id"},
        {"id": "chatgpt_composer", "label": "Chat composer supports Enter send, voice, streaming", "route": "/agents/:id"},
        {"id": "mobile_bottom_nav", "label": "Phone bottom nav for Home / Agents / Business / Ops", "route": "/"},
        {"id": "touch_targets", "label": "Primary actions ≥ 44px tall on mobile", "route": "/agents"},
        {"id": "safe_areas", "label": "Notch / home-indicator safe areas respected", "route": "/agents/:id"},
        {"id": "live_ops_banner", "label": "Live ops ticker visible outside chat", "route": "/ops"},
        {"id": "business_crm", "label": "Business CRM with clickable customers", "route": "/business"},
        {"id": "permissions", "label": "Agents/humans have permission + escalate-when", "route": "/agents/:id/manage"},
    ]
