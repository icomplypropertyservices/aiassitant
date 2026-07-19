"""
Agent skills: spawn agents, talk to agents, use connected apps, assign humans,
save memory, promote data into training, announce plans.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .agent_roles import is_orchestrator, normalize_role
from .integrations_service import secrets_from_row, meta_from_row, integrations_context_for_agent
from .live_ops import emit_ops
from . import channels
from .usage_billing import charge_usage, charge_event, bill_skill_execution, bill_llm_turn

def _charge_premium(db, user, skill_meta, default_cost=0.02, text: str = "", *, already_billed: bool = False):
    """Bill premium skill once. Prefer execute_skill as the single charge site.

    Fail closed: if both charge_event and charge_usage fail, re-raise so callers
    (execute_skill) treat the skill as failed and premium work does not free-run.
    """
    if already_billed:
        return 0.0
    cost = float(skill_meta.get("cost_credits") or default_cost)
    kind = skill_meta.get("meter_kind") or "premium-comm"
    try:
        charge_event(db, user, kind, text=text or skill_meta.get("id", ""), cost_override=cost)
    except Exception:
        try:
            charge_usage(db, user, kind if kind else "premium-comm", 50, 50, cost_override=cost)
        except Exception as e:
            # Both billing paths failed — do not allow premium skills to run free
            detail = getattr(e, "detail", None) or e
            raise RuntimeError(f"premium billing failed: {detail}") from e
    return cost

# ── Catalog ──────────────────────────────────────────────────────────────

SKILL_CATALOG: list[dict] = [
    {
        "id": "spawn_agent",
        "name": "Spawn agent",
        "description": "Create a new team agent under you (or as orchestrator under any lead).",
        "args": ["name", "template_type", "personality", "hierarchy_role", "parent_id"],
        # Members may spawn via UI/API; chat skill still prefers leads but is allowed for all operators
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "message_agent",
        "name": "Message agent",
        "description": "Send a message to another agent and optionally get their reply.",
        "args": ["to_agent_id", "message", "expect_reply"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "use_app",
        "name": "Use connected app",
        "description": "Call a connected integration (Slack, Gmail, Shopify, socials, etc.).",
        "args": ["app_id", "action", "payload"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "assign_human",
        "name": "Assign work to human",
        "description": (
            "Allocate a task to a human teammate. Omit human_id to assign to the account's "
            "My Human (primary). Posts to their message box and notifies when active."
        ),
        "args": ["human_id", "title", "description", "priority"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "save_memory",
        "name": "Save agent data",
        "description": "Persist a note/fact/deliverable in this agent's data vault.",
        "args": ["title", "content", "kind", "tags"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "save_training",
        "name": "Save to training",
        "description": "Promote text into the training library and attach to this agent.",
        "args": ["title", "content", "tags", "folder_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "create_task",
        "name": "Create task",
        "description": (
            "Create a task for yourself (default) or another agent/human. "
            "Always include success_criteria or done_when (measurable target). "
            "Active agents are queued and run immediately unless run_now=false."
        ),
        "args": [
            "title", "description", "agent_id", "human_id", "priority", "run_now",
            "meeting_id", "parent_task_id", "success_criteria", "done_when", "target",
        ],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "claim_task",
        "name": "Claim task",
        "description": (
            "Assign this task to yourself, attach DONE WHEN / TARGET acceptance criteria, "
            "queue it, and start running it now."
        ),
        "args": ["task_id", "success_criteria", "done_when", "target"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "announce_plan",
        "name": "Announce plan",
        "description": (
            "Publish a multi-step plan to live ops and create a parent task + child steps. "
            "String steps stay on the announcer (backward compatible). "
            "Dict steps may set agent_id / role (or role_hint / template_type) to assign via "
            "task_chain.pick_assignee; active agents are queued for autonomy."
        ),
        "args": ["title", "steps"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "execute_goal",
        "name": "Execute goal (auto chain)",
        "description": (
            "From one prompt: create parent goal, break into steps, delegate down hierarchy, "
            "set company/project targets, queue active agents, monitor completion."
        ),
        "args": ["goal", "title", "priority", "steps", "company_id", "project_id", "max_steps"],
        "roles": ["orchestrator", "lead", "member"],
    },
    # ── CRM + Diary skills (run existing customers, arrange diaries) ─────
    {
        "id": "list_customers",
        "name": "List customers",
        "description": "Search or list existing customers in CRM (by name, email, tags, status).",
        "args": ["q", "status", "tag", "limit"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "get_customer",
        "name": "Get customer",
        "description": "Fetch full record for a customer including recent deals and activity.",
        "args": ["customer_id", "email"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "create_customer",
        "name": "Create customer",
        "description": "Add a new customer/contact to CRM (name required; email, phone, tags, notes optional).",
        "args": [
            "name", "email", "phone", "account_name", "status", "tags", "notes",
            "source", "job_title", "website", "industry", "city", "country", "company_id",
        ],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "update_customer",
        "name": "Update customer",
        "description": "Edit contact details, owner, tags, notes, status on an existing customer.",
        "args": [
            "customer_id", "email", "name", "phone", "status", "tags", "notes",
            "owner_human_id", "owner_agent_id", "account_name", "job_title", "source",
        ],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "db_field_ops",
        "name": "DB field operations",
        "description": (
            "Core gate for auto-generated per-field CRUD skills "
            "(add_*/change_*/delete_* on entity fields). When enabled, agents may "
            "run any registered field skill without enabling each one individually."
        ),
        "args": ["entity", "field", "op"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
        "category": "data",
    },
    {
        "id": "delete_customer",
        "name": "Delete customer",
        "description": "Permanently remove a customer and their deals/activities from CRM.",
        "args": ["customer_id", "email"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "log_customer_activity",
        "name": "Log customer activity",
        "description": "Record a note, call, email, or meeting against a customer (also updates last_contacted).",
        "args": ["customer_id", "email", "kind", "title", "body"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "create_deal",
        "name": "Create deal",
        "description": "Create a new opportunity/deal for an existing customer in a pipeline.",
        "args": ["customer_id", "email", "title", "value", "priority", "expected_close", "pipeline_id", "stage_id"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "update_deal",
        "name": "Update deal",
        "description": "Change deal title, value, priority, status, description, or expected close.",
        "args": ["deal_id", "title", "value", "priority", "status", "description", "expected_close", "currency"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "delete_deal",
        "name": "Delete deal",
        "description": "Permanently remove a deal/opportunity from the pipeline board.",
        "args": ["deal_id"],
        "roles": ["orchestrator", "lead", "member"],
    },
    # ── Products + special offers ───────────────────────────────────
    {
        "id": "list_products",
        "name": "List products",
        "description": "List catalogue products. Filter q/status/kind/tag; has_offer=true for special offers only.",
        "args": ["q", "status", "kind", "tag", "has_offer", "limit"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "get_product",
        "name": "Get product",
        "description": "Fetch one product by product_id or name search (includes price and special offer).",
        "args": ["product_id", "name"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "create_product",
        "name": "Create product",
        "description": (
            "Add a product/service to the catalogue. Supports price, benefits, audience, "
            "and special offer (offer / special_offer promo text)."
        ),
        "args": [
            "name", "description", "price", "currency", "sku", "kind", "status",
            "tags", "benefits", "audience", "offer", "special_offer", "company_id",
        ],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "update_product",
        "name": "Update product",
        "description": "Change product fields: name, price, description, tags, status, benefits, offer, etc.",
        "args": [
            "product_id", "name", "description", "price", "currency", "sku", "kind", "status",
            "tags", "benefits", "audience", "offer", "special_offer", "company_id",
        ],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "delete_product",
        "name": "Delete product",
        "description": "Permanently remove a product from the catalogue.",
        "args": ["product_id"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "set_product_offer",
        "name": "Set product special offer",
        "description": (
            "Set or clear a special offer / promo CTA on a product "
            "(e.g. '20% off this week', 'Free survey for multi-lets'). Empty string clears."
        ),
        "args": ["product_id", "offer", "special_offer"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "schedule_meeting",
        "name": "Schedule meeting / diary",
        "description": "Arrange a diary entry (call, meeting, visit) for a customer. Supports start time and owner.",
        "args": ["customer_id", "email", "title", "start_at", "end_at", "location", "notes", "owner_human_id", "owner_agent_id"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "list_diary",
        "name": "List diary / meetings",
        "description": "List upcoming or customer-specific diary entries (appointments).",
        "args": ["customer_id", "email", "status", "upcoming"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    # ── CRM pipeline skills (full board control) ──────────────────
    {
        "id": "list_pipelines",
        "name": "List pipelines",
        "description": "List CRM pipelines (sales boards) with stage counts and open value.",
        "args": ["limit"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "get_pipeline",
        "name": "Get pipeline board",
        "description": "Full pipeline board: stages + deals in each stage (kanban snapshot).",
        "args": ["pipeline_id", "with_deals"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "list_pipeline_stages",
        "name": "List pipeline stages",
        "description": "List stages for a pipeline (name, type, probability, position).",
        "args": ["pipeline_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "move_deal",
        "name": "Move deal to stage",
        "description": "Move a deal to another stage (by stage_id or stage name).",
        "args": ["deal_id", "stage_id", "stage_name", "notes"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "win_deal",
        "name": "Win deal",
        "description": "Mark a deal as won and optionally set final value / notes.",
        "args": ["deal_id", "value", "notes"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "lose_deal",
        "name": "Lose deal",
        "description": "Mark a deal as lost with a reason.",
        "args": ["deal_id", "lost_reason", "notes"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "pipeline_summary",
        "name": "Pipeline summary",
        "description": "Totals by stage: deal counts, open value, win rate snapshot.",
        "args": ["pipeline_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "ensure_sales_pipeline",
        "name": "Ensure sales pipeline",
        "description": "Create the default Sales pipeline + stages if the workspace has none.",
        "args": [],
        "roles": ["orchestrator", "lead", "member"],
    },
    # ── Workspace read + universal comment (every agent) ──────────
    {
        "id": "list_tasks",
        "name": "List tasks",
        "description": (
            "List workspace tasks (board). Filter by status (todo/queued/in_progress/review/"
            "completed/failed or open), agent_id, priority, mine=true (this agent), q search, limit."
        ),
        "args": ["status", "agent_id", "priority", "mine", "open_only", "q", "limit"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "search_tasks",
        "name": "Search tasks",
        "description": (
            "Search tasks by text across title, description, labels, and results. "
            "Use when the human asks to find a task or work item."
        ),
        "args": ["q", "status", "agent_id", "limit"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "get_task",
        "name": "Get task",
        "description": "Fetch one task with full description, status, assignee, result, and child steps.",
        "args": ["task_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "update_task",
        "name": "Update task",
        "description": (
            "Update a task: status, result/note, priority, title, description, labels, "
            "or reassign agent_id / human_id. Use for progress notes and board changes."
        ),
        "args": [
            "task_id", "status", "result", "priority", "title", "description",
            "labels", "agent_id", "human_id", "append_result",
        ],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "respond_to_task",
        "name": "Respond to task",
        "description": (
            "Write a response/result on a task. Completes the task by default "
            "(complete=false keeps it in progress). Orchestrator should use this "
            "when answering or finishing work on a board item."
        ),
        "args": ["task_id", "response", "complete", "status", "append_result"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "complete_task",
        "name": "Complete task",
        "description": "Mark a task completed with an optional result summary. Unlocks auto-chain siblings.",
        "args": ["task_id", "result"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "delete_task",
        "name": "Delete task",
        "description": "Permanently remove a task (and its child steps) from the board.",
        "args": ["task_id"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "set_task_status",
        "name": "Set task status",
        "description": "Change only the board status: todo | queued | in_progress | review | completed | failed.",
        "args": ["task_id", "status"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "list_meetings",
        "name": "List meeting rooms",
        "description": "List brainstorm / war-room meeting rooms for this workspace.",
        "args": ["status", "limit"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "invite_to_meeting",
        "name": "Invite agents to meeting",
        "description": (
            "Add one or more agents as participants in a meeting room. "
            "Use meeting_id + agent_ids (or agent_id)."
        ),
        "args": ["meeting_id", "agent_ids", "agent_id", "role"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "list_activity",
        "name": "List activity logs",
        "description": (
            "Read agent activity logs across the workspace (or mine=true / agent_id). "
            "Use when starting work to see what teammates already did."
        ),
        "args": ["mine", "agent_id", "q", "type", "limit"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "list_humans",
        "name": "List human teammates",
        "description": "List human team members (My Human and others) with status and capacity.",
        "args": ["q", "limit"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "list_deals",
        "name": "List deals",
        "description": "List CRM deals/opportunities (open pipeline items).",
        "args": ["status", "q", "limit", "pipeline_id", "stage_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "read_workspace",
        "name": "Read workspace snapshot",
        "description": (
            "One-shot overview: companies, projects, agent counts, open tasks, "
            "recent meetings, humans — so you can act without asking the user."
        ),
        "args": [],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "comment",
        "name": "Comment on record",
        "description": (
            "Leave a note/comment on a workspace record: customer, task, meeting, "
            "human, deal, or agent memory. Use target_type + target_id + body."
        ),
        "args": ["target_type", "target_id", "body", "title"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    # ── Create skills + AgentBay sell/share ───────────────────────
    {
        "id": "create_skill",
        "name": "Create skill",
        "description": (
            "Invent a new reusable skill for this workspace (name, description, "
            "instructions, args). Optionally share with all teammates and/or list "
            "it for sale on AgentBay marketplace."
        ),
        "args": [
            "name", "description", "instructions", "args", "category",
            "share", "list_on_bay", "price",
        ],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "list_created_skills",
        "name": "List created skills",
        "description": "List skills this workspace (or you) invented, including AgentBay listing status.",
        "args": ["mine_only", "listed_only", "limit"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "publish_skill_to_bay",
        "name": "Sell skill on AgentBay",
        "description": (
            "Publish a created skill as a paid listing on AgentBay. "
            "Set skill_key or skill_id and price. Buyers discover it at /bay."
        ),
        "args": ["skill_key", "skill_id", "price", "title", "quantity"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "unpublish_skill_from_bay",
        "name": "Unpublish skill from AgentBay",
        "description": "Pause/remove a created skill listing from AgentBay (keeps the local skill).",
        "args": ["skill_key", "skill_id"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "share_skill",
        "name": "Share skill in workspace",
        "description": "Toggle whether a created skill is shared with all agents in this account.",
        "args": ["skill_key", "skill_id", "shared"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },

    # ── Meeting rooms (multi-agent brainstorm / war-room) ─────────
    {
        "id": "open_meeting",
        "name": "Open meeting room",
        "description": "Create a multi-agent meeting room (brainstorm / war-room) and invite agent participants.",
        "args": ["title", "purpose", "room_type", "agent_ids", "task_id", "project_id", "company_id"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "post_to_meeting",
        "name": "Post to meeting",
        "description": "Post a message into a meeting room thread as this agent.",
        "args": ["meeting_id", "content", "msg_type"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "run_meeting_round",
        "name": "Run meeting round",
        "description": "Have agent participants each contribute one turn in a meeting room.",
        "args": ["meeting_id", "prompt", "max_agents", "chair_only"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "close_meeting",
        "name": "Close meeting",
        "description": "Close a meeting room and store a summary of the discussion.",
        "args": ["meeting_id", "summary"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "extract_meeting_tasks",
        "name": "Extract meeting tasks",
        "description": "Create queued Task rows from meeting discussion (or explicit task list) linked to the meeting.",
        "args": ["meeting_id", "tasks", "agent_id"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ─────────────────────────────────────────────────────────────
    # COMPREHENSIVE COMMUNICATION SKILLS (Email / SMS / Voice / WhatsApp)
    # These are the most valuable — the best ones are charged (premium)
    # ─────────────────────────────────────────────────────────────
    {
        "id": "draft_email",
        "name": "Draft email",
        "description": "Write a professional email. Does NOT send (free). Use send_email to actually deliver.",
        "args": ["to", "subject", "body", "tone"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "send_email",
        "name": "Send email (premium)",
        "description": "Actually send a real email via Resend. This is a premium paid skill.",
        "args": ["to", "subject", "body", "from_name"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.02,
        "meter_kind": "premium-comm",
    },
    {
        "id": "draft_sms",
        "name": "Draft SMS / text",
        "description": "Write a concise, effective SMS or text message (free draft).",
        "args": ["to", "body"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "send_sms",
        "name": "Send SMS / text (Twilio)",
        "description": (
            "Initiate a real SMS text via Twilio. "
            "to must be E.164 (+15551234567). Requires Twilio keys (platform or Settings)."
        ),
        "args": ["to", "body"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.015,
        "meter_kind": "premium-comm",
    },
    {
        "id": "send_whatsapp",
        "name": "Send WhatsApp (Twilio)",
        "description": "Initiate a real WhatsApp text via Twilio sandbox or approved number.",
        "args": ["to", "body"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.02,
        "meter_kind": "premium-comm",
    },
    {
        "id": "make_voice_call",
        "name": "Make phone call + speech (Twilio)",
        "description": (
            "Initiate a real outbound phone call via Twilio. When answered, Twilio speaks "
            "your message (TTS speech). Optional voice (alice/man/woman) and language (en-US)."
        ),
        "args": ["to", "message", "voice", "language", "loop"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.08,
        "meter_kind": "voice_call",
    },
    {
        "id": "initiate_call",
        "name": "Initiate phone call",
        "description": "Alias for make_voice_call — start a Twilio call and speak a script to the human.",
        "args": ["to", "message", "voice", "language"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.08,
        "meter_kind": "voice_call",
    },
    {
        "id": "initiate_text",
        "name": "Initiate text / SMS",
        "description": "Alias for send_sms — start a Twilio SMS text to a phone number.",
        "args": ["to", "body"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.015,
        "meter_kind": "premium-comm",
    },
    {
        "id": "log_communication",
        "name": "Log communication",
        "description": "Record that you sent an email/SMS/call/WhatsApp (for CRM history, no real send).",
        "args": ["customer_id", "email", "kind", "to", "subject_or_title", "body"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "send_message",
        "name": "Send message (any channel)",
        "description": "Smart send: email, sms, whatsapp, or voice. Best general-purpose communication skill (premium if real delivery).",
        "args": ["to", "body", "subject", "channel", "customer_id"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.02,
    },

    # ── Image & Video (premium — always bill tokens) ─────────────
    {
        "id": "generate_image",
        "name": "Generate image (premium)",
        "description": "Create an image from a text prompt. Bills image tokens/credits every time.",
        "args": ["prompt", "style", "size"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
        "premium": True,
        "cost_credits": 0.06,
        "meter_kind": "image",
    },
    {
        "id": "generate_video",
        "name": "Generate video (premium)",
        "description": "Create a short video / motion concept from a prompt. Bills video tokens/credits every time.",
        "args": ["prompt", "duration_sec", "style"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.25,
        "meter_kind": "video",
    },

    # ── Content & Research ───────────────────────────────────────
    {
        "id": "generate_content",
        "name": "Generate content",
        "description": "Write blog posts, social copy, emails, scripts, proposals etc. High quality output.",
        "args": ["type", "topic", "audience", "tone", "length", "keywords"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "research",
        "name": "Research topic",
        "description": "Deep research on a topic, competitor, market, or person. Returns structured findings.",
        "args": ["query", "depth", "focus"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "summarize",
        "name": "Summarize text",
        "description": "Create concise, actionable summaries from long text, transcripts, or documents.",
        "args": ["text", "format", "max_points"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },

    # ── Calendar / Time ──────────────────────────────────────────
    {
        "id": "get_time",
        "name": "Get current time",
        "description": "Returns current date/time in the workspace timezone (useful for scheduling).",
        "args": ["timezone"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "suggest_times",
        "name": "Suggest meeting times",
        "description": "Propose good meeting slots based on availability logic or simple rules.",
        "args": ["duration_minutes", "days_ahead", "preferred_hours"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Advanced Business / Ops ─────────────────────────────────
    {
        "id": "create_invoice_draft",
        "name": "Create invoice draft",
        "description": "Generate a professional invoice draft for a customer/deal (text + suggested data).",
        "args": ["customer_id", "email", "items", "due_days", "notes"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "update_pipeline",
        "name": "Update pipeline / deal",
        "description": "Move deals, update values, change stages, or close opportunities (alias of move_deal / win / lose).",
        "args": ["deal_id", "stage_id", "stage_name", "status", "value", "notes", "lost_reason"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "escalate_to_human",
        "name": "Escalate to human",
        "description": (
            "Hand off work to an active human and ALWAYS notify them with a short SMS + email "
            "(SMTP/Resend + Twilio). Human must be active with email+phone set."
        ),
        "args": ["human_id", "title", "details", "urgency", "customer_id"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "notify_human",
        "name": "Notify human (email + SMS shortcut)",
        "description": (
            "Always send a short notification to an active human: SMS (Twilio) + email (SMTP/Resend) "
            "with an app deep-link shortcut. Requires active human with email+phone and SMTP+Twilio setup."
        ),
        "args": ["human_id", "title", "message", "details", "urgency"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },

    # ── Memory & Knowledge (advanced) ────────────────────────────
    {
        "id": "search_memory",
        "name": "Search agent memory",
        "description": "Search this agent's saved memory vault for relevant facts or history.",
        "args": ["query", "limit"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "search_knowledge",
        "name": "Search training knowledge",
        "description": "Search the shared training/knowledge base for relevant documents or notes.",
        "args": ["query", "limit", "tags"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },

    # ── Autonomy & Self-management ───────────────────────────────
    {
        "id": "set_agent_status",
        "name": "Set my status",
        "description": "Change this agent's idle_mode, permission_level or availability.",
        "args": ["idle_mode", "permission_level"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "create_reminder",
        "name": "Create reminder / follow-up",
        "description": "Create a future task or diary entry for yourself or another agent/human.",
        "args": ["title", "when", "for_agent_id", "for_human_id", "customer_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },

    # ============================================================
    # HUNDREDS OF SKILLS — COMPREHENSIVE CATALOG (150+)
    # Organized for autonomous multi-agent teams
    # ============================================================

    # ── Advanced Agent Creation & Management ("making them") ─────
    {
        "id": "spawn_team",
        "name": "Spawn team of agents",
        "description": "Create multiple specialist agents at once with good defaults.",
        "args": ["count", "base_name", "template_types", "parent_id"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "spawn_specialist",
        "name": "Spawn specialist",
        "description": "Create a highly focused specialist agent for a narrow domain.",
        "args": ["domain", "name", "parent_id"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "clone_agent",
        "name": "Clone agent",
        "description": "Duplicate an existing agent with same personality and skills.",
        "args": ["source_agent_id", "new_name"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "enable_skills_on",
        "name": "Enable skills on agent",
        "description": "Turn on a list of skills for another agent (powerful meta-skill).",
        "args": ["target_agent_id", "skill_ids"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "bulk_enable_skills",
        "name": "Bulk enable skills",
        "description": "Enable a powerful default skill set on many agents at once.",
        "args": ["agent_ids", "preset"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "configure_agent",
        "name": "Configure agent",
        "description": (
            "Change any writable agent field: name, template_type, personality, model, status, "
            "idle_mode, hierarchy_role, is_lead, permission_level, company_id, project_id, "
            "parent_id, escalate_when, escalate_reason, escalate_to, escalate_human_id, config."
        ),
        "args": [
            "target_agent_id", "name", "template_type", "personality", "model", "status",
            "idle_mode", "hierarchy_role", "is_lead", "permission_level", "company_id",
            "project_id", "parent_id", "escalate_when", "escalate_reason", "escalate_to",
            "escalate_human_id", "config",
        ],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "promote_to_lead",
        "name": "Promote to lead",
        "description": "Turn a member agent into a lead and optionally give it reports.",
        "args": ["agent_id", "report_agent_ids"],
        "roles": ["orchestrator"],
    },

    # ── Sales & Outreach (very rich) ─────────────────────────────
    {
        "id": "qualify_lead",
        "name": "Qualify lead",
        "description": "Score and qualify a lead using ICP and budget signals.",
        "args": ["customer_id", "notes"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "write_proposal",
        "name": "Write proposal",
        "description": "Generate a full sales proposal for a deal.",
        "args": ["deal_id", "customer_id", "value", "custom_points"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "objection_handler",
        "name": "Handle objection",
        "description": "Craft powerful responses to common sales objections.",
        "args": ["objection", "offer", "tone"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "follow_up_sequence",
        "name": "Create follow-up sequence",
        "description": "Generate 3-7 step email/SMS/WhatsApp follow-up sequence.",
        "args": ["customer_id", "goal", "channel"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "cold_outreach",
        "name": "Cold outreach",
        "description": "Write personalized cold email or LinkedIn message.",
        "args": ["to_name", "company", "pain_point", "offer"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "book_meeting",
        "name": "Book meeting",
        "description": "Negotiate and propose concrete meeting times with a prospect.",
        "args": ["customer_id", "preferred_slots"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Support & Success (rich) ─────────────────────────────────
    {
        "id": "triage_ticket",
        "name": "Triage support ticket",
        "description": "Classify urgency, category and suggest first response.",
        "args": ["subject", "body", "customer_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "refund_or_credit",
        "name": "Decide refund / credit",
        "description": "Apply company policy to decide on refund or goodwill credit.",
        "args": ["customer_id", "issue", "amount"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "knowledge_answer",
        "name": "Answer from knowledge base",
        "description": "Find the best answer from training data and draft reply.",
        "args": ["question", "customer_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "escalation_reason",
        "name": "Write escalation note",
        "description": "Create clear escalation reason + context for a human.",
        "args": ["customer_id", "issue_summary", "what_was_tried"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "onboarding_flow",
        "name": "Create onboarding flow",
        "description": "Build step-by-step onboarding checklist + messages for a new customer.",
        "args": ["customer_id", "product"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Content & Marketing (lots) ───────────────────────────────
    {
        "id": "linkedin_write_post",
        "name": "Write LinkedIn post (draft)",
        "description": "Create engaging LinkedIn post draft with hook, value and CTA. Use linkedin_post to publish live.",
        "args": ["topic", "tone", "include_hashtags"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "twitter_thread",
        "name": "Write Twitter/X thread",
        "description": "Create a punchy Twitter thread on a topic.",
        "args": ["topic", "length", "tone"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "ad_copy",
        "name": "Write ad copy",
        "description": "Write high-converting ad copy for Google/Facebook/Instagram.",
        "args": ["offer", "audience", "platform", "length"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "email_newsletter",
        "name": "Write newsletter",
        "description": "Create full email newsletter with subject, body and CTAs.",
        "args": ["theme", "audience", "length"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "video_script",
        "name": "Write video script",
        "description": "Create short or long form video script with timestamps.",
        "args": ["topic", "duration_seconds", "style"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "seo_article",
        "name": "Write SEO article",
        "description": "Write search-optimized article with headings and keywords.",
        "args": ["keyword", "word_count", "target_audience"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "case_study",
        "name": "Write case study",
        "description": "Turn a customer success into a compelling case study.",
        "args": ["customer_id", "results", "tone"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Coding & Engineering (very deep) ─────────────────────────
    {
        "id": "write_api_endpoint",
        "name": "Write API endpoint",
        "description": "Generate FastAPI / Express / Nest endpoint with validation.",
        "args": ["method", "path", "purpose", "auth_required"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "write_tests",
        "name": "Write tests",
        "description": "Generate unit + integration tests for given code.",
        "args": ["code", "framework", "coverage_goal"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "refactor_code",
        "name": "Refactor code",
        "description": "Improve readability, performance and structure of code.",
        "args": ["code", "goals"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "debug_error",
        "name": "Debug error",
        "description": "Analyze stack trace + logs and propose root cause + fix.",
        "args": ["error", "logs", "language"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "database_migration",
        "name": "Create DB migration",
        "description": "Write Alembic / Prisma / Django migration for schema change.",
        "args": ["change_description", "db_type"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "docker_setup",
        "name": "Create Docker setup",
        "description": "Generate Dockerfile + docker-compose for the project.",
        "args": ["language", "services"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "ci_pipeline",
        "name": "Create CI/CD pipeline",
        "description": "Write GitHub Actions / GitLab CI pipeline for build + test + deploy.",
        "args": ["provider", "deploy_target"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "code_review",
        "name": "Perform code review",
        "description": "Give detailed code review with severity and suggested fixes.",
        "args": ["pr_diff", "focus_areas"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },

    # ── Data, Analytics & Reporting ──────────────────────────────
    {
        "id": "build_dashboard_query",
        "name": "Build dashboard query",
        "description": "Write SQL or Python query for a business metric dashboard.",
        "args": ["metric", "time_range", "filters"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "generate_report",
        "name": "Generate report",
        "description": "Create a beautiful text + table + insight report.",
        "args": ["topic", "period", "audience"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "analyze_metrics",
        "name": "Analyze metrics",
        "description": "Find trends, anomalies and actionable insights from numbers.",
        "args": ["data_summary", "goal"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "forecast",
        "name": "Forecast numbers",
        "description": "Simple forecasting for revenue, leads, churn etc.",
        "args": ["historical_data", "periods_ahead", "method"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Finance, Invoicing & Admin ───────────────────────────────
    {
        "id": "chase_payment",
        "name": "Write payment chase",
        "description": "Polite but firm payment reminder sequence.",
        "args": ["customer_id", "invoice_number", "days_overdue"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "expense_categorize",
        "name": "Categorize expenses",
        "description": "Classify expenses for bookkeeping and tax.",
        "args": ["description", "amount", "vendor"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "monthly_summary",
        "name": "Monthly business summary",
        "description": "Create executive monthly summary with wins, risks and numbers.",
        "args": ["month", "highlights"],
        "roles": ["orchestrator", "lead"],
    },

    # ── HR & People Ops ──────────────────────────────────────────
    {
        "id": "write_job_description",
        "name": "Write job description",
        "description": "Create clear, attractive job description.",
        "args": ["role_title", "level", "must_haves"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "interview_questions",
        "name": "Create interview questions",
        "description": "Generate behavioral + technical interview questions.",
        "args": ["role", "seniority", "focus_areas"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "onboarding_plan",
        "name": "Create onboarding plan",
        "description": "30/60/90 day onboarding plan for a new hire.",
        "args": ["role", "team_size"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "performance_review",
        "name": "Draft performance review",
        "description": "Write balanced performance review with examples.",
        "args": ["person_name", "period", "strengths", "improvements"],
        "roles": ["orchestrator", "lead"],
    },

    # ── Legal, Compliance & Risk ────────────────────────────────
    {
        "id": "draft_contract_clause",
        "name": "Draft contract clause",
        "description": "Write a specific contract clause (for lawyer review).",
        "args": ["clause_type", "jurisdiction", "party_names"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "gdpr_request",
        "name": "Handle GDPR / data request",
        "description": "Draft response to data access / deletion request.",
        "args": ["request_type", "customer_email"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "risk_assessment",
        "name": "Risk assessment",
        "description": "Identify risks in a process, deal or feature.",
        "args": ["situation", "domain"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Creative & Design ────────────────────────────────────────
    {
        "id": "brand_voice_guide",
        "name": "Create brand voice guide",
        "description": "Define tone, do's and don'ts for the brand voice.",
        "args": ["brand_name", "values"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "logo_concept",
        "name": "Logo concept ideas",
        "description": "Generate detailed logo concept descriptions for a designer.",
        "args": ["company_name", "industry", "values"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "ui_copy",
        "name": "Write UI microcopy",
        "description": "Write clear, friendly button labels, placeholders, error messages.",
        "args": ["screen", "tone"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },

    # ── Automation & Workflows ───────────────────────────────────
    {
        "id": "design_workflow",
        "name": "Design workflow",
        "description": "Design a multi-step automated workflow between tools/agents.",
        "args": ["trigger", "steps", "tools"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "write_zapier_webhook",
        "name": "Write webhook payload",
        "description": "Create perfect JSON payload for Zapier / Make / n8n.",
        "args": ["action", "data_fields"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },

    # ── Self-Improvement & Reflection (agents improving themselves) ─
    {
        "id": "reflect_on_outcome",
        "name": "Reflect on outcome",
        "description": "Analyze what worked / didn't after completing a task and extract lessons.",
        "args": ["task_id", "result", "what_to_improve"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "improve_prompt",
        "name": "Improve own prompt",
        "description": "Suggest better system prompt or instructions for itself or another agent.",
        "args": ["current_prompt", "observed_problems"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "save_lesson",
        "name": "Save lesson to training",
        "description": "Turn an experience into reusable training data.",
        "args": ["lesson", "tags", "for_who"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },

    # ── General Productivity ─────────────────────────────────────
    {
        "id": "prioritize_list",
        "name": "Prioritize list",
        "description": "Take a list of tasks and return them in smart priority order with reasoning.",
        "args": ["tasks", "criteria"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "meeting_agenda",
        "name": "Create meeting agenda",
        "description": "Build a focused, time-boxed meeting agenda.",
        "args": ["purpose", "attendees", "duration"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "action_items",
        "name": "Extract action items",
        "description": "Turn notes or transcript into clear owner + due date action items.",
        "args": ["notes", "default_owner"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "decision_log",
        "name": "Log decision",
        "description": "Record a decision with context, options considered and rationale.",
        "args": ["decision", "context", "options"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ============================================================
    # HUNDREDS OF SKILLS — EXPANDED CATALOG (target 200+)
    # Agent creation / meta, Sales, Support, Content, Coding, Data,
    # Finance, HR, Legal, Creative, Automation, Ops, Research, Reflection
    # ============================================================

    # ── Meta / Agent Factory (the "spawn 40 agents making them" core) ──
    {
        "id": "spawn_team",
        "name": "Spawn team of agents",
        "description": "Spawn N specialist agents with sensible defaults and hierarchy. Use to rapidly build a 20-40 person team.",
        "args": ["count", "base_name", "template_types", "parent_id", "enable_preset"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "spawn_specialist",
        "name": "Spawn specialist",
        "description": "Spawn one highly focused specialist (e.g. 'SEO Copywriter', 'Stripe Billing', 'Churn Predictor').",
        "args": ["domain", "name", "parent_id", "skills"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "clone_agent",
        "name": "Clone agent",
        "description": "Duplicate another agent (personality, enabled skills, config) into a new sibling.",
        "args": ["source_agent_id", "new_name", "parent_id"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "enable_skills_on",
        "name": "Enable skills on agent",
        "description": "Powerful meta-skill: give any agent (or many) a list of skill ids. Core of 'making them'.",
        "args": ["target_agent_id", "skill_ids"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "bulk_enable_skills",
        "name": "Bulk enable skills",
        "description": "Give the same skill pack (full, sales, marketing, support, coding, research, lead, engineering, content, comms) to many agents at once. Always includes core free skills.",
        "args": ["agent_ids", "preset", "extra_skills"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "configure_agent",
        "name": "Configure agent",
        "description": (
            "Change any writable agent field (full DB surface): name, template_type, personality, "
            "model, status, idle_mode, hierarchy_role, is_lead, permission_level, company_id, "
            "project_id, parent_id, escalate_when/reason/to/human_id, config."
        ),
        "args": [
            "target_agent_id", "name", "template_type", "personality", "model", "status",
            "idle_mode", "hierarchy_role", "is_lead", "permission_level", "company_id",
            "project_id", "parent_id", "escalate_when", "escalate_reason", "escalate_to",
            "escalate_human_id", "config",
        ],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "promote_to_lead",
        "name": "Promote to lead",
        "description": "Turn a member into a lead and optionally re-parent other agents under them.",
        "args": ["agent_id", "report_agent_ids"],
        "roles": ["orchestrator"],
    },
    {
        "id": "pause_agent",
        "name": "Pause agent",
        "description": "Temporarily stop an agent from running cycles.",
        "args": ["target_agent_id"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "resume_agent",
        "name": "Resume agent",
        "description": "Resume a paused agent so it becomes never_idle again.",
        "args": ["target_agent_id"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "delete_agent",
        "name": "Delete agent",
        "description": "Permanently remove a non-critical agent (orchestrator protected).",
        "args": ["target_agent_id", "reason"],
        "roles": ["orchestrator"],
    },
    {
        "id": "list_team",
        "name": "List my team",
        "description": "Return all agents under the current agent or whole org for the orchestrator.",
        "args": ["include_skills", "role_filter"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Advanced Sales & Revenue (lots) ──────────────────────────
    {
        "id": "build_icp",
        "name": "Build ICP",
        "description": "Create or refine Ideal Customer Profile from data and notes.",
        "args": ["industry", "company_size", "pain", "budget_signal"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "enrich_lead",
        "name": "Enrich lead",
        "description": "Add company info, decision makers, recent news to a lead record.",
        "args": ["customer_id", "email", "sources"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "score_lead",
        "name": "Score lead",
        "description": "Give a numeric + letter score and rationale for a lead.",
        "args": ["customer_id", "email", "context"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "build_sales_script",
        "name": "Build sales script",
        "description": "Create call script, email sequence or LinkedIn sequence for a specific offer.",
        "args": ["offer", "persona", "channel", "length_steps"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "competitive_battlecard",
        "name": "Competitive battlecard",
        "description": "Create a one-pager comparing us vs named competitor on key points.",
        "args": ["competitor", "our_strengths", "weaknesses_to_address"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "proposal_pricing",
        "name": "Proposal pricing calculator",
        "description": "Suggest tiers and prices for a deal based on scope and value.",
        "args": ["deal_id", "scope", "customer_budget"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "close_plan",
        "name": "Close plan",
        "description": "Generate the final 3-5 step plan to win a deal this week.",
        "args": ["deal_id", "customer_id", "objections"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "upsell_crosssell",
        "name": "Upsell / cross-sell",
        "description": "Find expansion opportunities inside an existing customer.",
        "args": ["customer_id", "current_products"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "churn_risk",
        "name": "Churn risk analysis",
        "description": "Detect early churn signals and suggest retention plays.",
        "args": ["customer_id", "recent_activity"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Customer Success & Support (expanded) ────────────────────
    {
        "id": "health_score",
        "name": "Customer health score",
        "description": "Compute a health score and next best action for a customer.",
        "args": ["customer_id", "signals"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "qbr_prep",
        "name": "QBR prep pack",
        "description": "Prepare a quarterly business review pack for a key customer.",
        "args": ["customer_id", "period"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "success_plan",
        "name": "Success plan",
        "description": "Build 30/60/90 day success plan for a new or at-risk customer.",
        "args": ["customer_id", "goals"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "ticket_root_cause",
        "name": "Ticket root cause",
        "description": "Analyse support ticket + logs and identify root cause.",
        "args": ["ticket_text", "logs", "customer_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "sla_breach_risk",
        "name": "SLA breach risk",
        "description": "Flag tickets at risk of SLA breach and recommend actions.",
        "args": ["ticket_ids", "current_time"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "knowledge_gap",
        "name": "Knowledge gap finder",
        "description": "Find questions we keep getting that are missing from training.",
        "args": ["recent_tickets", "top_queries"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "cancel_save",
        "name": "Cancellation save",
        "description": "Craft a last-chance save offer and talking points for a cancelling customer.",
        "args": ["customer_id", "reason", "value"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Marketing & Growth (deep) ────────────────────────────────
    {
        "id": "content_calendar",
        "name": "Content calendar",
        "description": "Create a 4-12 week content calendar across channels.",
        "args": ["themes", "channels", "frequency"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "landing_page_copy",
        "name": "Landing page copy",
        "description": "High-converting hero, features, FAQ and CTA copy for a landing page.",
        "args": ["offer", "audience", "tone"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "email_sequence",
        "name": "Email nurture sequence",
        "description": "Build 5-8 email nurture/education sequence with subject lines.",
        "args": ["goal", "audience", "length"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "ab_test_ideas",
        "name": "A/B test ideas",
        "description": "Generate strong A/B test hypotheses for copy, offer or page.",
        "args": ["page_or_asset", "metric"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "influencer_pitch",
        "name": "Influencer pitch",
        "description": "Write personalised outreach to micro-influencers or partners.",
        "args": ["influencer_name", "platform", "angle"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "referral_program",
        "name": "Referral program design",
        "description": "Design simple powerful referral mechanics + copy.",
        "args": ["product", "incentive"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "webinar_outline",
        "name": "Webinar outline",
        "description": "Full webinar flow with talk tracks and CTA plan.",
        "args": ["topic", "duration", "audience"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "growth_loop",
        "name": "Growth loop design",
        "description": "Map a self-reinforcing acquisition / retention loop.",
        "args": ["input", "output", "flywheel_step"],
        "roles": ["orchestrator", "lead"],
    },

    # ── Product & Roadmap ────────────────────────────────────────
    {
        "id": "prioritise_features",
        "name": "Prioritise features",
        "description": "RICE or ICE score a list of feature ideas.",
        "args": ["features", "criteria"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "user_story_map",
        "name": "User story map",
        "description": "Break an epic into user stories and acceptance criteria.",
        "args": ["epic", "persona", "journey_steps"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "roadmap_quarter",
        "name": "Quarterly roadmap",
        "description": "Build a realistic quarterly roadmap with milestones.",
        "args": ["themes", "capacity", "quarter"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "changelog",
        "name": "Write changelog",
        "description": "Turn commits or tickets into beautiful customer-facing changelog.",
        "args": ["changes", "version"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "feedback_theming",
        "name": "Theme customer feedback",
        "description": "Cluster raw feedback into themes with frequency and quotes.",
        "args": ["feedback_items", "top_n"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },

    # ── Finance & Admin (rich) ───────────────────────────────────
    {
        "id": "cashflow_forecast",
        "name": "Cashflow forecast",
        "description": "Simple forward cash projection from invoices + expected payments.",
        "args": ["invoices", "months"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "pricing_model",
        "name": "Pricing model review",
        "description": "Analyse current pricing and suggest improvements.",
        "args": ["current_tiers", "usage_data", "competitors"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "expense_policy",
        "name": "Expense policy checker",
        "description": "Flag expenses outside policy and suggest corrections.",
        "args": ["expense_rows"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "subscription_health",
        "name": "Subscription health",
        "description": "MRR, churn, expansion and cohort summary from data.",
        "args": ["period", "data"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "tax_ready_export",
        "name": "Tax-ready export",
        "description": "Prepare clean CSV/rows for accountant or tax software.",
        "args": ["transactions", "period"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── HR, Recruiting & Culture ────────────────────────────────
    {
        "id": "sourcing_plan",
        "name": "Sourcing plan",
        "description": "Where and how to find great candidates for a role.",
        "args": ["role", "level", "location_type"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "cv_screen",
        "name": "CV screen",
        "description": "Score a CV against job description + red flags.",
        "args": ["cv_text", "job_description"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "offer_letter_draft",
        "name": "Offer letter draft",
        "description": "Draft a clean job offer letter (legal review required).",
        "args": ["candidate_name", "role", "salary", "start_date"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "team_morale",
        "name": "Team morale pulse",
        "description": "Suggest lightweight ways to measure and improve team energy.",
        "args": ["team_size", "recent_signals"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "one_on_one_agenda",
        "name": "1:1 agenda generator",
        "description": "Create focused 1:1 agenda for manager + report.",
        "args": ["person", "last_meeting", "goals"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Legal, Compliance, Risk (more) ───────────────────────────
    {
        "id": "policy_generator",
        "name": "Policy generator",
        "description": "Generate privacy, acceptable use, refund or AI policy drafts.",
        "args": ["policy_type", "jurisdiction", "business_type"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "contract_risk_scan",
        "name": "Contract risk scan",
        "description": "Highlight risky clauses in a contract for lawyer review.",
        "args": ["contract_text", "focus"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "data_processing_addendum",
        "name": "DPA draft",
        "description": "Draft a basic Data Processing Addendum (lawyer review).",
        "args": ["controller", "processor"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "incident_response",
        "name": "Incident response plan",
        "description": "Step-by-step security or service incident playbook.",
        "args": ["incident_type", "systems"],
        "roles": ["orchestrator", "lead"],
    },

    # ── Deep Coding & Dev (lots of specialists) ──────────────────
    {
        "id": "architecture_review",
        "name": "Architecture review",
        "description": "Review high-level system design and suggest improvements.",
        "args": ["components", "scale", "constraints"],
        "roles": ["orchestrator", "lead", "specialist"],
    },
    {
        "id": "openapi_spec",
        "name": "OpenAPI spec",
        "description": "Generate or complete an OpenAPI / Swagger spec.",
        "args": ["endpoints", "version"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "sql_optimise",
        "name": "SQL optimiser",
        "description": "Rewrite slow queries and add indexes / materialised views.",
        "args": ["query", "schema", "volume"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "load_test_plan",
        "name": "Load test plan",
        "description": "Design realistic load test scenarios and success criteria.",
        "args": ["endpoints", "expected_users"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "feature_flag_plan",
        "name": "Feature flag rollout plan",
        "description": "Design safe rollout strategy with kill switches.",
        "args": ["feature", "audiences"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "tech_debt_audit",
        "name": "Tech debt audit",
        "description": "List and prioritise tech debt with effort vs risk.",
        "args": ["modules", "known_pain"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "pair_debug",
        "name": "Pair debug session",
        "description": "Walk through a bug with hypotheses, experiments and fixes.",
        "args": ["symptom", "repro_steps", "logs"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "sdk_client",
        "name": "Generate SDK client",
        "description": "Create typed client library wrapper for an API.",
        "args": ["api_spec", "language"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },

    # ── Data, Analytics, BI ──────────────────────────────────────
    {
        "id": "metric_definition",
        "name": "Define metric",
        "description": "Create precise definition + calculation for a business metric.",
        "args": ["metric_name", "events", "filters"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "cohort_analysis",
        "name": "Cohort analysis",
        "description": "Build retention or revenue cohort table from events.",
        "args": ["event_type", "periods"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "funnel_report",
        "name": "Funnel report",
        "description": "Step-by-step conversion funnel with drop-off analysis.",
        "args": ["steps", "date_range"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "anomaly_detect",
        "name": "Anomaly detector",
        "description": "Find statistically unusual movements in metrics.",
        "args": ["series", "window"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "experiment_design",
        "name": "Experiment design",
        "description": "Design A/B or multi-armed bandit test with power calc.",
        "args": ["hypothesis", "metric", "expected_lift"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Integrations & Automation (very useful) ──────────────────
    {
        "id": "webhook_design",
        "name": "Webhook design",
        "description": "Design reliable webhook events + retry + signature scheme.",
        "args": ["events", "security"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "etl_pipeline",
        "name": "ETL pipeline sketch",
        "description": "Outline extract-transform-load steps between systems.",
        "args": ["source", "destination", "transformations"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "oauth_flow",
        "name": "OAuth integration flow",
        "description": "Describe exact OAuth2 / OIDC steps for a new provider.",
        "args": ["provider", "scopes"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "cron_schedule",
        "name": "Cron / schedule design",
        "description": "Choose good cron expressions and failure handling for jobs.",
        "args": ["job_name", "cadence", "timezone"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "sync_conflict",
        "name": "Sync conflict resolver",
        "description": "Rules for merging conflicting records from two systems.",
        "args": ["entities", "master_source"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Creative & Design (more) ─────────────────────────────────
    {
        "id": "brand_guidelines",
        "name": "Brand guidelines",
        "description": "Create concise living brand guidelines (voice + visual).",
        "args": ["brand_name", "values", "examples"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "illustration_brief",
        "name": "Illustration brief",
        "description": "Write a perfect brief for an illustrator or AI image tool.",
        "args": ["scene", "style", "use_case"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "pitch_deck_outline",
        "name": "Pitch deck outline",
        "description": "Slide-by-slide structure for investor or sales deck.",
        "args": ["stage", "audience", "key_numbers"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "social_asset_pack",
        "name": "Social asset pack",
        "description": "List of visual + copy assets needed for a campaign.",
        "args": ["campaign", "channels"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Reflection, Learning & Autonomy (agents improve themselves) ─
    {
        "id": "weekly_review",
        "name": "Weekly review",
        "description": "Summarise last 7 days wins, losses, learnings and next priorities.",
        "args": ["agent_id", "focus"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "lesson_extract",
        "name": "Lesson extract",
        "description": "Turn a specific failure or win into a reusable lesson card.",
        "args": ["event", "outcome", "root_cause"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "prompt_diff",
        "name": "Prompt diff",
        "description": "Compare two versions of a system prompt and explain delta.",
        "args": ["before", "after"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "autonomy_audit",
        "name": "Autonomy audit",
        "description": "Check if an agent has the skills, permissions and data to run without you.",
        "args": ["agent_id"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "training_gap",
        "name": "Training gap report",
        "description": "Identify what knowledge this agent is missing to be excellent.",
        "args": ["agent_id", "recent_failures"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── General Ops & Productivity (many) ────────────────────────
    {
        "id": "runbook",
        "name": "Write runbook",
        "description": "Create a repeatable runbook for a process with screenshots placeholders.",
        "args": ["process", "owner", "failure_modes"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "meeting_notes",
        "name": "Meeting notes + actions",
        "description": "Turn raw notes/transcript into decisions + owners + due dates.",
        "args": ["transcript", "attendees"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "okrs",
        "name": "Write OKRs",
        "description": "Create Objectives + Key Results for a team or company.",
        "args": ["objective", "team", "quarter"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "risk_register",
        "name": "Risk register",
        "description": "Maintain a living list of risks with owners and mitigations.",
        "args": ["risks", "project"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "status_update",
        "name": "Status update",
        "description": (
            "Create a crisp status report and notify the human owner (active account) "
            "via short SMS + email shortcuts when notify=true (default)."
        ),
        "args": ["project", "period", "highlights", "status", "message", "human_id", "notify"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "time_audit",
        "name": "Time audit",
        "description": "Analyse calendar + tasks and suggest focus improvements.",
        "args": ["calendar", "tasks"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "vendor_eval",
        "name": "Vendor evaluation",
        "description": "Score and compare 2-4 vendors for a purchase.",
        "args": ["vendors", "criteria", "use_case"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "process_map",
        "name": "Process map",
        "description": "Produce a clear step-by-step process map with decision points.",
        "args": ["process_name", "start", "end"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── More Communication variants (premium ready) ──────────────
    {
        "id": "personalised_video_script",
        "name": "Personalised video script",
        "description": "Write a short personalised video message script (for Loom etc).",
        "args": ["recipient", "goal", "tone"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "sms_campaign",
        "name": "SMS campaign draft",
        "description": "Design a multi-message SMS campaign with timing.",
        "args": ["audience", "offer", "steps"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "support_macro",
        "name": "Support macro",
        "description": "Create a reusable high-quality support reply template.",
        "args": ["situation", "tone"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "exec_summary_email",
        "name": "Executive summary email",
        "description": "Turn a long thread or report into a 5-line exec summary.",
        "args": ["content", "ask"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Reflection + Meta Learning (self-improving agents) ───────
    {
        "id": "post_mortem",
        "name": "Post mortem",
        "description": "Structured blameless post-mortem with timeline, causes, actions.",
        "args": ["incident", "timeline", "impact"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "skill_recommend",
        "name": "Recommend skills for agent",
        "description": "Given what an agent does, suggest the best skills to enable.",
        "args": ["agent_id", "observed_tasks"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "agent_compare",
        "name": "Compare agents",
        "description": "Compare two agents output quality, speed, cost and reliability.",
        "args": ["agent_a", "agent_b", "task_type"],
        "roles": ["orchestrator", "lead"],
    },

    # ============================================================
    # CONNECTED APPS — FULL RICH ACTIONS (one skill per real function)
    # Facebook, Instagram, LinkedIn, X, Gmail, Slack, Calendar, Sheets,
    # Shopify, HubSpot, Notion, Discord, WhatsApp Business, etc.
    # Agents should prefer these named skills over generic use_app.
    # ============================================================

    # ── Facebook (Meta Pages + Messenger) ────────────────────────
    {
        "id": "facebook_post",
        "name": "Facebook post",
        "description": "Post a text or link update to a connected Facebook Page.",
        "args": ["message", "link", "page_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
        "premium": True,
        "cost_credits": 0.02,
    },
    {
        "id": "facebook_reply_comment",
        "name": "Reply to Facebook comment",
        "description": "Reply to a specific comment on a Facebook post (page).",
        "args": ["comment_id", "message", "page_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
        "premium": True,
        "cost_credits": 0.015,
    },
    {
        "id": "facebook_reply_message",
        "name": "Reply to Facebook message / DM",
        "description": "Reply in Facebook Messenger to a user (page inbox).",
        "args": ["recipient_id", "message", "page_id"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.02,
    },
    {
        "id": "facebook_get_comments",
        "name": "Get Facebook comments",
        "description": "Fetch recent comments on a post or page for monitoring/replying.",
        "args": ["post_id", "page_id", "limit"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "facebook_get_posts",
        "name": "List Facebook page posts",
        "description": "Retrieve recent posts from a connected Facebook Page.",
        "args": ["page_id", "limit"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "facebook_get_conversations",
        "name": "Facebook Messenger inbox",
        "description": "List recent Messenger conversations for a page.",
        "args": ["page_id", "limit"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "facebook_like_comment",
        "name": "Like Facebook comment",
        "description": "React/like a comment on Facebook.",
        "args": ["comment_id", "page_id"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Instagram ────────────────────────────────────────────────
    {
        "id": "instagram_post",
        "name": "Instagram post",
        "description": "Create a photo/video post or reel on Instagram Business/Creator account (requires media URL or container).",
        "args": ["caption", "image_url", "video_url", "ig_user_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
        "premium": True,
        "cost_credits": 0.04,
    },
    {
        "id": "instagram_reply_comment",
        "name": "Reply to Instagram comment",
        "description": "Reply to a comment on an Instagram post or reel.",
        "args": ["comment_id", "message", "ig_user_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
        "premium": True,
        "cost_credits": 0.015,
    },
    {
        "id": "instagram_get_comments",
        "name": "Get Instagram comments",
        "description": "Fetch comments on an Instagram media object for engagement.",
        "args": ["media_id", "ig_user_id", "limit"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "instagram_get_media",
        "name": "List Instagram media",
        "description": "List recent posts/reels from the connected Instagram account.",
        "args": ["ig_user_id", "limit"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── LinkedIn ─────────────────────────────────────────────────
    {
        "id": "linkedin_post",
        "name": "LinkedIn post (live)",
        "description": "Publish a real post to personal profile or company page on LinkedIn.",
        "args": ["text", "author", "visibility", "link"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
        "premium": True,
        "cost_credits": 0.025,
    },
    {
        "id": "linkedin_comment",
        "name": "Comment on LinkedIn post",
        "description": "Leave a comment on a LinkedIn post (or reply to another comment).",
        "args": ["post_id", "text", "parent_comment_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
        "premium": True,
        "cost_credits": 0.015,
    },
    {
        "id": "linkedin_get_posts",
        "name": "List LinkedIn posts",
        "description": "Retrieve recent posts from a LinkedIn profile or company.",
        "args": ["author", "count"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "linkedin_get_comments",
        "name": "Get LinkedIn comments",
        "description": "Fetch comments on a LinkedIn post for replying/monitoring.",
        "args": ["post_id", "count"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── X / Twitter ──────────────────────────────────────────────
    {
        "id": "x_post",
        "name": "Post on X (Twitter)",
        "description": "Publish a tweet / X post (text, optionally with media).",
        "args": ["text", "reply_to_tweet_id", "quote_tweet_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
        "premium": True,
        "cost_credits": 0.02,
    },
    {
        "id": "x_reply",
        "name": "Reply on X",
        "description": "Reply to a specific tweet or X post.",
        "args": ["tweet_id", "text"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
        "premium": True,
        "cost_credits": 0.015,
    },
    {
        "id": "x_get_mentions",
        "name": "Get X mentions",
        "description": "Fetch recent mentions and replies directed at the account.",
        "args": ["limit"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "x_get_timeline",
        "name": "X home timeline",
        "description": "Get recent posts from the authenticated user's home timeline.",
        "args": ["limit"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "x_search",
        "name": "Search on X",
        "description": "Search recent tweets by keyword or hashtag.",
        "args": ["query", "limit"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },

    # ── Gmail (real connected Gmail) ─────────────────────────────
    {
        "id": "gmail_send",
        "name": "Gmail send",
        "description": "Send a real email from connected Gmail (Google Cloud OAuth). Supports To, Cc, Bcc.",
        "args": ["to", "subject", "body", "cc", "bcc", "html"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.02,
    },
    {
        "id": "gmail_reply",
        "name": "Gmail reply",
        "description": "Reply (or reply-all) to a Gmail thread/message with optional Cc/Bcc.",
        "args": ["thread_id", "message_id", "body", "to", "cc", "bcc", "reply_all"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.015,
    },
    {
        "id": "gmail_draft",
        "name": "Gmail draft",
        "description": "Create a draft email in Gmail (not sent yet). Supports Cc/Bcc.",
        "args": ["to", "subject", "body", "cc", "bcc"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "gmail_list",
        "name": "List Gmail messages",
        "description": "List recent messages or threads from Gmail inbox.",
        "args": ["query", "label", "limit"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "gmail_get_thread",
        "name": "Get Gmail thread",
        "description": "Fetch full conversation thread from Gmail by id.",
        "args": ["thread_id"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "gmail_search",
        "name": "Search Gmail",
        "description": "Advanced search in Gmail (same syntax as web Gmail).",
        "args": ["query", "limit"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "gmail_archive",
        "name": "Archive Gmail thread",
        "description": "Archive or remove a message/thread from inbox.",
        "args": ["message_id", "thread_id"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Generic Email (Resend-powered, works without Gmail OAuth) ──
    {
        "id": "email_send",
        "name": "Send email (any)",
        "description": "Send email via the platform email provider (Resend). Same as send_email.",
        "args": ["to", "subject", "body", "from_name"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.02,
    },
    {
        "id": "email_reply",
        "name": "Reply by email",
        "description": "Send a reply email in context of a customer (logs activity too).",
        "args": ["to", "subject", "body", "customer_id"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.02,
    },

    # ── Slack ────────────────────────────────────────────────────
    {
        "id": "slack_post",
        "name": "Post to Slack",
        "description": "Post a message to a Slack channel.",
        "args": ["channel", "text", "blocks"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
        "premium": True,
        "cost_credits": 0.01,
    },
    {
        "id": "slack_reply_thread",
        "name": "Reply in Slack thread",
        "description": "Reply inside an existing Slack thread.",
        "args": ["channel", "thread_ts", "text"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.01,
    },
    {
        "id": "slack_dm",
        "name": "Send Slack DM",
        "description": "Send a direct message to a Slack user.",
        "args": ["user_id", "text", "channel"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.015,
    },
    {
        "id": "slack_list_channels",
        "name": "List Slack channels",
        "description": "Get list of channels the bot is in.",
        "args": ["limit"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "slack_get_messages",
        "name": "Get Slack messages",
        "description": "Read recent messages from a Slack channel.",
        "args": ["channel", "limit", "oldest"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Google Calendar ──────────────────────────────────────────
    {
        "id": "calendar_create_event",
        "name": "Create calendar event",
        "description": "Create a new event in the connected Google Calendar.",
        "args": ["summary", "start", "end", "attendees", "location", "description"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.02,
    },
    {
        "id": "calendar_list_events",
        "name": "List calendar events",
        "description": "Get upcoming events from primary calendar.",
        "args": ["timeMin", "maxResults", "q"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "calendar_update_event",
        "name": "Update calendar event",
        "description": "Modify an existing calendar event (time, attendees, etc).",
        "args": ["event_id", "summary", "start", "end", "attendees"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "calendar_delete_event",
        "name": "Delete calendar event",
        "description": "Remove an event from the calendar.",
        "args": ["event_id"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Google Sheets ────────────────────────────────────────────
    {
        "id": "sheets_append",
        "name": "Append to Google Sheet",
        "description": "Append one or more rows to a Google Sheet.",
        "args": ["spreadsheet_id", "range", "values"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
        "premium": True,
        "cost_credits": 0.01,
    },
    {
        "id": "sheets_read",
        "name": "Read Google Sheet",
        "description": "Read values from a range in a Google Sheet.",
        "args": ["spreadsheet_id", "range"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "sheets_update",
        "name": "Update Google Sheet cells",
        "description": "Overwrite specific cells or range in a sheet.",
        "args": ["spreadsheet_id", "range", "values"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "sheets_create_sheet",
        "name": "Create new sheet tab",
        "description": "Add a new tab/sheet inside a spreadsheet.",
        "args": ["spreadsheet_id", "title"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Shopify ──────────────────────────────────────────────────
    {
        "id": "shopify_create_order_note",
        "name": "Add Shopify order note",
        "description": "Add a private note to a Shopify order.",
        "args": ["order_id", "note"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "shopify_update_product",
        "name": "Update Shopify product",
        "description": "Update title, price, inventory or tags on a product.",
        "args": ["product_id", "title", "price", "inventory", "tags", "add_tags"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "shopify_get_products",
        "name": "List Shopify products",
        "description": "List products with tags, SKU, and price from the Shopify store.",
        "args": ["limit", "tag", "title"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "shopify_get_orders",
        "name": "List Shopify orders",
        "description": "Retrieve recent orders (optionally filtered by status).",
        "args": ["status", "limit", "customer_email"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "shopify_get_customers",
        "name": "List Shopify customers",
        "description": "Search or list customers in the Shopify store (includes tags).",
        "args": ["query", "limit", "tag"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "shopify_update_customer",
        "name": "Update Shopify customer tags",
        "description": "Update a Shopify customer's tags and contact fields.",
        "args": ["customer_id", "tags", "add_tags", "email", "first_name", "last_name", "phone"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "shopify_sync_catalog",
        "name": "Sync Shopify into Business CRM",
        "description": (
            "Import Shopify products and customers into Business CRM with tags, "
            "linked to the user's company."
        ),
        "args": ["what", "company_id", "limit"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "shopify_push_product_tags",
        "name": "Push product tags to Shopify",
        "description": "Push a local Business product's tags/name/price to the linked Shopify product.",
        "args": ["product_id"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "shopify_push_customer_tags",
        "name": "Push customer tags to Shopify",
        "description": "Push a local Business customer's tags to the linked Shopify customer.",
        "args": ["customer_id"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "shopify_fulfill_order",
        "name": "Fulfill Shopify order",
        "description": "Mark an order as fulfilled and optionally send tracking.",
        "args": ["order_id", "tracking_number", "tracking_url"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── HubSpot ──────────────────────────────────────────────────
    {
        "id": "hubspot_create_contact",
        "name": "Create HubSpot contact",
        "description": "Create or update a contact in HubSpot CRM.",
        "args": ["email", "firstname", "lastname", "phone", "company"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "hubspot_create_deal",
        "name": "Create HubSpot deal",
        "description": "Create a deal/opportunity in HubSpot.",
        "args": ["dealname", "amount", "pipeline", "stage", "contact_email"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "hubspot_log_note",
        "name": "Log note in HubSpot",
        "description": "Add a timeline note or activity to a contact or deal.",
        "args": ["contact_id", "deal_id", "note"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "hubspot_get_contacts",
        "name": "Search HubSpot contacts",
        "description": "Search contacts by email, name or other properties.",
        "args": ["query", "limit"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Notion ───────────────────────────────────────────────────
    {
        "id": "notion_create_page",
        "name": "Create Notion page",
        "description": "Create a new page in a Notion database or under a parent.",
        "args": ["parent_id", "title", "properties", "children"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "notion_update_page",
        "name": "Update Notion page",
        "description": "Update properties or content of an existing Notion page.",
        "args": ["page_id", "properties", "archived"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "notion_query_database",
        "name": "Query Notion database",
        "description": "Run a filtered query against a Notion database.",
        "args": ["database_id", "filter", "sorts", "page_size"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "notion_append_block",
        "name": "Append blocks to Notion page",
        "description": "Add rich text, to-do, headings etc to a Notion page.",
        "args": ["page_id", "blocks"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Discord ──────────────────────────────────────────────────
    {
        "id": "discord_post",
        "name": "Post to Discord",
        "description": "Send a message via webhook or bot to a Discord channel.",
        "args": ["channel_id", "content", "embeds"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.01,
    },
    {
        "id": "discord_dm_user",
        "name": "DM Discord user",
        "description": "Send a direct message to a Discord user (bot must share server).",
        "args": ["user_id", "content"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.015,
    },

    # ── WhatsApp Business (via Twilio or Meta) ───────────────────
    {
        "id": "whatsapp_send",
        "name": "Send WhatsApp message",
        "description": "Send a WhatsApp message (same as send_whatsapp, explicit).",
        "args": ["to", "body"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.02,
    },
    {
        "id": "whatsapp_reply",
        "name": "Reply on WhatsApp",
        "description": "Reply in an existing WhatsApp conversation thread.",
        "args": ["to", "body", "context_message_id"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.02,
    },

    # ── Mailchimp ────────────────────────────────────────────────
    {
        "id": "mailchimp_add_subscriber",
        "name": "Add Mailchimp subscriber",
        "description": "Add or update a subscriber in a Mailchimp audience.",
        "args": ["list_id", "email", "status", "merge_fields"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "mailchimp_create_campaign",
        "name": "Create Mailchimp campaign",
        "description": "Create a draft email campaign in Mailchimp.",
        "args": ["list_id", "subject", "from_name", "html"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # ── Dropbox ──────────────────────────────────────────────────
    {
        "id": "dropbox_upload",
        "name": "Upload to Dropbox",
        "description": "Upload a file to Dropbox (base64 or url content).",
        "args": ["path", "content", "mode"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "dropbox_list",
        "name": "List Dropbox folder",
        "description": "List files and folders in a Dropbox path.",
        "args": ["path", "limit"],
        "roles": ["orchestrator", "lead", "member"],
    },

    # use_app already defined earlier — do not re-register
]

# ── Mega skill packs (20 domains × 50 = 1000) ───────────────────────────
# Loaded from app/skill_packs/*.json; execute via _skill_catalog_deliverable.
try:
    from .skill_packs import load_mega_skills  # noqa: E402

    _MEGA = load_mega_skills()
    if _MEGA:
        SKILL_CATALOG.extend(_MEGA)
except Exception:
    _MEGA = []

# Auto-generated per-field CRUD skills (optional package from skills.db_fields)
try:
    from .skills import db_fields as _db_fields_pkg

    _db_field_catalog = getattr(_db_fields_pkg, "build_catalog_entries", None)
    if callable(_db_field_catalog):
        SKILL_CATALOG.extend(_db_field_catalog() or [])
except Exception:
    pass

# Full agent actions: add/change/delete for every Agent column + entity ops
try:
    from .skills.agent_actions import build_agent_action_catalog  # noqa: E402

    _AGENT_ACTION_CAT = build_agent_action_catalog()
    if _AGENT_ACTION_CAT:
        SKILL_CATALOG.extend(_AGENT_ACTION_CAT)
except Exception:
    _AGENT_ACTION_CAT = []

# Finalize: dedupe + categories (skills_policy)
from .skills_policy import (  # noqa: E402
    dedupe_catalog,
    default_enabled_for_role,
    group_skills_by_category,
    premium_skill_ids,
    integration_skill_available,
    category_for,
    skill_pack_for_template,
    skills_for_pack,
    skills_for_template,
    role_matches_skill,
    is_mega_catalog_skill,
)

SKILL_CATALOG = dedupe_catalog(SKILL_CATALOG)

# Legacy name: lean free pack for member (~core + non-mega toolkit).
# Mega catalog (~1000) stays in SKILL_CATALOG for search/opt-in only.
# Domain agents get more via skills_for_template (non-mega domain layer).
DEFAULT_ENABLED = default_enabled_for_role("member", SKILL_CATALOG)
PREMIUM_SKILL_IDS = premium_skill_ids(SKILL_CATALOG)

# Outer fence only — body parsed with brace matching (nested JSON fails with non-greedy \{.*?\})
_SKILL_FENCE = re.compile(
    r"```(?:skill|skills|action)\s*([\s\S]*?)```",
    re.IGNORECASE,
)


def _extract_balanced_json_objects(s: str) -> list[str]:
    """Return top-level {...} JSON object strings with nested braces handled."""
    out: list[str] = []
    i = 0
    n = len(s or "")
    while i < n:
        if s[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        esc = False
        start = i
        for j in range(i, n):
            ch = s[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    out.append(s[start : j + 1])
                    i = j + 1
                    break
        else:
            break
    return out


def _normalize_skill_call(obj: dict) -> dict | None:
    """Accept {skill, args} or flat {skill, title, ...}."""
    if not isinstance(obj, dict):
        return None
    sid = obj.get("skill") or obj.get("name") or obj.get("id") or obj.get("action")
    if not sid:
        return None
    sid = str(sid).strip()
    if not sid:
        return None
    args = obj.get("args")
    if not isinstance(args, dict):
        args = {k: v for k, v in obj.items() if k not in ("skill", "name", "id", "action", "args")}
    return {"skill": sid, "args": args or {}}


def _created_skills_as_catalog(db: Session, user_id: int, agent_id: int | None = None) -> list[dict]:
    """Workspace-created skills as catalog entries (available to list/enable/run)."""
    try:
        q = db.query(models.CreatedSkill).filter(
            models.CreatedSkill.user_id == user_id,
            models.CreatedSkill.status != "archived",
        )
        rows = q.order_by(models.CreatedSkill.id.desc()).limit(200).all()
    except Exception:
        return []
    out = []
    for r in rows:
        # Shared with workspace OR owned by this agent
        if not r.shared and agent_id and r.agent_id != agent_id:
            continue
        try:
            args = json.loads(r.args_json or "[]")
            if not isinstance(args, list):
                args = []
        except Exception:
            args = []
        out.append({
            "id": r.skill_key,
            "name": r.name,
            "description": r.description or "",
            "args": args or ["context", "goal"],
            "roles": ["orchestrator", "lead", "member", "specialist"],
            "category": r.category or "custom",
            "handler": "created_skill",
            "custom": True,
            "created_skill_id": r.id,
            "shared": bool(r.shared),
            "listed_on_bay": bool(r.listed_on_bay),
            "list_price": float(r.list_price or 0),
            "instructions": (r.instructions or "")[:500],
            "creator_agent_id": r.agent_id,
        })
    return out


def list_skills_for_agent(agent: models.Agent, db: Session) -> list[dict]:
    role = normalize_role(agent)
    enabled = enabled_skill_ids(agent, db)
    # Always treat created skills as enabled when present for this agent/workspace
    catalog = list(SKILL_CATALOG) + _created_skills_as_catalog(db, agent.user_id, agent.id)
    out = []
    for s in catalog:
        allowed_roles = s.get("roles") or []
        # specialist inherits member pack (same as default_enabled_for_role)
        role_ok = role_matches_skill(role, allowed_roles) or is_orchestrator(agent)
        app_ok, app_err = integration_skill_available(s["id"], agent.user_id, db, {})
        is_custom = bool(s.get("custom") or str(s["id"]).startswith("custom_"))
        en = (s["id"] in enabled and role_ok) or (is_custom and role_ok)
        out.append({
            **{k: v for k, v in s.items() if k != "instructions"},
            "category": s.get("category") or category_for(s["id"]),
            "category_label": s.get("category_label"),
            "enabled": en,
            "role_allowed": role_ok,
            "premium": bool(s.get("premium")),
            "cost_credits": float(s.get("cost_credits") or 0) if s.get("premium") else 0,
            "custom": is_custom,
            "integration_ready": app_ok if app_err or s["id"].startswith((
                "gmail_", "sheets_", "calendar_", "facebook_", "slack_", "shopify_",
                "hubspot_", "notion_", "x_", "instagram_", "linkedin_", "discord_",
                "whatsapp_", "mailchimp_", "dropbox_",
            )) or s["id"] == "use_app" else True,
            "integration_error": app_err or None,
        })
    return out


def list_skills_grouped() -> list[dict]:
    """Admin/UI: skills grouped by category."""
    return group_skills_by_category(SKILL_CATALOG)


def enabled_skill_ids(agent: models.Agent, db: Session) -> set[str]:
    """Enabled skill set — always includes CORE free pack so agents never lose work tools."""
    from .skills_policy import _CORE_ALWAYS

    role = normalize_role(agent)
    defaults = set(default_enabled_for_role(role, SKILL_CATALOG))
    row = db.query(models.AgentSkillState).filter_by(agent_id=agent.id).first()
    stored: set[str] = set()
    if row and (row.enabled_json or "").strip():
        try:
            data = json.loads(row.enabled_json)
            if isinstance(data, list) and data:
                stored = {str(x) for x in data}
        except Exception:
            stored = set()
    if not stored:
        return defaults | set(_CORE_ALWAYS)
    # Merge core always — saved state must not strip task/meeting/log skills
    return stored | (set(_CORE_ALWAYS) & {s["id"] for s in SKILL_CATALOG}) | (
        defaults & set(_CORE_ALWAYS)
    )


def set_enabled_skills(db: Session, agent: models.Agent, skill_ids: list[str]) -> list[str]:
    """Persist enabled skills, capped by the owner's plan skills_per_agent.

    Always re-attaches CORE free skills so saves never wipe task/meeting tooling.
    """
    from .plans import max_enabled_skills, plan_skill_caps
    from .skills_policy import _CORE_ALWAYS

    valid = {s["id"] for s in SKILL_CATALOG}
    by_id = {s["id"]: s for s in SKILL_CATALOG}
    # Allow custom_* created skills through when present in DB state
    clean = []
    seen: set[str] = set()
    for s in skill_ids or []:
        sid = str(s).strip()
        if not sid or sid in seen:
            continue
        if sid in valid or sid.startswith("custom_"):
            clean.append(sid)
            seen.add(sid)
    # Force-save core pack (intersect catalog so unknown ids are not written)
    for c in _CORE_ALWAYS:
        if c in valid and c not in seen:
            clean.insert(0, c)
            seen.add(c)

    # Plan caps (admin accounts skip)
    plan_id = "none"
    is_admin = False
    try:
        owner = db.get(models.User, agent.user_id) if agent.user_id else None
        if owner:
            plan_id = owner.plan or "none"
            is_admin = getattr(owner, "role", None) == "admin"
    except Exception:
        owner = None

    if not is_admin:
        caps = plan_skill_caps(plan_id)
        # Drop premium skills if plan doesn't include them
        if not caps.get("premium_skills"):
            clean = [sid for sid in clean if not by_id.get(sid, {}).get("premium")]
        cap = int(caps.get("skills_per_agent") or 0)
        if cap > 0 and len(clean) > cap:
            # Prefer core skills first so plan caps never strip work tools
            core_on = [s for s in clean if s in _CORE_ALWAYS]
            rest = [s for s in clean if s not in _CORE_ALWAYS]
            clean = (core_on + rest)[: max(cap, len(core_on))]

    row = db.query(models.AgentSkillState).filter_by(agent_id=agent.id).first()
    if not row:
        row = models.AgentSkillState(agent_id=agent.id)
        db.add(row)
    row.enabled_json = json.dumps(clean)
    row.updated_at = datetime.utcnow()
    db.commit()
    return clean


def get_comprehensive_skill_catalog():
    """Return skills grouped by category (for Admin / agent skill UI)."""
    grouped = group_skills_by_category(SKILL_CATALOG)
    # Legacy dict shape some UIs expect: label → skills[]
    legacy = {g["label"]: g["skills"] for g in grouped}
    legacy["_meta"] = {
        "unique": len(SKILL_CATALOG),
        "premium": len(PREMIUM_SKILL_IDS),
        "categories": len(grouped),
        "groups": grouped,
    }
    return legacy


def skills_prompt_block(agent: models.Agent, db: Session, *, max_skills: int | None = None) -> str:
    """Compact skill catalogue for the LLM system prompt.

    Listing the full catalog (1000+ skills) on every chat blows context and makes
    replies slow/empty in the UI. Keep a short always-on core + category summary.
    Cap is plan.prompt_skills (fallback 48).
    """
    if max_skills is None:
        try:
            from .plans import plan_skill_caps
            owner = db.get(models.User, agent.user_id) if agent.user_id else None
            max_skills = int(plan_skill_caps(owner.plan if owner else "none").get("prompt_skills") or 48)
        except Exception:
            max_skills = 48
    max_skills = max(12, int(max_skills or 48))

    skills = [s for s in list_skills_for_agent(agent, db) if s.get("enabled")]
    if not skills:
        return ""

    # High-value skills always listed first (orchestrator / daily ops)
    priority_ids = [
        "create_task", "claim_task", "delete_task", "message_agent", "spawn_agent", "list_team",
        "list_customers", "create_customer", "update_customer", "delete_customer",
        "list_products", "get_product", "create_product", "update_product", "delete_product",
        "set_product_offer",
        "list_tasks", "search_tasks", "get_task", "update_task", "respond_to_task",
        "complete_task", "set_task_status", "list_activity", "create_deal", "update_deal", "delete_deal",
        "list_meetings", "invite_to_meeting", "open_meeting", "list_humans", "list_deals",
        "list_pipelines", "get_pipeline", "move_deal", "win_deal", "pipeline_summary",
        "read_workspace", "comment", "search_knowledge", "search_memory",
        "save_memory", "save_training", "announce_plan", "execute_goal", "status_update",
        "draft_email", "generate_content", "post_to_meeting", "run_meeting_round",
        "research", "summarize", "get_time", "escalate_to_human",
        "log_customer_activity", "create_deal", "prioritize_list", "action_items",
        "skill_recommend", "enable_skills_on", "configure_agent",
        "get_agent", "change_agent", "update_agent", "add_agent", "list_agent_fields",
        "reparent_agent", "rename_agent", "set_agent_field", "agent_field_ops",
    ]
    by_id = {s["id"]: s for s in skills}
    ordered: list[dict] = []
    seen: set[str] = set()
    for pid in priority_ids:
        if pid in by_id and pid not in seen:
            ordered.append(by_id[pid])
            seen.add(pid)
    # Fill remaining slots with non-premium skills, then premium
    rest = sorted(
        [s for s in skills if s["id"] not in seen],
        key=lambda s: (1 if s.get("premium") else 0, s.get("category") or "", s["id"]),
    )
    for s in rest:
        if len(ordered) >= max_skills:
            break
        ordered.append(s)
        seen.add(s["id"])

    # Category counts for the rest of the catalog
    cat_counts: dict[str, int] = {}
    for s in skills:
        cat = s.get("category_label") or s.get("category") or "other"
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    lines = [
        "You have SKILLS. When you must ACT (create/complete tasks, invite to meetings, CRM, etc.),",
        "emit skill blocks THEN write a short human reply that confirms what you did.",
        "CORRECT skill format (preferred — nested JSON is OK):",
        "```skill",
        '{"skill":"create_task","args":{"title":"...","description":"...","success_criteria":"..."}}',
        "```",
        "ALSO accepted:",
        "```skill",
        "complete_task",
        '{"task_id":123,"result":"what was delivered"}',
        "```",
        "Rules: use real skill ids from the list; fill required args; after skills run the system",
        "appends results — still narrate outcomes in plain language for the human.",
        f"Catalog: {len(skills)} skills enabled. Showing top {len(ordered)} for context "
        "(★ = premium / costs credits). Prefer free skills unless paid delivery is required.",
        "Core / listed skills:",
    ]
    for s in ordered:
        prefix = "★" if s.get("premium") else ""
        args = s.get("args") or []
        if isinstance(args, list):
            args_s = ",".join(str(a) for a in args[:6])
        else:
            args_s = str(args)[:80]
        desc = (s.get("description") or "")[:90]
        lines.append(f"- {s['id']}{prefix}: {desc} args=[{args_s}]")

    lines.append(
        "Other skill categories available (use skill id when you know it): "
        + ", ".join(f"{k}({v})" for k, v in sorted(cat_counts.items())[:16])
    )
    lines.append(
        "Apps: " + (integrations_context_for_agent(db, agent.id) or "(no apps linked)")
    )
    humans = db.query(models.Human).filter_by(owner_user_id=agent.user_id, status="active").limit(12).all()
    if humans:
        lines.append(
            "Humans: "
            + ", ".join(f"{h.name}(id={h.id})" for h in humans)
        )
    peers = (
        db.query(models.Agent)
        .filter(models.Agent.user_id == agent.user_id, models.Agent.id != agent.id)
        .limit(20)
        .all()
    )
    if peers:
        lines.append(
            "Other agents: "
            + ", ".join(f"{p.name}(id={p.id},{p.hierarchy_role})" for p in peers)
        )
    return "\n".join(lines)


def extract_skill_calls(text: str) -> list[dict]:
    """Parse skill directives from model output.

    Supported forms inside ```skill fences:
      1) {"skill":"create_task","args":{...}}
      2) create_task\\n{"title":"...","description":"..."}
      3) create_task\\n{"skill":"create_task","args":{...}}
    Also single-line JSON with "skill" outside fences.
    Nested braces are handled (old non-greedy regex dropped mid-object).
    """
    calls: list[dict] = []
    seen: set[str] = set()

    def _add(obj: dict | None) -> None:
        norm = _normalize_skill_call(obj) if obj else None
        if not norm:
            return
        key = json.dumps(norm, sort_keys=True, default=str)
        if key in seen:
            return
        seen.add(key)
        calls.append(norm)

    raw = text or ""
    for m in _SKILL_FENCE.finditer(raw):
        body = (m.group(1) or "").strip()
        if not body:
            continue
        # Form 1 / pure JSON body
        parsed_any = False
        for chunk in _extract_balanced_json_objects(body):
            try:
                obj = json.loads(chunk)
            except Exception:
                continue
            if isinstance(obj, dict) and (obj.get("skill") or obj.get("name") or obj.get("id")):
                _add(obj)
                parsed_any = True
            elif isinstance(obj, dict):
                # Form 2: skill id on first line, args JSON only
                first = body.splitlines()[0].strip() if body.splitlines() else ""
                # skill id as bare word / snake_case
                sid_m = re.match(r"^([a-z][a-z0-9_]{1,64})\s*$", first, re.I)
                if sid_m and not obj.get("skill"):
                    _add({"skill": sid_m.group(1), "args": obj})
                    parsed_any = True
                elif not obj.get("skill"):
                    # bare args with skill: line above
                    for line in body.splitlines()[:3]:
                        lm = re.match(r"^([a-z][a-z0-9_]{1,64})\s*$", line.strip(), re.I)
                        if lm:
                            _add({"skill": lm.group(1), "args": obj})
                            parsed_any = True
                            break
        if parsed_any:
            continue
        # Form 2 without nested detection: first line skill id + rest JSON
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        if len(lines) >= 2:
            sid_m = re.match(r"^([a-z][a-z0-9_]{1,64})$", lines[0], re.I)
            if sid_m:
                rest = "\n".join(lines[1:])
                for chunk in _extract_balanced_json_objects(rest) or ([rest] if rest.startswith("{") else []):
                    try:
                        args = json.loads(chunk)
                        if isinstance(args, dict):
                            if args.get("skill"):
                                _add(args)
                            else:
                                _add({"skill": sid_m.group(1), "args": args})
                    except Exception:
                        continue

    # Single-line JSON skill directives outside fences
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("{") and '"skill"' in line:
            try:
                obj = json.loads(line)
                _add(obj if isinstance(obj, dict) else None)
            except Exception:
                # try balanced extract from line
                for chunk in _extract_balanced_json_objects(line):
                    try:
                        _add(json.loads(chunk))
                    except Exception:
                        pass
    return calls


def strip_skill_blocks(text: str) -> str:
    cleaned = _SKILL_FENCE.sub("", text or "")
    # Remove leftover single-line skill JSON so chat stays human-readable
    lines_out = []
    for line in cleaned.splitlines():
        st = line.strip()
        if st.startswith("{") and '"skill"' in st:
            try:
                obj = json.loads(st)
                if isinstance(obj, dict) and obj.get("skill"):
                    continue
            except Exception:
                pass
        lines_out.append(line)
    cleaned = "\n".join(lines_out)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()



# Auto-generated skill dispatch table (from former elif chain). Do not hand-edit;
# re-run scripts/_refactor_skill_dispatch.py after adding skills, or append to HANDLER_TABLE.

# skill_id -> (handler_attr, mode, extra_args_tuple)
# mode: std | extra | meta | created | default
HANDLER_TABLE: dict[str, tuple[str, str, tuple]] = {
    'spawn_agent': ('_skill_spawn', 'std', ()),
    'message_agent': ('_skill_message', 'std', ()),
    'use_app': ('_skill_use_app', 'std', ()),
    'assign_human': ('_skill_assign_human', 'std', ()),
    'save_memory': ('_skill_save_memory', 'std', ()),
    'save_training': ('_skill_save_training', 'std', ()),
    'create_task': ('_skill_create_task', 'std', ()),
    'execute_goal': ('_skill_execute_goal', 'std', ()),
    'announce_plan': ('_skill_announce_plan', 'std', ()),
    'list_customers': ('_skill_list_customers', 'std', ()),
    'get_customer': ('_skill_get_customer', 'std', ()),
    'create_customer': ('_skill_create_customer', 'std', ()),
    'update_customer': ('_skill_update_customer', 'std', ()),
    'delete_customer': ('_skill_delete_customer', 'std', ()),
    'log_customer_activity': ('_skill_log_customer_activity', 'std', ()),
    'create_deal': ('_skill_create_deal', 'std', ()),
    'update_deal': ('_skill_update_deal', 'std', ()),
    'delete_deal': ('_skill_delete_deal', 'std', ()),
    'list_products': ('_skill_list_products', 'std', ()),
    'get_product': ('_skill_get_product', 'std', ()),
    'create_product': ('_skill_create_product', 'std', ()),
    'update_product': ('_skill_update_product', 'std', ()),
    'delete_product': ('_skill_delete_product', 'std', ()),
    'set_product_offer': ('_skill_set_product_offer', 'std', ()),
    'schedule_meeting': ('_skill_schedule_meeting', 'std', ()),
    'list_diary': ('_skill_list_diary', 'std', ()),
    'list_pipelines': ('_skill_list_pipelines', 'std', ()),
    'get_pipeline': ('_skill_get_pipeline', 'std', ()),
    'list_pipeline_stages': ('_skill_list_pipeline_stages', 'std', ()),
    'move_deal': ('_skill_move_deal', 'std', ()),
    'win_deal': ('_skill_win_deal', 'std', ()),
    'lose_deal': ('_skill_lose_deal', 'std', ()),
    'pipeline_summary': ('_skill_pipeline_summary', 'std', ()),
    'ensure_sales_pipeline': ('_skill_ensure_sales_pipeline', 'std', ()),
    'list_tasks': ('_skill_list_tasks', 'std', ()),
    'search_tasks': ('_skill_search_tasks', 'std', ()),
    'get_task': ('_skill_get_task', 'std', ()),
    'update_task': ('_skill_update_task', 'std', ()),
    'respond_to_task': ('_skill_respond_to_task', 'std', ()),
    'complete_task': ('_skill_complete_task', 'std', ()),
    'claim_task': ('_skill_claim_task', 'std', ()),
    'delete_task': ('_skill_delete_task', 'std', ()),
    'set_task_status': ('_skill_set_task_status', 'std', ()),
    'list_meetings': ('_skill_list_meetings', 'std', ()),
    'list_humans': ('_skill_list_humans', 'std', ()),
    'list_deals': ('_skill_list_deals', 'std', ()),
    'read_workspace': ('_skill_read_workspace', 'std', ()),
    'comment': ('_skill_comment', 'std', ()),
    'create_skill': ('_skill_create_skill', 'std', ()),
    'list_created_skills': ('_skill_list_created_skills', 'std', ()),
    'publish_skill_to_bay': ('_skill_publish_skill_to_bay', 'std', ()),
    'unpublish_skill_from_bay': ('_skill_unpublish_skill_from_bay', 'std', ()),
    'share_skill': ('_skill_share_skill', 'std', ()),
    'open_meeting': ('_skill_open_meeting', 'std', ()),
    'post_to_meeting': ('_skill_post_to_meeting', 'std', ()),
    'run_meeting_round': ('_skill_run_meeting_round', 'std', ()),
    'close_meeting': ('_skill_close_meeting', 'std', ()),
    'extract_meeting_tasks': ('_skill_extract_meeting_tasks', 'std', ()),
    'invite_to_meeting': ('_skill_invite_to_meeting', 'std', ()),
    'list_activity': ('_skill_list_activity', 'std', ()),
    'draft_email': ('_skill_draft_email', 'std', ()),
    'send_email': ('_skill_send_email', 'std', ()),
    'draft_sms': ('_skill_draft_sms', 'std', ()),
    'send_sms': ('_skill_send_sms', 'std', ()),
    'initiate_text': ('_skill_send_sms', 'std', ()),
    'send_whatsapp': ('_skill_send_whatsapp', 'std', ()),
    'make_voice_call': ('_skill_make_voice_call', 'std', ()),
    'initiate_call': ('_skill_make_voice_call', 'std', ()),
    'log_communication': ('_skill_log_communication', 'std', ()),
    'generate_image': ('_skill_generate_image', 'std', ()),
    'generate_video': ('_skill_generate_video', 'std', ()),
    'generate_content': ('_skill_generate_content', 'std', ()),
    'research': ('_skill_research', 'std', ()),
    'summarize': ('_skill_summarize', 'std', ()),
    'get_time': ('_skill_get_time', 'std', ()),
    'suggest_times': ('_skill_suggest_times', 'std', ()),
    'create_invoice_draft': ('_skill_create_invoice_draft', 'std', ()),
    'update_pipeline': ('_skill_update_pipeline', 'std', ()),
    'escalate_to_human': ('_skill_escalate_to_human', 'std', ()),
    'notify_human': ('_skill_notify_human', 'std', ()),
    'status_update': ('_skill_status_update', 'std', ()),
    'search_memory': ('_skill_search_memory', 'std', ()),
    'search_knowledge': ('_skill_search_knowledge', 'std', ()),
    'set_agent_status': ('_skill_set_agent_status', 'std', ()),
    'create_reminder': ('_skill_create_reminder', 'std', ()),
    'send_message': ('_skill_send_message', 'std', ()),
    'spawn_team': ('_skill_spawn_team', 'std', ()),
    'spawn_specialist': ('_skill_spawn_specialist', 'std', ()),
    'clone_agent': ('_skill_clone_agent', 'std', ()),
    'enable_skills_on': ('_skill_enable_skills_on', 'std', ()),
    'bulk_enable_skills': ('_skill_bulk_enable_skills', 'std', ()),
    'configure_agent': ('_skill_configure_agent', 'std', ()),
    'promote_to_lead': ('_skill_promote_to_lead', 'std', ()),
    'pause_agent': ('_skill_pause_agent', 'std', ()),
    'resume_agent': ('_skill_resume_agent', 'std', ()),
    'delete_agent': ('_skill_delete_agent', 'std', ()),
    'list_team': ('_skill_list_team', 'std', ()),
    # Full agent field / entity action skillset
    'get_agent': ('_skill_get_agent', 'std', ()),
    'add_agent': ('_skill_add_agent', 'std', ()),
    'create_agent': ('_skill_create_agent', 'std', ()),
    'change_agent': ('_skill_change_agent', 'std', ()),
    'update_agent': ('_skill_update_agent', 'std', ()),
    'reparent_agent': ('_skill_reparent_agent', 'std', ()),
    'demote_agent': ('_skill_demote_agent', 'std', ()),
    'rename_agent': ('_skill_rename_agent', 'std', ()),
    'set_agent_field': ('_skill_set_agent_field', 'std', ()),
    'list_agent_fields': ('_skill_list_agent_fields', 'std', ()),
    'agent_field_ops': ('_skill_agent_field_ops', 'std', ()),

    'facebook_post': ('_skill_facebook_post', 'std', ()),
    'facebook_reply_comment': ('_skill_facebook_reply_comment', 'std', ()),
    'facebook_reply_message': ('_skill_facebook_reply_message', 'std', ()),
    'facebook_get_comments': ('_skill_facebook_get_comments', 'std', ()),
    'facebook_get_posts': ('_skill_facebook_get_posts', 'std', ()),
    'facebook_get_conversations': ('_skill_facebook_get_conversations', 'std', ()),
    'facebook_like_comment': ('_skill_facebook_like_comment', 'std', ()),
    'instagram_post': ('_skill_instagram_post', 'std', ()),
    'instagram_reply_comment': ('_skill_instagram_reply_comment', 'std', ()),
    'instagram_get_comments': ('_skill_instagram_get_comments', 'std', ()),
    'instagram_get_media': ('_skill_instagram_get_media', 'std', ()),
    'linkedin_post': ('_skill_linkedin_post', 'std', ()),
    'linkedin_comment': ('_skill_linkedin_comment', 'std', ()),
    'linkedin_get_posts': ('_skill_linkedin_get_posts', 'std', ()),
    'linkedin_get_comments': ('_skill_linkedin_get_comments', 'std', ()),
    'x_post': ('_skill_x_post', 'std', ()),
    'x_reply': ('_skill_x_reply', 'std', ()),
    'x_get_mentions': ('_skill_x_get_mentions', 'std', ()),
    'x_get_timeline': ('_skill_x_get_timeline', 'std', ()),
    'x_search': ('_skill_x_search', 'std', ()),
    'gmail_send': ('_skill_gmail_send', 'std', ()),
    'gmail_reply': ('_skill_gmail_reply', 'std', ()),
    'gmail_draft': ('_skill_gmail_draft', 'std', ()),
    'gmail_list': ('_skill_gmail_list', 'std', ()),
    'gmail_get_thread': ('_skill_gmail_get_thread', 'std', ()),
    'gmail_search': ('_skill_gmail_search', 'std', ()),
    'gmail_archive': ('_skill_gmail_archive', 'std', ()),
    'email_send': ('_skill_send_email', 'std', ()),
    'email_reply': ('_skill_email_reply', 'std', ()),
    'slack_post': ('_skill_slack_post', 'std', ()),
    'slack_reply_thread': ('_skill_slack_reply_thread', 'std', ()),
    'slack_dm': ('_skill_slack_dm', 'std', ()),
    'slack_list_channels': ('_skill_slack_list_channels', 'std', ()),
    'slack_get_messages': ('_skill_slack_get_messages', 'std', ()),
    'calendar_create_event': ('_skill_calendar_create_event', 'std', ()),
    'calendar_list_events': ('_skill_calendar_list_events', 'std', ()),
    'calendar_update_event': ('_skill_calendar_update_event', 'std', ()),
    'calendar_delete_event': ('_skill_calendar_delete_event', 'std', ()),
    'sheets_append': ('_skill_sheets_append', 'std', ()),
    'sheets_read': ('_skill_sheets_read', 'std', ()),
    'sheets_update': ('_skill_sheets_update', 'std', ()),
    'sheets_create_sheet': ('_skill_sheets_create_sheet', 'std', ()),
    'shopify_create_order_note': ('_skill_shopify_action', 'extra', ('create_order_note',)),
    'shopify_update_product': ('_skill_shopify_action', 'extra', ('update_product',)),
    'shopify_get_products': ('_skill_shopify_action', 'extra', ('get_products',)),
    'shopify_get_orders': ('_skill_shopify_action', 'extra', ('get_orders',)),
    'shopify_get_customers': ('_skill_shopify_action', 'extra', ('get_customers',)),
    'shopify_update_customer': ('_skill_shopify_action', 'extra', ('update_customer',)),
    'shopify_fulfill_order': ('_skill_shopify_action', 'extra', ('fulfill_order',)),
    'shopify_sync_catalog': ('_skill_shopify_sync', 'std', ()),
    'shopify_push_product_tags': ('_skill_shopify_push_product', 'std', ()),
    'shopify_push_customer_tags': ('_skill_shopify_push_customer', 'std', ()),
    'hubspot_create_contact': ('_skill_hubspot_action', 'extra', ('create_contact',)),
    'hubspot_create_deal': ('_skill_hubspot_action', 'extra', ('create_deal',)),
    'hubspot_log_note': ('_skill_hubspot_action', 'extra', ('log_note',)),
    'hubspot_get_contacts': ('_skill_hubspot_action', 'extra', ('get_contacts',)),
    'notion_create_page': ('_skill_notion_action', 'extra', ('create_page',)),
    'notion_update_page': ('_skill_notion_action', 'extra', ('update_page',)),
    'notion_query_database': ('_skill_notion_action', 'extra', ('query_database',)),
    'notion_append_block': ('_skill_notion_action', 'extra', ('append_block',)),
    'discord_post': ('_skill_discord_action', 'extra', ('post',)),
    'discord_dm_user': ('_skill_discord_action', 'extra', ('dm_user',)),
    'whatsapp_send': ('_skill_send_whatsapp', 'std', ()),
    'whatsapp_reply': ('_skill_whatsapp_reply', 'std', ()),
    'mailchimp_add_subscriber': ('_skill_mailchimp_action', 'extra', ('add_subscriber',)),
    'mailchimp_create_campaign': ('_skill_mailchimp_action', 'extra', ('create_campaign',)),
    'dropbox_upload': ('_skill_dropbox_action', 'extra', ('upload',)),
    'dropbox_list': ('_skill_dropbox_action', 'extra', ('list',)),
}

DEFAULT_SKILL_HANDLER = '_skill_catalog_deliverable'
CUSTOM_SKILL_HANDLER = '_skill_run_created'

async def _dispatch_skill(
    skill_id: str,
    db,
    agent,
    user,
    args: dict,
    *,
    meta=None,
    is_custom: bool = False,
    custom_row=None,
):
    """Registry lookup — replaces the historical if/elif skill tree."""
    g = globals()
    if is_custom or (meta or {}).get("handler") == "created_skill":
        fn = g.get(CUSTOM_SKILL_HANDLER)
        if not fn:
            return {"ok": False, "error": "custom skill handler missing"}
        return await fn(db, agent, user, skill_id, meta, args, custom_row)

    entry = HANDLER_TABLE.get(skill_id)
    if entry:
        fname, mode, extras = entry
        fn = g.get(fname)
        if not fn:
            return {"ok": False, "error": f"handler {fname} missing"}
        if mode == "std":
            return await fn(db, agent, user, args)
        if mode == "extra":
            return await fn(db, agent, user, *extras, args)
        if mode == "meta":
            return await fn(db, agent, user, skill_id, meta, args)
        if mode == "created":
            return await fn(db, agent, user, skill_id, meta, args, custom_row)
        return await fn(db, agent, user, args)

    # Full agent field skillset: add_agent_<field> / change_agent_<field> / delete_agent_<field>
    try:
        from .skills.agent_actions import parse_agent_field_skill, _skill_agent_field_dispatch
        if parse_agent_field_skill(skill_id):
            return await _skill_agent_field_dispatch(db, agent, user, skill_id, args)
    except Exception:
        pass

    # Auto-generated per-field CRUD (add_*/change_*/delete_*) — pattern dispatch.
    # Skip via_alias matches (create_customer etc.) so HANDLER_TABLE / default path wins.
    _parse_field_skill = None
    _exec_field_skill = None
    try:
        from .skills import db_fields as _db_fields_mod

        _parse_field_skill = getattr(_db_fields_mod, "parse_skill_id", None)
        _exec_field_skill = (
            getattr(_db_fields_mod, "execute_field_skill", None)
            or getattr(_db_fields_mod, "_skill_db_field_dispatch", None)
            or getattr(_db_fields_mod, "FIELD_SKILL_HANDLER", None)
        )
    except Exception:
        pass
    if callable(_parse_field_skill) and callable(_exec_field_skill):
        try:
            _field_parsed = _parse_field_skill(skill_id)
        except Exception:
            _field_parsed = None
        _is_alias = isinstance(_field_parsed, dict) and _field_parsed.get("via_alias")
        if _field_parsed and not _is_alias:
            return await _exec_field_skill(db, agent, user, skill_id, args)

    # Catalog skills without dedicated side-effects
    fn = g.get(DEFAULT_SKILL_HANDLER)
    if not fn:
        return {"ok": False, "error": f"Unknown skill '{skill_id}'"}
    return await fn(db, agent, user, skill_id, meta, args)

async def execute_skill(
    db: Session,
    agent: models.Agent,
    user: models.User,
    skill_id: str,
    args: dict | None = None,
) -> dict[str, Any]:
    from .permissions import can_execute, can_delegate, can_manage, normalize_permission

    args = args or {}
    enabled = enabled_skill_ids(agent, db)
    # Custom skills (created by agents) are always runnable when they belong to this workspace
    custom_row = None
    if str(skill_id).startswith("custom_") or skill_id not in {s["id"] for s in SKILL_CATALOG}:
        try:
            custom_row = (
                db.query(models.CreatedSkill)
                .filter_by(user_id=user.id, skill_key=skill_id)
                .first()
            )
        except Exception:
            custom_row = None
    is_custom = custom_row is not None
    # Skill factory + marketplace meta always available to operators
    meta_skill_factory = skill_id in {
        "create_skill",
        "list_created_skills",
        "publish_skill_to_bay",
        "unpublish_skill_from_bay",
        "share_skill",
    }
    # Field CRUD: allow when db_field_ops (core) or parent entity update skill is enabled.
    # via_alias (create_customer / update_deal / …) keeps normal enable rules.
    field_gate_ok = False
    _field_parsed = None
    try:
        from .skills.db_fields import parse_skill_id as _parse_field_skill

        _field_parsed = _parse_field_skill(skill_id)
        _is_alias = isinstance(_field_parsed, dict) and _field_parsed.get("via_alias")
        if _field_parsed and not _is_alias:
            parent_skill = None
            if isinstance(_field_parsed, dict):
                parent_skill = (
                    _field_parsed.get("parent_skill")
                    or _field_parsed.get("entity_update_skill")
                    or _field_parsed.get("update_skill")
                )
                # Infer parent entity update skill: change_customer → update_customer
                if not parent_skill and _field_parsed.get("entity"):
                    parent_skill = f"update_{_field_parsed['entity']}"
            field_gate_ok = (
                "db_field_ops" in enabled
                or skill_id in enabled
                or (bool(parent_skill) and parent_skill in enabled)
            )
        if _is_alias:
            _field_parsed = None  # do not build synthetic meta for aliases
    except Exception:
        _field_parsed = None
        field_gate_ok = False

    # Agent field skillset: add_agent_* / change_agent_* / delete_agent_* / entity ops
    agent_field_gate_ok = False
    _agent_field_parsed = None
    try:
        from .skills.agent_actions import parse_agent_field_skill
        _agent_field_parsed = parse_agent_field_skill(skill_id)
        if _agent_field_parsed:
            agent_field_gate_ok = bool(
                "agent_field_ops" in enabled
                or "change_agent" in enabled
                or "configure_agent" in enabled
                or "update_agent" in enabled
                or skill_id in enabled
                or is_orchestrator(agent)
            )
    except Exception:
        _agent_field_parsed = None
        agent_field_gate_ok = False

    if (
        skill_id not in enabled
        and not is_orchestrator(agent)
        and not is_custom
        and not meta_skill_factory
        and not field_gate_ok
        and not agent_field_gate_ok
    ):
        return {"ok": False, "error": f"Skill '{skill_id}' is disabled for this agent"}

    meta = next((s for s in SKILL_CATALOG if s["id"] == skill_id), None)
    if not meta and is_custom:
        try:
            args_list = json.loads(custom_row.args_json or "[]")
        except Exception:
            args_list = []
        meta = {
            "id": custom_row.skill_key,
            "name": custom_row.name,
            "description": custom_row.description or "",
            "args": args_list,
            "roles": ["orchestrator", "lead", "member", "specialist"],
            "handler": "created_skill",
            "custom": True,
            "instructions": custom_row.instructions or "",
        }
    # Minimal meta for field skills not yet (or no longer) in SKILL_CATALOG
    if not meta and _field_parsed:
        if isinstance(_field_parsed, dict):
            meta = {
                "id": skill_id,
                "name": _field_parsed.get("name") or skill_id.replace("_", " ").title(),
                "description": _field_parsed.get("description") or f"Field skill {skill_id}",
                "args": list(_field_parsed.get("args") or ["entity_id", "value"]),
                "roles": list(
                    _field_parsed.get("roles")
                    or ["orchestrator", "lead", "member", "specialist"]
                ),
                "category": _field_parsed.get("category") or "data",
                "handler": "db_field",
                "field_skill": True,
            }
        else:
            meta = {
                "id": skill_id,
                "name": skill_id.replace("_", " ").title(),
                "description": f"Auto field skill: {skill_id}",
                "args": ["entity_id", "value"],
                "roles": ["orchestrator", "lead", "member", "specialist"],
                "category": "data",
                "handler": "db_field",
                "field_skill": True,
            }
    if not meta and _agent_field_parsed:
        meta = {
            "id": skill_id,
            "name": skill_id.replace("_", " ").title(),
            "description": f"Agent action: {skill_id}",
            "args": ["target_agent_id", "value"],
            "roles": ["orchestrator", "lead", "member", "specialist"],
            "category": "meta",
            "agent_action": True,
        }
    if not meta:
        return {"ok": False, "error": f"Unknown skill '{skill_id}'"}

    role = normalize_role(agent)
    # specialist inherits member skill roles (matches default_enabled / _CORE_ALWAYS)
    if not role_matches_skill(role, meta.get("roles")) and not is_orchestrator(agent):
        return {"ok": False, "error": f"Role '{role}' cannot use skill '{skill_id}'"}

    perm = normalize_permission(getattr(agent, "permission_level", None))
    # Assign human stays lead+; spawn is available to any operator (UI Spawn agent button)
    if skill_id == "assign_human" and not (
        can_delegate(perm) or is_orchestrator(agent)
    ):
        return {"ok": False, "error": f"Permission '{perm}' cannot assign humans — need lead or admin"}
    if skill_id == "spawn_agent" and not (
        can_execute(perm) or can_delegate(perm) or is_orchestrator(agent)
    ):
        return {"ok": False, "error": f"Permission '{perm}' cannot spawn — need operator or above"}
    # Core ops (in _CORE_ALWAYS): any operator+ may run; do not require lead
    if skill_id in (
        "create_task", "message_agent", "execute_goal",
        "open_meeting", "run_meeting_round", "extract_meeting_tasks",
        "status_update", "action_items",
    ) and not (
        can_execute(perm) or is_orchestrator(agent)
    ):
        return {"ok": False, "error": f"Permission '{perm}' cannot execute skills — need operator or above"}
    if skill_id in (
        "use_app", "save_memory", "save_training", "announce_plan",
        "post_to_meeting", "close_meeting",
    ) and not can_execute(perm):
        return {"ok": False, "error": f"Permission '{perm}' cannot execute skills"}

    # Gate integration skills (coming_soon apps / not connected)
    ok_int, err_int = integration_skill_available(skill_id, user.id, db, args)
    if not ok_int:
        return {"ok": False, "error": err_int}

    # Every skill requires an active plan + fuel (included tokens and/or wallet)
    try:
        from .auth_utils import ensure_credits as _ensure
        min_c = float(meta.get("cost_credits") or 0.01) if meta.get("premium") else None
        _ensure(db, user.id, min_credits=min_c)
    except Exception as e:
        return {"ok": False, "error": str(getattr(e, "detail", None) or e)}

    # Premium: hard wallet charge before execution (once). Handlers skip via _billed.
    if meta.get("premium"):
        try:
            charge_event(
                db, user,
                meta.get("meter_kind") or "premium-comm",
                text=json.dumps(args)[:500],
                cost_override=float(meta.get("cost_credits") or 0.02),
            )
            args = {**args, "_billed": True}
        except Exception as e:
            return {"ok": False, "error": str(getattr(e, "detail", None) or e)}

    await emit_ops(
        user.id,
        kind="skill",
        status="running",
        title=f"{agent.name} → {meta['name']}",
        detail=json.dumps(args)[:400],
        agent_id=agent.id,
        payload={"skill": skill_id, "args": args},
        db=db,
    )

    try:
        result = await _dispatch_skill(
            skill_id, db, agent, user, args,
            meta=meta, is_custom=is_custom, custom_row=custom_row,
        )
    except Exception as e:
        result = {"ok": False, "error": str(e)}

    # Bill every successful action (premium already charged; read/write/llm metered here)
    if isinstance(result, dict) and result.get("ok") is not False and not result.get("error"):
        try:
            usage = bill_skill_execution(
                db, user, skill_id, meta, result, args,
                company_id=getattr(agent, "company_id", None),
                project_id=getattr(agent, "project_id", None),
            )
            result = {**result, "usage": usage}
        except Exception as bill_err:
            # Do not free-run if billing hard-fails after a successful write
            if meta.get("premium"):
                result = {
                    "ok": False,
                    "error": f"Billing failed after skill: {getattr(bill_err, 'detail', None) or bill_err}",
                }
            else:
                # Soft: still return skill result but flag missing usage
                result = {**result, "usage_error": str(bill_err)[:200]}

    await emit_ops(
        user.id,
        kind="skill",
        status="done" if result.get("ok") else "failed",
        title=f"{agent.name} → {meta['name']}",
        detail=result.get("message") or result.get("error") or "",
        agent_id=agent.id,
        payload={"skill": skill_id, "result": result, "usage": result.get("usage") if isinstance(result, dict) else None},
        db=db,
    )
    return result


async def run_skills_from_text(
    db: Session,
    agent: models.Agent,
    user: models.User,
    text: str,
) -> tuple[str, list[dict]]:
    """Parse skill blocks, execute them, return cleaned reply + results."""
    calls = extract_skill_calls(text)
    results = []
    for call in calls:
        sid = str(call.get("skill") or "")
        args = call.get("args") if isinstance(call.get("args"), dict) else {
            k: v for k, v in call.items() if k != "skill"
        }
        r = await execute_skill(db, agent, user, sid, args)
        results.append({"skill": sid, **r})
    return strip_skill_blocks(text), results


def format_skill_results_human(skill_results: list[dict] | None, *, max_items: int = 12) -> str:
    """Rich human-readable summary of skill outcomes for chat replies."""
    if not skill_results:
        return ""
    lines: list[str] = []
    for r in skill_results[:max_items]:
        sid = r.get("skill") or "?"
        ok = bool(r.get("ok"))
        mark = "✓" if ok else "✗"
        msg = (r.get("message") or r.get("error") or ("ok" if ok else "failed")).strip()
        # Extra detail for product / CRM / task skills
        extra = []
        for key in (
            "product_id", "customer_id", "deal_id", "task_id", "meeting_id",
            "changed", "status", "title", "name",
        ):
            if r.get(key) is not None and key not in ("message",):
                val = r.get(key)
                if isinstance(val, list):
                    val = ", ".join(str(x) for x in val[:8])
                extra.append(f"{key}={val}")
        prod = r.get("product") if isinstance(r.get("product"), dict) else None
        if prod and prod.get("offer"):
            extra.append(f"offer={prod.get('offer')[:80]}")
        if prod and prod.get("price") is not None:
            extra.append(f"price={prod.get('price')} {prod.get('currency') or ''}".strip())
        detail = f" ({'; '.join(extra)})" if extra else ""
        lines.append(f"{mark} **{sid}**: {msg}{detail}")
    if not lines:
        return ""
    return "What I just did:\n" + "\n".join(f"- {ln}" for ln in lines)


# ── Load implementations from skills.handlers_all into this module ─────────
from .skills import handlers_all as _handlers_all  # noqa: E402

def _load_skill_handlers_into_globals() -> None:
    g = globals()
    for name, val in vars(_handlers_all).items():
        if name.startswith("_skill_") or name.startswith("_parse_") or name.startswith("_meeting_"):
            g[name] = val

_load_skill_handlers_into_globals()
