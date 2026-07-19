"""
Core Team — the default standing team every user gets.

Not the full ~20 professional seed; a compact always-on unit:
  Orchestrator + key leads + My Human.

Marked in agent.config.core_team = true so the UI can pin them.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .agent_hierarchy import ensure_main_orchestrator, ensure_master_designer, find_orchestrator
from .agent_scaffold import apply_create_defaults, repair_agent
from .agent_serialize import agent_out
from .human_service import ensure_my_human
from .plans import plan_limits
from .seed_templates import SEED_TEMPLATES

# Priority Core Team — 10 agents every user can run (fits trial 12-agent plan)
CORE_TEAM_SEEDS: list[tuple[str, str, str]] = [
    # (display_name_or_seed, template_type, hierarchy_role)
    ("Main AI Orchestrator", "orchestrator", "orchestrator"),
    ("Lead Agent / Team Lead", "lead", "lead"),
    ("Sales Lead Agent", "sales", "lead"),
    ("Operations Lead", "ops", "lead"),
    ("Customer Support Agent", "support", "member"),
    ("Sales Outreach Agent", "sales", "member"),
    ("Content Writer Agent", "content", "member"),
    ("Full-Stack Developer", "coding", "member"),
    ("Appointment Booker", "booking", "member"),
    ("Master Designer", "designer", "specialist"),
]


def _mark_core(agent: models.Agent) -> None:
    try:
        cfg = json.loads(agent.config or "{}")
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:
        cfg = {}
    if cfg.get("core_team") is True:
        return
    cfg["core_team"] = True
    agent.config = json.dumps(cfg)


def _find_by_name_or_type(db: Session, user_id: int, name: str, ttype: str) -> models.Agent | None:
    a = (
        db.query(models.Agent)
        .filter_by(user_id=user_id, name=name)
        .order_by(models.Agent.id)
        .first()
    )
    if a:
        return a
    # Fallback: template type match for core roles
    return (
        db.query(models.Agent)
        .filter(
            models.Agent.user_id == user_id,
            models.Agent.template_type == ttype,
        )
        .order_by(models.Agent.id)
        .first()
    )


def _create_core_member(
    db: Session,
    user: models.User,
    name: str,
    ttype: str,
    hrole: str,
    parent_id: int | None,
) -> models.Agent:
    tpl = next((t for t in SEED_TEMPLATES if t[0] == name), None)
    personality = ""
    if tpl:
        personality = (tpl[2] or "")[:220]
        ttype = tpl[1] or ttype
    if not personality:
        personality = f"Core team {ttype} agent. Professional, proactive, keeps the owner informed."
    defaults = apply_create_defaults(None, ttype, hrole)
    a = models.Agent(
        user_id=user.id,
        name=name,
        template_type=ttype,
        personality=personality,
        model=defaults["model"],
        idle_mode="never_idle",
        config=json.dumps({"autonomy": "full", "core_team": True}),
        hierarchy_role=hrole,
        is_lead=hrole in ("orchestrator", "lead"),
        parent_id=None if hrole == "orchestrator" else parent_id,
        permission_level=defaults["permission_level"],
        status="active",
        escalate_when="on_failure",
        escalate_to="parent" if hrole != "orchestrator" else "owner",
    )
    db.add(a)
    db.flush()
    repair_agent(db, a, force_never_idle=True, expand_skills=True)
    return a


def ensure_core_team(db: Session, user: models.User) -> dict[str, Any]:
    """
    Explicitly hire the standing Core Team (leads + specialists).

    Not called on register — new accounts only get Main AI Orchestrator.
    Trigger via POST /agents/core-team/ensure or product UI.
    Idempotent — re-marks existing agents as core_team.
    """
    max_agents = int(plan_limits(user.plan or "none").get("agents") or 0)
    if user.role == "admin":
        max_agents = max(max_agents, 10_000)
    if user.role != "admin" and (not user.subscription_active or user.plan in (None, "", "none")):
        # Still allow reading empty core team; create only orchestrator if they have access elsewhere
        pass

    created: list[int] = []
    members: list[models.Agent] = []

    # Always try orchestrator first
    orch = ensure_main_orchestrator(db, user)
    _mark_core(orch)
    members.append(orch)
    orch_id = orch.id

    count = db.query(models.Agent).filter_by(user_id=user.id).count()

    for name, ttype, hrole in CORE_TEAM_SEEDS:
        if name == "Main AI Orchestrator":
            continue
        existing = _find_by_name_or_type(db, user.id, name, ttype)
        if existing:
            _mark_core(existing)
            if not existing.parent_id and existing.id != orch_id and hrole != "orchestrator":
                existing.parent_id = orch_id
            members.append(existing)
            continue
        # Plan room?
        if user.role != "admin" and max_agents and count >= max_agents:
            break
        if name == "Master Designer":
            a = ensure_master_designer(db, user)
            _mark_core(a)
            if not a.parent_id:
                a.parent_id = orch_id
            members.append(a)
            created.append(a.id)
            count = db.query(models.Agent).filter_by(user_id=user.id).count()
            continue
        a = _create_core_member(db, user, name, ttype, hrole, orch_id)
        members.append(a)
        created.append(a.id)
        count += 1

    # My Human
    human = ensure_my_human(db, user)

    db.commit()
    for m in members:
        db.refresh(m)

    # De-dupe by id while preserving order
    seen: set[int] = set()
    unique: list[models.Agent] = []
    for m in members:
        if m.id in seen:
            continue
        seen.add(m.id)
        unique.append(m)

    return {
        "ok": True,
        "created_ids": created,
        "agents": [agent_out(a, db) for a in unique],
        "human": {
            "id": human.id,
            "name": human.name,
            "email": human.email,
            "role_title": human.role_title,
            "is_my_human": True,
            "status": human.status,
        },
        "count": len(unique),
        "slots": {"used": count, "max": max_agents},
        "roster": [name for name, _, _ in CORE_TEAM_SEEDS],
    }


def get_core_team(db: Session, user: models.User) -> dict[str, Any]:
    """Return core team without creating (except My Human flag read)."""
    agents = (
        db.query(models.Agent)
        .filter_by(user_id=user.id)
        .order_by(models.Agent.id.asc())
        .all()
    )
    core: list[models.Agent] = []
    for a in agents:
        try:
            cfg = json.loads(a.config or "{}")
        except Exception:
            cfg = {}
        is_core = bool(cfg.get("core_team"))
        if not is_core:
            # Also treat canonical orchestrator / designer / named leads as core
            if (a.hierarchy_role or "") == "orchestrator" or (a.template_type or "") in (
                "orchestrator", "designer",
            ):
                is_core = True
            elif (a.name or "") in {n for n, _, _ in CORE_TEAM_SEEDS}:
                is_core = True
        if is_core:
            core.append(a)

    # Sort: orchestrator first, then leads, then rest
    def sort_key(a: models.Agent):
        role = (a.hierarchy_role or "member")
        order = {"orchestrator": 0, "lead": 1, "specialist": 2, "member": 3}.get(role, 4)
        return (order, a.id)

    core.sort(key=sort_key)

    human = (
        db.query(models.Human)
        .filter_by(owner_user_id=user.id, is_my_human=True)
        .first()
    )

    return {
        "ok": True,
        "agents": [agent_out(a, db) for a in core],
        "human": (
            {
                "id": human.id,
                "name": human.name,
                "email": human.email,
                "role_title": human.role_title,
                "is_my_human": True,
                "status": human.status,
            }
            if human
            else None
        ),
        "count": len(core),
        "roster": [name for name, _, _ in CORE_TEAM_SEEDS],
        "empty": len(core) == 0,
    }
