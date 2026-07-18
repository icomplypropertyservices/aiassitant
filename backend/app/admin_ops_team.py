"""
Staff Admin ops team — day-to-day platform operations for role=admin only.

Layout:
  Staff Admin Orchestrator  (lead)     → quality  (Qwen on RunPod)
    ├─ Server Monitor Specialist       → grok-max (highest Grok / xAI)
    ├─ Fleet Ops Specialist            → fast     (Qwen)
    ├─ Billing Ops Specialist          → fast     (Qwen)
    └─ Security Ops Specialist         → reasoning (DeepSeek)

Customers never see these as product features; they live on the staff admin account.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .agent_roles import find_orchestrator

# template_type → agent definition
STAFF_TEAM_SPEC: list[dict[str, Any]] = [
    {
        "name": "Staff Admin Orchestrator",
        "template_type": "staff_orchestrator",
        "hierarchy_role": "lead",
        "model": "quality",  # Qwen quality tier
        "permission_level": "admin",
        "idle_mode": "never_idle",
        "personality": (
            "Calm, decisive platform ops lead. You run day-to-day staff admin issues: "
            "user problems, fleet health, billing anomalies, security flags, and routing work "
            "to the right specialist. Summarise for the human admin; act autonomously on routine items."
        ),
        "config": {
            "staff_ops": True,
            "mission": "Day-to-day platform admin: users, fleet, billing, security",
            "routes_to": ["server_monitor", "fleet_ops", "billing_ops", "security_ops"],
        },
        "is_root_staff": True,
    },
    {
        "name": "Server Monitor Specialist",
        "template_type": "server_monitor",
        "hierarchy_role": "specialist",
        "model": "grok-max",  # Highest Grok only
        "permission_level": "lead",
        "idle_mode": "never_idle",
        "personality": (
            "Elite infrastructure watchdog. You watch RunPod/Ollama fleet health, latency, "
            "model availability, disk/VRAM risk, proxy failures, and cold starts. "
            "You use the strongest reasoning available. Escalate critical outages immediately; "
            "propose concrete fixes (restart Ollama, pull model, remap Fast/Quality, expose ports)."
        ),
        "config": {
            "staff_ops": True,
            "focus": ["runpod", "ollama", "fleet", "proxy", "uptime"],
            "model_policy": "highest_grok_only",
        },
    },
    {
        "name": "Fleet Ops Specialist",
        "template_type": "fleet_ops",
        "hierarchy_role": "specialist",
        "model": "fast",  # Qwen
        "permission_level": "operator",
        "idle_mode": "never_idle",
        "personality": (
            "Hands-on fleet operator. Pull/delete Ollama models, adjust Fast/Quality/Reasoning maps, "
            "verify tags, and keep recommended models present. Prefer Qwen for speed/cost."
        ),
        "config": {"staff_ops": True, "focus": ["models", "routing", "pulls"]},
    },
    {
        "name": "Billing Ops Specialist",
        "template_type": "billing_ops",
        "hierarchy_role": "specialist",
        "model": "fast",  # Qwen
        "permission_level": "operator",
        "idle_mode": "never_idle",
        "personality": (
            "Billing and wallet specialist. Track low-credit users, top-up needs, plan anomalies, "
            "and Stripe/crypto payment issues. Clear, numerical, action-oriented."
        ),
        "config": {"staff_ops": True, "focus": ["wallets", "plans", "usage"]},
    },
    {
        "name": "Security Ops Specialist",
        "template_type": "security_ops",
        "hierarchy_role": "specialist",
        "model": "reasoning",  # DeepSeek R1 tier
        "permission_level": "operator",
        "idle_mode": "never_idle",
        "personality": (
            "Security and abuse specialist. Watch for suspicious signups, key leaks, "
            "abuse of fleet APIs, and permission mistakes. Reason carefully before acting."
        ),
        "config": {"staff_ops": True, "focus": ["abuse", "keys", "access"]},
    },
]

STAFF_TEMPLATE_TYPES = frozenset(s["template_type"] for s in STAFF_TEAM_SPEC)


def _find_by_type(db: Session, user_id: int, template_type: str) -> models.Agent | None:
    return (
        db.query(models.Agent)
        .filter_by(user_id=user_id, template_type=template_type)
        .order_by(models.Agent.id)
        .first()
    )


def _upsert_staff_agent(
    db: Session,
    user: models.User,
    spec: dict[str, Any],
    parent_id: int | None,
) -> models.Agent:
    existing = _find_by_type(db, user.id, spec["template_type"])
    cfg = dict(spec.get("config") or {})
    cfg["staff_ops"] = True
    cfg_json = json.dumps(cfg)

    if existing:
        existing.name = spec["name"]
        existing.model = spec["model"]
        existing.hierarchy_role = spec["hierarchy_role"]
        existing.permission_level = spec["permission_level"]
        existing.idle_mode = spec["idle_mode"]
        existing.personality = spec["personality"]
        existing.config = cfg_json
        existing.status = "active"
        existing.is_lead = spec["hierarchy_role"] in ("lead", "orchestrator")
        if not spec.get("is_root_staff"):
            existing.parent_id = parent_id
        else:
            # Staff orchestrator reports to main workspace orchestrator if present
            orch = find_orchestrator(db, user.id)
            existing.parent_id = orch.id if orch and orch.id != existing.id else None
        existing.escalate_when = "on_failure"
        existing.escalate_to = "owner" if spec.get("is_root_staff") else "parent"
        db.flush()
        from .agent_scaffold import repair_agent
        # Do not let map_model downgrade grok-max incorrectly — repair keeps map_model
        repair_agent(db, existing, force_never_idle=True, expand_skills=True)
        # Enforce model after repair (repair maps but must keep grok-max / tiers)
        existing.model = spec["model"]
        return existing

    orch = find_orchestrator(db, user.id)
    a = models.Agent(
        user_id=user.id,
        name=spec["name"],
        template_type=spec["template_type"],
        personality=spec["personality"],
        model=spec["model"],
        idle_mode=spec["idle_mode"],
        config=cfg_json,
        is_lead=spec["hierarchy_role"] in ("lead", "orchestrator"),
        hierarchy_role=spec["hierarchy_role"],
        parent_id=(
            (orch.id if orch else None) if spec.get("is_root_staff") else parent_id
        ),
        permission_level=spec["permission_level"],
        status="active",
        escalate_when="on_failure",
        escalate_to="owner" if spec.get("is_root_staff") else "parent",
    )
    db.add(a)
    db.flush()
    from .agent_scaffold import repair_agent
    repair_agent(db, a, force_never_idle=True, expand_skills=True)
    a.model = spec["model"]
    return a


def ensure_staff_ops_team(db: Session, user: models.User) -> dict[str, Any]:
    """
    Create/update the staff admin ops team. Only for users with role=admin.
    """
    if (user.role or "").lower() != "admin":
        return {"ok": False, "error": "staff ops team is only for admin accounts", "agents": []}

    # Ensure workspace orchestrator exists first (staff lead hangs under it)
    from .agent_hierarchy import ensure_main_orchestrator
    ensure_main_orchestrator(db, user)

    created: list[models.Agent] = []
    staff_orch: models.Agent | None = None

    for spec in STAFF_TEAM_SPEC:
        if spec.get("is_root_staff"):
            staff_orch = _upsert_staff_agent(db, user, spec, parent_id=None)
            created.append(staff_orch)

    parent_id = staff_orch.id if staff_orch else None
    for spec in STAFF_TEAM_SPEC:
        if spec.get("is_root_staff"):
            continue
        a = _upsert_staff_agent(db, user, spec, parent_id=parent_id)
        created.append(a)

    db.commit()
    for a in created:
        db.refresh(a)

    return {
        "ok": True,
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "template_type": a.template_type,
                "model": a.model,
                "hierarchy_role": a.hierarchy_role,
                "parent_id": a.parent_id,
                "status": a.status,
            }
            for a in created
        ],
        "policy": {
            "server_monitor": "grok-max (highest Grok)",
            "others": "Qwen (fast/quality) or DeepSeek (reasoning) via RunPod",
            "orchestrator": "Staff Admin Orchestrator handles day-to-day admin issues",
        },
    }


def list_staff_ops_team(db: Session, user_id: int) -> list[models.Agent]:
    return (
        db.query(models.Agent)
        .filter(
            models.Agent.user_id == user_id,
            models.Agent.template_type.in_(list(STAFF_TEMPLATE_TYPES)),
        )
        .order_by(models.Agent.id)
        .all()
    )


def staff_ops_brief(db: Session, user: models.User) -> dict[str, Any]:
    """Snapshot for Admin UI: team + fleet probe summary."""
    agents = list_staff_ops_team(db, user.id)
    from .runpod_fleet import probe_ollama, get_model_map, get_connection
    # probe is async — caller may pass precomputed; here sync-safe placeholder
    return {
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "template_type": a.template_type,
                "model": a.model,
                "hierarchy_role": a.hierarchy_role,
                "parent_id": a.parent_id,
                "status": a.status,
                "personality": (a.personality or "")[:200],
            }
            for a in agents
        ],
        "model_map": get_model_map(),
        "connection": get_connection(include_secrets=False),
        "spec": [
            {
                "name": s["name"],
                "template_type": s["template_type"],
                "model": s["model"],
                "role": s["hierarchy_role"],
            }
            for s in STAFF_TEAM_SPEC
        ],
    }
