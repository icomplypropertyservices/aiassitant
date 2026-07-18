"""Single place to assemble agent system prompts (chat, tasks, websockets)."""
from __future__ import annotations

import json
from sqlalchemy.orm import Session

from . import models
from .training_context import knowledge_context_for_agent
from .agent_roles import is_orchestrator, normalize_role


def team_context(agent: models.Agent, db: Session) -> str:
    """Hierarchy text for lead/member prompts."""
    parts = []
    role = normalize_role(agent)
    tpl = (getattr(agent, "template_type", None) or "").lower()
    if is_orchestrator(agent):
        parts.append(
            "Hierarchy role: MAIN AI ORCHESTRATOR (top of the organisation). "
            "You coordinate all companies, projects, leads, and specialist agents. "
            "Delegate; do not do specialist work yourself unless asked."
        )
    elif tpl == "staff_orchestrator":
        parts.append(
            "Hierarchy role: STAFF ADMIN ORCHESTRATOR. "
            "You own day-to-day platform admin issues: fleet health, billing, security, user blockers. "
            "Delegate to Server Monitor (infra), Fleet Ops (models), Billing Ops, Security Ops. "
            "Report clear actions to the human staff admin."
        )
    elif tpl == "server_monitor":
        parts.append(
            "Hierarchy role: SERVER MONITOR SPECIALIST (highest Grok). "
            "You exclusively watch RunPod/Ollama/proxy health and recommend concrete remediations."
        )
    else:
        parts.append(f"Hierarchy role: {role}.")
    if agent.company_id or agent.project_id:
        co = db.get(models.Company, agent.company_id) if agent.company_id else None
        pr = db.get(models.Project, agent.project_id) if agent.project_id else None
        bits = []
        if co:
            bits.append(f"company={co.name}")
        if pr:
            bits.append(f"project={pr.name}")
        if bits:
            parts.append("Assigned scope: " + ", ".join(bits) + ".")
    if agent.parent_id:
        lead = db.get(models.Agent, agent.parent_id)
        if lead:
            parts.append(f"You report to lead agent: {lead.name} (id={lead.id}).")
    reports = db.query(models.Agent).filter_by(parent_id=agent.id).all()
    if reports:
        names = ", ".join(f"{r.name} [{r.template_type}/{r.status}]" for r in reports)
        parts.append(f"You lead this team ({len(reports)}): {names}.")
        parts.append(
            "As lead you may recommend delegation, prioritise work, and summarise team status."
        )
    return " ".join(parts)


def build_agent_system_prompt(
    db: Session,
    agent: models.Agent,
    *,
    include_config: bool = True,
    extra: str = "",
) -> str:
    """Canonical system/context block for any agent LLM call."""
    team = team_context(agent, db)
    train = knowledge_context_for_agent(db, agent.id)
    cfg = ""
    if include_config:
        raw = agent.config or "{}"
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            cfg = f" Config: {json.dumps(parsed) if not isinstance(parsed, str) else parsed}."
        except Exception:
            cfg = f" Config: {raw}."
    from .agent_skills import skills_prompt_block

    skills = skills_prompt_block(agent, db)
    perm = getattr(agent, "permission_level", None) or "operator"
    esc_when = getattr(agent, "escalate_when", None) or "on_failure"
    esc_to = getattr(agent, "escalate_to", None) or "parent"
    esc_reason = (getattr(agent, "escalate_reason", None) or "").strip()
    policy = (
        f" Permission level: {perm}. "
        f"Escalate when: {esc_when}"
        + (f" ({esc_reason})" if esc_reason else "")
        + f". Escalate to: {esc_to}."
    )
    autonomy = (
        " AUTONOMY: You run 100% autonomously. Do not wait for the human unless truly blocked. "
        "Use skills (```skill blocks) to take real action: create_task, message_agent, spawn_agent, "
        "list_customers, draft_email, send_email, generate_content, generate_image, save_memory, etc. "
        "Escalate only on failure or missing credentials. Prefer action over advice."
    )
    base = (
        f"You are {agent.name}, an AI business agent. "
        f"Personality: {agent.personality}. "
        f"Template type: {agent.template_type}.{cfg} {team}{policy}{autonomy}\n{train}"
    )
    if skills:
        base = f"{base}\n\n{skills}"
    if extra:
        return f"{base}\n{extra}".strip()
    return base.strip()


def build_task_prompt(
    db: Session,
    agent: models.Agent,
    description: str,
    *,
    business_context: dict | None = None,
) -> str:
    system = build_agent_system_prompt(db, agent)
    ctx = json.dumps(business_context or {})
    return (
        f"{system}\nBusiness context: {ctx}\n"
        f"Complete this task and produce the final deliverable text "
        f"(e.g. the email/message itself), no preamble:\n\n{description}"
    )
