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
            "As lead you may recommend delegation, prioritise work, summarise team status, "
            "and keep the human owner informed of team progress."
        )
    return " ".join(parts)


# Appended on live human chat (REST + WS) so "you" always means the person typing.
CHAT_ADDRESS_RULE = (
    "CHAT ADDRESSING: In this conversation you speak directly to the human owner who wrote "
    "the user messages. Address them as \"you\". Speak as yourself in first person (\"I\" / \"me\"). "
    "Never talk about them in third person (\"the user\", \"the human\", \"they\") as if someone else "
    "is listening, and never write as if you are replying to a different person than the one chatting. "
    "If they ask you to draft a message for a third party, label it clearly (e.g. \"Draft for customer:\") "
    "and use that recipient's perspective only inside the draft — not for this chat."
)

# How the agent should sound and when to surface questions under the reply.
HUMAN_VOICE_RULE = (
    "HUMAN VOICE (required for every chat reply):\n"
    "- Talk like a capable colleague in plain spoken English — warm, clear, natural.\n"
    "- Do NOT sound like a log file, API, or developer console. Avoid dumping raw JSON, "
    "YAML, stack traces, SQL, shell commands, long code fences, bullet walls of flags, "
    "or \"strips\" of system status unless they explicitly asked for technical output.\n"
    "- Prefer short paragraphs and everyday words. Use contractions when natural "
    "(I'm, we'll, let's). Lead with the answer, then a little context if needed.\n"
    "- Never invent fake UI chrome like [SYSTEM], >>>, or markdown tables of internal IDs.\n"
    "- Skill actions still work, but keep skill blocks minimal and never replace your "
    "spoken reply with only a skill block.\n"
    "\n"
    "QUESTIONS FOR THE HUMAN (when you need input):\n"
    "- If you need a decision, missing detail, or confirmation, ask clearly in your prose, "
    "AND also emit a questions block so the UI can show clickable boxes under your reply:\n"
    "```questions\n"
    "- Short question one?\n"
    "- Short question two?\n"
    "```\n"
    "- Use 1–4 short, concrete questions (one line each, end with ?). No nested lists.\n"
    "- If you do not need anything from them, omit the questions block entirely.\n"
    "- Do not put the questions block before your human reply — always write the natural "
    "answer first, then the optional questions block."
)


def chat_voice_extra() -> str:
    """Extra system lines for live human chat only."""
    return f"{CHAT_ADDRESS_RULE}\n\n{HUMAN_VOICE_RULE}"


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
        "You may READ the whole workspace: training library, CRM pipelines, tasks, meetings, humans, "
        "deals, team (use read_workspace, list_pipelines, get_pipeline, pipeline_summary, list_deals, "
        "list_tasks, search_tasks, get_task, list_customers, list_meetings, list_humans, "
        "search_knowledge, get_customer). "
        "TASK BOARD — you DO the work (not just advise). Use skills without asking permission: "
        "list_tasks / search_tasks (mine=true for your queue); get_task for detail; "
        "claim_task to assign yourself open work and queue it with exact done-when targets; "
        "create_task to add work for yourself or teammates (include success_criteria / done_when / target); "
        "set_task_status in_progress when you start; respond_to_task or complete_task when finished "
        "with a concrete result that matches the target; update_task for progress notes. "
        "When you create a task for yourself, set agent_id to your id and run_now true so it executes. "
        "Orchestrators: open work / task id / 'board' → list_tasks or search_tasks first, then "
        "claim_task / create_task / complete_task. Never leave work as vague advice — always a board row "
        "with a measurable done-when, then complete it. "
        "Run the sales board with create_deal, move_deal, win_deal, lose_deal, update_pipeline. "
        "You may COMMENT / note on records with the comment skill (target_type + target_id + body) "
        "or post_to_meeting / log_customer_activity / message_agent / Human messages. "
        "Always inform the human owner of progress: use notify_human or status_update so they get "
        "a short SMS + email shortcut (active human with email+phone; SMTP+Twilio required). "
        "Also report in chat when present; save_memory / create_task / message_agent as needed. "
        "You may CREATE new skills with create_skill (name, description, instructions, args) and "
        "optionally list them for sale on AgentBay with publish_skill_to_bay or list_on_bay=true. "
        "Use skills (```skill blocks) to take real action: execute_goal, create_task, list_tasks, "
        "search_tasks, get_task, respond_to_task, complete_task, update_task, set_task_status, "
        "message_agent, spawn_agent, announce_plan, status_update, list_customers, comment, "
        "draft_email, send_email, save_memory, etc. "
        "For multi-step human goals always use execute_goal or create_task with parent_task_id. "
        "Escalate only on failure or missing credentials. Prefer action over advice."
    )
    # System "You" = this agent. Human chat partners are clarified via CHAT_ADDRESS_RULE on chat routes.
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
    task_id: int | None = None,
    task_title: str | None = None,
    priority: str | None = None,
    labels: str | None = None,
) -> str:
    """Prompt for autonomy / task_runner — forces concrete work + complete_task."""
    system = build_agent_system_prompt(db, agent)
    ctx = json.dumps(business_context or {})
    tid = task_id if task_id is not None else "?"
    title = (task_title or "").strip() or "Work item"
    pri = (priority or "medium").strip()
    labs = (labels or "").strip()
    body = (description or "").strip()
    # Extract success lines if already in description
    success_hint = ""
    for marker in ("DONE WHEN:", "SUCCESS:", "TARGET:", "ACCEPTANCE:"):
        if marker in body.upper():
            success_hint = " (match the DONE WHEN / TARGET lines in the brief exactly)"
            break
    work_block = f"""
=== ACTIVE TASK (you must finish this) ===
task_id: {tid}
title: {title}
priority: {pri}
labels: {labs or "—"}

BRIEF:
{body}

MANDATORY WORK ORDER:
1) Do the real work now (draft, research, CRM, create child tasks, message agents, etc.).
2) Hit the success criteria / DONE WHEN / TARGET in the brief{success_hint}.
3) When finished, emit this skill (required — board stays open without it):

```skill
complete_task
{{"task_id": {tid}, "result": "<1-5 sentences: what you delivered and how it meets the target>"}}
```

If blocked, use:
```skill
set_task_status
{{"task_id": {tid}, "status": "failed"}}
```
and put the blocker in a result note via update_task.

Produce the deliverable in your reply (email body, plan, analysis, etc.) — no empty "I'll do it later".
If mid-work is material, status_update / notify_human so the owner stays informed.
"""
    return f"{system}\nBusiness context: {ctx}\n{work_block}"
