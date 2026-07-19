"""
Debug team: 10 agents + gatekeeper that must check every fix.

Gatekeeper (lead) never auto-completes peer work without review_task.
Specialists produce fixes; all work is labeled needs-review / has-checklist.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .agent_hierarchy import ensure_main_orchestrator
from .agent_roles import find_orchestrator
from .agent_scaffold import repair_agent, ORCHESTRATOR_MODEL
from .patterns import save_pattern

# Exactly 10 agents: 1 gatekeeper lead + 9 specialists
DEBUG_TEAM_SPEC: list[dict[str, Any]] = [
    {
        "name": "Debug Gatekeeper",
        "template_type": "debug_gatekeeper",
        "hierarchy_role": "lead",
        "model": "quality",
        "permission_level": "lead",
        "is_gatekeeper": True,
        "personality": (
            "Strict quality gatekeeper. You never mark work done until checklists pass. "
            "You assign debug specialists, require DONE WHEN + checklist on every task, "
            "and use review_task to approve or reject with what's wrong. "
            "Everything must be checked — no silent pass."
        ),
        "focus": ["review", "checklist", "gate", "qa"],
    },
    {
        "name": "Backend API Debugger",
        "template_type": "debug_backend",
        "hierarchy_role": "specialist",
        "model": "quality",
        "personality": "Backend API specialist. Trace routes, 500s, skill dispatch, auth, and DB.",
        "focus": ["api", "fastapi", "skills", "db"],
    },
    {
        "name": "Frontend UI Debugger",
        "template_type": "debug_frontend",
        "hierarchy_role": "specialist",
        "model": "quality",
        "personality": "Frontend specialist. SPA routes, settings, forms, and connection UX.",
        "focus": ["ui", "react", "settings", "forms"],
    },
    {
        "name": "Twilio Comms Debugger",
        "template_type": "debug_twilio",
        "hierarchy_role": "specialist",
        "model": "quality",
        "personality": (
            "Twilio specialist. Verify SID/token/from, SMS, voice, WhatsApp, and Settings → Apps connection. "
            "Highest priority integration."
        ),
        "focus": ["twilio", "sms", "voice", "comms"],
    },
    {
        "name": "Integrations Debugger",
        "template_type": "debug_integrations",
        "hierarchy_role": "specialist",
        "model": "quality",
        "personality": "Integrations specialist. OAuth, API keys, Shopify, Google, Slack connections.",
        "focus": ["oauth", "apps", "connections"],
    },
    {
        "name": "Billing Debugger",
        "template_type": "debug_billing",
        "hierarchy_role": "specialist",
        "model": "quality",
        "personality": "Billing specialist. Stripe subscriptions, checkout confirm, meters, plans.",
        "focus": ["stripe", "subscription", "tokens", "meter"],
    },
    {
        "name": "Autonomy Tasks Debugger",
        "template_type": "debug_autonomy",
        "hierarchy_role": "specialist",
        "model": "quality",
        "personality": "Autonomy specialist. Queues, cron tick-all, task chains, finalize/review gates.",
        "focus": ["autonomy", "tasks", "cron", "chains"],
    },
    {
        "name": "CRM Pipeline Debugger",
        "template_type": "debug_crm",
        "hierarchy_role": "specialist",
        "model": "quality",
        "personality": "CRM specialist. Customers, deals, pipelines, create_customer/create_deal skills.",
        "focus": ["crm", "deals", "pipeline"],
    },
    {
        "name": "Auth Security Debugger",
        "template_type": "debug_auth",
        "hierarchy_role": "specialist",
        "model": "reasoning",
        "personality": "Auth/security specialist. Sessions, API keys, ownership, plan gates.",
        "focus": ["auth", "keys", "permissions"],
    },
    {
        "name": "QA Smoke Debugger",
        "template_type": "debug_qa",
        "hierarchy_role": "specialist",
        "model": "fast",
        "personality": (
            "QA smoke specialist. Run end-to-end checklists, report failures to Gatekeeper, "
            "never self-approve."
        ),
        "focus": ["qa", "smoke", "e2e"],
    },
]

DEBUG_TEMPLATE_TYPES = frozenset(s["template_type"] for s in DEBUG_TEAM_SPEC)


def _find(db: Session, user_id: int, template_type: str) -> models.Agent | None:
    return (
        db.query(models.Agent)
        .filter_by(user_id=user_id, template_type=template_type)
        .order_by(models.Agent.id)
        .first()
    )


def _upsert(
    db: Session,
    user: models.User,
    spec: dict[str, Any],
    parent_id: int | None,
) -> models.Agent:
    cfg = {
        "debug_team": True,
        "gatekeeper": bool(spec.get("is_gatekeeper")),
        "focus": spec.get("focus") or [],
        "require_review": True,
        "mission": "Fix product bugs; all work gatekeeper-checked",
    }
    orch = find_orchestrator(db, user.id)
    if spec.get("is_gatekeeper"):
        resolved_parent = orch.id if orch else None
    else:
        resolved_parent = parent_id

    existing = _find(db, user.id, spec["template_type"])
    if existing:
        existing.name = spec["name"]
        existing.model = spec["model"]
        existing.hierarchy_role = spec["hierarchy_role"]
        existing.permission_level = spec.get("permission_level") or (
            "lead" if spec.get("is_gatekeeper") else "operator"
        )
        existing.idle_mode = "never_idle"
        existing.personality = spec["personality"]
        existing.config = json.dumps(cfg)
        existing.status = "active"
        existing.is_lead = bool(spec.get("is_gatekeeper"))
        if resolved_parent and resolved_parent != existing.id:
            existing.parent_id = resolved_parent
        existing.escalate_when = "on_failure"
        existing.escalate_to = "parent" if not spec.get("is_gatekeeper") else "orchestrator"
        db.flush()
        repair_agent(db, existing, force_never_idle=True, expand_skills=True)
        existing.model = spec["model"]
        return existing

    a = models.Agent(
        user_id=user.id,
        name=spec["name"],
        template_type=spec["template_type"],
        personality=spec["personality"],
        model=spec["model"],
        idle_mode="never_idle",
        config=json.dumps(cfg),
        is_lead=bool(spec.get("is_gatekeeper")),
        hierarchy_role=spec["hierarchy_role"],
        parent_id=resolved_parent,
        permission_level=spec.get("permission_level") or (
            "lead" if spec.get("is_gatekeeper") else "operator"
        ),
        status="active",
        escalate_when="on_failure",
        escalate_to="parent" if not spec.get("is_gatekeeper") else "orchestrator",
    )
    db.add(a)
    db.flush()
    repair_agent(db, a, force_never_idle=True, expand_skills=True)
    a.model = spec["model"]
    return a


def ensure_debug_team(db: Session, user: models.User) -> dict[str, Any]:
    """Create/update 10 debug agents with gatekeeper lead. Any active subscriber."""
    ensure_main_orchestrator(db, user)

    gate = None
    agents: list[models.Agent] = []
    for spec in DEBUG_TEAM_SPEC:
        if spec.get("is_gatekeeper"):
            gate = _upsert(db, user, spec, parent_id=None)
            agents.append(gate)
            break

    parent_id = gate.id if gate else None
    for spec in DEBUG_TEAM_SPEC:
        if spec.get("is_gatekeeper"):
            continue
        a = _upsert(db, user, spec, parent_id=parent_id)
        agents.append(a)

    # Re-parent specialists under gatekeeper
    if gate:
        for a in agents:
            if a.id != gate.id:
                a.parent_id = gate.id
                a.escalate_to = "parent"

    db.commit()
    for a in agents:
        db.refresh(a)

    # Pattern: every debug run is multi-step + gatekeeper review
    try:
        save_pattern(
            db,
            user,
            gate or agents[0],
            name="debug-full-check",
            description=(
                "Full product debug under Gatekeeper. Every specialist step has checklist; "
                "Gatekeeper reviews before chain continues."
            ),
            steps=[
                {
                    "title": "Twilio & channels check",
                    "role_hint": "debug_twilio",
                    "done_when": "Twilio ready for SMS/voice or clear blocker documented",
                    "checklist": [
                        "twilio_sid configured",
                        "twilio_token configured",
                        "twilio_from E.164",
                        "Settings Apps shows Twilio connected or keys saved",
                    ],
                },
                {
                    "title": "Integrations apps check",
                    "role_hint": "debug_integrations",
                    "done_when": "Catalog connect paths verified",
                    "checklist": ["list connected apps", "probe failures noted"],
                },
                {
                    "title": "Billing subscription check",
                    "role_hint": "debug_billing",
                    "done_when": "Plans/checkout/meter paths verified",
                    "checklist": ["payment-options ready", "meter returns tokens"],
                },
                {
                    "title": "Autonomy offline queue check",
                    "role_hint": "debug_autonomy",
                    "done_when": "Queued tasks drain without login path verified",
                    "checklist": ["autonomy settings on", "queued drain works"],
                },
                {
                    "title": "Gatekeeper final review",
                    "role_hint": "debug_gatekeeper",
                    "done_when": "All prior checklists reviewed; failed items re-queued",
                    "checklist": [
                        "review_task used for each specialist deliverable",
                        "no unchecked work marked complete",
                        "status_update to human",
                    ],
                },
            ],
            checklist=[
                "Twilio working or blocked with reason",
                "Apps connect UI works",
                "Subscription purchase path works",
                "Everything gatekeeper-checked",
            ],
            category="debug",
            tags="debug,gatekeeper",
        )
    except Exception:
        pass

    return {
        "ok": True,
        "count": len(agents),
        "gatekeeper_id": gate.id if gate else None,
        "gatekeeper_name": gate.name if gate else None,
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "template_type": a.template_type,
                "model": a.model,
                "hierarchy_role": a.hierarchy_role,
                "parent_id": a.parent_id,
                "status": a.status,
                "is_gatekeeper": bool(
                    json.loads(a.config or "{}").get("gatekeeper")
                    if a.config
                    else False
                ),
            }
            for a in agents
        ],
        "policy": {
            "rule": "Nothing is done until Debug Gatekeeper review_task approves",
            "pattern": "debug-full-check",
            "checklist_required": True,
        },
    }


def list_debug_team(db: Session, user_id: int) -> list[models.Agent]:
    return (
        db.query(models.Agent)
        .filter(
            models.Agent.user_id == user_id,
            models.Agent.template_type.in_(list(DEBUG_TEMPLATE_TYPES)),
        )
        .order_by(models.Agent.id)
        .all()
    )


async def run_debug_gate_check(
    db: Session,
    user: models.User,
    *,
    focus: str = "full",
) -> dict[str, Any]:
    """Start gatekeeper-led debug workflow (all steps require review)."""
    from .orchestration.workflow_run import start_workflow, run_pattern

    team = ensure_debug_team(db, user)
    gate_id = team.get("gatekeeper_id")
    gate = db.get(models.Agent, gate_id) if gate_id else None
    if not gate:
        return {"ok": False, "error": "gatekeeper missing"}

    # Prefer saved pattern for full check
    if (focus or "full") == "full":
        try:
            return await run_pattern(
                db, user, gate, "debug-full-check",
                title="Debug full check (gatekeeper)",
                priority="high",
            )
        except Exception:
            pass

    # Twilio-first focused run
    if focus == "twilio":
        return await start_workflow(
            db, user, gate,
            title="Twilio gatekeeper check",
            description="Verify Twilio connect + SMS/voice readiness. Gatekeeper must approve.",
            steps=[
                {
                    "title": "Connect and probe Twilio",
                    "role_hint": "debug_twilio",
                    "agent_id": next(
                        (a["id"] for a in team["agents"] if a["template_type"] == "debug_twilio"),
                        None,
                    ),
                    "done_when": "Twilio ready or blocker documented",
                    "checklist": [
                        "SID + token + from set",
                        "probe ok or clear error",
                        "channels status ready=true or documented",
                    ],
                },
                {
                    "title": "Gatekeeper review Twilio",
                    "role_hint": "debug_gatekeeper",
                    "agent_id": gate.id,
                    "done_when": "review_task approve/reject with evidence",
                    "checklist": ["reviewed specialist output", "human notified"],
                },
            ],
            checklist=["Twilio production-ready or blocked"],
            require_review=True,
            save_as_pattern=False,
        )

    return await run_pattern(
        db, user, gate, "debug-full-check",
        title="Debug full check (gatekeeper)",
        priority="high",
    )
