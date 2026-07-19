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
