"""
Orchestrator guidance: ensure Main Orchestrator + companies + wallets + starter work.

Companies are PRIVATE to the logged-in user. Defaults are generic placeholders
built from the account's own company name — never seed another customer's brands.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .agent_hierarchy import ensure_main_orchestrator
from .agent_wallets import get_or_create_wallet
from .plans import plan_limits
from .usage_billing import ensure_period, heal_subscription_flags


def default_companies_for_user(user: models.User) -> list[dict[str, Any]]:
    """Private starter companies for this account only (no shared brand names)."""
    base = (getattr(user, "name", None) or "My").strip().split()[0] or "My"
    primary = None
    # Prefer first owned company name if already created at register
    # (caller may pass companies= explicitly)
    primary_name = f"{base} company"
    return [
        {
            "slug": "primary",
            "name": primary_name,
            "industry": "General",
            "notes": "Your primary private workspace company.",
            "projects": [
                {
                    "name": "Operations",
                    "description": "Day-to-day ops and follow-ups",
                    "tasks": [
                        "Triage open enquiries",
                        "List top priorities this week",
                        "Draft follow-up messages",
                    ],
                },
                {
                    "name": "Growth",
                    "description": "Sales and pipeline",
                    "tasks": ["Build ICP notes", "Draft outreach sequence"],
                },
            ],
            "lead_name": "Ops Lead",
            "lead_type": "ops",
        },
        {
            "slug": "clients",
            "name": f"{base} clients",
            "industry": "Client work",
            "notes": "Separate client delivery from internal ops (private to your account).",
            "projects": [
                {
                    "name": "Delivery",
                    "description": "Active client work",
                    "tasks": ["List open client tasks", "Draft status update for owner"],
                },
            ],
            "lead_name": "Client Services Lead",
            "lead_type": "sales",
        },
        {
            "slug": "products",
            "name": f"{base} products",
            "industry": "Products / catalogue",
            "notes": "Optional products or catalogue stream.",
            "projects": [
                {
                    "name": "Catalogue",
                    "description": "Offers and product notes",
                    "tasks": ["List top offers", "Draft product blurb"],
                },
            ],
            "lead_name": "Products Lead",
            "lead_type": "sales",
        },
    ]


# Back-compat name for imports that expect DEFAULT_COMPANIES (generic only)
DEFAULT_COMPANIES: list[dict[str, Any]] = default_companies_for_user(
    type("U", (), {"name": "My"})()  # type: ignore[misc]
)


def _company_by_name(db: Session, user_id: int, name: str) -> models.Company | None:
    return (
        db.query(models.Company)
        .filter(
            models.Company.owner_user_id == user_id,
            models.Company.name == name,
        )
        .first()
    )


def _ensure_lead(
    db: Session,
    user: models.User,
    orch: models.Agent,
    company: models.Company,
    name: str,
    template_type: str,
) -> models.Agent:
    existing = (
        db.query(models.Agent)
        .filter_by(user_id=user.id, name=name, company_id=company.id)
        .first()
    )
    if existing:
        if not existing.parent_id:
            existing.parent_id = orch.id
        existing.hierarchy_role = existing.hierarchy_role or "lead"
        existing.is_lead = True
        db.flush()
        return existing
    a = models.Agent(
        user_id=user.id,
        company_id=company.id,
        parent_id=orch.id,
        name=name,
        template_type=template_type,
        hierarchy_role="lead",
        is_lead=True,
        personality=f"Lead for {company.name}. Coordinate specialists and report to the Main Orchestrator.",
        model="quality",
        idle_mode="never_idle",
        permission_level="lead",
        status="active",
        config=json.dumps({"company_slug": company.name, "role": "company_lead"}),
    )
    db.add(a)
    db.flush()
    return a


def bootstrap_workspace(
    db: Session,
    user: models.User,
    *,
    companies: list[dict] | None = None,
    create_wallets: bool = True,
    create_leads: bool = False,
    create_seed_tasks: bool = False,
) -> dict[str, Any]:
    """
    Orchestrator-driven setup (private to this user only):
    1. Heal plan tokens
    2. Ensure Main AI Orchestrator
    3. Optionally ensure companies + projects
    4. Optional company leads (default OFF — new accounts stay orchestrator-only)
    5. Optional starter tasks (default OFF)
    6. Crypto wallets for orchestrator (+ leads if created)

    Never copies another account's brands, agents, or CRM rows.
    """
    # Always private to this user — never inject another tenant's brand names
    if companies is None:
        companies = default_companies_for_user(user)
        # Prefer real company name from register / first company
        existing0 = (
            db.query(models.Company)
            .filter_by(owner_user_id=user.id)
            .order_by(models.Company.id)
            .first()
        )
        if existing0 and existing0.name and companies:
            companies = list(companies)
            companies[0] = {**companies[0], "name": existing0.name}

    report: dict[str, Any] = {
        "user_id": user.id,
        "email": user.email,
        "companies": [],
        "agents_created": [],
        "wallets": [],
        "tasks_created": 0,
        "projects_created": 0,
    }

    # Plan / meter heal
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal:
        bal = models.Balance(user_id=user.id, credits=0.0)
        db.add(bal)
        db.flush()
    limits = plan_limits(user.plan or "none")
    expected = int(limits.get("tokens_included") or 0)
    if user.subscription_active and expected > 0 and int(bal.tokens_included or 0) <= 0:
        bal.tokens_included = expected
    ensure_period(bal, user)
    heal_subscription_flags(db, user)
    db.commit()

    orch = ensure_main_orchestrator(db, user)
    report["orchestrator_id"] = orch.id
    report["agents_created"].append({"id": orch.id, "name": orch.name, "role": "orchestrator"})

    max_companies = int(limits.get("companies") or 15)
    if user.role == "admin":
        max_companies = max(max_companies, 50)

    specs = companies or DEFAULT_COMPANIES
    existing_count = db.query(models.Company).filter_by(owner_user_id=user.id).count()

    for spec in specs:
        co = _company_by_name(db, user.id, spec["name"])
        created = False
        if not co:
            if existing_count >= max_companies and user.role != "admin":
                report["companies"].append(
                    {"name": spec["name"], "skipped": True, "reason": "plan_company_limit"}
                )
                continue
            co = models.Company(
                owner_user_id=user.id,
                name=spec["name"],
                industry=spec.get("industry") or "",
                notes=spec.get("notes") or "",
            )
            db.add(co)
            db.flush()
            existing_count += 1
            created = True
        else:
            # Enrich empty notes
            if not (co.notes or "").strip() and spec.get("notes"):
                co.notes = spec["notes"]
            if not (co.industry or "").strip() and spec.get("industry"):
                co.industry = spec["industry"]

        co_report = {
            "id": co.id,
            "name": co.name,
            "created": created,
            "projects": [],
            "lead_id": None,
        }

        for pspec in spec.get("projects") or []:
            pname = pspec["name"]
            proj = (
                db.query(models.Project)
                .filter_by(company_id=co.id, name=pname, owner_user_id=user.id)
                .first()
            )
            if not proj:
                proj = models.Project(
                    company_id=co.id,
                    owner_user_id=user.id,
                    name=pname,
                    description=pspec.get("description") or "",
                    status="active",
                )
                db.add(proj)
                db.flush()
                report["projects_created"] += 1
                # Seed tasks are opt-in — fresh accounts start empty except orchestrator
                if create_seed_tasks:
                    from .task_status import initial_task_status

                    seed_status = initial_task_status(
                        agent=orch, assignee_type="agent", run_now=True
                    )
                    for title in pspec.get("tasks") or []:
                        t = models.Task(
                            user_id=user.id,
                            company_id=co.id,
                            project_id=proj.id,
                            title=title,
                            description=title,
                            status=seed_status,
                            assignee_type="agent",
                            agent_id=orch.id,
                            priority="medium",
                        )
                        db.add(t)
                        report["tasks_created"] += 1
            co_report["projects"].append({"id": proj.id, "name": proj.name})

        lead = None
        if create_leads:
            lead = _ensure_lead(
                db,
                user,
                orch,
                co,
                spec.get("lead_name") or f"{co.name} Lead",
                spec.get("lead_type") or "ops",
            )
            co_report["lead_id"] = lead.id
            report["agents_created"].append(
                {"id": lead.id, "name": lead.name, "role": "lead", "company_id": co.id}
            )

        if create_wallets:
            for agent in ([orch, lead] if lead else [orch]):
                if not agent:
                    continue
                # Only one wallet per agent — orch wallet once
                w = get_or_create_wallet(db, user, agent, generate_keys=True)
                if agent.company_id != co.id and agent.id == orch.id:
                    pass  # orch wallet shared
                report["wallets"].append(
                    {
                        "wallet_id": w.id,
                        "public_id": w.public_id,
                        "agent_id": agent.id,
                        "agent_name": agent.name,
                        "eth": w.eth_address,
                    }
                )

        # Attach orch to first company if unset
        if not orch.company_id:
            orch.company_id = co.id

        report["companies"].append(co_report)

    # Mission on orchestrator
    try:
        cfg = json.loads(orch.config or "{}")
    except Exception:
        cfg = {}
    cfg["mission"] = (
        "Coordinate this account's private companies, projects, and agents. "
        "Route sales, ops, products, git repos, and local machine agents. "
        "Keep wallets funded and skills enabled. Never expose data outside this workspace."
    )
    cfg["companies_guidance"] = [c.get("name") for c in (companies or DEFAULT_COMPANIES)]
    cfg["bootstrap_at"] = datetime.utcnow().isoformat() + "Z"
    cfg["private"] = True
    orch.config = json.dumps(cfg)
    db.commit()

    report["ok"] = True
    report["message"] = (
        f"Orchestrator ready with {len(report['companies'])} companies, "
        f"{report['projects_created']} new projects, {report['tasks_created']} tasks."
    )
    return report
