"""
Agent scaffolding — clear split between REPAIR (writes) and RESOLVE (read-only).

REPAIR (mutations): create agent, seed team, spawn, POST /ops/scaffold only.
RESOLVE (no DB writes): chat, task run, autonomy tick runtime decisions.

This avoids rewriting every agent on every request (the previous failure mode).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .agent_roles import find_orchestrator, is_orchestrator, normalize_role
from .agent_skills import DEFAULT_ENABLED, SKILL_CATALOG, set_enabled_skills, PREMIUM_SKILL_IDS
from .skills_policy import default_enabled_for_role as _policy_default_enabled
from .permissions import can_execute, normalize_permission

# One map: legacy / provider ids → neutral managed chat ids
# Staff Server Monitor uses grok-max (highest Grok via xAI). Everyone else → RunPod Qwen/DeepSeek tiers.
_MODEL_MAP = {
    "vps-fast": "fast",
    "vps-quality": "quality",
    "vps-qwen-fast": "fast",
    "vps-qwen-7b": "fast",
    "vps-qwen-14b": "quality",
    "vps-qwen-32b": "large",
    "vps-qwen-coder": "quality",
    "vps-qwen-coder-7b": "fast",
    "vps-qwen-coder-14b": "quality",
    "vps-qwen-coder-32b": "large",
    "vps-qwen-large": "large",
    "vps-qwen-72b": "large",
    "deepseek": "reasoning",
    "deepseek-r1": "reasoning",
    "qwen": "quality",
    # Highest Grok for staff server monitor only
    "grok": "grok-max",
    "grok-max": "grok-max",
    "grok-fast": "grok-max",
    "grok-mini": "grok-max",
    "grok-3": "grok-max",
    "grok-4": "grok-max",
    "grok-4.3": "grok-max",
    "grok-4.5": "grok-max",
    "claude-haiku": "fast",
    "claude-sonnet": "quality",
    "claude-opus": "reasoning",
}

_NEUTRAL = frozenset({
    "fast", "quality", "reasoning", "large", "small", "medium",
    "image", "video", "grok-max",
})


def map_model(model: str | None) -> str:
    m = (model or "quality").strip().lower()
    if m in _MODEL_MAP:
        return _MODEL_MAP[m]
    if m in _NEUTRAL:
        return m
    if m.startswith("grok"):
        return "grok-max"
    if m.startswith(("vps", "qwen", "ollama", "deepseek")):
        return "quality" if "deepseek" not in m else "reasoning"
    return m or "quality"


def is_grok_model(model: str | None) -> bool:
    m = map_model(model)
    return m == "grok-max" or (m or "").startswith("grok")


def role_default_permission(role: str) -> str:
    if role == "orchestrator":
        return "admin"
    if role == "lead":
        return "lead"
    return "operator"


def role_allowed_skill_ids(role: str, agent: models.Agent | None = None) -> list[str]:
    """Skills this role may use (catalog filter)."""
    out = []
    for s in SKILL_CATALOG:
        roles = s.get("roles") or []
        if role in roles or role == "orchestrator" or (agent and is_orchestrator(agent)):
            out.append(s["id"])
    return out or list(DEFAULT_ENABLED)


def default_enabled_skills_for_role(role: str, agent: models.Agent | None = None) -> list[str]:
    """
    Role packs (skills_policy):
      member/specialist — free toolkit, no premium, no destructive meta
      lead — + premium + spawn (not delete)
      orchestrator — full
    """
    r = (role or "member").lower()
    if agent and is_orchestrator(agent):
        r = "orchestrator"
    return _policy_default_enabled(r, SKILL_CATALOG)


@dataclass(frozen=True)
class RuntimeAgent:
    """Read-only view for chat/task/LLM — never mutates DB."""
    id: int
    name: str
    model: str
    mode_hint: str
    can_execute: bool
    idle_mode: str
    permission_level: str
    hierarchy_role: str
    status: str
    company_id: int | None
    project_id: int | None


def resolve_runtime(agent: models.Agent) -> RuntimeAgent:
    """Hot-path: pure read. No DB writes."""
    role = normalize_role(agent)
    perm = normalize_permission(getattr(agent, "permission_level", None))
    return RuntimeAgent(
        id=agent.id,
        name=agent.name or "Agent",
        model=map_model(agent.model),
        mode_hint=(agent.template_type or "general"),
        can_execute=can_execute(perm) and (agent.status or "active") == "active",
        idle_mode=(agent.idle_mode or "allow_idle"),
        permission_level=perm,
        hierarchy_role=role,
        status=agent.status or "active",
        company_id=agent.company_id,
        project_id=agent.project_id,
    )


def repair_agent(
    db: Session,
    agent: models.Agent,
    *,
    force_never_idle: bool = True,
    expand_skills: bool = True,
    respect_pause: bool = True,
) -> models.Agent:
    """
    Mutating repair — call only from create / seed / spawn / POST /ops/scaffold.

    Does NOT run on every chat message or autonomy tick.
    """
    role = normalize_role(agent)
    agent.hierarchy_role = role
    if role == "orchestrator":
        agent.is_lead = True
        agent.parent_id = None
        if not (agent.template_type or "").strip():
            agent.template_type = "orchestrator"
    elif role == "lead":
        agent.is_lead = True

    perm = normalize_permission(getattr(agent, "permission_level", None))
    if perm == "viewer":
        perm = role_default_permission(role)
    if role == "orchestrator":
        perm = "admin"
    elif role == "lead" and perm == "operator":
        perm = "lead"
    agent.permission_level = perm

    if force_never_idle:
        agent.idle_mode = "never_idle"

    status = (agent.status or "").lower()
    if status in ("", "draft") or agent.status is None:
        agent.status = "active"
    # respect_pause: never flip paused → active here

    agent.model = map_model(agent.model)

    if not (getattr(agent, "escalate_when", None) or "").strip():
        agent.escalate_when = "on_failure"
    if not (getattr(agent, "escalate_to", None) or "").strip():
        agent.escalate_to = "parent" if agent.parent_id else "orchestrator"

    if agent.parent_id is None and role != "orchestrator":
        orch = find_orchestrator(db, agent.user_id)
        if orch and orch.id != agent.id:
            agent.parent_id = orch.id

    if expand_skills and agent.id:
        wanted = default_enabled_skills_for_role(role, agent)
        row = db.query(models.AgentSkillState).filter_by(agent_id=agent.id).first()
        if not row:
            set_enabled_skills(db, agent, wanted)
        else:
            try:
                existing = set(json.loads(row.enabled_json or "[]"))
            except Exception:
                existing = set()
            # Expand with new free skills only; never force premium onto members
            free_wanted = set(wanted)
            if not existing or free_wanted - existing:
                merged = sorted(existing | free_wanted)
                set_enabled_skills(db, agent, merged)

    return agent


# Back-compat aliases used by older call sites during transition
def scaffold_agent(db: Session, agent: models.Agent, *, full_skills: bool = True) -> models.Agent:
    """Deprecated name → repair_agent (mutating). Prefer repair_agent explicitly."""
    return repair_agent(db, agent, force_never_idle=True, expand_skills=full_skills)


def scaffold_workspace(db: Session, user_id: int) -> dict[str, Any]:
    """Explicit full-team repair. Only /ops/scaffold and seed should call this."""
    return repair_workspace(db, user_id)


def repair_workspace(db: Session, user_id: int) -> dict[str, Any]:
    from .agent_hierarchy import ensure_main_orchestrator

    user = db.get(models.User, user_id)
    if not user:
        return {"ok": False, "error": "user not found"}

    orch = ensure_main_orchestrator(db, user)
    repair_agent(db, orch, force_never_idle=True, expand_skills=True)

    agents = db.query(models.Agent).filter_by(user_id=user_id).all()
    fixed = 0
    for a in agents:
        before = (a.model, a.idle_mode, a.permission_level, a.parent_id, a.status)
        repair_agent(db, a, force_never_idle=True, expand_skills=True, respect_pause=True)
        after = (a.model, a.idle_mode, a.permission_level, a.parent_id, a.status)
        if before != after:
            fixed += 1

    settings = db.query(models.WorkspaceSettings).filter_by(user_id=user_id).first()
    if not settings:
        settings = models.WorkspaceSettings(
            user_id=user_id,
            autonomy_enabled=True,
            autonomy_interval_sec=300,
            task_stuck_minutes=30,
        )
        db.add(settings)
    else:
        if settings.autonomy_enabled is None:
            settings.autonomy_enabled = True
        # Floor 5 min — never_idle fleets must not thrash RunPod
        if not settings.autonomy_interval_sec or settings.autonomy_interval_sec < 120:
            settings.autonomy_interval_sec = max(300, int(settings.autonomy_interval_sec or 300))

    db.commit()
    return {
        "ok": True,
        "agents": len(agents),
        "updated": fixed,
        "orchestrator_id": orch.id,
        "autonomy_enabled": bool(settings.autonomy_enabled),
    }


def apply_create_defaults(
    data_model: str | None,
    template_type: str | None,
    hierarchy_role: str | None,
) -> dict:
    role = (hierarchy_role or "").lower()
    tpl = (template_type or "").lower()
    if tpl == "orchestrator" or role == "orchestrator":
        return {
            "model": map_model(data_model or "quality"),
            "idle_mode": "never_idle",
            "permission_level": "admin",
            "status": "active",
        }
    if tpl == "lead" or role == "lead":
        return {
            "model": map_model(data_model or "quality"),
            "idle_mode": "never_idle",
            "permission_level": "lead",
            "status": "active",
        }
    return {
        "model": map_model(data_model or "fast"),
        "idle_mode": "never_idle",
        "permission_level": "operator",
        "status": "active",
    }
