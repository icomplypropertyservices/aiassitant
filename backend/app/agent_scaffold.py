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
from .agent_roles import find_orchestrator, is_lead_agent, is_orchestrator, normalize_role
from .agent_skills import DEFAULT_ENABLED, SKILL_CATALOG, set_enabled_skills, PREMIUM_SKILL_IDS
from .skills_policy import (
    default_enabled_for_role as _policy_default_enabled,
    role_matches_skill,
    skills_for_template,
)
from .permissions import can_execute, normalize_permission

# One map: legacy / provider ids → neutral managed chat ids
# Main orchestrator uses grok-4.3; staff Server Monitor uses grok-max (top Grok).
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
    # Grok family — keep 4.3 distinct for Main Orchestrator (do not collapse to max/4.5)
    "grok": "grok-4.3",
    "grok-max": "grok-max",
    "grok-fast": "fast",
    "grok-mini": "fast",
    "grok-3": "grok-4.3",
    "grok-4": "grok-4.3",
    "grok-4.3": "grok-4.3",
    "grok-4.5": "grok-max",
    "claude-haiku": "fast",
    "claude-sonnet": "quality",
    "claude-opus": "reasoning",
}

_NEUTRAL = frozenset({
    "fast", "quality", "reasoning", "large", "small", "medium",
    "image", "video", "grok-max", "grok-4.3", "grok-4.5",
})

# Main AI Orchestrator always runs on Grok 4.3
ORCHESTRATOR_MODEL = "grok-4.3"


def map_model(model: str | None) -> str:
    m = (model or "quality").strip().lower()
    if m in _MODEL_MAP:
        return _MODEL_MAP[m]
    if m in _NEUTRAL:
        return m
    if "4.3" in m:
        return "grok-4.3"
    if m.startswith("grok"):
        return "grok-max"
    if m.startswith(("vps", "qwen", "ollama", "deepseek")):
        return "quality" if "deepseek" not in m else "reasoning"
    return m or "quality"


# Models too weak for multi-skill business work (CRM, outreach, goal chains)
_WEAK_MODELS = frozenset({"fast", "small", "medium"})

# Template → recommended neutral model (agents that complete real work need quality+)
_TEMPLATE_MODEL = {
    "orchestrator": ORCHESTRATOR_MODEL,
    "staff_orchestrator": "quality",
    "lead": "quality",
    "sales": "quality",
    "outreach": "quality",
    "lead_gen": "quality",
    "crm": "quality",
    "booking": "quality",
    "support": "quality",
    "ops": "quality",
    "content": "quality",
    "marketing": "quality",
    "seo": "quality",
    "social": "quality",
    "coding": "quality",
    "developer": "quality",
    "engineer": "quality",
    "qa": "quality",
    "designer": "quality",
    "finance": "quality",
    "bookkeep": "quality",
    "research": "reasoning",
    "analyst": "reasoning",
    "data": "reasoning",
    "server_monitor": "grok-max",
    "fleet_ops": "quality",
    "billing_ops": "quality",
    "security_ops": "reasoning",
}


def recommended_model(
    template_type: str | None = None,
    hierarchy_role: str | None = None,
) -> str:
    """Best default model so agents can finish multi-step CRM / outreach / coding work."""
    role = (hierarchy_role or "").lower()
    tpl = (template_type or "").lower()
    if tpl == "orchestrator" or role == "orchestrator":
        return ORCHESTRATOR_MODEL
    if role == "lead" or tpl == "lead":
        return "quality"
    if tpl in _TEMPLATE_MODEL:
        return _TEMPLATE_MODEL[tpl]
    return "quality"


def is_grok_model(model: str | None) -> bool:
    m = map_model(model)
    return m in ("grok-max", "grok-4.3", "grok-4.5") or (m or "").startswith("grok")


def role_default_permission(role: str) -> str:
    if role == "orchestrator":
        return "admin"
    if role == "lead":
        return "lead"
    return "operator"


def role_allowed_skill_ids(role: str, agent: models.Agent | None = None) -> list[str]:
    """Skills this role may use (catalog filter). specialist inherits member."""
    if agent and is_orchestrator(agent):
        role = "orchestrator"
    out = []
    for s in SKILL_CATALOG:
        if role_matches_skill(role, s.get("roles")) or (agent and is_orchestrator(agent)):
            out.append(s["id"])
    return out or list(DEFAULT_ENABLED)


def default_enabled_skills_for_role(role: str, agent: models.Agent | None = None) -> list[str]:
    """
    Role packs + optional template_type domain pack (skills_policy):
      member/specialist — free toolkit + domain pack when template is set
      lead — CRM + workflows + media + meetings + integrations (+ domain)
      orchestrator — full
    When agent.template_type maps to sales/marketing/support/coding/research/crm/…
    real domain skills are layered on the complete role pack (never empty lean only).
    """
    r = (role or "member").lower()
    if agent and is_orchestrator(agent):
        r = "orchestrator"
    tpl = getattr(agent, "template_type", None) if agent else None
    # Always prefer template-aware pack when we have a template OR lead/orch role
    if tpl or r in ("orchestrator", "lead"):
        return skills_for_template(tpl, SKILL_CATALOG, role=r)
    return _policy_default_enabled(r, SKILL_CATALOG)


