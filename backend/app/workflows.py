"""
Named multi-agent workflow presets.

Example product flow:
  Get 50 sales targets → save in CRM → second agent emails/calls → update pipeline.

Presets expand into explicit step lists for task_chain.start_goal_chain so handoffs
are reliable (role_hint + DONE WHEN + skill instructions) instead of a vague goal.

Coverage: sales, support, marketing, coding, ops (+ product catalogue helpers).
Each preset declares agent_types so dashboards can filter via workflows_for_template().
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .task_chain import (
    decompose_sales_pipeline,
    start_goal_chain,
    _extract_count,
    looks_like_sales_pipeline,
)

log = logging.getLogger("app.workflows")

# ── Catalog: multi-agent workflow presets ───────────────────────────────────
# agent_types = template_type values that should see this workflow in the dashboard.
WORKFLOW_PRESETS: list[dict[str, Any]] = [
    # ─── SALES ──────────────────────────────────────────────────────────────
    {
        "id": "sales_targets_crm_outreach",
        "name": "Sales targets → CRM → outreach",
        "description": (
            "Agent 1 generates N sales targets, saves CRM customers + deals, and runs "
            "qualify_lead. Agent 2 (outreach) emails/calls preferred qualified leads, "
            "logs activity; sales re-qualifies and updates the pipeline."
        ),
        "category": "sales",
        "agent_types": [
            "sales", "outreach", "lead_gen", "crm", "sdr", "ae", "pipeline", "booking",
        ],
        "default_count": 50,
        "params": [
            {
                "key": "count",
                "label": "Number of sales targets",
                "type": "number",
                "default": 50,
                "min": 5,
                "max": 100,
            },
            {
                "key": "niche",
                "label": "Niche / ICP (optional)",
                "type": "string",
                "default": "",
                "placeholder": "e.g. UK ecommerce brands",
            },
        ],
        "steps_preview": [
            "Generate sales targets (Sales)",
            "Save customers + deals + qualify_lead (Sales)",
            "Emails and calls — prefer qualified (Outreach)",
            "Update pipeline + re-qualify (Sales)",
            "Report results to human (Orchestrator)",
        ],
    },
    {
        "id": "crm_outreach_only",
        "name": "Outreach existing CRM pipeline",
        "description": (
            "Skip lead gen — work open CRM customers/deals: draft/send emails, "
            "log calls, move pipeline stages, notify the owner."
        ),
        "category": "sales",
        "agent_types": ["sales", "outreach", "crm", "sdr", "ae", "booking"],
        "default_count": 20,
        "params": [
            {
                "key": "batch",
                "label": "Max contacts this run",
                "type": "number",
                "default": 20,
                "min": 5,
                "max": 50,
            },
        ],
        "steps_preview": [
            "Pull open CRM deals (Sales)",
            "Emails and calls (Outreach)",
            "Update pipeline + report (Sales)",
        ],
    },
    {
        "id": "sales_pipeline_review",
        "name": "Pipeline review → unstick deals",
        "description": (
            "Sales pulls pipeline summary, flags stalled deals, writes next-step win plans, "
            "outreach re-engages stuck contacts, lead reports forecast risk to the human."
        ),
        "category": "sales",
        "agent_types": ["sales", "crm", "ae", "pipeline", "lead"],
        "default_count": 25,
        "params": [
            {
                "key": "batch",
                "label": "Max deals to review",
                "type": "number",
                "default": 25,
                "min": 5,
                "max": 80,
            },
        ],
        "steps_preview": [
            "Pipeline summary + stall flags (Sales)",
            "Win plans for stuck deals (Sales)",
            "Re-engage stalled contacts (Outreach)",
            "Forecast brief to human (Lead/Orchestrator)",
        ],
    },
    {
        "id": "sales_proposal_pack",
        "name": "Proposal pack for open deals",
        "description": (
            "Research open opportunities, draft proposals/pricing, log CRM activity, "
            "and package a human-ready proposal brief."
        ),
        "category": "sales",
        "agent_types": ["sales", "ae", "crm", "lead"],
        "default_count": 5,
        "params": [
            {
                "key": "batch",
                "label": "Max proposals",
                "type": "number",
                "default": 5,
                "min": 1,
                "max": 15,
            },
            {
                "key": "niche",
                "label": "Offer focus (optional)",
                "type": "string",
                "default": "",
                "placeholder": "e.g. annual SaaS + onboarding",
            },
        ],
        "steps_preview": [
            "Shortlist proposal-ready deals (Sales)",
            "Research + draft proposals (Sales)",
            "Pricing & CRM log (Sales)",
            "Package for human approval (Orchestrator)",
        ],
    },
    {
        "id": "sales_meeting_followup",
        "name": "Meeting follow-up → CRM → next steps",
        "description": (
            "Pull recent meetings/action items, update CRM notes and stages, "
            "send follow-up emails, and notify the owner of commitments."
        ),
        "category": "sales",
        "agent_types": ["sales", "outreach", "crm", "ae", "booking"],
        "default_count": 10,
        "params": [
            {
                "key": "batch",
                "label": "Max meetings/contacts",
                "type": "number",
                "default": 10,
                "min": 3,
                "max": 30,
            },
        ],
        "steps_preview": [
            "List recent meetings / open actions (Sales)",
            "Update CRM notes + stages (Sales)",
            "Send follow-up emails (Outreach)",
            "Commitments report to human (Orchestrator)",
        ],
    },
    # ─── SUPPORT ────────────────────────────────────────────────────────────
    {
        "id": "support_ticket_triage",
        "name": "Support triage → resolve → follow-up",
        "description": (
            "Support agent triages open work, resolves or drafts replies, "
            "logs customer activity, and notifies the human of VIP/blocked cases."
        ),
        "category": "support",
        "agent_types": ["support", "customer", "success", "cx", "cs", "helpdesk"],
        "default_count": 10,
        "params": [],
        "steps_preview": [
            "List open support tasks / customers",
            "draft_email + log_customer_activity per case",
            "Escalate VIP/blocked to human",
        ],
    },
    {
        "id": "support_vip_recovery",
        "name": "VIP health → recovery → escalate",
        "description": (
            "Identify VIP/high-value customers at risk, draft recovery outreach, "
            "log activity, and escalate blockers with a clear human ask."
        ),
        "category": "support",
        "agent_types": ["support", "success", "cx", "cs", "customer"],
        "default_count": 10,
        "params": [
            {
                "key": "batch",
                "label": "Max VIP accounts",
                "type": "number",
                "default": 10,
                "min": 3,
                "max": 30,
            },
        ],
        "steps_preview": [
            "Find VIP / at-risk customers (Support)",
            "Recovery plan + outreach drafts (Support)",
            "Log activity / send where safe (Support)",
            "Escalate VIP blockers (Orchestrator)",
        ],
    },
    {
        "id": "support_kb_macros",
        "name": "KB macros from recurring issues",
        "description": (
            "Mine open/recent support patterns, write reusable macros and knowledge notes, "
            "and deliver a pack the team can reuse."
        ),
        "category": "support",
        "agent_types": ["support", "success", "cx"],
        "default_count": 8,
        "params": [
            {
                "key": "batch",
                "label": "How many macros / articles",
                "type": "number",
                "default": 8,
                "min": 3,
                "max": 20,
            },
        ],
        "steps_preview": [
            "Cluster recurring issues (Support)",
            "Draft macros + KB replies (Support)",
            "Save memory / training notes (Support)",
            "Publish pack to human (Orchestrator)",
        ],
    },
    {
        "id": "support_churn_save",
        "name": "Churn save campaign",
        "description": (
            "Find at-risk customers, draft save offers and empathetic outreach, "
            "log CRM activity, report save rate potential to the owner."
        ),
        "category": "support",
        "agent_types": ["support", "success", "cs", "customer", "sales"],
        "default_count": 15,
        "params": [
            {
                "key": "batch",
                "label": "Max at-risk accounts",
                "type": "number",
                "default": 15,
                "min": 5,
                "max": 40,
            },
        ],
        "steps_preview": [
            "Identify at-risk accounts (Support)",
            "Save offer + reply drafts (Support)",
            "Outreach + CRM activity (Outreach/Support)",
            "Save campaign brief to human (Orchestrator)",
        ],
    },
    # ─── MARKETING ──────────────────────────────────────────────────────────
    {
        "id": "marketing_campaign_launch",
        "name": "Campaign brief → content → launch pack",
        "description": (
            "Marketing builds a campaign brief, content calendar, channel copy, "
            "and a launch pack the human can approve."
        ),
        "category": "marketing",
        "agent_types": ["marketing", "content", "growth", "seo", "social", "brand"],
        "default_count": 1,
        "params": [
            {
                "key": "niche",
                "label": "Campaign theme / goal",
                "type": "string",
                "default": "",
                "placeholder": "e.g. Q3 product launch for SMB landlords",
            },
            {
                "key": "batch",
                "label": "Content pieces to draft",
                "type": "number",
                "default": 6,
                "min": 3,
                "max": 20,
            },
        ],
        "steps_preview": [
            "Campaign brief + goals (Marketing)",
            "Content calendar (Marketing)",
            "Draft multi-channel copy (Marketing/Content)",
            "Launch pack to human (Orchestrator)",
        ],
    },
    {
        "id": "marketing_content_sprint",
        "name": "Content sprint (batch publish pack)",
        "description": (
            "Plan themes, generate a batch of content assets (email, social, web), "
            "align with product offers if present, deliver a publish-ready pack."
        ),
        "category": "marketing",
        "agent_types": ["marketing", "content", "social", "growth"],
        "default_count": 8,
        "params": [
            {
                "key": "count",
                "label": "Content pieces",
                "type": "number",
                "default": 8,
                "min": 3,
                "max": 25,
            },
            {
                "key": "niche",
                "label": "Theme / audience (optional)",
                "type": "string",
                "default": "",
                "placeholder": "e.g. property managers on LinkedIn",
            },
        ],
        "steps_preview": [
            "Theme + channel plan (Marketing)",
            "Generate content batch (Content)",
            "Polish + CTA alignment (Marketing)",
            "Publish pack to human (Orchestrator)",
        ],
    },
    {
        "id": "marketing_seo_pack",
        "name": "SEO topic → outlines → drafts",
        "description": (
            "Research SEO topics for the niche, produce outlines, draft articles/landing "
            "copy, and report a ranked content backlog."
        ),
        "category": "marketing",
        "agent_types": ["marketing", "content", "seo", "growth"],
        "default_count": 5,
        "params": [
            {
                "key": "count",
                "label": "Topics / drafts",
                "type": "number",
                "default": 5,
                "min": 2,
                "max": 15,
            },
            {
                "key": "niche",
                "label": "Keyword niche",
                "type": "string",
                "default": "",
                "placeholder": "e.g. HMO licensing compliance UK",
            },
        ],
        "steps_preview": [
            "Keyword / topic research (Marketing)",
            "Outlines + intent map (Content)",
            "Draft articles / landing copy (Content)",
            "SEO backlog report (Orchestrator)",
        ],
    },
    {
        "id": "marketing_social_week",
        "name": "Social week pack",
        "description": (
            "Plan a week of social posts, draft platform-native copy, "
            "add CTAs tied to products/offers, deliver a scheduled pack."
        ),
        "category": "marketing",
        "agent_types": ["marketing", "social", "content", "brand"],
        "default_count": 12,
        "params": [
            {
                "key": "count",
                "label": "Posts this week",
                "type": "number",
                "default": 12,
                "min": 5,
                "max": 30,
            },
            {
                "key": "niche",
                "label": "Theme / campaign (optional)",
                "type": "string",
                "default": "",
                "placeholder": "e.g. founder stories + case studies",
            },
        ],
        "steps_preview": [
            "Weekly themes by channel (Social)",
            "Draft posts + hooks (Content)",
            "CTA + offer alignment (Marketing)",
            "Schedule pack to human (Orchestrator)",
        ],
    },
    # ─── CODING ─────────────────────────────────────────────────────────────
    {
        "id": "coding_feature_ship",
        "name": "Feature ship: design → plan → tests",
        "description": (
            "Engineering designs the change, breaks implementation into owned steps, "
            "defines tests/QA criteria, and reports a ship-ready plan to the lead."
        ),
        "category": "coding",
        "agent_types": ["coding", "code", "engineer", "engineering", "developer", "dev", "qa"],
        "default_count": 1,
        "params": [
            {
                "key": "niche",
                "label": "Feature / goal",
                "type": "string",
                "default": "",
                "placeholder": "e.g. webhook retry queue with DLQ",
            },
        ],
        "steps_preview": [
            "Clarify scope + success criteria (Lead)",
            "Technical design (Engineering)",
            "Implementation plan + write_api_endpoint notes (Engineering)",
            "write_tests plan + code_review criteria (QA/Engineering)",
            "Ship plan to human (Orchestrator)",
        ],
    },
    {
        "id": "coding_bug_triage",
        "name": "Bug triage → repro → fix plan",
        "description": (
            "Triage open bug-like tasks, capture repro steps, propose fixes with risk notes, "
            "and escalate blockers needing human product decisions."
        ),
        "category": "coding",
        "agent_types": ["coding", "engineer", "engineering", "developer", "qa", "devops"],
        "default_count": 10,
        "params": [
            {
                "key": "batch",
                "label": "Max bugs to triage",
                "type": "number",
                "default": 10,
                "min": 3,
                "max": 30,
            },
        ],
        "steps_preview": [
            "List open bug/defect work (Engineering)",
            "Repro steps + severity (QA)",
            "Fix plan + risk notes (Engineering)",
            "Triage report to human (Orchestrator)",
        ],
    },
    {
        "id": "coding_api_scaffold",
        "name": "API scaffold: contract → schema → tests",
        "description": (
            "Design API contracts, schema notes, endpoint checklist, and test cases "
            "so implementation can start without ambiguity."
        ),
        "category": "coding",
        "agent_types": ["coding", "engineer", "engineering", "developer", "dev"],
        "default_count": 1,
        "params": [
            {
                "key": "niche",
                "label": "API / resource focus",
                "type": "string",
                "default": "",
                "placeholder": "e.g. public billing webhooks v2",
            },
        ],
        "steps_preview": [
            "Requirements + resources (Engineering)",
            "API contract + write_api_endpoint sketch (Engineering)",
            "Schema / data model notes (Engineering)",
            "write_tests cases + code_review criteria (QA)",
            "Scaffold pack to human (Orchestrator)",
        ],
    },
    {
        "id": "coding_tech_debt",
        "name": "Tech debt audit → prioritised backlog",
        "description": (
            "Audit known debt signals from tasks/memory, score impact vs effort, "
            "propose a sprint-sized backlog, notify the lead."
        ),
        "category": "coding",
        "agent_types": ["coding", "engineer", "engineering", "devops", "qa"],
        "default_count": 12,
        "params": [
            {
                "key": "batch",
                "label": "Max debt items",
                "type": "number",
                "default": 12,
                "min": 5,
                "max": 40,
            },
        ],
        "steps_preview": [
            "Inventory debt signals (Engineering)",
            "Score impact vs effort (Engineering)",
            "Sprint-sized backlog (Lead/Engineering)",
            "Debt brief to human (Orchestrator)",
        ],
    },
    # ─── OPS ────────────────────────────────────────────────────────────────
    {
        "id": "ops_sop_standardize",
        "name": "SOP standardize: map → SOP → RACI",
        "description": (
            "Map a process, write the SOP, define RACI and SLAs, deliver a runbook "
            "the team can execute without the founder."
        ),
        "category": "ops",
        "agent_types": ["ops", "operations", "fleet", "manager", "lead"],
        "default_count": 1,
        "params": [
            {
                "key": "niche",
                "label": "Process name",
                "type": "string",
                "default": "",
                "placeholder": "e.g. new client onboarding",
            },
        ],
        "steps_preview": [
            "Process map + pain points (Ops)",
            "Write SOP (Ops)",
            "RACI + SLA definition (Ops)",
            "Runbook pack to human (Orchestrator)",
        ],
    },
    {
        "id": "ops_weekly_review",
        "name": "Weekly ops review → blockers → brief",
        "description": (
            "Roll up open tasks across the team, surface blockers and SLA risks, "
            "and send a crisp weekly ops brief to the human."
        ),
        "category": "ops",
        "agent_types": ["ops", "operations", "manager", "lead", "orchestrator"],
        "default_count": 50,
        "params": [
            {
                "key": "batch",
                "label": "Max tasks to scan",
                "type": "number",
                "default": 50,
                "min": 10,
                "max": 150,
            },
        ],
        "steps_preview": [
            "list_tasks scan + status rollup (Ops)",
            "Blockers + SLA risks (Ops)",
            "Prioritised next-week plan (Lead)",
            "status_update weekly brief to human (Orchestrator)",
        ],
    },
    {
        "id": "ops_onboarding_runbook",
        "name": "Team / client onboarding runbook",
        "description": (
            "Build a step-by-step onboarding checklist, owners, systems, "
            "and first-week success criteria; notify the human when ready."
        ),
        "category": "ops",
        "agent_types": ["ops", "operations", "hr", "manager", "lead"],
        "default_count": 1,
        "params": [
            {
                "key": "niche",
                "label": "Who is being onboarded",
                "type": "string",
                "default": "",
                "placeholder": "e.g. new AE hire or new client workspace",
            },
        ],
        "steps_preview": [
            "Onboarding goals + systems (Ops)",
            "Day-by-day checklist (Ops)",
            "Owners + handoffs (Ops)",
            "Runbook to human (Orchestrator)",
        ],
    },
    {
        "id": "ops_incident_response",
        "name": "Incident response: triage → fix plan → postmortem",
        "description": (
            "Triage an operational incident, coordinate fix owners, communicate status, "
            "and draft a short postmortem with action items."
        ),
        "category": "ops",
        "agent_types": ["ops", "operations", "devops", "support", "lead"],
        "default_count": 1,
        "params": [
            {
                "key": "niche",
                "label": "Incident summary",
                "type": "string",
                "default": "",
                "placeholder": "e.g. email provider 5xx / CRM sync lag",
            },
        ],
        "steps_preview": [
            "Triage impact + severity (Ops)",
            "Mitigation + owner tasks (Ops/Engineering)",
            "Status updates (Ops)",
            "Postmortem + actions to human (Orchestrator)",
        ],
    },
    # ─── PRODUCT (catalogue helpers — shared with sales/marketing/ops) ──────
    {
        "id": "product_catalog_build",
        "name": "Build product catalogue",
        "description": (
            "Research / define N products or services, write them into the catalogue "
            "(write_product / create_product), set prices and special offers, then report."
        ),
        "category": "product",
        "agent_types": ["product", "catalog", "sales", "marketing", "ops"],
        "default_count": 5,
        "params": [
            {
                "key": "count",
                "label": "How many products",
                "type": "number",
                "default": 5,
                "min": 1,
                "max": 30,
            },
            {
                "key": "niche",
                "label": "Category / niche (optional)",
                "type": "string",
                "default": "",
                "placeholder": "e.g. property compliance services",
            },
        ],
        "steps_preview": [
            "Audit existing catalogue (list/search products)",
            "Define product specs + pricing",
            "Write products to catalogue",
            "Set offers / benefits",
            "Report catalogue to human",
        ],
    },
    {
        "id": "product_offer_campaign",
        "name": "Product offers → promo copy",
        "description": (
            "Read catalogue products, set special offers, draft marketing emails/SMS "
            "and content for the offer campaign, notify the owner."
        ),
        "category": "product",
        "agent_types": ["product", "catalog", "sales", "marketing", "content"],
        "default_count": 10,
        "params": [
            {
                "key": "batch",
                "label": "Max products this run",
                "type": "number",
                "default": 10,
                "min": 1,
                "max": 40,
            },
            {
                "key": "niche",
                "label": "Offer theme (optional)",
                "type": "string",
                "default": "",
                "placeholder": "e.g. spring 20% off multi-lets",
            },
        ],
        "steps_preview": [
            "List / read products",
            "Set special offers",
            "Draft promo email + content",
            "Status update to human",
        ],
    },
    {
        "id": "product_catalog_audit",
        "name": "Audit & fix product catalogue",
        "description": (
            "Search and read all products, fix missing prices/descriptions/status, "
            "archive stale SKUs, summarize gaps for the lead."
        ),
        "category": "product",
        "agent_types": ["product", "catalog", "ops", "sales"],
        "default_count": 50,
        "params": [
            {
                "key": "batch",
                "label": "Max products to audit",
                "type": "number",
                "default": 50,
                "min": 5,
                "max": 100,
            },
        ],
        "steps_preview": [
            "List & search products",
            "Read incomplete records",
            "Write/update fixes",
            "Archive or flag stale items",
            "Report to lead/human",
        ],
    },
    # ─── RESEARCH / FINANCE (analyst templates + research pack) ─────────────
    {
        "id": "research_competitor_brief",
        "name": "Competitor research → battlecard brief",
        "description": (
            "Research named competitors or niche rivals, build battlecards "
            "(positioning, pricing signals, strengths/weaknesses), and deliver a "
            "decision-ready brief for sales/marketing."
        ),
        "category": "research",
        "agent_types": [
            "research", "analyst", "analysis", "data", "marketing", "sales", "lead",
        ],
        "default_count": 5,
        "params": [
            {
                "key": "count",
                "label": "How many competitors",
                "type": "number",
                "default": 5,
                "min": 2,
                "max": 15,
            },
            {
                "key": "niche",
                "label": "Market / rival focus (optional)",
                "type": "string",
                "default": "",
                "placeholder": "e.g. UK property SaaS vs [names]",
            },
        ],
        "steps_preview": [
            "Scope rivals + research questions (Research)",
            "research + summarize per competitor (Research)",
            "Battlecards + win themes (Research/Sales)",
            "Brief + status_update to human (Orchestrator)",
        ],
    },
    {
        "id": "finance_cashflow_forecast",
        "name": "Cashflow / pipeline forecast pack",
        "description": (
            "Pull pipeline and deal signals, score forecast risk, draft a simple "
            "cashflow/runway narrative, and notify the owner with clear asks."
        ),
        "category": "research",
        "agent_types": [
            "finance", "research", "analyst", "billing", "bookkeep", "data",
            "ops", "lead", "sales",
        ],
        "default_count": 30,
        "params": [
            {
                "key": "batch",
                "label": "Max deals / signals to scan",
                "type": "number",
                "default": 30,
                "min": 5,
                "max": 100,
            },
            {
                "key": "niche",
                "label": "Forecast horizon / focus (optional)",
                "type": "string",
                "default": "",
                "placeholder": "e.g. next 90 days ARR + open pipeline",
            },
        ],
        "steps_preview": [
            "pipeline_summary + open deals snapshot (Finance/Sales)",
            "Forecast risk + cashflow narrative (Research/Finance)",
            "Scenarios (base / upside / downside)",
            "status_update brief to human (Orchestrator)",
        ],
    },
]


# Template / name aliases → canonical category used for filtering
_TEMPLATE_TO_CATEGORY: dict[str, str] = {
    # sales
    "sales": "sales",
    "outreach": "sales",
    "lead_gen": "sales",
    "crm": "sales",
    "sdr": "sales",
    "ae": "sales",
    "pipeline": "sales",
    "lead_qualifier": "sales",
    "qualifier": "sales",
    "booking": "sales",  # sales pack in skills_policy; keep support triage via agent_types
    "account": "sales",
    # support
    "support": "support",
    "customer": "support",
    "success": "support",
    "cx": "support",
    "cs": "support",
    "reviews": "support",
    "helpdesk": "support",
    # marketing
    "marketing": "marketing",
    "content": "marketing",
    "growth": "marketing",
    "seo": "marketing",
    "social": "marketing",
    "brand": "marketing",
    "designer": "marketing",
    # coding
    "coding": "coding",
    "code": "coding",
    "engineer": "coding",
    "engineering": "coding",
    "developer": "coding",
    "dev": "coding",
    "qa": "coding",
    "devops": "coding",
    "fullstack": "coding",
    # ops
    "ops": "ops",
    "operations": "ops",
    "fleet": "ops",
    "manager": "ops",
    "hr": "ops",
    # product
    "product": "product",
    "catalog": "product",
    "catalogue": "product",
    # research / analysis / finance → curated multi-category set (no dedicated presets)
    "research": "research",
    "analyst": "research",
    "analysis": "research",
    "data": "research",
    "finance": "research",
    "bookkeep": "research",
    "billing": "research",
}

# Workflow ids suggested for research/analyst/finance templates (cross-category, ordered)
_RESEARCH_WORKFLOW_IDS: tuple[str, ...] = (
    "research_competitor_brief",
    "finance_cashflow_forecast",
    "marketing_seo_pack",
    "marketing_campaign_launch",
    "ops_weekly_review",
    "sales_pipeline_review",
    "sales_proposal_pack",
    "product_catalog_audit",
    "coding_tech_debt",
    "support_kb_macros",
)

_ALLOWED_PRIORITIES = frozenset({"low", "medium", "normal", "high", "urgent"})

# Diverse defaults when template matches nothing (avoid dumping only sales presets)
_FALLBACK_WORKFLOW_IDS: tuple[str, ...] = (
    "ops_weekly_review",
    "marketing_content_sprint",
    "product_catalog_audit",
    "sales_pipeline_review",
)

# Hierarchy roles that see the full catalog
_LEAD_ROLES = frozenset({"orchestrator", "lead", "admin", "manager"})
_LEAD_TEMPLATES = frozenset({"orchestrator", "staff_orchestrator", "lead", "manager"})


def list_workflow_presets() -> list[dict[str, Any]]:
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "description": p["description"],
            "category": p.get("category") or "general",
            "agent_types": list(p.get("agent_types") or []),
            "default_count": p.get("default_count"),
            "params": p.get("params") or [],
            "steps_preview": p.get("steps_preview") or [],
        }
        for p in WORKFLOW_PRESETS
    ]


def get_preset(workflow_id: str) -> dict[str, Any] | None:
    wid = (workflow_id or "").strip().lower()
    for p in WORKFLOW_PRESETS:
        if p["id"] == wid:
            return p
    return None


def workflows_for_template(
    template_type: str | None = None,
    *,
    hierarchy_role: str | None = None,
    agent_name: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Filter workflow presets for an agent role/template.

    Leads / orchestrators get the full catalog. Specialists get workflows whose
    category or agent_types match their template (with name-based fallbacks).
    """
    all_wf = list_workflow_presets()
    tpl = (template_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    role = (hierarchy_role or "").strip().lower()
    name_l = (agent_name or "").strip().lower()

    if role in _LEAD_ROLES or tpl in _LEAD_TEMPLATES:
        out = all_wf
    else:
        cat = _TEMPLATE_TO_CATEGORY.get(tpl)
        # Name-based hints when template is blank/generic
        if not cat and name_l:
            for token, mapped in (
                ("sales", "sales"),
                ("outreach", "sales"),
                ("crm", "sales"),
                ("booking", "sales"),
                ("support", "support"),
                ("success", "support"),
                ("marketing", "marketing"),
                ("content", "marketing"),
                ("social", "marketing"),
                ("seo", "marketing"),
                ("engineer", "coding"),
                ("developer", "coding"),
                ("coding", "coding"),
                ("ops", "ops"),
                ("operations", "ops"),
                ("product", "product"),
                ("catalog", "product"),
                ("research", "research"),
                ("analyst", "research"),
                ("finance", "research"),
            ):
                if token in name_l:
                    cat = mapped
                    break

        matched: list[dict[str, Any]] = []
        by_id = {w["id"]: w for w in all_wf}

        # Research / finance / analyst: curated cross-category pack
        if cat == "research" or tpl in (
            "research", "analyst", "analysis", "data", "finance", "bookkeep", "billing",
        ):
            for wid in _RESEARCH_WORKFLOW_IDS:
                w = by_id.get(wid)
                if w and w not in matched:
                    matched.append(w)

        for w in all_wf:
            if w in matched:
                continue
            types = [t.lower() for t in (w.get("agent_types") or [])]
            wcat = (w.get("category") or "").lower()
            if tpl and (tpl in types or tpl == wcat):
                matched.append(w)
                continue
            if cat and cat != "research" and (cat == wcat or cat in types):
                matched.append(w)
                continue
        # Related product workflows for sales/marketing/ops
        if cat in ("sales", "marketing", "ops") and not any(
            m.get("category") == "product" for m in matched
        ):
            for w in all_wf:
                if w.get("category") == "product" and cat in [
                    t.lower() for t in (w.get("agent_types") or [])
                ]:
                    if w not in matched:
                        matched.append(w)

        if matched:
            out = matched
        else:
            # Diverse non-sales-only defaults for unknown templates
            out = [by_id[i] for i in _FALLBACK_WORKFLOW_IDS if i in by_id] or all_wf[:4]

    if limit is not None and limit > 0:
        return out[:limit]
    return out


# ── Step builders ───────────────────────────────────────────────────────────

def _steps_for_crm_outreach(batch: int = 20) -> list[dict[str, Any]]:
    b = max(5, min(50, int(batch or 20)))
    return [
        {
            "title": f"Pull up to {b} open CRM opportunities",
            "description": (
                f"Skills: list_customers, list_deals, list_qualified_leads, "
                f"get_pipeline / pipeline_summary.\n"
                f"Identify up to {b} open deals or recent customers that need outreach.\n"
                f"Prefer higher lead_score / lead_status=qualified when present.\n"
                f"Write the shortlist in the task result (name, email, deal id, stage, score).\n\n"
                f"DONE WHEN: Shortlist of ≤{b} contacts ready for outreach.\n"
                f"TARGET: Named CRM shortlist with emails for the outreach agent."
            ),
            "role_hint": "sales",
            "done_when": f"Shortlist of up to {b} CRM contacts",
            "checklist": [
                "list_customers or list_deals used",
                f"≤{b} contacts with emails in result",
            ],
        },
        {
            "title": "Emails, calls, activity logs",
            "description": (
                f"For EACH shortlisted contact from the prior step:\n"
                f"  1) draft_email — personalized pitch (REQUIRED).\n"
                f"  2) send_email when credentials/policy allow; else leave draft.\n"
                f"  3) log_customer_activity — channel, outcome, next step (REQUIRED).\n"
                f"  4) Call script / call skill if phone present.\n"
                f"  5) Optionally set_lead_status to contacted after a real touch.\n"
                f"Batch size ≤{b}. Emit real ```skill blocks — prose alone is NOT enough.\n\n"
                f"DONE WHEN: Outreach attempted and logged for the shortlist batch.\n"
                f"TARGET: Activity visible on CRM customers for Sales to move pipeline."
            ),
            "role_hint": "outreach",
            "done_when": "Outreach logged on shortlisted customers",
            "checklist": [
                "draft_email used on shortlist",
                "log_customer_activity used on shortlist",
            ],
        },
        {
            "title": "Update pipeline and report",
            "description": (
                "After outreach: move_deal / update_deal for contacted leads; "
                "re-run qualify_lead or set_lead_status when interest is real; "
                "pipeline_summary; status_update or notify_human with counts.\n\n"
                "Skills: move_deal, update_deal, qualify_lead / set_lead_status, "
                "pipeline_summary, status_update.\n\n"
                "DONE WHEN: Pipeline updated and human notified.\n"
                "TARGET: Clear owner brief with numbers."
            ),
            "role_hint": "sales",
            "done_when": "Pipeline updated and human status_update sent",
            "checklist": ["pipeline_summary or move_deal used", "status_update or notify_human"],
        },
    ]


def _steps_for_sales_pipeline_review(batch: int = 25) -> list[dict[str, Any]]:
    b = max(5, min(80, int(batch or 25)))
    return [
        {
            "title": f"Pipeline summary — flag stalls (≤{b})",
            "description": (
                f"pipeline_summary / list_deals / list_customers. Review up to {b} open deals.\n"
                f"Flag stalled (no activity, stuck stage, missing next step).\n\n"
                f"DONE WHEN: Stall list with deal ids + reasons.\n"
                f"TARGET: Prioritised stuck-deal list."
            ),
            "role_hint": "sales",
            "done_when": "Stalled deals listed with reasons",
        },
        {
            "title": "Win plans for stuck deals",
            "description": (
                "For each stalled deal: next action, owner, value, risk. "
                "update_deal / log_customer_activity where useful.\n\n"
                "DONE WHEN: Win plan per stalled deal.\n"
                "TARGET: Concrete next steps, not vague notes."
            ),
            "role_hint": "sales",
            "done_when": "Win plans written for stalled deals",
        },
        {
            "title": "Re-engage stalled contacts",
            "description": (
                "draft_email / send_email / log_customer_activity for stalled contacts. "
                "Respect batch size; real skill blocks required.\n\n"
                "DONE WHEN: Re-engagement attempted on top stalled deals.\n"
                "TARGET: Activity logged on CRM."
            ),
            "role_hint": "outreach",
            "done_when": "Re-engagement outreach logged",
        },
        {
            "title": "Forecast risk brief to human",
            "description": (
                "status_update or notify_human: stalled count, value at risk, top 3 actions.\n\n"
                "DONE WHEN: Human has forecast risk brief.\n"
                "TARGET: Numbers + asks."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of pipeline risk",
        },
    ]


def _steps_for_sales_proposal_pack(batch: int = 5, focus: str = "") -> list[dict[str, Any]]:
    b = max(1, min(15, int(batch or 5)))
    focus_bit = f" Offer focus: {focus}." if focus else ""
    return [
        {
            "title": f"Shortlist ≤{b} proposal-ready deals",
            "description": (
                f"list_deals / list_customers — pick up to {b} opportunities ready for a proposal."
                f"{focus_bit}\n\n"
                f"DONE WHEN: Shortlist with deal ids, contacts, amounts.\n"
                f"TARGET: Clear proposal queue."
            ),
            "role_hint": "sales",
            "done_when": f"Up to {b} proposal-ready deals shortlisted",
        },
        {
            "title": "Research + draft proposals",
            "description": (
                f"For each deal draft a proposal: problem, solution, pricing options, next step."
                f"{focus_bit}\n"
                f"Use generate_content / draft_email as needed.\n\n"
                f"DONE WHEN: Draft proposal text for each shortlisted deal.\n"
                f"TARGET: Human-readable proposal drafts."
            ),
            "role_hint": "sales",
            "done_when": "Proposal drafts ready",
        },
        {
            "title": "Pricing notes + CRM log",
            "description": (
                "log_customer_activity on each account; update_deal notes with proposal summary.\n\n"
                "DONE WHEN: CRM reflects proposal status.\n"
                "TARGET: Activity + deal notes updated."
            ),
            "role_hint": "sales",
            "done_when": "CRM updated with proposal notes",
        },
        {
            "title": "Proposal pack to human",
            "description": (
                "status_update / notify_human with proposal summaries and asks for approval.\n\n"
                "DONE WHEN: Owner has the proposal pack.\n"
                "TARGET: Clear approval asks."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of proposal pack",
        },
    ]


def _steps_for_sales_meeting_followup(batch: int = 10) -> list[dict[str, Any]]:
    b = max(3, min(30, int(batch or 10)))
    return [
        {
            "title": f"List recent meetings / open actions (≤{b})",
            "description": (
                f"list_tasks / list_customers / list_activity — find up to {b} meeting follow-ups "
                f"or open commitments.\n\n"
                f"DONE WHEN: Follow-up queue documented.\n"
                f"TARGET: Who, what was promised, due when."
            ),
            "role_hint": "sales",
            "done_when": "Meeting follow-up queue listed",
        },
        {
            "title": "Update CRM notes + stages",
            "description": (
                "log_customer_activity, update_deal / move_deal for meeting outcomes.\n\n"
                "DONE WHEN: CRM reflects meeting outcomes.\n"
                "TARGET: Notes + stage accuracy."
            ),
            "role_hint": "sales",
            "done_when": "CRM updated from meetings",
        },
        {
            "title": "Send follow-up emails",
            "description": (
                "draft_email / send_email for each commitment; log_customer_activity.\n\n"
                "DONE WHEN: Follow-ups sent or drafted with blockers noted.\n"
                "TARGET: No silent commitments."
            ),
            "role_hint": "outreach",
            "done_when": "Follow-up emails drafted/sent",
        },
        {
            "title": "Commitments report to human",
            "description": (
                "status_update / notify_human: open commitments, sent follow-ups, risks.\n\n"
                "DONE WHEN: Human has commitments brief.\n"
                "TARGET: Clear owner view."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of meeting commitments",
        },
    ]


def _steps_for_support() -> list[dict[str, Any]]:
    return [
        {
            "title": "Triage open support work",
            "description": (
                "list_tasks (mine=false) for open support items; list_customers with issues; "
                "list_activity for recent friction. Prioritise VIP/urgent.\n"
                "Write a ranked queue in the result (customer, issue, severity, next action).\n\n"
                "Skills: list_tasks, list_customers, list_activity.\n\n"
                "DONE WHEN: Prioritised queue written in result.\n"
                "TARGET: Top issues ranked for draft_email / log_customer_activity."
            ),
            "role_hint": "support",
            "done_when": "Prioritised support queue documented",
            "checklist": ["list_tasks or list_customers used", "Ranked queue in result"],
        },
        {
            "title": "Resolve or draft customer replies",
            "description": (
                "For EACH priority case from triage:\n"
                "  1) draft_email — clear, empathetic reply with next step (REQUIRED skill).\n"
                "  2) send_email when credentials/policy allow; otherwise leave draft.\n"
                "  3) log_customer_activity — note issue, action taken, channel "
                "(REQUIRED skill; prose alone is NOT enough).\n"
                "  4) complete_task on child work when fixed.\n\n"
                "Skills REQUIRED: draft_email, log_customer_activity "
                "(send_email optional when safe).\n"
                "Emit real ```skill blocks — do not only describe the reply.\n\n"
                "DONE WHEN: draft_email + log_customer_activity for each priority case "
                "(or blocker noted with log_customer_activity).\n"
                "TARGET: Customer-facing progress with CRM activity visible."
            ),
            "role_hint": "support",
            "done_when": "draft_email and log_customer_activity for priority cases",
            "checklist": [
                "draft_email used for priority cases",
                "log_customer_activity used for priority cases",
            ],
        },
        {
            "title": "Escalate VIP/blocked + notify human",
            "description": (
                "status_update / notify_human for anything blocked or VIP "
                "(include which cases got draft_email / log_customer_activity).\n"
                "save_memory support_triage_summary.\n\n"
                "DONE WHEN: Human has a short triage report with counts.\n"
                "TARGET: Owner notified."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of triage outcomes",
            "checklist": ["status_update or notify_human sent"],
        },
    ]


def _steps_for_support_vip_recovery(batch: int = 10) -> list[dict[str, Any]]:
    b = max(3, min(30, int(batch or 10)))
    return [
        {
            "title": f"Find VIP / at-risk customers (≤{b})",
            "description": (
                f"list_customers / list_activity / list_deals — identify up to {b} VIP or "
                f"high-value accounts with friction signals.\n\n"
                f"DONE WHEN: VIP shortlist with risk notes.\n"
                f"TARGET: Named accounts + why at risk."
            ),
            "role_hint": "support",
            "done_when": "VIP at-risk shortlist ready",
        },
        {
            "title": "Recovery plans + outreach drafts",
            "description": (
                "For each VIP: recovery plan + draft_email (REQUIRED skill) with a concrete next step. "
                "Optional save offer. Tone: empathetic, not defensive.\n"
                "Skills REQUIRED: draft_email.\n\n"
                "DONE WHEN: Plan + draft_email per VIP.\n"
                "TARGET: Ready-to-send recovery outreach."
            ),
            "role_hint": "support",
            "done_when": "Recovery plans and drafts ready",
            "checklist": ["draft_email used for VIP shortlist"],
        },
        {
            "title": "Log activity / send where safe",
            "description": (
                "log_customer_activity (REQUIRED) for each VIP touch; "
                "send_email only when safe and policy allows. "
                "Note anything needing human approval.\n"
                "Skills REQUIRED: log_customer_activity (send_email optional).\n\n"
                "DONE WHEN: Activity logged; sends or pending approvals listed.\n"
                "TARGET: CRM truth matches outreach state."
            ),
            "role_hint": "support",
            "done_when": "VIP recovery activity logged",
            "checklist": ["log_customer_activity used for VIP shortlist"],
        },
        {
            "title": "Escalate VIP blockers to human",
            "description": (
                "status_update / notify_human: VIP list, actions taken, asks for owner.\n\n"
                "DONE WHEN: Human has VIP recovery brief.\n"
                "TARGET: Clear escalation asks."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of VIP recovery status",
        },
    ]


def _steps_for_support_kb_macros(batch: int = 8) -> list[dict[str, Any]]:
    b = max(3, min(20, int(batch or 8)))
    return [
        {
            "title": "Cluster recurring support issues",
            "description": (
                "list_tasks / list_activity — cluster recurring issues into themes "
                f"that deserve macros (aim for {b}).\n\n"
                "DONE WHEN: Theme list with frequency notes.\n"
                "TARGET: Prioritised macro candidates."
            ),
            "role_hint": "support",
            "done_when": "Recurring issue clusters documented",
        },
        {
            "title": f"Draft {b} macros / KB replies",
            "description": (
                f"Write up to {b} reusable macros: trigger, reply body, when NOT to use. "
                f"generate_content or draft_email style as needed.\n\n"
                f"DONE WHEN: {b} macros drafted.\n"
                f"TARGET: Copy-paste ready support macros."
            ),
            "role_hint": "support",
            "done_when": f"{b} support macros drafted",
        },
        {
            "title": "Save memory / training notes",
            "description": (
                "save_memory or save_training with macro pack summary for the team.\n\n"
                "DONE WHEN: Macros persisted in memory/training.\n"
                "TARGET: Team can reuse without re-asking."
            ),
            "role_hint": "support",
            "done_when": "Macro pack saved to memory",
        },
        {
            "title": "Publish KB pack to human",
            "description": (
                "status_update / notify_human with macro titles and full text summary.\n\n"
                "DONE WHEN: Human has the KB/macro pack.\n"
                "TARGET: Owner can approve or edit."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of KB macro pack",
        },
    ]


def _steps_for_support_churn_save(batch: int = 15) -> list[dict[str, Any]]:
    b = max(5, min(40, int(batch or 15)))
    return [
        {
            "title": f"Identify at-risk accounts (≤{b})",
            "description": (
                f"list_customers / list_deals / list_activity — find up to {b} churn risks "
                f"(complaints, stalled renewals, low engagement).\n\n"
                f"DONE WHEN: At-risk list with signals.\n"
                f"TARGET: Named accounts + risk reason."
            ),
            "role_hint": "support",
            "done_when": "At-risk accounts shortlisted",
        },
        {
            "title": "Save offers + empathetic drafts",
            "description": (
                "draft_email save campaigns; note offer levers. Avoid overpromising.\n\n"
                "DONE WHEN: Save draft per priority account.\n"
                "TARGET: Ready-to-review save outreach."
            ),
            "role_hint": "support",
            "done_when": "Save drafts ready",
        },
        {
            "title": "Outreach + CRM activity",
            "description": (
                "send_email where safe; log_customer_activity for all; "
                "update_deal if retention stage exists.\n\n"
                "DONE WHEN: Outreach attempted and logged.\n"
                "TARGET: Activity on each at-risk account."
            ),
            "role_hint": "outreach",
            "done_when": "Churn-save outreach logged",
        },
        {
            "title": "Save campaign brief to human",
            "description": (
                "status_update / notify_human: contacted count, offers used, needs owner decision.\n\n"
                "DONE WHEN: Human has save-campaign brief.\n"
                "TARGET: Numbers + open asks."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of churn-save campaign",
        },
    ]


def _steps_for_marketing_campaign(batch: int = 6, theme: str = "") -> list[dict[str, Any]]:
    b = max(3, min(20, int(batch or 6)))
    theme_bit = f" Theme/goal: {theme}." if theme else ""
    return [
        {
            "title": "Campaign brief + goals",
            "description": (
                f"Write campaign brief: goal, audience, channels, success metrics."
                f"{theme_bit}\n"
                f"Skills: generate_content; save_memory campaign_brief.\n\n"
                f"DONE WHEN: One-page brief in result.\n"
                f"TARGET: Goals + metrics clear."
            ),
            "role_hint": "marketing",
            "done_when": "Campaign brief written",
        },
        {
            "title": "Content calendar",
            "description": (
                f"Plan a multi-channel calendar for ~{b} pieces with themes, formats, dates."
                f"{theme_bit}\n\n"
                f"DONE WHEN: Calendar table in result.\n"
                f"TARGET: Owned slots by channel."
            ),
            "role_hint": "marketing",
            "done_when": "Content calendar drafted",
        },
        {
            "title": f"Draft {b} multi-channel assets",
            "description": (
                f"generate_content / draft_email for up to {b} assets (email, social, web)."
                f"{theme_bit}\n\n"
                f"DONE WHEN: Draft copy for each calendar slot.\n"
                f"TARGET: Publish-ready drafts (not outlines only)."
            ),
            "role_hint": "content",
            "done_when": f"{b} content assets drafted",
        },
        {
            "title": "Launch pack to human",
            "description": (
                "status_update / notify_human with brief, calendar, and draft links/text.\n\n"
                "DONE WHEN: Human has launch pack for approval.\n"
                "TARGET: Clear approve/edit asks."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of campaign launch pack",
        },
    ]


def _steps_for_marketing_content_sprint(count: int = 8, theme: str = "") -> list[dict[str, Any]]:
    n = max(3, min(25, int(count or 8)))
    theme_bit = f" Theme: {theme}." if theme else ""
    return [
        {
            "title": "Theme + channel plan",
            "description": (
                f"Plan themes and channels for a {n}-piece content sprint."
                f"{theme_bit}\n\n"
                f"DONE WHEN: Theme plan with channel mix.\n"
                f"TARGET: No random one-offs."
            ),
            "role_hint": "marketing",
            "done_when": "Sprint theme plan ready",
        },
        {
            "title": f"Generate {n} content pieces",
            "description": (
                f"generate_content for {n} pieces (mix formats). Real skill blocks required."
                f"{theme_bit}\n\n"
                f"DONE WHEN: {n} drafts in result.\n"
                f"TARGET: Full drafts with CTAs."
            ),
            "role_hint": "content",
            "done_when": f"{n} content drafts generated",
        },
        {
            "title": "Polish + CTA alignment",
            "description": (
                "list_products if offers exist; align CTAs to real products/offers. "
                "Tighten hooks and proof.\n\n"
                "DONE WHEN: CTAs consistent with catalogue/offers.\n"
                "TARGET: Sell-aligned copy."
            ),
            "role_hint": "marketing",
            "done_when": "CTAs polished and aligned",
        },
        {
            "title": "Publish pack to human",
            "description": (
                "status_update / notify_human with titles + full draft pack summary.\n\n"
                "DONE WHEN: Human has publish pack.\n"
                "TARGET: Ready for schedule/publish."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of content sprint pack",
        },
    ]


def _steps_for_marketing_seo_pack(count: int = 5, niche: str = "") -> list[dict[str, Any]]:
    n = max(2, min(15, int(count or 5)))
    niche_bit = f" Niche: {niche}." if niche else ""
    return [
        {
            "title": f"Keyword / topic research ({n} topics)",
            "description": (
                f"Research {n} SEO topics / keywords."
                f"{niche_bit}\n"
                f"Use generate_content / research-style analysis; save_memory seo_topics.\n\n"
                f"DONE WHEN: Ranked topic list with intent.\n"
                f"TARGET: {n} topics with primary keywords."
            ),
            "role_hint": "marketing",
            "done_when": f"{n} SEO topics researched",
        },
        {
            "title": "Outlines + intent map",
            "description": (
                f"Write outlines for each of the {n} topics (H2/H3, intent, internal links).\n\n"
                f"DONE WHEN: Outline per topic.\n"
                f"TARGET: Writer-ready structure."
            ),
            "role_hint": "content",
            "done_when": "SEO outlines complete",
        },
        {
            "title": f"Draft {n} articles / landing pages",
            "description": (
                f"generate_content drafts for the {n} outlines. Include meta title/description.\n\n"
                f"DONE WHEN: Draft body for each topic.\n"
                f"TARGET: First-draft publishable quality."
            ),
            "role_hint": "content",
            "done_when": f"{n} SEO drafts written",
        },
        {
            "title": "SEO backlog report",
            "description": (
                "status_update / notify_human: topics, draft status, recommended publish order.\n\n"
                "DONE WHEN: Human has SEO backlog brief.\n"
                "TARGET: Ranked publish order."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of SEO pack",
        },
    ]


def _steps_for_marketing_social_week(count: int = 12, theme: str = "") -> list[dict[str, Any]]:
    n = max(5, min(30, int(count or 12)))
    theme_bit = f" Theme: {theme}." if theme else ""
    return [
        {
            "title": "Weekly themes by channel",
            "description": (
                f"Plan a week of social across channels for ~{n} posts."
                f"{theme_bit}\n\n"
                f"DONE WHEN: Channel plan with post slots.\n"
                f"TARGET: Balanced week (not all one platform)."
            ),
            "role_hint": "marketing",
            "done_when": "Social week plan ready",
        },
        {
            "title": f"Draft {n} posts + hooks",
            "description": (
                f"generate_content for {n} platform-native posts with hooks and hashtags where useful."
                f"{theme_bit}\n\n"
                f"DONE WHEN: {n} post drafts.\n"
                f"TARGET: Ready-to-schedule copy."
            ),
            "role_hint": "content",
            "done_when": f"{n} social posts drafted",
        },
        {
            "title": "CTA + offer alignment",
            "description": (
                "list_products if available; align CTAs to real offers. "
                "Tighten weak posts.\n\n"
                "DONE WHEN: CTAs tied to real offers/products where possible.\n"
                "TARGET: Conversion-minded social pack."
            ),
            "role_hint": "marketing",
            "done_when": "Social CTAs aligned",
        },
        {
            "title": "Schedule pack to human",
            "description": (
                "status_update / notify_human with day-by-day post pack.\n\n"
                "DONE WHEN: Human has schedule pack.\n"
                "TARGET: Clear calendar of posts."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of social week pack",
        },
    ]


def _steps_for_coding_feature_ship(feature: str = "") -> list[dict[str, Any]]:
    feat = f" Feature: {feature}." if feature else ""
    return [
        {
            "title": "Clarify scope + success criteria",
            "description": (
                f"Clarify the feature goal, non-goals, success criteria, and constraints."
                f"{feat}\n"
                f"list_tasks related work; save_memory feature_scope.\n\n"
                f"DONE WHEN: Scope + DONE WHEN criteria written.\n"
                f"TARGET: No ambiguous ship bar."
            ),
            "role_hint": "lead",
            "done_when": "Feature scope and success criteria clear",
        },
        {
            "title": "Technical design",
            "description": (
                f"Write technical design: architecture, interfaces, trade-offs, risks."
                f"{feat}\n"
                f"generate_content or structured design in result. Note any new HTTP surfaces "
                f"that will later use write_api_endpoint.\n\n"
                f"DONE WHEN: Design doc in task result.\n"
                f"TARGET: Implementable design, not slides."
            ),
            "role_hint": "coding",
            "done_when": "Technical design documented",
        },
        {
            "title": "Implementation breakdown",
            "description": (
                "Break design into ordered implementation steps with owners/files/modules. "
                "create_task for sub-work if useful.\n"
                "For each new HTTP route, sketch write_api_endpoint args "
                "(method, path, purpose, auth_required) so implementers can call the skill.\n"
                "Flag modules that will need code_review before merge.\n\n"
                "Skills to plan for: write_api_endpoint, write_tests, code_review, "
                "refactor_code, database_migration as needed.\n\n"
                "DONE WHEN: Ordered implementation checklist with skill hints.\n"
                "TARGET: Sprint-executable steps."
            ),
            "role_hint": "coding",
            "done_when": "Implementation steps listed with write_api_endpoint / code_review notes",
            "checklist": [
                "Implementation steps ordered",
                "write_api_endpoint notes for new routes (or N/A)",
            ],
        },
        {
            "title": "Test plan + QA criteria",
            "description": (
                "Define unit/integration/e2e checks, edge cases, acceptance tests.\n"
                "Plan write_tests coverage goals (framework + coverage_goal). "
                "Define code_review focus_areas (security, correctness, performance) "
                "as the ship gate before human approve.\n\n"
                "Skills: write_tests, code_review (use when reviewing diffs/PRs).\n\n"
                "DONE WHEN: Test plan + code_review criteria with pass bar.\n"
                "TARGET: QA can verify ship readiness."
            ),
            "role_hint": "coding",
            "done_when": "Test plan and code_review criteria written",
            "checklist": [
                "write_tests plan defined",
                "code_review focus areas listed",
            ],
        },
        {
            "title": "Ship plan to human",
            "description": (
                "status_update / notify_human: design summary, steps, "
                "write_api_endpoint surface list, write_tests/code_review gate, residual risks.\n\n"
                "DONE WHEN: Human has ship plan.\n"
                "TARGET: Approve/implement decision ready."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of feature ship plan",
        },
    ]


def _steps_for_coding_bug_triage(batch: int = 10) -> list[dict[str, Any]]:
    b = max(3, min(30, int(batch or 10)))
    return [
        {
            "title": f"List open bug/defect work (≤{b})",
            "description": (
                f"list_tasks / search_tasks for bugs, defects, failures — up to {b}.\n\n"
                f"DONE WHEN: Prioritised bug list.\n"
                f"TARGET: Severity-ordered queue."
            ),
            "role_hint": "coding",
            "done_when": "Bug queue prioritised",
        },
        {
            "title": "Repro steps + severity",
            "description": (
                "For top bugs: repro steps, expected vs actual, severity, environment notes.\n"
                "Use debug_error on stack traces/logs when available "
                "(error, logs, language args).\n\n"
                "Skills: debug_error when traces exist.\n\n"
                "DONE WHEN: Repro notes for top items.\n"
                "TARGET: Another engineer can reproduce."
            ),
            "role_hint": "coding",
            "done_when": "Repro steps documented",
        },
        {
            "title": "Fix plan + risk notes",
            "description": (
                "Propose fix approach, risk, test needs, rollback idea per top bug.\n"
                "Note follow-up write_tests coverage and a code_review gate after the fix. "
                "If the bug is API-shaped, note write_api_endpoint changes needed.\n\n"
                "Skills to plan: debug_error, write_tests, code_review, refactor_code.\n\n"
                "DONE WHEN: Fix plan per prioritised bug.\n"
                "TARGET: Actionable engineering plan."
            ),
            "role_hint": "coding",
            "done_when": "Fix plans written",
        },
        {
            "title": "Triage report to human",
            "description": (
                "status_update / notify_human: counts by severity, top fixes, product decisions needed.\n\n"
                "DONE WHEN: Human has triage report.\n"
                "TARGET: Clear priority + asks."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of bug triage",
        },
    ]


def _steps_for_coding_api_scaffold(focus: str = "") -> list[dict[str, Any]]:
    focus_bit = f" Focus: {focus}." if focus else ""
    return [
        {
            "title": "Requirements + resources",
            "description": (
                f"Capture API requirements, actors, resources, auth, non-functional needs."
                f"{focus_bit}\n\n"
                f"DONE WHEN: Requirements list complete.\n"
                f"TARGET: No missing must-haves."
            ),
            "role_hint": "coding",
            "done_when": "API requirements captured",
        },
        {
            "title": "API contract design",
            "description": (
                f"Design endpoints/methods/errors/versioning."
                f"{focus_bit}\n"
                f"For each endpoint, prepare write_api_endpoint args: method, path, purpose, "
                f"auth_required — so implementation can call the skill directly.\n\n"
                f"Skills: write_api_endpoint (implementation handoff).\n\n"
                f"DONE WHEN: Contract sketch + write_api_endpoint checklist in result.\n"
                f"TARGET: Implementable OpenAPI-style notes."
            ),
            "role_hint": "coding",
            "done_when": "API contract designed with write_api_endpoint checklist",
            "checklist": ["write_api_endpoint args sketched per route"],
        },
        {
            "title": "Schema / data model notes",
            "description": (
                "Entities, keys, indexes, migration notes for the API surface. "
                "Note database_migration when schema changes are required.\n\n"
                "DONE WHEN: Schema notes written.\n"
                "TARGET: Data model ready for implementers."
            ),
            "role_hint": "coding",
            "done_when": "Schema notes complete",
        },
        {
            "title": "Test cases + acceptance",
            "description": (
                "Happy path + error + auth test cases; acceptance criteria checklist.\n"
                "Map cases to write_tests (framework + coverage_goal). "
                "Define code_review focus_areas for the PR that lands the API.\n\n"
                "Skills: write_tests, code_review.\n\n"
                "DONE WHEN: Test case list + code_review gate ready.\n"
                "TARGET: QA can execute without guessing."
            ),
            "role_hint": "coding",
            "done_when": "API test cases and code_review criteria written",
            "checklist": ["write_tests cases listed", "code_review focus areas listed"],
        },
        {
            "title": "Scaffold pack to human",
            "description": (
                "status_update / notify_human with contract, write_api_endpoint checklist, "
                "schema, write_tests/code_review summary.\n\n"
                "DONE WHEN: Human has API scaffold pack.\n"
                "TARGET: Ready to implement."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of API scaffold",
        },
    ]


def _steps_for_coding_tech_debt(batch: int = 12) -> list[dict[str, Any]]:
    b = max(5, min(40, int(batch or 12)))
    return [
        {
            "title": f"Inventory debt signals (≤{b})",
            "description": (
                f"list_tasks / search_tasks / search_memory — inventory up to {b} tech-debt items "
                f"(TODOs, flaky tests, slow paths, missing write_tests coverage, brittle APIs).\n"
                f"Skills: list_tasks, search_tasks, tech_debt_audit if available.\n\n"
                f"DONE WHEN: Debt inventory listed.\n"
                f"TARGET: Named debt items with sources."
            ),
            "role_hint": "coding",
            "done_when": "Tech debt inventory listed",
            "checklist": ["list_tasks or search_tasks used", f"≤{b} debt items named"],
        },
        {
            "title": "Score impact vs effort",
            "description": (
                "Score each item impact/effort/risk; recommend order.\n"
                "Note which items need refactor_code, write_tests, write_api_endpoint, "
                "or code_review as the remediation path.\n\n"
                "DONE WHEN: Scored backlog with skill remediation hints.\n"
                "TARGET: Prioritisation transparent."
            ),
            "role_hint": "coding",
            "done_when": "Debt items scored",
            "checklist": ["Impact/effort scores written", "Remediation skill hints listed"],
        },
        {
            "title": "Sprint-sized backlog",
            "description": (
                "Pick a sprint-sized slice; create_task for top items if useful.\n"
                "Each top item should name the primary skill path "
                "(refactor_code / write_tests / write_api_endpoint / code_review).\n\n"
                "DONE WHEN: Sprint backlog proposed with skill paths.\n"
                "TARGET: Executable this sprint."
            ),
            "role_hint": "lead",
            "done_when": "Sprint debt backlog proposed",
        },
        {
            "title": "Debt brief to human",
            "description": (
                "status_update / notify_human with top debt, scores, sprint proposal, "
                "and residual risk if deferred.\n\n"
                "DONE WHEN: Human has debt brief.\n"
                "TARGET: Decision-ready summary."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of tech debt plan",
            "checklist": ["status_update or notify_human sent"],
        },
    ]


def _steps_for_ops_sop(process: str = "") -> list[dict[str, Any]]:
    proc = f" Process: {process}." if process else ""
    return [
        {
            "title": "Process map + pain points",
            "description": (
                f"Map end-to-end process stages, handoffs, systems, pain points."
                f"{proc}\n\n"
                f"DONE WHEN: Process map in result.\n"
                f"TARGET: Stages + owners + pain points."
            ),
            "role_hint": "ops",
            "done_when": "Process map documented",
        },
        {
            "title": "Write SOP",
            "description": (
                f"Write standard operating procedure with steps, systems, controls."
                f"{proc}\n"
                f"generate_content / save_memory as needed.\n\n"
                f"DONE WHEN: Full SOP draft.\n"
                f"TARGET: Someone new can follow it."
            ),
            "role_hint": "ops",
            "done_when": "SOP written",
        },
        {
            "title": "RACI + SLA definition",
            "description": (
                "Define RACI matrix and operational SLAs with escalation rules.\n\n"
                "DONE WHEN: RACI + SLA table in result.\n"
                "TARGET: Clear accountability."
            ),
            "role_hint": "ops",
            "done_when": "RACI and SLAs defined",
        },
        {
            "title": "Runbook pack to human",
            "description": (
                "status_update / notify_human with SOP + RACI + SLA summary.\n\n"
                "DONE WHEN: Human has runbook pack.\n"
                "TARGET: Approve-and-rollout ready."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of SOP runbook",
        },
    ]


def _steps_for_ops_weekly_review(batch: int = 50) -> list[dict[str, Any]]:
    b = max(10, min(150, int(batch or 50)))
    return [
        {
            "title": f"Scan open tasks + status (≤{b})",
            "description": (
                f"Call list_tasks across the team (limit {b}; mine=false / open work). "
                f"Group by status, owner, and risk. Do not invent task lists from memory alone.\n\n"
                f"Skills REQUIRED: list_tasks (search_tasks optional for stuck keywords).\n\n"
                f"DONE WHEN: Rollup table from list_tasks in result.\n"
                f"TARGET: Counts by status + owners."
            ),
            "role_hint": "ops",
            "done_when": "Open work rollup from list_tasks complete",
            "checklist": ["list_tasks used", "Status/owner rollup written"],
        },
        {
            "title": "Blockers + SLA risks",
            "description": (
                "From the list_tasks rollup, flag blocked, overdue, or VIP-impacting work; "
                "note escalation needs. Re-check list_tasks if status changed mid-run.\n\n"
                "DONE WHEN: Blocker list prioritised.\n"
                "TARGET: Top risks clear."
            ),
            "role_hint": "ops",
            "done_when": "Blockers and SLA risks listed",
        },
        {
            "title": "Prioritised next-week plan",
            "description": (
                "Propose next-week priorities and ownership from the list_tasks snapshot; "
                "create_task for critical gaps if useful.\n\n"
                "DONE WHEN: Next-week plan written.\n"
                "TARGET: Owned priorities."
            ),
            "role_hint": "lead",
            "done_when": "Next-week plan prioritised",
        },
        {
            "title": "Weekly brief to human",
            "description": (
                "Send status_update (REQUIRED) with counts from list_tasks, top blockers, "
                "next-week plan, and asks. Use notify_human as well if the owner is offline "
                "from agent chat. Prose alone is NOT enough — emit a real status_update skill block.\n\n"
                "Skills REQUIRED: status_update (notify_human optional backup).\n\n"
                "DONE WHEN: Human has weekly ops brief via status_update.\n"
                "TARGET: Crisp executive summary."
            ),
            "role_hint": "orchestrator",
            "done_when": "status_update sent for weekly ops review",
            "checklist": ["status_update sent"],
        },
    ]


def _steps_for_ops_onboarding(who: str = "") -> list[dict[str, Any]]:
    who_bit = f" Onboarding for: {who}." if who else ""
    return [
        {
            "title": "Onboarding goals + systems",
            "description": (
                f"Define goals, systems, access, first-week success criteria."
                f"{who_bit}\n\n"
                f"DONE WHEN: Goals + systems list ready.\n"
                f"TARGET: Nothing critical missing."
            ),
            "role_hint": "ops",
            "done_when": "Onboarding goals and systems listed",
        },
        {
            "title": "Day-by-day checklist",
            "description": (
                f"Write day 1–5 (or week 1) checklist with concrete tasks."
                f"{who_bit}\n\n"
                f"DONE WHEN: Checklist complete.\n"
                f"TARGET: Executable without founder micromanagement."
            ),
            "role_hint": "ops",
            "done_when": "Onboarding checklist written",
        },
        {
            "title": "Owners + handoffs",
            "description": (
                "Assign owners per step; define handoffs and escalation.\n\n"
                "DONE WHEN: Owner map complete.\n"
                "TARGET: Every step has an owner."
            ),
            "role_hint": "ops",
            "done_when": "Owners and handoffs defined",
        },
        {
            "title": "Runbook to human",
            "description": (
                "status_update / notify_human with full onboarding runbook.\n\n"
                "DONE WHEN: Human has onboarding pack.\n"
                "TARGET: Ready to execute."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of onboarding runbook",
        },
    ]


def _steps_for_ops_incident(summary: str = "") -> list[dict[str, Any]]:
    sum_bit = f" Incident: {summary}." if summary else ""
    return [
        {
            "title": "Triage impact + severity",
            "description": (
                f"Triage incident: impact, severity, affected customers/systems, timeline."
                f"{sum_bit}\n\n"
                f"DONE WHEN: Severity + impact statement written.\n"
                f"TARGET: Shared facts, not speculation."
            ),
            "role_hint": "ops",
            "done_when": "Incident triage complete",
        },
        {
            "title": "Mitigation + owner tasks",
            "description": (
                "Define mitigation steps and owners; create_task / message_agent if team exists. "
                "Coding hint for technical fixes when relevant.\n\n"
                "DONE WHEN: Mitigation plan with owners.\n"
                "TARGET: Parallel work unblocked."
            ),
            "role_hint": "ops",
            "done_when": "Mitigation plan owned",
        },
        {
            "title": "Status updates",
            "description": (
                "status_update for stakeholders; log what changed and what's next.\n\n"
                "DONE WHEN: Status cadence documented.\n"
                "TARGET: No silent incidents."
            ),
            "role_hint": "ops",
            "done_when": "Incident status updates sent",
        },
        {
            "title": "Postmortem + actions to human",
            "description": (
                "Draft short postmortem: root cause hypothesis, timeline, action items. "
                "notify_human / status_update.\n\n"
                "DONE WHEN: Human has postmortem + actions.\n"
                "TARGET: Prevent recurrence."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of incident postmortem",
        },
    ]


def _steps_for_product_catalog_build(count: int = 5, niche: str = "") -> list[dict[str, Any]]:
    n = max(1, min(30, int(count or 5)))
    niche_bit = f" Niche/category: {niche}." if niche else ""
    return [
        {
            "title": "Audit existing product catalogue",
            "description": (
                f"list_products / search_products (limit 50). Note what already exists "
                f"so we do not duplicate SKUs. Write a short inventory in the result.\n"
                f"{niche_bit}\n\n"
                f"Skills: list_products, search_products, read_product.\n\n"
                f"DONE WHEN: Catalogue snapshot listed (names, prices, offers).\n"
                f"TARGET: Clear picture of current products."
            ),
            "role_hint": "sales",
            "done_when": "Existing products listed",
            "checklist": ["list_products or search_products ran", "Inventory written in result"],
        },
        {
            "title": f"Define {n} product specs",
            "description": (
                f"Define {n} products/services{niche_bit}: name, price, kind, benefits, audience, "
                f"optional offer. Prefer services + products the business can sell.\n\n"
                f"DONE WHEN: Spec sheet for {n} items ready to write.\n"
                f"TARGET: Name, price, description, benefits per item."
            ),
            "role_hint": "sales",
            "done_when": f"{n} product specs drafted",
            "checklist": [f"{n} product names defined", "Price on each item"],
        },
        {
            "title": f"Write {n} products to catalogue",
            "description": (
                f"For each of the {n} specs call write_product or create_product "
                f"(use write_product to upsert by name). Include price, description, tags, benefits.\n\n"
                f"Skills REQUIRED: write_product / create_product (prose alone is NOT enough).\n\n"
                f"DONE WHEN: {n} products exist in catalogue with product_ids.\n"
                f"TARGET: Product ids listed in result."
            ),
            "role_hint": "sales",
            "done_when": f"{n} products written via skills",
            "checklist": [
                "write_product or create_product used for each item",
                "Product ids returned",
            ],
        },
        {
            "title": "Set special offers + polish",
            "description": (
                "set_product_offer or update_product offer on key SKUs; "
                "fill missing description/benefits with update_product / write_product.\n\n"
                "DONE WHEN: Offers set where planned; gaps filled.\n"
                "TARGET: Catalogue sell-ready."
            ),
            "role_hint": "sales",
            "done_when": "Offers and polish applied",
            "checklist": ["At least one offer set or explicitly none needed"],
        },
        {
            "title": "Report catalogue to human",
            "description": (
                "list_products again; status_update or notify_human with names, prices, offers, "
                "and product_ids. save_memory product_catalog_build.\n\n"
                "DONE WHEN: Human has the catalogue brief.\n"
                "TARGET: Owner notified."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified with product list",
            "checklist": ["status_update or notify_human sent"],
        },
    ]


def _steps_for_product_offer_campaign(batch: int = 10, theme: str = "") -> list[dict[str, Any]]:
    b = max(1, min(40, int(batch or 10)))
    theme_bit = f" Offer theme: {theme}." if theme else ""
    return [
        {
            "title": f"Read up to {b} products",
            "description": (
                f"list_products / search_products limit {b}; read_product on each pick.\n"
                f"{theme_bit}\n\n"
                f"DONE WHEN: Shortlist of products with current prices/offers.\n"
                f"TARGET: Product ids + names ready for promos."
            ),
            "role_hint": "sales",
            "done_when": f"Up to {b} products read",
            "checklist": ["list_products/search_products used", "read_product on key items"],
        },
        {
            "title": "Set special offers",
            "description": (
                f"set_product_offer or write_product offer=… on each shortlisted product.\n"
                f"{theme_bit}\n\n"
                f"Skills REQUIRED: set_product_offer / update_product / write_product.\n\n"
                f"DONE WHEN: Offers saved on products (not just drafted in prose).\n"
                f"TARGET: offer field non-empty on campaign SKUs."
            ),
            "role_hint": "sales",
            "done_when": "Special offers written to products",
            "checklist": ["set_product_offer or update_product used"],
        },
        {
            "title": "Draft promo email + content",
            "description": (
                "draft_email and generate_content for the offer campaign using real product names "
                "and offer text from the catalogue. log_customer_activity if a list exists.\n\n"
                "DONE WHEN: Promo copy ready (email + short social/web blurb).\n"
                "TARGET: Copy references real product offers."
            ),
            "role_hint": "outreach",
            "done_when": "Promo email and content drafted",
            "checklist": ["draft_email or generate_content used"],
        },
        {
            "title": "Notify human of campaign pack",
            "description": (
                "status_update / notify_human with product list, offers, and draft copy summary.\n\n"
                "DONE WHEN: Owner has the campaign pack.\n"
                "TARGET: Clear human brief."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of offer campaign",
        },
    ]


def _steps_for_research_competitor_brief(count: int = 5, niche: str = "") -> list[dict[str, Any]]:
    n = max(2, min(15, int(count or 5)))
    niche_bit = f" Focus: {niche}." if niche else ""
    return [
        {
            "title": f"Scope {n} rivals + research questions",
            "description": (
                f"Name up to {n} competitors or rival products to study."
                f"{niche_bit}\n"
                f"Write research questions: positioning, pricing signals, ICP, strengths/weaknesses, "
                f"where we win/lose.\n"
                f"Skills: research, save_memory competitor_scope.\n\n"
                f"DONE WHEN: Rival list + questions documented.\n"
                f"TARGET: Clear research scope (not vague 'do competitive analysis')."
            ),
            "role_hint": "research",
            "done_when": f"Up to {n} competitors scoped with questions",
            "checklist": [f"≤{n} rivals named", "Research questions written"],
        },
        {
            "title": f"Research + summarize {n} competitors",
            "description": (
                f"For each rival: research + summarize (positioning, offers, proof, gaps)."
                f"{niche_bit}\n"
                f"Skills REQUIRED: research and/or summarize (real skill blocks).\n\n"
                f"DONE WHEN: One-pager notes per competitor.\n"
                f"TARGET: Evidence-based notes, not generic adjectives."
            ),
            "role_hint": "research",
            "done_when": f"Notes for up to {n} competitors",
            "checklist": ["research or summarize used"],
        },
        {
            "title": "Battlecards + win themes",
            "description": (
                "Turn notes into battlecards: talk tracks, landmines, pricing posture, "
                "when to escalate. generate_content / generate_report as needed.\n\n"
                "DONE WHEN: Battlecard pack for sales/marketing.\n"
                "TARGET: Usable in a live deal conversation."
            ),
            "role_hint": "research",
            "done_when": "Battlecards drafted",
        },
        {
            "title": "Competitor brief to human",
            "description": (
                "status_update / notify_human with rival summary, win themes, and open questions. "
                "save_memory competitor_brief.\n\n"
                "DONE WHEN: Human has the brief.\n"
                "TARGET: Decision-ready competitive pack."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of competitor brief",
            "checklist": ["status_update or notify_human sent"],
        },
    ]


def _steps_for_finance_cashflow_forecast(batch: int = 30, focus: str = "") -> list[dict[str, Any]]:
    b = max(5, min(100, int(batch or 30)))
    focus_bit = f" Horizon/focus: {focus}." if focus else ""
    return [
        {
            "title": f"Pipeline + deal snapshot (≤{b})",
            "description": (
                f"pipeline_summary, list_deals, list_customers — scan up to {b} open deals/signals."
                f"{focus_bit}\n"
                f"Note stages, values, age, stall risk. Do not invent deal values.\n"
                f"Skills: pipeline_summary, list_deals, list_customers.\n\n"
                f"DONE WHEN: Snapshot table with values and stages.\n"
                f"TARGET: Ground truth from CRM skills."
            ),
            "role_hint": "sales",
            "done_when": "Pipeline snapshot captured",
            "checklist": ["pipeline_summary or list_deals used"],
        },
        {
            "title": "Forecast risk + cashflow narrative",
            "description": (
                f"Draft forecast narrative: weighted pipeline, concentration risk, timing."
                f"{focus_bit}\n"
                f"Skills: research / summarize / generate_report / cashflow_forecast if available.\n\n"
                f"DONE WHEN: Base forecast narrative with assumptions.\n"
                f"TARGET: Numbers + assumptions explicit."
            ),
            "role_hint": "research",
            "done_when": "Forecast narrative written",
        },
        {
            "title": "Scenarios: base / upside / downside",
            "description": (
                "Three scenarios with drivers and what would change the outcome. "
                "Flag decisions the owner must make.\n\n"
                "DONE WHEN: Three scenarios documented.\n"
                "TARGET: Actionable scenario pack."
            ),
            "role_hint": "research",
            "done_when": "Three forecast scenarios ready",
        },
        {
            "title": "Forecast brief to human",
            "description": (
                "status_update / notify_human: headline forecast, risks, top asks. "
                "save_memory finance_forecast_brief.\n\n"
                "DONE WHEN: Owner has forecast brief.\n"
                "TARGET: Clear numbers + decisions."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of finance forecast",
            "checklist": ["status_update or notify_human sent"],
        },
    ]


def _steps_for_product_catalog_audit(batch: int = 50) -> list[dict[str, Any]]:
    b = max(5, min(100, int(batch or 50)))
    return [
        {
            "title": f"List/search up to {b} products",
            "description": (
                f"list_products limit {b}; search_products for empty price/description/status issues.\n\n"
                f"DONE WHEN: Full inventory with flags (missing price, draft, no offer, etc.).\n"
                f"TARGET: Audit spreadsheet-style list in result."
            ),
            "role_hint": "ops",
            "done_when": "Catalogue inventory with gap flags",
            "checklist": ["list_products ran"],
        },
        {
            "title": "Read incomplete products",
            "description": (
                "read_product / get_product on incomplete rows. Note exact fields to fix.\n\n"
                "DONE WHEN: Fix list per product_id.\n"
                "TARGET: Field-level gap list."
            ),
            "role_hint": "ops",
            "done_when": "Incomplete products fully read",
        },
        {
            "title": "Write fixes",
            "description": (
                "write_product / update_product for missing description, price, tags, benefits. "
                "Do NOT invent illegal prices — flag unknowns.\n\n"
                "Skills REQUIRED: write_product or update_product.\n\n"
                "DONE WHEN: Fixable gaps written to DB.\n"
                "TARGET: Improved catalogue completeness."
            ),
            "role_hint": "sales",
            "done_when": "Product fields updated via skills",
            "checklist": ["write_product or update_product used"],
        },
        {
            "title": "Archive stale or flag",
            "description": (
                "archive_product for clearly obsolete SKUs; leave others active. "
                "Never hard-delete without human ask.\n\n"
                "DONE WHEN: Stale items archived or listed for human decision.\n"
                "TARGET: Clean active catalogue."
            ),
            "role_hint": "ops",
            "done_when": "Stale products archived or flagged",
        },
        {
            "title": "Audit report to lead/human",
            "description": (
                "status_update / notify_human: counts fixed, archived, still open gaps.\n\n"
                "DONE WHEN: Lead has the audit summary.\n"
                "TARGET: Numbers + product_ids."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of audit results",
        },
    ]


def build_workflow_prompt(
    preset: dict[str, Any],
    *,
    count: int | None = None,
    niche: str = "",
    extra: str = "",
    params: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Return (goal prompt text, explicit steps) for a preset."""
    params = params or {}
    wid = preset["id"]
    niche = (niche or params.get("niche") or "").strip()
    extra = (extra or params.get("extra") or "").strip()

    def _with_extra(prompt: str) -> str:
        if extra:
            return f"{prompt}\n\nExtra instructions: {extra}"
        return prompt

    if wid == "sales_targets_crm_outreach":
        n = int(count if count is not None else params.get("count") or preset.get("default_count") or 50)
        n = max(5, min(100, n))
        niche_bit = f" Focus niche/ICP: {niche}." if niche else ""
        prompt = (
            f"Get {n} sales targets and save them in CRM, then outreach "
            f"(emails and calls) and update the sales pipeline.{niche_bit}"
        )
        return _with_extra(prompt), decompose_sales_pipeline(prompt, max_steps=6)

    if wid == "crm_outreach_only":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 20)
        b = max(5, min(50, b))
        prompt = f"Outreach up to {b} existing CRM contacts: email, call, update pipeline."
        return _with_extra(prompt), _steps_for_crm_outreach(b)

    if wid == "sales_pipeline_review":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 25)
        b = max(5, min(80, b))
        prompt = f"Review up to {b} pipeline deals, unstick stalls, re-engage, report forecast risk."
        return _with_extra(prompt), _steps_for_sales_pipeline_review(b)

    if wid == "sales_proposal_pack":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 5)
        b = max(1, min(15, b))
        focus = niche or str(params.get("theme") or "")
        focus_bit = f" Focus: {focus}." if focus else ""
        prompt = f"Build proposal packs for up to {b} open deals.{focus_bit}"
        return _with_extra(prompt), _steps_for_sales_proposal_pack(b, focus)

    if wid == "sales_meeting_followup":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 10)
        b = max(3, min(30, b))
        prompt = f"Follow up up to {b} recent meetings: CRM update, emails, commitments report."
        return _with_extra(prompt), _steps_for_sales_meeting_followup(b)

    if wid == "support_ticket_triage":
        prompt = "Triage open support work, resolve or draft replies, escalate VIP/blocked."
        return _with_extra(prompt), _steps_for_support()

    if wid == "support_vip_recovery":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 10)
        b = max(3, min(30, b))
        prompt = f"VIP health recovery for up to {b} accounts: plans, outreach, escalate blockers."
        return _with_extra(prompt), _steps_for_support_vip_recovery(b)

    if wid == "support_kb_macros":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 8)
        b = max(3, min(20, b))
        prompt = f"Build {b} support macros/KB replies from recurring issues and publish the pack."
        return _with_extra(prompt), _steps_for_support_kb_macros(b)

    if wid == "support_churn_save":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 15)
        b = max(5, min(40, b))
        prompt = f"Churn-save campaign for up to {b} at-risk accounts: offers, outreach, report."
        return _with_extra(prompt), _steps_for_support_churn_save(b)

    if wid == "marketing_campaign_launch":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 6)
        b = max(3, min(20, b))
        theme = niche or str(params.get("theme") or "")
        theme_bit = f" Theme: {theme}." if theme else ""
        prompt = f"Launch campaign pack: brief, calendar, {b} assets, human approval.{theme_bit}"
        return _with_extra(prompt), _steps_for_marketing_campaign(b, theme)

    if wid == "marketing_content_sprint":
        n = int(count if count is not None else params.get("count") or preset.get("default_count") or 8)
        n = max(3, min(25, n))
        theme = niche or str(params.get("theme") or "")
        theme_bit = f" Theme: {theme}." if theme else ""
        prompt = f"Content sprint: plan and draft {n} multi-channel pieces.{theme_bit}"
        return _with_extra(prompt), _steps_for_marketing_content_sprint(n, theme)

    if wid == "marketing_seo_pack":
        n = int(count if count is not None else params.get("count") or preset.get("default_count") or 5)
        n = max(2, min(15, n))
        niche_bit = f" Niche: {niche}." if niche else ""
        prompt = f"SEO pack: research, outline, and draft {n} topics.{niche_bit}"
        return _with_extra(prompt), _steps_for_marketing_seo_pack(n, niche)

    if wid == "marketing_social_week":
        n = int(count if count is not None else params.get("count") or preset.get("default_count") or 12)
        n = max(5, min(30, n))
        theme = niche or str(params.get("theme") or "")
        theme_bit = f" Theme: {theme}." if theme else ""
        prompt = f"Social week pack: plan and draft {n} posts.{theme_bit}"
        return _with_extra(prompt), _steps_for_marketing_social_week(n, theme)

    if wid == "coding_feature_ship":
        feature = niche or str(params.get("feature") or params.get("theme") or "")
        feat_bit = f" Feature: {feature}." if feature else ""
        prompt = f"Ship feature plan: scope, design, implementation steps, tests.{feat_bit}"
        return _with_extra(prompt), _steps_for_coding_feature_ship(feature)

    if wid == "coding_bug_triage":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 10)
        b = max(3, min(30, b))
        prompt = f"Triage up to {b} bugs: repro, fix plans, report to human."
        return _with_extra(prompt), _steps_for_coding_bug_triage(b)

    if wid == "coding_api_scaffold":
        focus = niche or str(params.get("feature") or params.get("theme") or "")
        focus_bit = f" Focus: {focus}." if focus else ""
        prompt = f"API scaffold pack: requirements, contract, schema, tests.{focus_bit}"
        return _with_extra(prompt), _steps_for_coding_api_scaffold(focus)

    if wid == "coding_tech_debt":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 12)
        b = max(5, min(40, b))
        prompt = f"Tech debt audit for up to {b} items: score, sprint backlog, brief human."
        return _with_extra(prompt), _steps_for_coding_tech_debt(b)

    if wid == "ops_sop_standardize":
        process = niche or str(params.get("process") or params.get("theme") or "")
        proc_bit = f" Process: {process}." if process else ""
        prompt = f"Standardize process: map, SOP, RACI, SLA runbook.{proc_bit}"
        return _with_extra(prompt), _steps_for_ops_sop(process)

    if wid == "ops_weekly_review":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 50)
        b = max(10, min(150, b))
        prompt = f"Weekly ops review across up to {b} tasks: blockers, plan, human brief."
        return _with_extra(prompt), _steps_for_ops_weekly_review(b)

    if wid == "ops_onboarding_runbook":
        who = niche or str(params.get("who") or params.get("theme") or "")
        who_bit = f" For: {who}." if who else ""
        prompt = f"Build onboarding runbook with checklist, owners, handoffs.{who_bit}"
        return _with_extra(prompt), _steps_for_ops_onboarding(who)

    if wid == "ops_incident_response":
        summary = niche or str(params.get("incident") or params.get("theme") or "")
        sum_bit = f" Incident: {summary}." if summary else ""
        prompt = f"Incident response: triage, mitigate, status, postmortem.{sum_bit}"
        return _with_extra(prompt), _steps_for_ops_incident(summary)

    if wid == "product_catalog_build":
        n = int(count if count is not None else params.get("count") or preset.get("default_count") or 5)
        n = max(1, min(30, n))
        niche_bit = f" Focus: {niche}." if niche else ""
        prompt = (
            f"Build {n} products/services in the catalogue using write_product/create_product, "
            f"set prices and offers, then report to the human.{niche_bit}"
        )
        return _with_extra(prompt), _steps_for_product_catalog_build(n, niche)

    if wid == "product_offer_campaign":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 10)
        b = max(1, min(40, b))
        theme = niche or str(params.get("theme") or "")
        theme_bit = f" Theme: {theme}." if theme else ""
        prompt = (
            f"Read up to {b} products, set special offers, draft promo email/content, "
            f"notify human.{theme_bit}"
        )
        return _with_extra(prompt), _steps_for_product_offer_campaign(b, theme)

    if wid == "product_catalog_audit":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 50)
        b = max(5, min(100, b))
        prompt = (
            f"Audit up to {b} catalogue products: list/read, fix via write_product, "
            f"archive stale, report gaps."
        )
        return _with_extra(prompt), _steps_for_product_catalog_audit(b)

    if wid == "research_competitor_brief":
        n = int(count if count is not None else params.get("count") or preset.get("default_count") or 5)
        n = max(2, min(15, n))
        niche_bit = f" Focus: {niche}." if niche else ""
        prompt = (
            f"Research up to {n} competitors, build battlecards, and deliver a "
            f"decision-ready brief to the human.{niche_bit}"
        )
        return _with_extra(prompt), _steps_for_research_competitor_brief(n, niche)

    if wid == "finance_cashflow_forecast":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 30)
        b = max(5, min(100, b))
        focus = niche or str(params.get("focus") or params.get("theme") or "")
        focus_bit = f" Horizon/focus: {focus}." if focus else ""
        prompt = (
            f"Scan up to {b} pipeline/deal signals, draft cashflow/forecast scenarios, "
            f"and notify the owner.{focus_bit}"
        )
        return _with_extra(prompt), _steps_for_finance_cashflow_forecast(b, focus)

    # Fallback: treat free text
    prompt = extra or preset.get("name") or wid
    if looks_like_sales_pipeline(prompt):
        return prompt, decompose_sales_pipeline(prompt)
    return prompt, []


def _coerce_int(value: Any, *, field: str) -> tuple[int | None, str | None]:
    """Parse an optional int; return (value, error). Empty/None → (None, None)."""
    if value is None or value == "":
        return None, None
    if isinstance(value, bool):
        return None, f"{field} must be a whole number (got boolean)"
    if isinstance(value, float) and not float(value).is_integer():
        return None, f"{field} must be a whole number (got {value!r})"
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, f"{field} must be a whole number (got {value!r})"


def validate_workflow_params(
    preset: dict[str, Any],
    *,
    count: int | None = None,
    niche: str = "",
    extra: str = "",
    params: dict[str, Any] | None = None,
    priority: str = "high",
) -> dict[str, Any]:
    """
    Validate caller inputs against the preset param schema.

    Returns:
      {ok: True, count, niche, extra, params, priority}
      or {ok: False, error: "..."}.
    """
    params = dict(params or {})
    niche = (niche if niche is not None else "") or str(params.get("niche") or "")
    niche = str(niche).strip()
    extra = (extra if extra is not None else "") or str(params.get("extra") or "")
    extra = str(extra).strip()
    if len(niche) > 500:
        return {"ok": False, "error": "niche is too long (max 500 characters)"}
    if len(extra) > 4000:
        return {"ok": False, "error": "extra instructions are too long (max 4000 characters)"}

    pri = (priority or "high").strip().lower()
    if pri not in _ALLOWED_PRIORITIES:
        allowed = ", ".join(sorted(_ALLOWED_PRIORITIES))
        return {
            "ok": False,
            "error": f"Invalid priority {priority!r}. Allowed: {allowed}",
        }

    top_count, err = _coerce_int(count, field="count")
    if err:
        return {"ok": False, "error": err}

    schema = list(preset.get("params") or [])
    number_keys = {
        str(p.get("key")): p
        for p in schema
        if (p.get("type") or "string") == "number" and p.get("key")
    }

    resolved_count = top_count
    for key, spec in number_keys.items():
        raw = params.get(key)
        if raw is None and top_count is not None and key in ("count", "batch"):
            raw = top_count
        parsed, err = _coerce_int(raw, field=key)
        if err:
            return {"ok": False, "error": err}
        if parsed is None:
            continue
        lo = spec.get("min")
        hi = spec.get("max")
        label = spec.get("label") or key
        if lo is not None and parsed < int(lo):
            return {"ok": False, "error": f"{label} must be ≥ {lo} (got {parsed})"}
        if hi is not None and parsed > int(hi):
            return {"ok": False, "error": f"{label} must be ≤ {hi} (got {parsed})"}
        params[key] = parsed
        if key in ("count", "batch") and resolved_count is None:
            resolved_count = parsed

    # Top-level count alone against primary number param (count → batch → first)
    if top_count is not None and number_keys:
        if "count" in number_keys:
            spec = number_keys["count"]
        elif "batch" in number_keys:
            spec = number_keys["batch"]
        else:
            spec = next(iter(number_keys.values()))
        lo = spec.get("min")
        hi = spec.get("max")
        label = spec.get("label") or spec.get("key") or "count"
        if lo is not None and top_count < int(lo):
            return {"ok": False, "error": f"{label} must be ≥ {lo} (got {top_count})"}
        if hi is not None and top_count > int(hi):
            return {"ok": False, "error": f"{label} must be ≤ {hi} (got {top_count})"}
        resolved_count = top_count
        key = str(spec.get("key") or "count")
        if key not in params:
            params[key] = top_count

    return {
        "ok": True,
        "count": resolved_count,
        "niche": niche,
        "extra": extra,
        "params": params,
        "priority": pri,
    }


async def start_workflow(
    db: Session,
    user: models.User,
    owner: models.Agent,
    workflow_id: str,
    *,
    count: int | None = None,
    niche: str = "",
    extra: str = "",
    params: dict[str, Any] | None = None,
    company_id: int | None = None,
    project_id: int | None = None,
    priority: str = "high",
) -> dict[str, Any]:
    """Launch a named workflow as an auto-chain goal."""
    wid = (workflow_id or "").strip()
    if not wid:
        return {"ok": False, "error": "workflow_id is required"}

    preset = get_preset(wid)
    if not preset:
        known = ", ".join(p["id"] for p in WORKFLOW_PRESETS[:8])
        more = len(WORKFLOW_PRESETS) - 8
        hint = f" Known examples: {known}" + (f" (+{more} more)." if more > 0 else ".")
        return {"ok": False, "error": f"Unknown workflow: {workflow_id}.{hint}"}

    if owner is None:
        return {"ok": False, "error": "No owner agent provided for workflow"}

    validated = validate_workflow_params(
        preset,
        count=count,
        niche=niche,
        extra=extra,
        params=params,
        priority=priority,
    )
    if not validated.get("ok"):
        return {
            "ok": False,
            "error": validated.get("error") or "Invalid workflow parameters",
            "workflow_id": preset["id"],
        }

    v_count = validated.get("count")
    v_niche = validated.get("niche") or ""
    v_extra = validated.get("extra") or ""
    v_params = validated.get("params") or {}
    v_priority = validated.get("priority") or "high"

    prompt, steps = build_workflow_prompt(
        preset,
        count=v_count,
        niche=v_niche,
        extra=v_extra,
        params=v_params,
    )
    if not steps:
        return {
            "ok": False,
            "error": (
                f"Workflow {preset['id']!r} produced no steps — "
                "check params or use a different preset"
            ),
            "workflow_id": preset["id"],
        }

    title = preset["name"]
    if v_count is not None:
        title = f"{preset['name']} ({v_count})"

    result = await start_goal_chain(
        db,
        user,
        owner,
        prompt,
        title=title[:160],
        company_id=company_id,
        project_id=project_id,
        priority=v_priority,
        steps=steps,
        max_steps=6,
        auto_queue=True,
    )
    if isinstance(result, dict):
        result["workflow_id"] = preset["id"]
        result["workflow_name"] = preset["name"]
        result.setdefault("ok", True)
        result["params_used"] = {
            "count": v_count,
            "niche": v_niche,
            "priority": v_priority,
            "params": v_params,
        }
    return result
