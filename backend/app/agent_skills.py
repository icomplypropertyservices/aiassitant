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
from .usage_billing import charge_usage, charge_event

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
        "roles": ["orchestrator", "lead"],
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
        "description": "Allocate a task to a human teammate.",
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
        "description": "Create a task for an agent or human.",
        "args": ["title", "description", "agent_id", "human_id", "priority"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "announce_plan",
        "name": "Announce plan",
        "description": "Publish a multi-step plan to the live ops banner.",
        "args": ["title", "steps"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
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
        "id": "update_customer",
        "name": "Update customer",
        "description": "Edit contact details, owner, tags, notes, status on an existing customer.",
        "args": ["customer_id", "email", "name", "phone", "status", "tags", "notes", "owner_human_id", "owner_agent_id"],
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
        "args": ["customer_id", "email", "title", "value", "priority", "expected_close"],
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
        "name": "Send SMS (premium)",
        "description": "Send a real SMS via Twilio. Premium paid skill.",
        "args": ["to", "body"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.015,
        "meter_kind": "premium-comm",
    },
    {
        "id": "send_whatsapp",
        "name": "Send WhatsApp (premium)",
        "description": "Send a real WhatsApp message via Twilio. Premium paid skill.",
        "args": ["to", "body"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.02,
        "meter_kind": "premium-comm",
    },
    {
        "id": "make_voice_call",
        "name": "Make voice call (premium)",
        "description": "Place a real phone call and speak a message via Twilio. Premium paid skill. Always meters tokens + credits.",
        "args": ["to", "message"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.08,
        "meter_kind": "voice_call",
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
        "description": "Move deals, update values, change stages, or close opportunities.",
        "args": ["deal_id", "stage_id", "status", "value", "notes"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "escalate_to_human",
        "name": "Escalate to human",
        "description": "Hand off a task or customer issue to a specific human teammate with context.",
        "args": ["human_id", "title", "details", "urgency", "customer_id"],
        "roles": ["orchestrator", "lead", "member"],
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
        "description": "Change model, personality, idle mode, permission level of another agent.",
        "args": ["target_agent_id", "model", "personality", "idle_mode", "permission_level"],
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
        "description": "Give the same powerful skill preset (full, sales, support, engineering, comms) to many agents at once.",
        "args": ["agent_ids", "preset", "extra_skills"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "configure_agent",
        "name": "Configure agent",
        "description": "Change model, personality, idle_mode, permission_level, escalate rules on another agent.",
        "args": ["target_agent_id", "model", "personality", "idle_mode", "permission_level", "escalate_when"],
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
        "description": "Create a crisp red/amber/green status report for stakeholders.",
        "args": ["project", "period", "highlights"],
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
        "description": "Send a real email from the connected Gmail account.",
        "args": ["to", "subject", "body", "cc", "bcc"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.02,
    },
    {
        "id": "gmail_reply",
        "name": "Gmail reply",
        "description": "Reply to a specific Gmail thread or message id.",
        "args": ["thread_id", "message_id", "body", "to"],
        "roles": ["orchestrator", "lead", "member"],
        "premium": True,
        "cost_credits": 0.015,
    },
    {
        "id": "gmail_draft",
        "name": "Gmail draft",
        "description": "Create a draft email in Gmail (not sent yet).",
        "args": ["to", "subject", "body"],
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
        "args": ["product_id", "title", "price", "inventory", "tags"],
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
        "description": "Search or list customers in the Shopify store.",
        "args": ["query", "limit"],
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

# Finalize: dedupe + categories (skills_policy)
from .skills_policy import (  # noqa: E402
    dedupe_catalog,
    default_enabled_for_role,
    group_skills_by_category,
    premium_skill_ids,
    integration_skill_available,
    category_for,
)

SKILL_CATALOG = dedupe_catalog(SKILL_CATALOG)

# Legacy name: full unique catalog ids (not the role pack)
DEFAULT_ENABLED = [s["id"] for s in SKILL_CATALOG]
PREMIUM_SKILL_IDS = premium_skill_ids(SKILL_CATALOG)

_SKILL_BLOCK = re.compile(
    r"```skill\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)


def list_skills_for_agent(agent: models.Agent, db: Session) -> list[dict]:
    role = normalize_role(agent)
    enabled = enabled_skill_ids(agent, db)
    out = []
    for s in SKILL_CATALOG:
        allowed_roles = s.get("roles") or []
        role_ok = role in allowed_roles or is_orchestrator(agent)
        app_ok, app_err = integration_skill_available(s["id"], agent.user_id, db, {})
        out.append({
            **s,
            "category": s.get("category") or category_for(s["id"]),
            "category_label": s.get("category_label"),
            "enabled": s["id"] in enabled and role_ok,
            "role_allowed": role_ok,
            "premium": bool(s.get("premium")),
            "cost_credits": float(s.get("cost_credits") or 0) if s.get("premium") else 0,
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
    role = normalize_role(agent)
    row = db.query(models.AgentSkillState).filter_by(agent_id=agent.id).first()
    if not row or not (row.enabled_json or "").strip():
        return set(default_enabled_for_role(role, SKILL_CATALOG))
    try:
        data = json.loads(row.enabled_json)
        if isinstance(data, list) and data:
            return set(str(x) for x in data)
    except Exception:
        pass
    return set(default_enabled_for_role(role, SKILL_CATALOG))


def set_enabled_skills(db: Session, agent: models.Agent, skill_ids: list[str]) -> list[str]:
    valid = {s["id"] for s in SKILL_CATALOG}
    clean = [s for s in skill_ids if s in valid]
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


def skills_prompt_block(agent: models.Agent, db: Session, *, max_skills: int = 48) -> str:
    """Compact skill catalogue for the LLM system prompt.

    Listing all 248 skills on every chat blows context (10k+ tokens) and makes
    replies slow/empty in the UI. Keep a short always-on core + category summary.
    """
    skills = [s for s in list_skills_for_agent(agent, db) if s.get("enabled")]
    if not skills:
        return ""

    # High-value skills always listed first (orchestrator / daily ops)
    priority_ids = [
        "create_task", "message_agent", "spawn_agent", "list_team", "list_customers",
        "save_memory", "save_training", "announce_plan", "draft_email", "generate_content",
        "research", "summarize", "get_time", "search_memory", "escalate_to_human",
        "log_customer_activity", "create_deal", "prioritize_list", "action_items",
        "skill_recommend", "enable_skills_on", "configure_agent",
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
        "You have SKILLS. When you need to act (not just answer), emit one or more blocks:",
        "```skill",
        '{"skill":"<id>","args":{...}}',
        "```",
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
    calls = []
    for m in _SKILL_BLOCK.finditer(text or ""):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and obj.get("skill"):
                calls.append(obj)
        except Exception:
            continue
    # Also accept single-line JSON skill directives
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("{") and '"skill"' in line:
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and obj.get("skill") and obj not in calls:
                    calls.append(obj)
            except Exception:
                pass
    return calls


def strip_skill_blocks(text: str) -> str:
    cleaned = _SKILL_BLOCK.sub("", text or "")
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


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
    if skill_id not in enabled and not is_orchestrator(agent):
        return {"ok": False, "error": f"Skill '{skill_id}' is disabled for this agent"}

    meta = next((s for s in SKILL_CATALOG if s["id"] == skill_id), None)
    if not meta:
        return {"ok": False, "error": f"Unknown skill '{skill_id}'"}

    role = normalize_role(agent)
    if role not in (meta.get("roles") or []) and not is_orchestrator(agent):
        return {"ok": False, "error": f"Role '{role}' cannot use skill '{skill_id}'"}

    perm = normalize_permission(getattr(agent, "permission_level", None))
    if skill_id in ("spawn_agent", "assign_human", "create_task", "message_agent") and not (
        can_delegate(perm) or is_orchestrator(agent)
    ):
        return {"ok": False, "error": f"Permission '{perm}' cannot delegate/spawn — need lead or admin"}
    if skill_id in ("use_app", "save_memory", "save_training", "announce_plan") and not can_execute(perm):
        return {"ok": False, "error": f"Permission '{perm}' cannot execute skills"}

    # Gate integration skills (coming_soon apps / not connected)
    ok_int, err_int = integration_skill_available(skill_id, user.id, db, args)
    if not ok_int:
        return {"ok": False, "error": err_int}

    # Premium only: wallet-hard charge before execution (once).
    # Non-premium skills never force wallet here — they use included tokens via LLM/chat billing.
    if meta.get("premium"):
        try:
            from .auth_utils import ensure_credits as _ensure
            _ensure(db, user.id, min_credits=float(meta.get("cost_credits") or 0.01))
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
        if skill_id == "spawn_agent":
            result = await _skill_spawn(db, agent, user, args)
        elif skill_id == "message_agent":
            result = await _skill_message(db, agent, user, args)
        elif skill_id == "use_app":
            result = await _skill_use_app(db, agent, user, args)
        elif skill_id == "assign_human":
            result = await _skill_assign_human(db, agent, user, args)
        elif skill_id == "save_memory":
            result = await _skill_save_memory(db, agent, user, args)
        elif skill_id == "save_training":
            result = await _skill_save_training(db, agent, user, args)
        elif skill_id == "create_task":
            result = await _skill_create_task(db, agent, user, args)
        elif skill_id == "announce_plan":
            result = await _skill_announce_plan(db, agent, user, args)
        elif skill_id == "list_customers":
            result = await _skill_list_customers(db, agent, user, args)
        elif skill_id == "get_customer":
            result = await _skill_get_customer(db, agent, user, args)
        elif skill_id == "update_customer":
            result = await _skill_update_customer(db, agent, user, args)
        elif skill_id == "log_customer_activity":
            result = await _skill_log_customer_activity(db, agent, user, args)
        elif skill_id == "create_deal":
            result = await _skill_create_deal(db, agent, user, args)
        elif skill_id == "schedule_meeting":
            result = await _skill_schedule_meeting(db, agent, user, args)
        elif skill_id == "list_diary":
            result = await _skill_list_diary(db, agent, user, args)

        # ── New comprehensive comms & power skills ─────────────────
        elif skill_id == "draft_email":
            result = await _skill_draft_email(db, agent, user, args)
        elif skill_id == "send_email":
            result = await _skill_send_email(db, agent, user, args)
        elif skill_id == "draft_sms":
            result = await _skill_draft_sms(db, agent, user, args)
        elif skill_id == "send_sms":
            result = await _skill_send_sms(db, agent, user, args)
        elif skill_id == "send_whatsapp":
            result = await _skill_send_whatsapp(db, agent, user, args)
        elif skill_id == "make_voice_call":
            result = await _skill_make_voice_call(db, agent, user, args)
        elif skill_id == "log_communication":
            result = await _skill_log_communication(db, agent, user, args)
        elif skill_id == "generate_image":
            result = await _skill_generate_image(db, agent, user, args)
        elif skill_id == "generate_video":
            result = await _skill_generate_video(db, agent, user, args)

        elif skill_id == "generate_content":
            result = await _skill_generate_content(db, agent, user, args)
        elif skill_id == "research":
            result = await _skill_research(db, agent, user, args)
        elif skill_id == "summarize":
            result = await _skill_summarize(db, agent, user, args)

        elif skill_id == "get_time":
            result = await _skill_get_time(db, agent, user, args)
        elif skill_id == "suggest_times":
            result = await _skill_suggest_times(db, agent, user, args)

        elif skill_id == "create_invoice_draft":
            result = await _skill_create_invoice_draft(db, agent, user, args)
        elif skill_id == "update_pipeline":
            result = await _skill_update_pipeline(db, agent, user, args)
        elif skill_id == "escalate_to_human":
            result = await _skill_escalate_to_human(db, agent, user, args)

        elif skill_id == "search_memory":
            result = await _skill_search_memory(db, agent, user, args)
        elif skill_id == "search_knowledge":
            result = await _skill_search_knowledge(db, agent, user, args)

        elif skill_id == "set_agent_status":
            result = await _skill_set_agent_status(db, agent, user, args)
        elif skill_id == "create_reminder":
            result = await _skill_create_reminder(db, agent, user, args)

        # Smart unified send (best general communication skill)
        elif skill_id == "send_message":
            result = await _skill_send_message(db, agent, user, args)

        # ── META AGENT MAKING SKILLS (spawn 40s of agents + enable their skills) ──
        elif skill_id == "spawn_team":
            result = await _skill_spawn_team(db, agent, user, args)
        elif skill_id == "spawn_specialist":
            result = await _skill_spawn_specialist(db, agent, user, args)
        elif skill_id == "clone_agent":
            result = await _skill_clone_agent(db, agent, user, args)
        elif skill_id == "enable_skills_on":
            result = await _skill_enable_skills_on(db, agent, user, args)
        elif skill_id == "bulk_enable_skills":
            result = await _skill_bulk_enable_skills(db, agent, user, args)
        elif skill_id == "configure_agent":
            result = await _skill_configure_agent(db, agent, user, args)
        elif skill_id == "promote_to_lead":
            result = await _skill_promote_to_lead(db, agent, user, args)
        elif skill_id == "pause_agent":
            result = await _skill_pause_agent(db, agent, user, args)
        elif skill_id == "resume_agent":
            result = await _skill_resume_agent(db, agent, user, args)
        elif skill_id == "delete_agent":
            result = await _skill_delete_agent(db, agent, user, args)
        elif skill_id == "list_team":
            result = await _skill_list_team(db, agent, user, args)

        # ── CONNECTED APPS — FULL ACTIONS (Facebook, Instagram, X, LinkedIn, Gmail, Slack, Calendar, Sheets, Shopify, etc.) ──
        # Facebook
        elif skill_id == "facebook_post":
            result = await _skill_facebook_post(db, agent, user, args)
        elif skill_id == "facebook_reply_comment":
            result = await _skill_facebook_reply_comment(db, agent, user, args)
        elif skill_id == "facebook_reply_message":
            result = await _skill_facebook_reply_message(db, agent, user, args)
        elif skill_id == "facebook_get_comments":
            result = await _skill_facebook_get_comments(db, agent, user, args)
        elif skill_id == "facebook_get_posts":
            result = await _skill_facebook_get_posts(db, agent, user, args)
        elif skill_id == "facebook_get_conversations":
            result = await _skill_facebook_get_conversations(db, agent, user, args)
        elif skill_id == "facebook_like_comment":
            result = await _skill_facebook_like_comment(db, agent, user, args)

        # Instagram
        elif skill_id == "instagram_post":
            result = await _skill_instagram_post(db, agent, user, args)
        elif skill_id == "instagram_reply_comment":
            result = await _skill_instagram_reply_comment(db, agent, user, args)
        elif skill_id == "instagram_get_comments":
            result = await _skill_instagram_get_comments(db, agent, user, args)
        elif skill_id == "instagram_get_media":
            result = await _skill_instagram_get_media(db, agent, user, args)

        # LinkedIn
        elif skill_id == "linkedin_post":
            result = await _skill_linkedin_post(db, agent, user, args)
        elif skill_id == "linkedin_comment":
            result = await _skill_linkedin_comment(db, agent, user, args)
        elif skill_id == "linkedin_get_posts":
            result = await _skill_linkedin_get_posts(db, agent, user, args)
        elif skill_id == "linkedin_get_comments":
            result = await _skill_linkedin_get_comments(db, agent, user, args)

        # X / Twitter
        elif skill_id == "x_post":
            result = await _skill_x_post(db, agent, user, args)
        elif skill_id == "x_reply":
            result = await _skill_x_reply(db, agent, user, args)
        elif skill_id == "x_get_mentions":
            result = await _skill_x_get_mentions(db, agent, user, args)
        elif skill_id == "x_get_timeline":
            result = await _skill_x_get_timeline(db, agent, user, args)
        elif skill_id == "x_search":
            result = await _skill_x_search(db, agent, user, args)

        # Gmail + generic email
        elif skill_id == "gmail_send":
            result = await _skill_gmail_send(db, agent, user, args)
        elif skill_id == "gmail_reply":
            result = await _skill_gmail_reply(db, agent, user, args)
        elif skill_id == "gmail_draft":
            result = await _skill_gmail_draft(db, agent, user, args)
        elif skill_id == "gmail_list":
            result = await _skill_gmail_list(db, agent, user, args)
        elif skill_id == "gmail_get_thread":
            result = await _skill_gmail_get_thread(db, agent, user, args)
        elif skill_id == "gmail_search":
            result = await _skill_gmail_search(db, agent, user, args)
        elif skill_id == "gmail_archive":
            result = await _skill_gmail_archive(db, agent, user, args)
        elif skill_id == "email_send":
            result = await _skill_send_email(db, agent, user, args)
        elif skill_id == "email_reply":
            result = await _skill_email_reply(db, agent, user, args)

        # Slack
        elif skill_id == "slack_post":
            result = await _skill_slack_post(db, agent, user, args)
        elif skill_id == "slack_reply_thread":
            result = await _skill_slack_reply_thread(db, agent, user, args)
        elif skill_id == "slack_dm":
            result = await _skill_slack_dm(db, agent, user, args)
        elif skill_id == "slack_list_channels":
            result = await _skill_slack_list_channels(db, agent, user, args)
        elif skill_id == "slack_get_messages":
            result = await _skill_slack_get_messages(db, agent, user, args)

        # Google Calendar
        elif skill_id == "calendar_create_event":
            result = await _skill_calendar_create_event(db, agent, user, args)
        elif skill_id == "calendar_list_events":
            result = await _skill_calendar_list_events(db, agent, user, args)
        elif skill_id == "calendar_update_event":
            result = await _skill_calendar_update_event(db, agent, user, args)
        elif skill_id == "calendar_delete_event":
            result = await _skill_calendar_delete_event(db, agent, user, args)

        # Google Sheets
        elif skill_id == "sheets_append":
            result = await _skill_sheets_append(db, agent, user, args)
        elif skill_id == "sheets_read":
            result = await _skill_sheets_read(db, agent, user, args)
        elif skill_id == "sheets_update":
            result = await _skill_sheets_update(db, agent, user, args)
        elif skill_id == "sheets_create_sheet":
            result = await _skill_sheets_create_sheet(db, agent, user, args)

        # Shopify
        elif skill_id == "shopify_create_order_note":
            result = await _skill_shopify_action(db, agent, user, "create_order_note", args)
        elif skill_id == "shopify_update_product":
            result = await _skill_shopify_action(db, agent, user, "update_product", args)
        elif skill_id == "shopify_get_orders":
            result = await _skill_shopify_action(db, agent, user, "get_orders", args)
        elif skill_id == "shopify_get_customers":
            result = await _skill_shopify_action(db, agent, user, "get_customers", args)
        elif skill_id == "shopify_fulfill_order":
            result = await _skill_shopify_action(db, agent, user, "fulfill_order", args)

        # HubSpot
        elif skill_id == "hubspot_create_contact":
            result = await _skill_hubspot_action(db, agent, user, "create_contact", args)
        elif skill_id == "hubspot_create_deal":
            result = await _skill_hubspot_action(db, agent, user, "create_deal", args)
        elif skill_id == "hubspot_log_note":
            result = await _skill_hubspot_action(db, agent, user, "log_note", args)
        elif skill_id == "hubspot_get_contacts":
            result = await _skill_hubspot_action(db, agent, user, "get_contacts", args)

        # Notion
        elif skill_id == "notion_create_page":
            result = await _skill_notion_action(db, agent, user, "create_page", args)
        elif skill_id == "notion_update_page":
            result = await _skill_notion_action(db, agent, user, "update_page", args)
        elif skill_id == "notion_query_database":
            result = await _skill_notion_action(db, agent, user, "query_database", args)
        elif skill_id == "notion_append_block":
            result = await _skill_notion_action(db, agent, user, "append_block", args)

        # Discord
        elif skill_id == "discord_post":
            result = await _skill_discord_action(db, agent, user, "post", args)
        elif skill_id == "discord_dm_user":
            result = await _skill_discord_action(db, agent, user, "dm_user", args)

        # WhatsApp (explicit)
        elif skill_id == "whatsapp_send":
            result = await _skill_send_whatsapp(db, agent, user, args)
        elif skill_id == "whatsapp_reply":
            result = await _skill_whatsapp_reply(db, agent, user, args)

        # Others (Mailchimp, Dropbox)
        elif skill_id == "mailchimp_add_subscriber":
            result = await _skill_mailchimp_action(db, agent, user, "add_subscriber", args)
        elif skill_id == "mailchimp_create_campaign":
            result = await _skill_mailchimp_action(db, agent, user, "create_campaign", args)
        elif skill_id == "dropbox_upload":
            result = await _skill_dropbox_action(db, agent, user, "upload", args)
        elif skill_id == "dropbox_list":
            result = await _skill_dropbox_action(db, agent, user, "list", args)

        else:
            # Catalog skills without dedicated side-effects: structured LLM deliverable
            # (sales scripts, reports, code drafts, HR copy, etc.)
            result = await _skill_catalog_deliverable(db, agent, user, skill_id, meta, args)
    except Exception as e:
        result = {"ok": False, "error": str(e)}

    await emit_ops(
        user.id,
        kind="skill",
        status="done" if result.get("ok") else "failed",
        title=f"{agent.name} → {meta['name']}",
        detail=result.get("message") or result.get("error") or "",
        agent_id=agent.id,
        payload={"skill": skill_id, "result": result},
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


# ── Individual skills ────────────────────────────────────────────────────

async def _skill_spawn(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    name = (args.get("name") or "New agent").strip()[:120]
    template = (args.get("template_type") or "custom").strip()[:80]
    personality = (args.get("personality") or "Professional, helpful, concise.").strip()
    hrole = (args.get("hierarchy_role") or "member").strip()
    if hrole not in ("lead", "member", "specialist"):
        hrole = "member"
    parent_id = args.get("parent_id")
    if parent_id is None:
        parent_id = agent.id if not is_orchestrator(agent) else None
    else:
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            parent_id = agent.id

    from .agent_scaffold import map_model, repair_agent

    child = models.Agent(
        user_id=user.id,
        company_id=agent.company_id,
        project_id=agent.project_id,
        parent_id=parent_id,
        hierarchy_role=hrole,
        is_lead=hrole == "lead",
        name=name,
        template_type=template,
        personality=personality,
        model=map_model(agent.model or "fast"),
        status="active",
        idle_mode="never_idle",
        permission_level="lead" if hrole == "lead" else "operator",
        config=json.dumps({"autonomy": "full", "spawned_by": agent.id}),
        escalate_when="on_failure",
        escalate_to="parent",
    )
    db.add(child)
    db.flush()
    repair_agent(db, child, force_never_idle=True, expand_skills=True)
    db.commit()
    db.refresh(child)
    return {
        "ok": True,
        "message": f"Spawned autonomous agent {child.name} (id={child.id})",
        "agent": {
            "id": child.id,
            "name": child.name,
            "hierarchy_role": child.hierarchy_role,
            "model": child.model,
            "idle_mode": child.idle_mode,
            "permission_level": child.permission_level,
        },
    }


async def _skill_message(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        to_id = int(args.get("to_agent_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "to_agent_id required"}
    target = db.get(models.Agent, to_id)
    if not target or target.user_id != user.id:
        return {"ok": False, "error": "Target agent not found"}
    content = (args.get("message") or "").strip()
    if not content:
        return {"ok": False, "error": "message required"}

    pair = sorted([agent.id, target.id])
    thread_key = f"{pair[0]}-{pair[1]}"
    msg = models.AgentMessage(
        user_id=user.id,
        from_agent_id=agent.id,
        to_agent_id=target.id,
        thread_key=thread_key,
        content=content,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    reply_text = None
    if args.get("expect_reply", True):
        # Lightweight auto-reply from target using their personality (no nested skill loop)
        from .llm import complete
        from .user_keys import credentials_for_user
        from .agent_prompts import build_agent_system_prompt

        system = build_agent_system_prompt(db, target)
        prompt = (
            f"You received an internal message from teammate agent "
            f"{agent.name} (id={agent.id}):\n\n{content}\n\n"
            "Reply helpfully in 1-3 short paragraphs. Do not emit skill blocks."
        )
        creds = credentials_for_user(db, user.id)
        try:
            reply_text = await complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                target.model or "quality",
                "general",
                credentials=creds,
            )
            reply_text = (reply_text or "").strip()
            if reply_text:
                reply = models.AgentMessage(
                    user_id=user.id,
                    from_agent_id=target.id,
                    to_agent_id=agent.id,
                    thread_key=thread_key,
                    content=reply_text,
                )
                db.add(reply)
                db.commit()
                # Agent-to-agent LLM always meters tokens
                try:
                    from .usage_billing import bill_llm_turn
                    bill_llm_turn(
                        db, user, target.model or "fast",
                        [{"role": "user", "content": prompt}],
                        reply_text,
                    )
                except Exception:
                    pass
        except Exception as e:
            reply_text = f"(auto-reply failed: {e})"

    return {
        "ok": True,
        "message": f"Messaged {target.name}",
        "thread_key": thread_key,
        "message_id": msg.id,
        "reply": reply_text,
    }


async def _skill_use_app(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from .integration_actions import run_app_action

    app_id = (args.get("app_id") or "").strip().lower()
    action = (args.get("action") or "status").strip().lower()
    payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
    if not app_id:
        return {"ok": False, "error": "app_id required"}

    # Must be allocated to this agent
    links = db.query(models.AgentIntegration).filter_by(agent_id=agent.id).all()
    conn = None
    for link in links:
        c = db.get(models.IntegrationConnection, link.connection_id)
        if c and c.app_id == app_id and c.user_id == user.id:
            conn = c
            break
    if not conn:
        # Fall back to any connected app of that type for orchestrators
        if is_orchestrator(agent):
            conn = (
                db.query(models.IntegrationConnection)
                .filter_by(user_id=user.id, app_id=app_id, status="connected")
                .order_by(models.IntegrationConnection.id.desc())
                .first()
            )
    if not conn:
        return {"ok": False, "error": f"No connected '{app_id}' app allocated to this agent"}

    result = await run_app_action(conn, action, payload)
    return result


async def _skill_assign_human(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        human_id = int(args.get("human_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "human_id required"}
    human = db.get(models.Human, human_id)
    if not human or human.owner_user_id != user.id:
        return {"ok": False, "error": "Human not found"}
    title = (args.get("title") or args.get("description") or "Work item")[:120]
    description = (args.get("description") or title).strip()
    priority = args.get("priority") or "medium"
    t = models.Task(
        user_id=user.id,
        agent_id=agent.id,
        human_id=human.id,
        assignee_type="human",
        company_id=human.company_id or agent.company_id,
        project_id=human.project_id or agent.project_id,
        title=title,
        description=f"[Assigned by agent {agent.name}] {description}",
        status="todo",
        priority=priority,
        labels="human,allocated",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    await emit_ops(
        user.id,
        kind="human",
        status="queued",
        title=f"Work for {human.name}",
        detail=title,
        agent_id=agent.id,
        human_id=human.id,
        task_id=t.id,
        db=db,
    )
    return {
        "ok": True,
        "message": f"Assigned to {human.name}",
        "task_id": t.id,
        "human": {"id": human.id, "name": human.name},
    }


async def _skill_save_memory(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    content = (args.get("content") or "").strip()
    if not content:
        return {"ok": False, "error": "content required"}
    mem = models.AgentMemory(
        agent_id=agent.id,
        user_id=user.id,
        kind=(args.get("kind") or "note")[:40],
        title=(args.get("title") or content[:60])[:200],
        content=content,
        tags=(args.get("tags") or "")[:200],
    )
    db.add(mem)
    db.commit()
    db.refresh(mem)
    return {"ok": True, "message": "Saved to agent data vault", "memory_id": mem.id}


async def _skill_save_training(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    content = (args.get("content") or "").strip()
    if not content:
        return {"ok": False, "error": "content required"}
    title = (args.get("title") or f"From {agent.name}")[:200]
    folder_id = args.get("folder_id")
    try:
        folder_id = int(folder_id) if folder_id is not None else None
    except (TypeError, ValueError):
        folder_id = None

    kf = models.KnowledgeFile(
        user_id=user.id,
        folder_id=folder_id,
        name=title,
        description=f"Saved by agent {agent.name}",
        tags=(args.get("tags") or "agent-saved")[:200],
        kind="note",
        storage="local",
        mime_type="text/plain",
        size_bytes=len(content.encode("utf-8")),
        content_text=content,
        status="ready",
    )
    db.add(kf)
    db.flush()
    # Grant this agent access
    db.add(models.AgentKnowledgeAccess(
        agent_id=agent.id,
        resource_type="file",
        resource_id=kf.id,
        permission="read",
    ))
    # Also keep a memory pointer
    mem = models.AgentMemory(
        agent_id=agent.id,
        user_id=user.id,
        kind="training_candidate",
        title=title,
        content=content[:2000],
        tags="training",
        knowledge_file_id=kf.id,
    )
    db.add(mem)
    db.commit()
    db.refresh(kf)
    return {
        "ok": True,
        "message": f"Saved to training library as '{title}'",
        "knowledge_file_id": kf.id,
    }


async def _skill_create_task(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    title = (args.get("title") or args.get("description") or "Task")[:120]
    description = (args.get("description") or title).strip()
    agent_id = args.get("agent_id") or agent.id
    human_id = args.get("human_id")
    try:
        agent_id = int(agent_id) if agent_id is not None else agent.id
    except (TypeError, ValueError):
        agent_id = agent.id
    try:
        human_id = int(human_id) if human_id is not None else None
    except (TypeError, ValueError):
        human_id = None

    target = db.get(models.Agent, agent_id)
    if not target or target.user_id != user.id:
        return {"ok": False, "error": "agent not found"}

    t = models.Task(
        user_id=user.id,
        agent_id=target.id,
        human_id=human_id,
        assignee_type="human" if human_id else "agent",
        company_id=target.company_id,
        project_id=target.project_id,
        title=title,
        description=description,
        status="todo",
        priority=args.get("priority") or "medium",
        labels="skill-created",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"ok": True, "message": "Task created", "task_id": t.id}


async def _skill_announce_plan(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    title = (args.get("title") or "Plan")[:200]
    steps = args.get("steps") or []
    if isinstance(steps, str):
        steps = [s.strip() for s in steps.split("\n") if s.strip()]
    if not isinstance(steps, list):
        steps = []
    plan_id = f"plan-{uuid.uuid4().hex[:10]}"
    await emit_ops(
        user.id,
        kind="plan",
        status="running",
        title=title,
        detail=f"{len(steps)} steps",
        agent_id=agent.id,
        plan_id=plan_id,
        payload={"steps": steps},
        db=db,
    )
    for i, step in enumerate(steps[:20], 1):
        text = step if isinstance(step, str) else json.dumps(step)
        await emit_ops(
            user.id,
            kind="step",
            status="queued",
            title=f"Step {i}",
            detail=text[:500],
            agent_id=agent.id,
            plan_id=plan_id,
            db=db,
        )
    return {"ok": True, "message": f"Plan announced ({len(steps)} steps)", "plan_id": plan_id}


# ── CRM + Diary skill implementations (operate on existing customers) ────

async def _skill_list_customers(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from .routers.business import _customer_out
    q = (args.get("q") or "").strip()
    status = args.get("status")
    tag = args.get("tag")
    try:
        limit = min(100, int(args.get("limit") or 25))
    except Exception:
        limit = 25
    query = db.query(models.Customer).filter_by(owner_user_id=user.id)
    if status:
        query = query.filter_by(status=status)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (models.Customer.name.ilike(like)) |
            (models.Customer.email.ilike(like)) |
            (models.Customer.account_name.ilike(like)) |
            (models.Customer.phone.ilike(like))
        )
    if tag:
        query = query.filter(models.Customer.tags.ilike(f"%{tag}%"))
    rows = query.order_by(models.Customer.updated_at.desc()).limit(limit).all()
    return {
        "ok": True,
        "count": len(rows),
        "customers": [_customer_out(c, db, light=True) for c in rows],
    }


async def _skill_get_customer(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from .routers.business import _customer_out, _owned_customer
    cid = args.get("customer_id")
    email = (args.get("email") or "").strip()
    cust = None
    if cid:
        try:
            cust = _owned_customer(db, int(cid), user)
        except Exception:
            cust = None
    if not cust and email:
        cust = db.query(models.Customer).filter_by(owner_user_id=user.id, email=email).first()
    if not cust:
        return {"ok": False, "error": "customer not found (provide customer_id or email)"}
    deals = db.query(models.Deal).filter_by(customer_id=cust.id).order_by(models.Deal.updated_at.desc()).limit(10).all()
    acts = db.query(models.CustomerActivity).filter_by(customer_id=cust.id).order_by(models.CustomerActivity.id.desc()).limit(15).all()
    diary = db.query(models.DiaryEntry).filter_by(customer_id=cust.id).order_by(models.DiaryEntry.start_at.asc().nullslast()).limit(10).all()
    return {
        "ok": True,
        "customer": _customer_out(cust, db),
        "deals": [{"id": d.id, "title": d.title, "value": d.value, "status": d.status, "stage_id": d.stage_id} for d in deals],
        "recent_activity": [{"id": a.id, "kind": a.kind, "title": a.title, "body": a.body, "created_at": a.created_at} for a in acts],
        "diary": [{"id": d.id, "title": d.title, "start_at": d.start_at, "status": d.status} for d in diary],
    }


async def _skill_update_customer(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from .routers.business import _customer_out
    cid = args.get("customer_id")
    email = (args.get("email") or "").strip()
    cust = None
    if cid:
        try:
            cust = db.get(models.Customer, int(cid))
        except Exception:
            cust = None
    if not cust and email:
        cust = db.query(models.Customer).filter_by(owner_user_id=user.id, email=email).first()
    if not cust or cust.owner_user_id != user.id:
        return {"ok": False, "error": "customer not found or not owned"}
    for f in ("name", "phone", "status", "tags", "notes"):
        if args.get(f) is not None:
            val = args[f]
            setattr(cust, f, (val or "").strip() if isinstance(val, str) else val)
    if args.get("owner_human_id") is not None:
        cust.owner_human_id = args.get("owner_human_id") or None
    if args.get("owner_agent_id") is not None:
        cust.owner_agent_id = args.get("owner_agent_id") or None
    cust.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(cust)
    return {"ok": True, "message": f"Updated {cust.name}", "customer": _customer_out(cust, db, light=True)}


async def _skill_log_customer_activity(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    cid = args.get("customer_id")
    email = (args.get("email") or "").strip()
    cust = None
    if cid:
        try:
            cust = db.get(models.Customer, int(cid))
        except Exception:
            cust = None
    if not cust and email:
        cust = db.query(models.Customer).filter_by(owner_user_id=user.id, email=email).first()
    if not cust or cust.owner_user_id != user.id:
        return {"ok": False, "error": "customer not found or not owned"}
    kind = (args.get("kind") or "note").strip()
    title = (args.get("title") or kind.title()).strip()
    body = (args.get("body") or "").strip()
    a = models.CustomerActivity(
        customer_id=cust.id,
        owner_user_id=user.id,
        kind=kind,
        title=title,
        body=body,
        agent_id=agent.id,
    )
    db.add(a)
    cust.last_contacted_at = datetime.utcnow()
    cust.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(a)
    await emit_ops(user.id, kind="action", status="info", title=f"{cust.name}: {title}", detail=body[:180], agent_id=agent.id, db=db)
    return {"ok": True, "activity_id": a.id, "kind": kind}


async def _skill_create_deal(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from .routers.business import _deal_out, _owned_customer, _ensure_default_pipeline
    cid = args.get("customer_id")
    email = (args.get("email") or "").strip()
    cust = None
    if cid:
        try:
            cust = _owned_customer(db, int(cid), user)
        except Exception:
            cust = None
    if not cust and email:
        cust = db.query(models.Customer).filter_by(owner_user_id=user.id, email=email).first()
    if not cust or cust.owner_user_id != user.id:
        return {"ok": False, "error": "customer not found or not owned"}
    pipe = _ensure_default_pipeline(db, user)
    stage = db.query(models.PipelineStage).filter_by(pipeline_id=pipe.id).order_by(models.PipelineStage.position).first()
    if not stage:
        return {"ok": False, "error": "no stages in default pipeline"}
    title = (args.get("title") or f"Opportunity for {cust.name}")[:200]
    d = models.Deal(
        owner_user_id=user.id,
        pipeline_id=pipe.id,
        stage_id=stage.id,
        customer_id=cust.id,
        title=title,
        value=float(args.get("value") or 0),
        currency="USD",
        status="open",
        priority=args.get("priority") or "medium",
        expected_close=_parse_dt_safe(args.get("expected_close")),
        owner_agent_id=agent.id,
    )
    db.add(d)
    db.flush()
    db.add(models.CustomerActivity(
        customer_id=cust.id,
        owner_user_id=user.id,
        kind="deal",
        title=f"Deal created by {agent.name}: {title}",
        body=f"Value: {d.value}",
        deal_id=d.id,
        agent_id=agent.id,
    ))
    db.commit()
    db.refresh(d)
    return {"ok": True, "deal": _deal_out(d, db)}


def _parse_dt_safe(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", ""))
    except Exception:
        return None


async def _skill_schedule_meeting(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    cid = args.get("customer_id")
    email = (args.get("email") or "").strip()
    cust = None
    if cid:
        try:
            cust = db.get(models.Customer, int(cid))
        except Exception:
            cust = None
    if not cust and email:
        cust = db.query(models.Customer).filter_by(owner_user_id=user.id, email=email).first()
    if not cust or cust.owner_user_id != user.id:
        return {"ok": False, "error": "customer not found or not owned"}
    title = (args.get("title") or f"Meeting with {cust.name}")[:200]
    start = _parse_dt_safe(args.get("start_at"))
    end = _parse_dt_safe(args.get("end_at"))
    d = models.DiaryEntry(
        owner_user_id=user.id,
        customer_id=cust.id,
        title=title,
        start_at=start,
        end_at=end,
        location=(args.get("location") or "").strip(),
        notes=(args.get("notes") or "").strip(),
        status="scheduled",
        owner_human_id=args.get("owner_human_id"),
        owner_agent_id=agent.id,
    )
    db.add(d)
    db.flush()
    db.add(models.CustomerActivity(
        customer_id=cust.id,
        owner_user_id=user.id,
        kind="meeting",
        title=f"Scheduled: {title}",
        body=f"{start.isoformat() if start else 'TBD'} @ {d.location or '—'}",
        agent_id=agent.id,
    ))
    cust.last_contacted_at = datetime.utcnow()
    db.commit()
    db.refresh(d)
    await emit_ops(user.id, kind="action", status="info", title=f"Diary: {title}", detail=cust.name, agent_id=agent.id, db=db)
    return {
        "ok": True,
        "diary_id": d.id,
        "title": d.title,
        "start_at": d.start_at,
        "status": d.status,
    }


async def _skill_list_diary(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    cid = args.get("customer_id")
    email = (args.get("email") or "").strip()
    status = args.get("status")
    upcoming = bool(args.get("upcoming"))
    q = db.query(models.DiaryEntry).filter_by(owner_user_id=user.id)
    if cid:
        try:
            q = q.filter_by(customer_id=int(cid))
        except Exception:
            pass
    elif email:
        c = db.query(models.Customer).filter_by(owner_user_id=user.id, email=email).first()
        if c:
            q = q.filter_by(customer_id=c.id)
    if status:
        q = q.filter_by(status=status)
    if upcoming:
        now = datetime.utcnow()
        q = q.filter(models.DiaryEntry.status == "scheduled", (models.DiaryEntry.start_at >= now) | (models.DiaryEntry.start_at.is_(None)))
    rows = q.order_by(models.DiaryEntry.start_at.asc().nullslast(), models.DiaryEntry.id.desc()).limit(50).all()
    out = []
    for d in rows:
        cust = db.get(models.Customer, d.customer_id)
        out.append({
            "id": d.id,
            "customer_id": d.customer_id,
            "customer_name": cust.name if cust else None,
            "title": d.title,
            "start_at": d.start_at,
            "end_at": d.end_at,
            "location": d.location,
            "status": d.status,
        })
    return {"ok": True, "count": len(out), "diary": out}


# ─────────────────────────────────────────────────────────────────────────────
# NEW COMPREHENSIVE + PREMIUM COMMUNICATION SKILLS IMPLEMENTATIONS
# Email, SMS, WhatsApp, Voice are first-class and the best ones are charged
# ─────────────────────────────────────────────────────────────────────────────

async def _skill_draft_email(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    to = (args.get("to") or "").strip()
    subject = (args.get("subject") or "Follow-up").strip()
    body = (args.get("body") or "").strip()
    tone = args.get("tone") or "professional"
    if not to:
        return {"ok": False, "error": "to (email address) is required"}
    if not body:
        body = f"Hi,\n\nI wanted to follow up regarding our conversation.\n\nBest regards,\n{agent.name}"
    return {
        "ok": True,
        "draft": True,
        "to": to,
        "subject": subject,
        "body": body,
        "tone": tone,
        "note": "This is a draft. Call send_email (premium) to actually deliver it."
    }


async def _skill_send_email(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    to = (args.get("to") or "").strip()
    subject = (args.get("subject") or "Message from " + agent.name).strip()
    body = (args.get("body") or "").strip()
    if not to or not body:
        return {"ok": False, "error": "to and body are required"}

    if not args.get("_billed"):
        meta = next((s for s in SKILL_CATALOG if s["id"] == "send_email"), {})
        _charge_premium(db, user, meta, 0.02, text=body)

    sent, detail = await channels.send_email(to, subject, body)
    await emit_ops(user.id, kind="action", status="done" if sent else "failed",
                   title=f"Email {'sent' if sent else 'drafted'}", detail=to, agent_id=agent.id, db=db)
    return {"ok": sent, "to": to, "subject": subject, "detail": detail}


async def _skill_draft_sms(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    to = (args.get("to") or "").strip()
    body = (args.get("body") or "").strip()
    if not to:
        return {"ok": False, "error": "to (phone number) is required"}
    return {"ok": True, "draft": True, "to": to, "body": body, "note": "Draft only. Use send_sms to actually deliver (premium)."}


async def _skill_send_sms(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    to = (args.get("to") or "").strip()
    body = (args.get("body") or "").strip()
    if not to or not body:
        return {"ok": False, "error": "to and body are required"}

    if not args.get("_billed"):
        meta = next((s for s in SKILL_CATALOG if s["id"] == "send_sms"), {})
        _charge_premium(db, user, meta, 0.015, text=body)

    sent, detail = await channels.send_sms(to, body)
    await emit_ops(user.id, kind="action", status="done" if sent else "failed",
                   title=f"SMS {'sent' if sent else 'drafted'}", detail=to, agent_id=agent.id, db=db)
    return {"ok": sent, "to": to, "detail": detail}


async def _skill_send_whatsapp(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    to = (args.get("to") or "").strip()
    body = (args.get("body") or "").strip()
    if not to or not body:
        return {"ok": False, "error": "to (whatsapp:+number) and body are required"}

    if not args.get("_billed"):
        meta = next((s for s in SKILL_CATALOG if s["id"] == "send_whatsapp"), {})
        _charge_premium(db, user, meta, 0.02, text=body)

    sent, detail = await channels.send_whatsapp(to, body)
    await emit_ops(user.id, kind="action", status="done" if sent else "failed",
                   title=f"WhatsApp {'sent' if sent else 'drafted'}", detail=to, agent_id=agent.id, db=db)
    return {"ok": sent, "to": to, "detail": detail}


async def _skill_make_voice_call(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    to = (args.get("to") or "").strip()
    message = (args.get("message") or f"Hello from {agent.name}. This is an automated call with an important update.").strip()
    if not to:
        return {"ok": False, "error": "to (phone number) is required"}

    if not args.get("_billed"):
        meta = next((s for s in SKILL_CATALOG if s["id"] == "make_voice_call"), {})
        _charge_premium(db, user, meta, 0.08, text=message)

    sent, detail = await channels.make_call(to, message)
    await emit_ops(user.id, kind="action", status="done" if sent else "failed",
                   title=f"Voice call {'placed' if sent else 'scripted'}", detail=to, agent_id=agent.id, db=db)
    return {"ok": sent, "to": to, "detail": detail}


async def _skill_generate_image(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    prompt = (args.get("prompt") or "").strip()
    if len(prompt) < 3:
        return {"ok": False, "error": "prompt is required"}
    meta = next((s for s in SKILL_CATALOG if s["id"] == "generate_image"), {})
    # If execute_skill already charged premium, avoid double-charge when called via run
    # Skills run path charges once here when not charged upstream — check cost_credits flag
    if not args.get("_billed"):
        _charge_premium(db, user, meta, 0.06, text=prompt)

    from .routers.media import _svg_placeholder
    url = _svg_placeholder(prompt, "image")
    # Try live image API when available
    try:
        from . import config
        import httpx
        key = config.get_grok_token() or ""
        if key:
            async with httpx.AsyncClient(timeout=90) as client:
                r = await client.post(
                    "https://api.x.ai/v1/images/generations",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model": "grok-imagine-image", "prompt": prompt, "n": 1},
                )
                if r.status_code < 400:
                    body = r.json()
                    u = (body.get("data") or [{}])[0].get("url")
                    if u:
                        url = u
    except Exception:
        pass

    await emit_ops(
        user.id, kind="action", status="done",
        title="Image generated", detail=prompt[:120], agent_id=agent.id, db=db,
    )
    return {"ok": True, "url": url, "prompt": prompt, "style": args.get("style"), "size": args.get("size")}


async def _skill_generate_video(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    prompt = (args.get("prompt") or "").strip()
    if len(prompt) < 3:
        return {"ok": False, "error": "prompt is required"}
    meta = next((s for s in SKILL_CATALOG if s["id"] == "generate_video"), {})
    if not args.get("_billed"):
        _charge_premium(db, user, meta, 0.25, text=prompt)

    from .routers.media import _svg_placeholder
    poster = _svg_placeholder(prompt, "video")
    await emit_ops(
        user.id, kind="action", status="done",
        title="Video job created", detail=prompt[:120], agent_id=agent.id, db=db,
    )
    return {
        "ok": True,
        "poster_url": poster,
        "video_url": None,
        "prompt": prompt,
        "duration_sec": args.get("duration_sec") or 4,
        "note": "Poster ready. Full video URL when media worker is configured.",
    }


async def _skill_log_communication(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    cid = args.get("customer_id")
    email = (args.get("email") or "").strip()
    kind = (args.get("kind") or "email").strip()
    to = (args.get("to") or "").strip()
    title = (args.get("subject_or_title") or "").strip()
    body = (args.get("body") or "").strip()

    cust = None
    if cid:
        try:
            cust = db.get(models.Customer, int(cid))
        except Exception:
            pass
    elif email:
        cust = db.query(models.Customer).filter_by(owner_user_id=user.id, email=email).first()

    if cust:
        db.add(models.CustomerActivity(
            customer_id=cust.id,
            owner_user_id=user.id,
            kind=kind,
            title=title or f"{kind.title()} sent",
            body=body[:500],
            agent_id=agent.id,
        ))
        cust.last_contacted_at = datetime.utcnow()
        db.commit()

    return {"ok": True, "logged": True, "kind": kind, "to": to or email, "customer_id": getattr(cust, 'id', None)}


async def _skill_catalog_deliverable(
    db: Session,
    agent: models.Agent,
    user: models.User,
    skill_id: str,
    meta: dict,
    args: dict,
) -> dict:
    """
    Generic path for catalog skills without a dedicated side-effect handler.

    Marks the skill as accepted and gives the model a concrete deliverable brief
    so agents never hit hard "not implemented" for sales/HR/code/content skills.
    Optionally runs a short LLM completion when a model is available.
    """
    name = (meta or {}).get("name") or skill_id
    desc = (meta or {}).get("description") or ""
    brief = {
        "skill": skill_id,
        "name": name,
        "description": desc,
        "args": args or {},
        "agent": getattr(agent, "name", None),
        "role": getattr(agent, "hierarchy_role", None) or getattr(agent, "template_type", None),
    }
    instruction = (
        f"You are executing skill '{name}' ({skill_id}).\n"
        f"Goal: {desc}\n"
        f"Arguments: {json.dumps(args or {}, default=str)[:2000]}\n"
        "Produce a complete, usable deliverable (not a plan to do it later)."
    )
    content = ""
    try:
        from .llm import complete
        from .agent_scaffold import resolve_runtime

        rt = resolve_runtime(agent)
        model = getattr(rt, "model", None) or agent.model or "vps-fast"
        # Prefer a quality text model when on VPS placeholder ids
        messages = [
            {
                "role": "system",
                "content": f"You are {agent.name}, a business AI agent. Output only the deliverable.",
            },
            {"role": "user", "content": instruction},
        ]
        content = await complete(
            messages,
            model=model,
            mode=getattr(rt, "mode_hint", None) or "general",
        )
        content = (content or "").strip()
        # Always meter tokens for catalog deliverables (draft skills)
        if content:
            try:
                from .usage_billing import bill_llm_turn
                bill_llm_turn(db, user, model, messages, content)
            except Exception:
                pass
    except Exception as e:
        # Still ok — caller LLM can finish from the brief
        content = ""
        brief["llm_error"] = str(e)[:200]

    # Persist short memory so later turns can reuse
    try:
        title = f"Skill: {name}"
        body = content[:3500] if content else instruction[:1500]
        db.add(
            models.AgentMemory(
                agent_id=agent.id,
                user_id=user.id,
                kind="deliverable",
                title=title[:200],
                content=body,
                tags=skill_id,
            )
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    return {
        "ok": True,
        "mode": "catalog_deliverable",
        "skill": skill_id,
        "name": name,
        "brief": brief,
        "content": content or None,
        "message": (
            f"Skill '{name}' completed."
            if content
            else f"Skill '{name}' accepted — produce the deliverable from the brief."
        ),
        "instruction": instruction,
    }


async def _skill_generate_content(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    ctype = args.get("type") or "email"
    topic = args.get("topic") or ""
    audience = args.get("audience") or ""
    tone = args.get("tone") or "professional"
    length = args.get("length") or "medium"
    keywords = args.get("keywords") or ""
    # The actual generation happens in the LLM reply. This skill just structures the request.
    return {"ok": True, "request": {"type": ctype, "topic": topic, "audience": audience, "tone": tone, "length": length, "keywords": keywords}}


async def _skill_research(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    return {"ok": True, "request": {"query": args.get("query"), "depth": args.get("depth", "normal"), "focus": args.get("focus")}}


async def _skill_summarize(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    return {"ok": True, "request": {"format": args.get("format", "bullets"), "max_points": args.get("max_points", 8)}}


async def _skill_get_time(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from datetime import datetime, timezone
    tz = args.get("timezone") or "UTC"
    now = datetime.now(timezone.utc)
    return {"ok": True, "iso": now.isoformat(), "timezone": tz, "note": "Use for scheduling logic."}


async def _skill_suggest_times(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    return {"ok": True, "suggestions": ["Tomorrow 10:00", "Tomorrow 14:30", "Friday 09:00"], "duration_minutes": args.get("duration_minutes", 30)}


async def _skill_create_invoice_draft(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    return {"ok": True, "draft": True, "customer_id": args.get("customer_id"), "items": args.get("items", []), "message": "Invoice draft prepared."}


async def _skill_update_pipeline(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    # Lightweight wrapper – actual work is done via business router in practice
    return {"ok": True, "request": args, "note": "Best used together with business CRM endpoints."}


async def _skill_escalate_to_human(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    return await _skill_assign_human(db, agent, user, {
        "human_id": args.get("human_id"),
        "title": args.get("title"),
        "description": args.get("details"),
        "priority": args.get("urgency", "high"),
    })


async def _skill_search_memory(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    q = (args.get("query") or "").lower()
    mems = db.query(models.AgentMemory).filter_by(agent_id=agent.id).order_by(models.AgentMemory.id.desc()).limit(50).all()
    hits = [m for m in mems if q in (m.content or "").lower() or q in (m.title or "").lower()]
    return {"ok": True, "hits": [{"id": h.id, "title": h.title, "content": h.content[:400], "kind": h.kind} for h in hits[:10]]}


async def _skill_search_knowledge(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    return {"ok": True, "request": args, "note": "Search knowledge base via training endpoints for best results."}


async def _skill_set_agent_status(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    if args.get("idle_mode"):
        agent.idle_mode = args["idle_mode"]
    if args.get("permission_level"):
        agent.permission_level = args["permission_level"]
    db.commit()
    return {"ok": True, "updated": {"idle_mode": agent.idle_mode, "permission_level": agent.permission_level}}


async def _skill_create_reminder(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    return await _skill_create_task(db, agent, user, {
        "title": args.get("title"),
        "description": args.get("title"),
        "agent_id": args.get("for_agent_id"),
        "human_id": args.get("for_human_id"),
        "priority": "medium",
    })


async def _skill_send_message(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Smart unified communication skill.
    channel can be: email | sms | whatsapp | voice | auto (default)
    This is the single best skill for agents to use when they want to reach a human.
    """
    to = (args.get("to") or "").strip()
    body = (args.get("body") or args.get("message") or "").strip()
    subject = args.get("subject") or f"Update from {agent.name}"
    channel = (args.get("channel") or "auto").lower()
    cid = args.get("customer_id")

    if not to or not body:
        return {"ok": False, "error": "to and body are required"}

    # Try to resolve customer for logging
    cust = None
    if cid:
        try:
            cust = db.get(models.Customer, int(cid))
        except Exception:
            pass

    # Auto-detect channel from "to"
    if channel == "auto":
        if "@" in to:
            channel = "email"
        elif to.lower().startswith("whatsapp:") or "whatsapp" in to.lower():
            channel = "whatsapp"
        elif to.replace("+", "").replace("-", "").replace(" ", "").isdigit():
            channel = "sms"
        else:
            channel = "sms"

    result = {"ok": False}

    billed = bool(args.get("_billed"))
    if channel == "email":
        meta = next((s for s in SKILL_CATALOG if s["id"] == "send_email"), {})
        _charge_premium(db, user, meta, 0.02, text=body, already_billed=billed)
        sent, detail = await channels.send_email(to, subject, body)
        result = {"ok": sent, "channel": "email", "to": to, "detail": detail}

    elif channel == "sms":
        meta = next((s for s in SKILL_CATALOG if s["id"] == "send_sms"), {})
        _charge_premium(db, user, meta, 0.015, text=body, already_billed=billed)
        sent, detail = await channels.send_sms(to, body)
        result = {"ok": sent, "channel": "sms", "to": to, "detail": detail}

    elif channel == "whatsapp":
        meta = next((s for s in SKILL_CATALOG if s["id"] == "send_whatsapp"), {})
        _charge_premium(db, user, meta, 0.02, text=body, already_billed=billed)
        sent, detail = await channels.send_whatsapp(to, body)
        result = {"ok": sent, "channel": "whatsapp", "to": to, "detail": detail}

    elif channel == "voice":
        meta = next((s for s in SKILL_CATALOG if s["id"] == "make_voice_call"), {})
        _charge_premium(db, user, meta, 0.08, text=body, already_billed=billed)
        sent, detail = await channels.make_call(to, body)
        result = {"ok": sent, "channel": "voice", "to": to, "detail": detail}

    else:
        meta = next((s for s in SKILL_CATALOG if s["id"] == "send_email"), {})
        _charge_premium(db, user, meta, 0.02, text=body, already_billed=billed)
        sent, detail = await channels.send_email(to, subject, body)
        result = {"ok": sent, "channel": "email", "to": to, "detail": detail}

    # Log to CRM if we have a customer
    if cust:
        db.add(models.CustomerActivity(
            customer_id=cust.id,
            owner_user_id=user.id,
            kind=channel if channel in ("email", "sms", "call") else "note",
            title=f"{channel.title()} via {agent.name}",
            body=body[:400],
            agent_id=agent.id,
        ))
        cust.last_contacted_at = datetime.utcnow()
        db.commit()

    await emit_ops(user.id, kind="action", status="done" if result.get("ok") else "failed",
                   title=f"Sent via {result.get('channel', channel)}", detail=to, agent_id=agent.id, db=db)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# META SKILLS — "spawn 40 agents making them"
# These let agents autonomously create, configure, clone and skill-enable dozens of agents.
# ─────────────────────────────────────────────────────────────────────────────

async def _skill_spawn_team(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Spawn N agents quickly with optional preset skills. Core engine for building big teams."""
    try:
        count = max(1, min(80, int(args.get("count") or 5)))
    except Exception:
        count = 5
    base = (args.get("base_name") or "Specialist").strip() or "Specialist"
    templates = args.get("template_types") or ["member"]
    if isinstance(templates, str):
        templates = [t.strip() for t in templates.split(",") if t.strip()]
    parent_id = args.get("parent_id")
    if parent_id is None:
        parent_id = agent.id if not is_orchestrator(agent) else None
    preset = (args.get("enable_preset") or "full").lower()

    from .agent_scaffold import scaffold_agent, map_model

    created = []
    for i in range(count):
        ttype = templates[i % len(templates)] if templates else "member"
        name = f"{base} {i+1}"
        while db.query(models.Agent).filter_by(user_id=user.id, name=name).first():
            name = f"{base} {i+1}-{uuid.uuid4().hex[:4]}"

        hrole = "lead" if ttype in ("lead", "orchestrator") else ("specialist" if ttype == "specialist" else "member")
        child = models.Agent(
            user_id=user.id,
            company_id=agent.company_id,
            project_id=agent.project_id,
            parent_id=parent_id,
            hierarchy_role=hrole,
            is_lead=hrole in ("lead", "orchestrator"),
            name=name,
            template_type=ttype,
            personality="Autonomous specialist created by " + agent.name,
            model=map_model(agent.model),
            status="active",
            idle_mode="never_idle",
            permission_level="lead" if hrole == "lead" else "operator",
            config=json.dumps({"autonomy": "full", "spawned_by": agent.id, "spawn_team": True}),
            escalate_when="on_failure",
            escalate_to="parent",
        )
        db.add(child)
        db.flush()
        scaffold_agent(db, child, full_skills=True)
        if preset:
            await _apply_preset_skills(db, child, preset)
        created.append({"id": child.id, "name": child.name, "role": hrole})
    db.commit()
    return {"ok": True, "count": len(created), "agents": created, "message": f"Spawned team of {len(created)} agents."}


async def _apply_preset_skills(db: Session, target: models.Agent, preset: str):
    """Helper used by spawn + bulk_enable."""
    valid = {s["id"] for s in SKILL_CATALOG}
    preset = (preset or "").lower()
    base = set(DEFAULT_ENABLED)

    if preset in ("full", "all"):
        to_enable = list(valid)
    elif preset == "sales":
        to_enable = [x for x in base if any(k in x for k in ("sales", "lead", "proposal", "outreach", "cold", "book", "qualif", "close", "churn", "upsell"))] or base
    elif preset == "support":
        to_enable = [x for x in base if any(k in x for k in ("support", "ticket", "triage", "refund", "escalat", "onboard", "knowledge", "health", "cancel"))] or base
    elif preset == "engineering":
        to_enable = [x for x in base if any(k in x for k in ("code", "api", "test", "debug", "refactor", "docker", "ci", "migration", "review", "arch"))] or base
    elif preset == "comms":
        to_enable = [x for x in base if any(k in x for k in ("email", "sms", "whatsapp", "voice", "send", "call", "message"))] or base
    elif preset == "content":
        to_enable = [x for x in base if any(k in x for k in ("content", "linkedin", "twitter", "ad", "newsletter", "seo", "video", "script", "blog"))] or base
    else:
        to_enable = list(base)

    set_enabled_skills(db, target, list(to_enable)[:220])


async def _skill_spawn_specialist(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    domain = (args.get("domain") or "specialist").strip()
    name = (args.get("name") or f"{domain.title()} Specialist").strip()
    parent_id = args.get("parent_id") or (agent.id if not is_orchestrator(agent) else None)
    extra = args.get("skills") or []

    from .agent_scaffold import scaffold_agent, map_model

    child = models.Agent(
        user_id=user.id,
        company_id=agent.company_id,
        project_id=agent.project_id,
        parent_id=parent_id,
        hierarchy_role="specialist",
        is_lead=False,
        name=name,
        template_type=domain.lower()[:40],
        personality=f"World-class specialist in {domain}. Created by {agent.name}.",
        model=map_model(agent.model),
        status="active",
        idle_mode="never_idle",
        permission_level="operator",
        config=json.dumps({"autonomy": "full", "domain": domain, "spawned_by": agent.id}),
        escalate_when="on_failure",
        escalate_to="parent",
    )
    db.add(child)
    db.flush()
    scaffold_agent(db, child, full_skills=True)

    wanted = set(DEFAULT_ENABLED)
    for sid in (extra or []):
        if sid in {s["id"] for s in SKILL_CATALOG}:
            wanted.add(sid)
    set_enabled_skills(db, child, list(wanted))
    db.commit()
    db.refresh(child)
    return {"ok": True, "agent": {"id": child.id, "name": child.name}, "message": f"Spawned specialist {name}"}


async def _skill_clone_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        src_id = int(args.get("source_agent_id"))
    except Exception:
        return {"ok": False, "error": "source_agent_id required"}
    src = db.get(models.Agent, src_id)
    if not src or src.user_id != user.id:
        return {"ok": False, "error": "Source agent not found"}

    new_name = (args.get("new_name") or (src.name + " (clone)"))[:120]
    parent = args.get("parent_id") or src.parent_id

    from .agent_scaffold import scaffold_agent, map_model
    clone = models.Agent(
        user_id=user.id,
        company_id=src.company_id,
        project_id=src.project_id,
        parent_id=parent,
        hierarchy_role=src.hierarchy_role,
        is_lead=src.is_lead,
        name=new_name,
        template_type=src.template_type,
        personality=src.personality,
        model=map_model(src.model),
        status="active",
        idle_mode=src.idle_mode or "never_idle",
        permission_level=src.permission_level,
        config=src.config,
        escalate_when=src.escalate_when or "on_failure",
        escalate_to=src.escalate_to or "parent",
        escalate_reason=getattr(src, "escalate_reason", ""),
    )
    db.add(clone)
    db.flush()
    scaffold_agent(db, clone, full_skills=True)

    src_enabled = enabled_skill_ids(src, db)
    if src_enabled:
        set_enabled_skills(db, clone, list(src_enabled))
    db.commit()
    db.refresh(clone)
    return {"ok": True, "cloned": {"id": clone.id, "name": clone.name, "from": src.id}}


async def _skill_enable_skills_on(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        target_id = int(args.get("target_agent_id"))
    except Exception:
        return {"ok": False, "error": "target_agent_id required"}
    tgt = db.get(models.Agent, target_id)
    if not tgt or tgt.user_id != user.id:
        return {"ok": False, "error": "Target agent not found"}

    skill_ids = args.get("skill_ids") or []
    if isinstance(skill_ids, str):
        skill_ids = [s.strip() for s in skill_ids.split(",") if s.strip()]
    valid = {s["id"] for s in SKILL_CATALOG}
    clean = [s for s in skill_ids if s in valid]
    if not clean:
        return {"ok": False, "error": "No valid skill_ids provided"}

    existing = enabled_skill_ids(tgt, db)
    new_set = list(set(existing) | set(clean))
    set_enabled_skills(db, tgt, new_set)
    await emit_ops(user.id, kind="skill", status="done",
                   title=f"Enabled {len(clean)} skills on {tgt.name}", agent_id=agent.id, db=db)
    return {"ok": True, "target": tgt.id, "enabled_now": len(new_set), "added": len(clean)}


async def _skill_bulk_enable_skills(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    ids = args.get("agent_ids") or []
    if isinstance(ids, str):
        ids = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    preset = args.get("preset") or "full"
    extra = args.get("extra_skills") or []

    results = []
    for aid in ids:
        try:
            a = db.get(models.Agent, int(aid))
            if a and a.user_id == user.id:
                await _apply_preset_skills(db, a, preset)
                if extra:
                    cur = enabled_skill_ids(a, db)
                    add = [x for x in extra if x in {s["id"] for s in SKILL_CATALOG}]
                    set_enabled_skills(db, a, list(set(cur) | set(add)))
                results.append({"id": a.id, "name": a.name, "ok": True})
        except Exception as e:
            results.append({"id": aid, "ok": False, "error": str(e)})
    db.commit()
    return {"ok": True, "updated": len([r for r in results if r.get("ok")]), "results": results}


async def _skill_configure_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        tgt = db.get(models.Agent, int(args.get("target_agent_id")))
    except Exception:
        return {"ok": False, "error": "target_agent_id required"}
    if not tgt or tgt.user_id != user.id:
        return {"ok": False, "error": "Target not found"}

    for field in ("model", "personality", "idle_mode", "permission_level", "escalate_when"):
        if args.get(field) is not None:
            setattr(tgt, field, args[field])
    db.commit()
    return {"ok": True, "configured": tgt.id, "name": tgt.name}


async def _skill_promote_to_lead(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        tgt = db.get(models.Agent, int(args.get("agent_id")))
    except Exception:
        return {"ok": False, "error": "agent_id required"}
    if not tgt or tgt.user_id != user.id:
        return {"ok": False, "error": "Agent not found"}

    tgt.hierarchy_role = "lead"
    tgt.is_lead = True
    tgt.permission_level = "lead"

    report_ids = args.get("report_agent_ids") or []
    wired = 0
    for rid in report_ids:
        try:
            r = db.get(models.Agent, int(rid))
            if r and r.user_id == user.id:
                r.parent_id = tgt.id
                wired += 1
        except Exception:
            pass
    db.commit()
    return {"ok": True, "promoted": tgt.id, "reports_wired": wired}


async def _skill_pause_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        tgt = db.get(models.Agent, int(args.get("target_agent_id")))
    except Exception:
        return {"ok": False, "error": "target_agent_id required"}
    if not tgt or tgt.user_id != user.id:
        return {"ok": False, "error": "not found"}
    tgt.status = "paused"
    tgt.idle_mode = "allow_idle"
    db.commit()
    return {"ok": True, "paused": tgt.id}


async def _skill_resume_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        tgt = db.get(models.Agent, int(args.get("target_agent_id")))
    except Exception:
        return {"ok": False, "error": "target_agent_id required"}
    if not tgt or tgt.user_id != user.id:
        return {"ok": False, "error": "not found"}
    tgt.status = "active"
    tgt.idle_mode = "never_idle"
    db.commit()
    return {"ok": True, "resumed": tgt.id}


async def _skill_delete_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        tgt = db.get(models.Agent, int(args.get("target_agent_id")))
    except Exception:
        return {"ok": False, "error": "target_agent_id required"}
    if not tgt or tgt.user_id != user.id:
        return {"ok": False, "error": "not found"}
    if is_orchestrator(tgt):
        return {"ok": False, "error": "Cannot delete the orchestrator"}
    db.delete(tgt)
    db.commit()
    return {"ok": True, "deleted": int(args.get("target_agent_id"))}


async def _skill_list_team(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    q = db.query(models.Agent).filter_by(user_id=user.id)
    if not is_orchestrator(agent):
        q = q.filter(models.Agent.parent_id == agent.id)
    role_filter = args.get("role_filter")
    if role_filter:
        q = q.filter_by(hierarchy_role=role_filter)
    rows = q.order_by(models.Agent.id).limit(200).all()
    out = []
    for a in rows:
        sk = list(enabled_skill_ids(a, db)) if args.get("include_skills") else None
        out.append({
            "id": a.id, "name": a.name, "role": a.hierarchy_role,
            "status": a.status, "idle": a.idle_mode, "skills": sk
        })
    return {"ok": True, "count": len(out), "team": out}


# ─────────────────────────────────────────────────────────────────────────────
# CONNECTED APP SKILL IMPLEMENTATIONS
# These call the real integration_actions.py or channels for Facebook, Instagram,
# X, LinkedIn, Gmail, Slack, Calendar, Sheets, Shopify, etc.
# ─────────────────────────────────────────────────────────────────────────────

async def _run_app(db, agent, user, app_id: str, action: str, payload: dict) -> dict:
    from . import models as _m
    from .integration_actions import run_app_action
    conn = (
        db.query(_m.IntegrationConnection)
        .filter_by(user_id=user.id, app_id=app_id, status="connected")
        .order_by(_m.IntegrationConnection.id.desc())
        .first()
    )
    if not conn:
        # Also try agent-specific allocation
        link = db.query(_m.AgentIntegration).filter_by(agent_id=agent.id).first()
        if link:
            conn = db.get(_m.IntegrationConnection, link.connection_id)
    if not conn:
        return {"ok": False, "error": f"No connected {app_id} app"}
    return await run_app_action(conn, action, payload or {})


# Facebook
async def _skill_facebook_post(db, agent, user, args):
    return await _run_app(db, agent, user, "facebook", "post", {
        "message": args.get("message") or args.get("text"),
        "link": args.get("link"),
        "page_id": args.get("page_id"),
    })

async def _skill_facebook_reply_comment(db, agent, user, args):
    return await _run_app(db, agent, user, "facebook", "reply_comment", {
        "comment_id": args.get("comment_id"),
        "message": args.get("message"),
        "page_id": args.get("page_id"),
    })

async def _skill_facebook_reply_message(db, agent, user, args):
    return await _run_app(db, agent, user, "facebook", "reply_message", {
        "recipient_id": args.get("recipient_id"),
        "message": args.get("message"),
        "page_id": args.get("page_id"),
    })

async def _skill_facebook_get_comments(db, agent, user, args):
    return await _run_app(db, agent, user, "facebook", "get_comments", args)

async def _skill_facebook_get_posts(db, agent, user, args):
    return await _run_app(db, agent, user, "facebook", "get_posts", args)

async def _skill_facebook_get_conversations(db, agent, user, args):
    return await _run_app(db, agent, user, "facebook", "get_conversations", args)

async def _skill_facebook_like_comment(db, agent, user, args):
    return await _run_app(db, agent, user, "facebook", "like_comment", args)


# Instagram
async def _skill_instagram_post(db, agent, user, args):
    return await _run_app(db, agent, user, "instagram", "post", args)

async def _skill_instagram_reply_comment(db, agent, user, args):
    return await _run_app(db, agent, user, "instagram", "reply_comment", args)

async def _skill_instagram_get_comments(db, agent, user, args):
    return await _run_app(db, agent, user, "instagram", "get_comments", args)

async def _skill_instagram_get_media(db, agent, user, args):
    return await _run_app(db, agent, user, "instagram", "get_media", args)


# LinkedIn
async def _skill_linkedin_post(db, agent, user, args):
    return await _run_app(db, agent, user, "linkedin", "post", args)

async def _skill_linkedin_comment(db, agent, user, args):
    return await _run_app(db, agent, user, "linkedin", "comment", args)

async def _skill_linkedin_get_posts(db, agent, user, args):
    return await _run_app(db, agent, user, "linkedin", "get_posts", args)

async def _skill_linkedin_get_comments(db, agent, user, args):
    return await _run_app(db, agent, user, "linkedin", "get_comments", args)


# X / Twitter
async def _skill_x_post(db, agent, user, args):
    return await _run_app(db, agent, user, "x", "post", args)

async def _skill_x_reply(db, agent, user, args):
    return await _run_app(db, agent, user, "x", "reply", args)

async def _skill_x_get_mentions(db, agent, user, args):
    return await _run_app(db, agent, user, "x", "get_mentions", args)

async def _skill_x_get_timeline(db, agent, user, args):
    return await _run_app(db, agent, user, "x", "get_timeline", args)

async def _skill_x_search(db, agent, user, args):
    return await _run_app(db, agent, user, "x", "search", args)


# Gmail
async def _skill_gmail_send(db, agent, user, args):
    return await _run_app(db, agent, user, "gmail", "send", args)

async def _skill_gmail_reply(db, agent, user, args):
    return await _run_app(db, agent, user, "gmail", "reply", args)

async def _skill_gmail_draft(db, agent, user, args):
    return await _run_app(db, agent, user, "gmail", "draft", args)

async def _skill_gmail_list(db, agent, user, args):
    return await _run_app(db, agent, user, "gmail", "list", args)

async def _skill_gmail_get_thread(db, agent, user, args):
    return await _run_app(db, agent, user, "gmail", "get_thread", args)

async def _skill_gmail_search(db, agent, user, args):
    return await _run_app(db, agent, user, "gmail", "search", args)

async def _skill_gmail_archive(db, agent, user, args):
    return await _run_app(db, agent, user, "gmail", "archive", args)


async def _skill_email_reply(db, agent, user, args):
    # Convenience: send email + log to CRM customer
    res = await _skill_send_email(db, agent, user, args)
    cid = args.get("customer_id")
    if cid and res.get("ok"):
        try:
            from . import models as _m
            c = db.get(_m.Customer, int(cid))
            if c:
                db.add(_m.CustomerActivity(
                    customer_id=c.id, owner_user_id=user.id,
                    kind="email", title=args.get("subject") or "Reply",
                    body=(args.get("body") or "")[:500], agent_id=agent.id
                ))
                db.commit()
        except Exception:
            pass
    return res


# Slack
async def _skill_slack_post(db, agent, user, args):
    return await _run_app(db, agent, user, "slack", "post", args)

async def _skill_slack_reply_thread(db, agent, user, args):
    return await _run_app(db, agent, user, "slack", "reply_thread", args)

async def _skill_slack_dm(db, agent, user, args):
    return await _run_app(db, agent, user, "slack", "dm", args)

async def _skill_slack_list_channels(db, agent, user, args):
    return await _run_app(db, agent, user, "slack", "list_channels", args)

async def _skill_slack_get_messages(db, agent, user, args):
    return await _run_app(db, agent, user, "slack", "get_messages", args)


# Google Calendar
async def _skill_calendar_create_event(db, agent, user, args):
    return await _run_app(db, agent, user, "google", "create_event", args)

async def _skill_calendar_list_events(db, agent, user, args):
    return await _run_app(db, agent, user, "google", "list_events", args)

async def _skill_calendar_update_event(db, agent, user, args):
    return await _run_app(db, agent, user, "google", "update_event", args)

async def _skill_calendar_delete_event(db, agent, user, args):
    return await _run_app(db, agent, user, "google", "delete_event", args)


# Google Sheets
async def _skill_sheets_append(db, agent, user, args):
    return await _run_app(db, agent, user, "google_sheets", "append", args)

async def _skill_sheets_read(db, agent, user, args):
    return await _run_app(db, agent, user, "google_sheets", "read", args)

async def _skill_sheets_update(db, agent, user, args):
    return await _run_app(db, agent, user, "google_sheets", "update", args)

async def _skill_sheets_create_sheet(db, agent, user, args):
    return await _run_app(db, agent, user, "google_sheets", "create_sheet", args)


# Shopify (via generic use_app style)
async def _skill_shopify_action(db, agent, user, subaction, args):
    p = {**args, "action": subaction}
    return await _run_app(db, agent, user, "shopify", subaction, p)


# HubSpot
async def _skill_hubspot_action(db, agent, user, subaction, args):
    return await _run_app(db, agent, user, "hubspot", subaction, args)


# Notion
async def _skill_notion_action(db, agent, user, subaction, args):
    return await _run_app(db, agent, user, "notion", subaction, args)


# Discord
async def _skill_discord_action(db, agent, user, subaction, args):
    return await _run_app(db, agent, user, "discord", subaction, args)


# WhatsApp reply helper
async def _skill_whatsapp_reply(db, agent, user, args):
    return await _skill_send_whatsapp(db, agent, user, args)


# Mailchimp + Dropbox (light)
async def _skill_mailchimp_action(db, agent, user, subaction, args):
    return await _run_app(db, agent, user, "mailchimp", subaction, args)

async def _skill_dropbox_action(db, agent, user, subaction, args):
    return await _run_app(db, agent, user, "dropbox", subaction, args)