def ensure_agent_skills(db: Session, agent: models.Agent) -> list[str]:
    """
    Persist the full role + template skill pack onto AgentSkillState.

    - Missing / empty state → write template/role pack
      (create_task, execute_goal, message_agent, status_update, open_meeting, …)
    - Existing state → expand/merge so new core + domain skills turn ON without
      stripping skills the user already enabled
    - Always force market-leading core (CRM + workflows + tasks) via
      _CORE_ALWAYS; leads also re-attach LEAD_FLOW_SKILLS (pipeline + media)

    Call from create / spawn / ensure-orchestrator / repair (expand_skills).
    Safe no-op when agent has no id yet.
    """
    if not agent or not getattr(agent, "id", None):
        return []
    from .agent_skills import LEAD_FLOW_SKILLS, SKILL_CATALOG
    from .skills_policy import _CORE_ALWAYS, _LEAD_ALWAYS

    role = normalize_role(agent)
    catalog_ids = {s["id"] for s in SKILL_CATALOG}
    wanted = set(default_enabled_skills_for_role(role, agent))
    # Market-leading core always attached (CRM funnel, workflows, tasks, meetings)
    wanted |= _CORE_ALWAYS & catalog_ids
    if is_orchestrator(agent) or is_lead_agent(agent) or role in ("lead", "orchestrator"):
        wanted |= (LEAD_FLOW_SKILLS | _LEAD_ALWAYS) & catalog_ids
    wanted_list = list(wanted)

    row = db.query(models.AgentSkillState).filter_by(agent_id=agent.id).first()
    if not row:
        return set_enabled_skills(db, agent, wanted_list)
    try:
        raw = json.loads(row.enabled_json or "[]")
        existing = {str(x) for x in raw} if isinstance(raw, list) else set()
    except Exception:
        existing = set()
    if not existing:
        return set_enabled_skills(db, agent, wanted_list)
    missing = wanted - existing
    if missing:
        merged = sorted(existing | wanted)
        return set_enabled_skills(db, agent, merged)
    return sorted(existing)


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
        # Main orchestrator always on Grok 4.3 (hire, projects, late-work sorting)
        agent.model = ORCHESTRATOR_MODEL
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

    if role != "orchestrator":
        agent.model = map_model(agent.model)
        # Bump weak defaults so specialists can actually complete multi-skill tasks
        if agent.model in _WEAK_MODELS:
            agent.model = recommended_model(agent.template_type, role)
    else:
        agent.model = ORCHESTRATOR_MODEL

    if not (getattr(agent, "escalate_when", None) or "").strip():
        agent.escalate_when = "on_failure"
    if not (getattr(agent, "escalate_to", None) or "").strip():
        agent.escalate_to = "parent" if agent.parent_id else "orchestrator"

    if agent.parent_id is None and role != "orchestrator":
        orch = find_orchestrator(db, agent.user_id)
        if orch and orch.id != agent.id:
            agent.parent_id = orch.id

    if expand_skills and agent.id:
        # Full role pack: create_task, execute_goal, message_agent, open_meeting, …
        ensure_agent_skills(db, agent)
        ensure_open_workspace_access(db, agent)

    return agent


def ensure_open_workspace_access(db: Session, agent: models.Agent) -> None:
    """
    Agents may read training + use connected apps by default.

    Sets AgentProgram policy allow_all_files / allow_all_apps unless the owner
    already locked them off (explicit false stays false only if key present as false
    after first open grant — first repair opens; later repairs keep existing True).
    """
    if not agent or not getattr(agent, "id", None):
        return
    prog = db.query(models.AgentProgram).filter_by(agent_id=agent.id).first()
    if not prog:
        prog = models.AgentProgram(
            agent_id=agent.id,
            instructions=(
                "You can read the full training library, CRM, tasks, meetings, team, "
                "and deals for this workspace. Comment/note on records when useful. "
                "Use skills: list_tasks, search_tasks, get_task, create_task, claim_task, "
                "respond_to_task, complete_task, update_task, set_task_status, "
                "list_customers, list_meetings, list_humans, search_knowledge, "
                "comment, post_to_meeting, message_agent. "
                "Orchestrators: proactively list/search tasks and respond/complete them when needed."
            ),
            policy_json=json.dumps({
                "allow_all_files": True,
                "allow_all_apps": True,
                "max_file_chars": 16000,
            }),
        )
        db.add(prog)
        try:
            db.commit()
        except Exception:
            db.rollback()
        return
    try:
        pol = json.loads(prog.policy_json or "{}")
        if not isinstance(pol, dict):
            pol = {}
    except Exception:
        pol = {}
    changed = False
    # Open by default; only keep closed if owner explicitly set false
    if pol.get("allow_all_files") is not False and not pol.get("allow_all_files"):
        pol["allow_all_files"] = True
        changed = True
    if pol.get("allow_all_apps") is not False and not pol.get("allow_all_apps"):
        pol["allow_all_apps"] = True
        changed = True
    if not (prog.instructions or "").strip():
        prog.instructions = (
            "You can read and comment across this workspace (training, CRM, tasks, "
            "meetings, humans, deals). Prefer action via skills over asking permission."
        )
        changed = True
    if changed:
        prog.policy_json = json.dumps(pol)
        try:
            db.commit()
        except Exception:
            db.rollback()


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
    rec = recommended_model(tpl, role)
    if tpl == "orchestrator" or role == "orchestrator":
        return {
            "model": map_model(data_model or rec),
            "idle_mode": "never_idle",
            "permission_level": "admin",
            "status": "active",
        }
    if tpl == "lead" or role == "lead":
        return {
            "model": map_model(data_model or rec),
            "idle_mode": "never_idle",
            "permission_level": "lead",
            "status": "active",
        }
    # Specialists (sales, support, coding, …) default to quality — not fast —
    # so they reliably emit skill blocks and finish CRM / outreach work.
    return {
        "model": map_model(data_model or rec),
        "idle_mode": "never_idle",
        "permission_level": "operator",
        "status": "active",
    }
