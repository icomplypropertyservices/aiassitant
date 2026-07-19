"""
Named multi-agent workflow presets.

Example product flow:
  Get 50 sales targets → save in CRM → second agent emails/calls → update pipeline.

Presets expand into explicit step lists for task_chain.start_goal_chain so handoffs
are reliable (role_hint + DONE WHEN + skill instructions) instead of a vague goal.
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

# Catalog shown in per-agent dashboards and Settings → Agents
WORKFLOW_PRESETS: list[dict[str, Any]] = [
    {
        "id": "sales_targets_crm_outreach",
        "name": "Sales targets → CRM → outreach",
        "description": (
            "Agent 1 generates N sales targets and saves them as CRM customers + deals. "
            "Agent 2 sends emails/calls, logs activity, and updates the pipeline."
        ),
        "category": "sales",
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
            "Save customers + deals in CRM (Sales)",
            "Emails and calls (Outreach)",
            "Update pipeline stages (Sales)",
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
        "id": "support_ticket_triage",
        "name": "Support triage → resolve → follow-up",
        "description": (
            "Support agent triages open work, resolves or drafts replies, "
            "logs customer activity, and notifies the human of VIP/blocked cases."
        ),
        "category": "support",
        "default_count": 10,
        "params": [],
        "steps_preview": [
            "List open support tasks / customers",
            "Draft replies and log activity",
            "Escalate VIP/blocked to human",
        ],
    },
    {
        "id": "product_catalog_build",
        "name": "Build product catalogue",
        "description": (
            "Research / define N products or services, write them into the catalogue "
            "(write_product / create_product), set prices and special offers, then report."
        ),
        "category": "product",
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
]


def list_workflow_presets() -> list[dict[str, Any]]:
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "description": p["description"],
            "category": p.get("category") or "general",
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


def _steps_for_crm_outreach(batch: int = 20) -> list[dict[str, Any]]:
    b = max(5, min(50, int(batch or 20)))
    return [
        {
            "title": f"Pull up to {b} open CRM opportunities",
            "description": (
                f"list_customers, list_deals, get_pipeline / pipeline_summary.\n"
                f"Identify up to {b} open deals or recent customers that need outreach.\n"
                f"Write the shortlist in the task result (name, email, deal id, stage).\n\n"
                f"DONE WHEN: Shortlist of ≤{b} contacts ready for outreach.\n"
                f"TARGET: Named CRM shortlist with emails."
            ),
            "role_hint": "sales",
            "done_when": f"Shortlist of up to {b} CRM contacts",
        },
        {
            "title": "Emails, calls, activity logs",
            "description": (
                f"For each shortlisted contact: draft_email, send_email when possible, "
                f"log_customer_activity; call script if phone present.\n"
                f"Batch size ≤{b}. Real skill blocks required.\n\n"
                f"DONE WHEN: Outreach attempted and logged for the shortlist batch.\n"
                f"TARGET: Activity visible on CRM customers."
            ),
            "role_hint": "outreach",
            "done_when": "Outreach logged on shortlisted customers",
        },
        {
            "title": "Update pipeline and report",
            "description": (
                "move_deal / update_deal for contacted leads; pipeline_summary; "
                "status_update or notify_human with counts.\n\n"
                "DONE WHEN: Pipeline updated and human notified.\n"
                "TARGET: Clear owner brief with numbers."
            ),
            "role_hint": "sales",
            "done_when": "Pipeline updated and human status_update sent",
        },
    ]


def _steps_for_support() -> list[dict[str, Any]]:
    return [
        {
            "title": "Triage open support work",
            "description": (
                "list_tasks mine=false open support items; list_customers with issues; "
                "list_activity. Prioritise VIP/urgent.\n\n"
                "DONE WHEN: Prioritised queue written in result.\n"
                "TARGET: Top issues ranked."
            ),
            "role_hint": "support",
            "done_when": "Prioritised support queue documented",
        },
        {
            "title": "Resolve or draft customer replies",
            "description": (
                "draft_email / send_email or log_customer_activity for each priority case. "
                "complete_task child work when fixed.\n\n"
                "DONE WHEN: Replies drafted/sent or blockers noted.\n"
                "TARGET: Customer-facing progress on top cases."
            ),
            "role_hint": "support",
            "done_when": "Replies or resolutions for priority cases",
        },
        {
            "title": "Escalate VIP/blocked + notify human",
            "description": (
                "status_update / notify_human for anything blocked or VIP. "
                "save_memory support_triage_summary.\n\n"
                "DONE WHEN: Human has a short triage report.\n"
                "TARGET: Owner notified."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human notified of triage outcomes",
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

    if wid == "sales_targets_crm_outreach":
        n = int(count if count is not None else params.get("count") or preset.get("default_count") or 50)
        n = max(5, min(100, n))
        niche_bit = f" Focus niche/ICP: {niche}." if niche else ""
        prompt = (
            f"Get {n} sales targets and save them in CRM, then outreach "
            f"(emails and calls) and update the sales pipeline.{niche_bit}"
        )
        if extra:
            prompt = f"{prompt}\n\nExtra instructions: {extra}"
        return prompt, decompose_sales_pipeline(prompt, max_steps=6)

    if wid == "crm_outreach_only":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 20)
        b = max(5, min(50, b))
        prompt = f"Outreach up to {b} existing CRM contacts: email, call, update pipeline."
        if extra:
            prompt = f"{prompt}\n\nExtra instructions: {extra}"
        return prompt, _steps_for_crm_outreach(b)

    if wid == "support_ticket_triage":
        prompt = "Triage open support work, resolve or draft replies, escalate VIP/blocked."
        if extra:
            prompt = f"{prompt}\n\nExtra instructions: {extra}"
        return prompt, _steps_for_support()

    if wid == "product_catalog_build":
        n = int(count if count is not None else params.get("count") or preset.get("default_count") or 5)
        n = max(1, min(30, n))
        niche_bit = f" Focus: {niche}." if niche else ""
        prompt = (
            f"Build {n} products/services in the catalogue using write_product/create_product, "
            f"set prices and offers, then report to the human.{niche_bit}"
        )
        if extra:
            prompt = f"{prompt}\n\nExtra instructions: {extra}"
        return prompt, _steps_for_product_catalog_build(n, niche)

    if wid == "product_offer_campaign":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 10)
        b = max(1, min(40, b))
        theme = niche or str(params.get("theme") or "")
        theme_bit = f" Theme: {theme}." if theme else ""
        prompt = (
            f"Read up to {b} products, set special offers, draft promo email/content, "
            f"notify human.{theme_bit}"
        )
        if extra:
            prompt = f"{prompt}\n\nExtra instructions: {extra}"
        return prompt, _steps_for_product_offer_campaign(b, theme)

    if wid == "product_catalog_audit":
        b = int(count if count is not None else params.get("batch") or params.get("count") or 50)
        b = max(5, min(100, b))
        prompt = (
            f"Audit up to {b} catalogue products: list/read, fix via write_product, "
            f"archive stale, report gaps."
        )
        if extra:
            prompt = f"{prompt}\n\nExtra instructions: {extra}"
        return prompt, _steps_for_product_catalog_audit(b)

    # Fallback: treat free text
    prompt = extra or preset.get("name") or wid
    if looks_like_sales_pipeline(prompt):
        return prompt, decompose_sales_pipeline(prompt)
    return prompt, []


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
    preset = get_preset(workflow_id)
    if not preset:
        return {"ok": False, "error": f"Unknown workflow: {workflow_id}"}

    prompt, steps = build_workflow_prompt(
        preset,
        count=count,
        niche=niche,
        extra=extra,
        params=params,
    )
    title = preset["name"]
    if count or (params or {}).get("count"):
        n = count if count is not None else (params or {}).get("count")
        if n:
            title = f"{preset['name']} ({n})"

    result = await start_goal_chain(
        db,
        user,
        owner,
        prompt,
        title=title[:160],
        company_id=company_id,
        project_id=project_id,
        priority=priority or "high",
        steps=steps if steps else None,
        max_steps=6,
        auto_queue=True,
    )
    if isinstance(result, dict):
        result["workflow_id"] = preset["id"]
        result["workflow_name"] = preset["name"]
    return result
