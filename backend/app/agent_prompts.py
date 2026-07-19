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
            "You run on Grok 4.3. You coordinate all companies, projects, leads, and specialist agents. "
            "You HIRE talent with hire_agent / spawn_agent / spawn_team when the team is short. "
            "You CREATE companies/projects (create_company, create_project) and MAKE work happen "
            "(create_task, create_workflow, execute_goal). "
            "You SORT LATE PROJECTS with sort_late_projects (re-queue stuck work, recovery tasks, notify human). "
            "Delegate specialist execution; do not do deep specialist work yourself unless blocked."
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
            if not isinstance(parsed, dict):
                parsed = {}
            # Prefer explicit custom_fields block for the model
            custom = parsed.get("custom_fields") if isinstance(parsed.get("custom_fields"), dict) else {}
            if not custom:
                try:
                    from .skills.agent_actions import get_custom_fields
                    custom = get_custom_fields(agent)
                except Exception:
                    custom = {}
            parts = []
            if custom:
                parts.append(f"Custom fields: {json.dumps(custom, ensure_ascii=False)}")
            # Remaining config (without dumping huge blobs)
            other = {k: v for k, v in parsed.items() if k != "custom_fields"}
            if other:
                parts.append(f"Config: {json.dumps(other, ensure_ascii=False)[:800]}")
            if parts:
                cfg = " " + " ".join(parts) + "."
            elif parsed:
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
        "list_activity (workspace logs — you may read ALL team activity logs) before duplicating work; "
        "claim_task to assign yourself open work with done-when targets; "
        "create_task for yourself or teammates (always success_criteria / done_when / target "
        "AND checklist of items the lead will verify); "
        "LEADS: when giving work to subagents use create_workflow with steps "
        "[{title, description, agent_id|role, done_when, checklist}] so each agent knows "
        "exactly what will be checked. Save reusable recipes with create_pattern; run with run_pattern. "
        "After a subagent completes, review_task: action=approve or reject with feedback "
        "(what's wrong) and checks_failed so the agent is messaged and re-runs. "
        "Never leave wrong work as completed — reject with a clear WHAT'S WRONG note. "
        "set_task_status in_progress when you start; respond_to_task or complete_task when finished "
        "with evidence matching the target. "
        "MEETINGS: open_meeting, invite_to_meeting (agent_ids), post_to_meeting, run_meeting_round, "
        "list_meetings, extract_meeting_tasks. Always invite the agents who need to speak. "
        "When you create a task for yourself, agent_id=self and run_now true. "
        "Orchestrators: board questions → list_tasks/search_tasks → claim/create/complete. "
        "Never leave work as vague advice — always a board row with measurable done-when, then complete it. "
        "Run the sales board with create_deal, move_deal, win_deal, lose_deal, update_pipeline. "
        "MULTI-AGENT SALES PIPELINE: when asked for N sales targets → CRM → outreach, "
        "use execute_goal (or the platform auto-chain). Typical handoff: "
        "(1) sales agent generates N targets, (2) sales agent create_customer + create_deal for each, "
        "(3) outreach agent draft_email/send_email + calls + log_customer_activity, "
        "(4) sales agent move_deal / pipeline_summary, (5) status_update the human. "
        "Never stop after listing targets in chat — always persist CRM rows with skills. "
        "You may COMMENT / note on records with the comment skill (target_type + target_id + body) "
        "or post_to_meeting / log_customer_activity / message_agent / Human messages. "
        "Always inform the human owner of progress: use notify_human or status_update so they get "
        "a short SMS + email shortcut (active human with email+phone; SMTP+Twilio required). "
        "Also report in chat when present; save_memory / create_task / message_agent as needed. "
        "You may CREATE new skills with create_skill (name, description, instructions, args) and "
        "optionally list them for sale on AgentBay with publish_skill_to_bay or list_on_bay=true. "
        "Use skills (```skill blocks) to take real action — never only describe them. "
        "Correct format: ```skill then {\"skill\":\"create_task\",\"args\":{...}} then ```. "
        "Also accepted: skill id on its own line then args JSON. "
        "Always pair actions with a clear human-facing reply of what happened. "
        "Key skills: hire_agent, spawn_agent, spawn_team, sort_late_projects, list_projects, "
        "create_project, create_company, execute_goal, create_task, create_workflow, create_pattern, "
        "run_pattern, review_task, claim_task, list_tasks, complete_task, "
        "list_activity, invite_to_meeting, open_meeting, message_agent, save_memory, "
        "list_customers, create_customer, list_products, create_product, update_product, "
        "set_product_offer, comment, draft_email, status_update, "
        "list_agent_custom_fields, set_agent_custom_field, get_agent_custom_field. "
        "Use custom fields for free-form agent metadata (territory, quota, niche notes). "
        "After every skill, explain the result in plain language (names, ids, offers, prices). "
        "For multi-step human goals use execute_goal or create_task with parent_task_id. "
        "AFTER EVERY substantive conversation: leave a workflow (create_task / execute_goal for yourself) "
        "so work continues without waiting for the human. The platform also auto-queues a post-chat "
        "workflow for you — when you pick it up, complete real deliverables and complete_task. "
        "You may respond and act on your own between human messages. "
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
    # Inject recent team activity so the agent starts oriented (read-all-logs)
    recent_logs_txt = ""
    try:
        team_ids = [
            a.id for a in db.query(models.Agent).filter_by(user_id=agent.user_id).limit(60).all()
        ]
        if team_ids:
            names = {
                a.id: a.name
                for a in db.query(models.Agent).filter(models.Agent.id.in_(team_ids)).all()
            }
            rows = (
                db.query(models.ActivityLog)
                .filter(models.ActivityLog.agent_id.in_(team_ids))
                .order_by(models.ActivityLog.id.desc())
                .limit(10)
                .all()
            )
            if rows:
                lines = []
                for r in rows:
                    who = names.get(r.agent_id) or f"agent:{r.agent_id}"
                    lines.append(f"- [{r.type}] {who}: {(r.message or '')[:140]}")
                recent_logs_txt = "RECENT TEAM ACTIVITY (you can read all logs via list_activity):\n" + "\n".join(lines)
    except Exception:
        recent_logs_txt = ""

    work_block = f"""
=== ACTIVE TASK (you must finish this) ===
task_id: {tid}
title: {title}
priority: {pri}
labels: {labs or "—"}

BRIEF:
{body}

{recent_logs_txt}

=== STANDARD WORKFLOW (follow in order — this is how you work) ===
STEP 0 — ORIENT (skills):
  - list_activity (optional mine=true or workspace) — see what already happened
  - list_tasks mine=true / get_task if needed
  - read_workspace if scope is unclear

STEP 1 — PLAN:
  - Restate DONE WHEN / TARGET / CHECKLIST in one line each
  - If you are a LEAD giving work to subagents: create_workflow (or create_task per agent)
    with checklist items you will verify — never assign vague tasks
  - If multi-part for yourself: create_task children with success_criteria + checklist
  - Reuse team recipes via list_patterns / run_pattern or create_pattern after a good run
  - If discussion needed: open_meeting + invite_to_meeting, or post_to_meeting

STEP 2 — EXECUTE (do real work now — stay busy until finished):
  - You remain IN PROGRESS until complete_task (or failed). Do not stop after a plan-only reply.
  - Drafts, CRM, research, generate_content, deals, emails (draft), meeting rounds, etc.
  - Sales/CRM steps: emit create_customer / create_deal skill blocks (not just a list in prose).
  - Persist data with skills: save_memory, create_customer, create_deal, set_agent_custom_field,
    create_product, log_customer_activity, update_task — prose does NOT save to the database.
  - Outreach steps: draft_email, send_email, log_customer_activity; then move_deal.
  - Use update_task to leave progress notes mid-flight (status stays in_progress).
  - If description contains WHAT'S WRONG / lead feedback: fix those issues first

STEP 3 — PROVE & CLOSE{success_hint}:
  - Deliverable must satisfy DONE WHEN / TARGET and every CHECKLIST item
  - In complete_task result, briefly tick each checklist item
  - LEADS reviewing others: review_task action=approve OR reject with feedback + checks_failed
  - REQUIRED finish skill (when YOU own the work) — task stays open until you call this:

```skill
complete_task
{{"task_id": {tid}, "result": "<1-5 sentences: what you delivered and how it meets the target>"}}
```

If blocked after a real attempt:

```skill
set_task_status
{{"task_id": {tid}, "status": "failed"}}
```
plus update_task with the blocker note.

No empty "I'll do it later". Use skills to SAVE data, then complete_task.
Material mid-work → status_update / notify_human.
"""
    return f"{system}\nBusiness context: {ctx}\n{work_block}"
