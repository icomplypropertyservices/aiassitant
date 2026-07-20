"""Thin CRM service layer shared by HTTP routers and agent skills.

Ownership checks via ownership.require_owned; tags via tags_util.
Serializers and pipeline bootstrap live here so business.py / skills can share
them without circular imports through routers.business.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from . import models
from .ownership import require_owned
from .tags_util import normalize_tags, tags_list


DEFAULT_STAGES = [
    ("New lead", "open", "#8c8c8c", 0, 10),
    ("Contacted", "open", "#1668dc", 1, 25),
    ("Qualified", "open", "#13c2c2", 2, 50),
    ("Proposal", "open", "#722ed1", 3, 70),
    ("Negotiation", "open", "#fa8c16", 4, 85),
    ("Won", "won", "#52c41a", 5, 100),
    ("Lost", "lost", "#ff4d4f", 6, 0),
]


# ── Ownership ─────────────────────────────────────────────────────────────

def get_owned_customer(db: Session, user: models.User, customer_id: int) -> models.Customer:
    return require_owned(
        db, models.Customer, customer_id, user,
        user_field="owner_user_id", not_found="Customer not found",
    )


def get_owned_pipeline(db: Session, user: models.User, pipeline_id: int) -> models.Pipeline:
    return require_owned(
        db, models.Pipeline, pipeline_id, user,
        user_field="owner_user_id", not_found="Pipeline not found",
    )


def get_owned_deal(db: Session, user: models.User, deal_id: int) -> models.Deal:
    return require_owned(
        db, models.Deal, deal_id, user,
        user_field="owner_user_id", not_found="Deal not found",
    )


def find_customer_by_email(
    db: Session, user: models.User, email: str,
) -> models.Customer | None:
    email = (email or "").strip()
    if not email:
        return None
    return (
        db.query(models.Customer)
        .filter_by(owner_user_id=user.id, email=email)
        .first()
    )


def resolve_customer(
    db: Session,
    user: models.User,
    customer_id: int | str | None = None,
    email: str | None = None,
) -> models.Customer | None:
    """Soft resolve by id (owned) or email — never raises (for skills)."""
    cust = None
    if customer_id is not None and str(customer_id).strip() != "":
        try:
            cust = get_owned_customer(db, user, int(customer_id))
        except Exception:
            cust = None
    if not cust and email:
        cust = find_customer_by_email(db, user, email)
    return cust


# ── Serializers ───────────────────────────────────────────────────────────

def customer_out(c: models.Customer, db: Session, *, light: bool = False) -> dict:
    human = db.get(models.Human, c.owner_human_id) if c.owner_human_id else None
    agent = db.get(models.Agent, c.owner_agent_id) if c.owner_agent_id else None
    co = db.get(models.Company, c.company_id) if c.company_id else None
    open_deals = (
        db.query(models.Deal)
        .filter_by(customer_id=c.id, status="open")
        .count()
    )
    total_value = (
        db.query(func.coalesce(func.sum(models.Deal.value), 0.0))
        .filter_by(customer_id=c.id)
        .scalar()
    )
    base = {
        "id": c.id,
        "name": c.name,
        "email": c.email or "",
        "phone": c.phone or "",
        "job_title": c.job_title or "",
        "account_name": c.account_name or "",
        "website": c.website or "",
        "industry": c.industry or "",
        "city": c.city or "",
        "country": c.country or "",
        "status": c.status or "active",
        "source": c.source or "",
        "tags": tags_list(c.tags),
        "tags_raw": c.tags or "",
        "lead_status": getattr(c, "lead_status", None) or "",
        "lead_score": float(getattr(c, "lead_score", None) or 0),
        "qualified_at": getattr(c, "qualified_at", None),
        "budget": float(getattr(c, "budget", None) or 0),
        "company_size": getattr(c, "company_size", None) or "",
        "linkedin_url": getattr(c, "linkedin_url", None) or "",
        "icp_notes": getattr(c, "icp_notes", None) or "",
        "disqualified_reason": getattr(c, "disqualified_reason", None) or "",
        "company_id": c.company_id,
        "company_name": co.name if co else None,
        "external_source": getattr(c, "external_source", None) or "",
        "external_id": getattr(c, "external_id", None) or "",
        "owner_human_id": c.owner_human_id,
        "owner_human_name": human.name if human else None,
        "owner_agent_id": c.owner_agent_id,
        "owner_agent_name": agent.name if agent else None,
        "annual_value": c.annual_value or 0.0,
        "open_deals": open_deals,
        "pipeline_value": float(total_value or 0),
        "last_contacted_at": c.last_contacted_at,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }
    if light:
        return base
    base.update({
        "address": c.address or "",
        "notes": c.notes or "",
    })
    return base


def deal_out(d: models.Deal, db: Session) -> dict:
    cust = db.get(models.Customer, d.customer_id)
    stage = db.get(models.PipelineStage, d.stage_id)
    human = db.get(models.Human, d.owner_human_id) if d.owner_human_id else None
    agent = db.get(models.Agent, d.owner_agent_id) if d.owner_agent_id else None
    return {
        "id": d.id,
        "title": d.title,
        "value": d.value or 0.0,
        "currency": d.currency or "USD",
        "status": d.status,
        "priority": d.priority or "medium",
        "pipeline_id": d.pipeline_id,
        "stage_id": d.stage_id,
        "stage_name": stage.name if stage else None,
        "stage_color": stage.color if stage else None,
        "customer_id": d.customer_id,
        "customer_name": cust.name if cust else None,
        "account_name": cust.account_name if cust else None,
        "company_id": d.company_id,
        "expected_close": d.expected_close,
        "owner_human_id": d.owner_human_id,
        "owner_human_name": human.name if human else None,
        "owner_agent_id": d.owner_agent_id,
        "owner_agent_name": agent.name if agent else None,
        "position": d.position or 0,
        "description": d.description or "",
        "lost_reason": d.lost_reason or "",
        "created_at": d.created_at,
        "updated_at": d.updated_at,
        "closed_at": d.closed_at,
    }


def activity_out(a: models.CustomerActivity) -> dict:
    return {
        "id": a.id,
        "customer_id": a.customer_id,
        "kind": a.kind,
        "title": a.title or "",
        "body": a.body or "",
        "deal_id": a.deal_id,
        "agent_id": a.agent_id,
        "human_id": a.human_id,
        "created_at": a.created_at,
    }


# ── Pipeline bootstrap ────────────────────────────────────────────────────

def list_pipeline_stages(db: Session, pipeline_id: int) -> list[models.PipelineStage]:
    return (
        db.query(models.PipelineStage)
        .filter_by(pipeline_id=pipeline_id)
        .order_by(models.PipelineStage.position, models.PipelineStage.id)
        .all()
    )


def _stage_name_key(name: str | None) -> str:
    return (name or "").strip().lower()


def ensure_pipeline_stages(
    db: Session,
    pipeline: models.Pipeline,
    *,
    commit: bool = True,
) -> tuple[list[models.PipelineStage], list[str]]:
    """Ensure sales board stages exist on *pipeline*.

    - Empty pipeline → seed full DEFAULT_STAGES (includes Qualified / Won / Lost).
    - Existing stages → add any missing DEFAULT_STAGES by name (case-insensitive),
      treating names containing "qualif" as covering "Qualified".
    Returns (stages ordered, names_added).
    """
    stages = list_pipeline_stages(db, pipeline.id)
    added: list[str] = []

    def _covers(default_name: str, existing_names: list[str]) -> bool:
        key = _stage_name_key(default_name)
        if key in existing_names:
            return True
        # Fuzzy: "Qualified" ↔ any stage with "qualif" in the name
        if "qualif" in key:
            return any("qualif" in n for n in existing_names)
        return False

    if not stages:
        for name, st, color, pos, prob in DEFAULT_STAGES:
            db.add(models.PipelineStage(
                pipeline_id=pipeline.id, name=name, stage_type=st,
                color=color, position=pos, probability=prob,
            ))
            added.append(name)
        if commit:
            db.commit()
        else:
            db.flush()
        stages = list_pipeline_stages(db, pipeline.id)
        return stages, added

    existing_keys = [_stage_name_key(s.name) for s in stages]
    max_pos = max((s.position or 0) for s in stages)
    for name, st, color, pos, prob in DEFAULT_STAGES:
        if _covers(name, existing_keys):
            continue
        # Prefer canonical position when free; otherwise append after max
        use_pos = pos if not any((s.position or 0) == pos for s in stages) else (max_pos + 1)
        max_pos = max(max_pos, use_pos)
        db.add(models.PipelineStage(
            pipeline_id=pipeline.id, name=name, stage_type=st,
            color=color, position=use_pos, probability=prob,
        ))
        existing_keys.append(_stage_name_key(name))
        added.append(name)

    if added:
        if commit:
            db.commit()
        else:
            db.flush()
        stages = list_pipeline_stages(db, pipeline.id)
    return stages, added


def ensure_default_pipeline(
    db: Session,
    user: models.User,
    *,
    commit: bool = True,
) -> models.Pipeline:
    """Return the workspace default sales pipeline, creating/repairing as needed.

    Always ensures DEFAULT_STAGES (including Qualified) are present.
    """
    p = (
        db.query(models.Pipeline)
        .filter_by(owner_user_id=user.id, is_default=True)
        .first()
    )
    created = False
    if not p:
        p = (
            db.query(models.Pipeline)
            .filter_by(owner_user_id=user.id)
            .order_by(models.Pipeline.id)
            .first()
        )
        if p:
            p.is_default = True
        else:
            p = models.Pipeline(
                owner_user_id=user.id,
                name="Sales pipeline",
                description="Default sales pipeline",
                kind="sales",
                is_default=True,
            )
            db.add(p)
            db.flush()
            created = True

    # Seed / repair stages (Qualified, Won, Lost, …)
    _stages, _added = ensure_pipeline_stages(db, p, commit=False)
    if commit:
        db.commit()
        db.refresh(p)
    elif created:
        db.flush()
    return p


def ensure_sales_pipeline(
    db: Session,
    user: models.User,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    """Bootstrap/repair default sales pipeline + stages. Used by skills & tests.

    Returns a structured result with pipeline id, stage list, and has_qualified_stage.
    """
    p = ensure_default_pipeline(db, user, commit=commit)
    stages = list_pipeline_stages(db, p.id)
    names = [s.name for s in stages]
    has_qualified = any("qualif" in (n or "").lower() for n in names)
    has_won = any((s.stage_type or "").lower() == "won" for s in stages)
    has_lost = any((s.stage_type or "").lower() == "lost" for s in stages)
    return {
        "ok": True,
        "pipeline": p,
        "pipeline_id": p.id,
        "pipeline_name": p.name,
        "stages": stages,
        "stage_names": names,
        "has_qualified_stage": has_qualified,
        "has_won_stage": has_won,
        "has_lost_stage": has_lost,
        "stage_count": len(stages),
    }


def parse_dt(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", ""))
    except Exception:
        return None


# ── Customer queries / mutations ──────────────────────────────────────────

def list_customers(
    db: Session,
    user: models.User,
    *,
    q: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    company_id: int | None = None,
    lead_status: str | None = None,
    has_lead_status: bool = False,
    min_lead_score: float | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[models.Customer], int]:
    """Return (rows, total) for owned customers with optional filters."""
    try:
        limit = max(1, min(500, int(limit or 25)))
    except Exception:
        limit = 25
    try:
        offset = max(0, int(offset or 0))
    except Exception:
        offset = 0

    query = db.query(models.Customer).filter_by(owner_user_id=user.id)
    if status:
        query = query.filter_by(status=status)
    if company_id is not None:
        query = query.filter_by(company_id=company_id)
    if lead_status:
        query = query.filter(models.Customer.lead_status == str(lead_status).strip().lower())
    elif has_lead_status:
        query = query.filter(
            models.Customer.lead_status.isnot(None),
            models.Customer.lead_status != "",
        )
    if min_lead_score is not None:
        try:
            query = query.filter(models.Customer.lead_score >= float(min_lead_score))
        except (TypeError, ValueError):
            pass
    if q:
        like = f"%{str(q).strip()}%"
        query = query.filter(or_(
            models.Customer.name.ilike(like),
            models.Customer.email.ilike(like),
            models.Customer.account_name.ilike(like),
            models.Customer.phone.ilike(like),
            models.Customer.tags.ilike(like),
        ))
    if tag:
        query = query.filter(models.Customer.tags.ilike(f"%{str(tag).strip()}%"))
    total = query.count()
    rows = (
        query.order_by(models.Customer.updated_at.desc(), models.Customer.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows, total


_CUSTOMER_STR_FIELDS = (
    "name", "email", "phone", "job_title", "account_name", "website",
    "industry", "address", "city", "country", "status", "source", "notes",
    "lead_status",
    "company_size", "linkedin_url", "icp_notes", "disqualified_reason",
)

# Canonical lead funnel statuses for sales AI skills
LEAD_STATUSES = frozenset({
    "new", "contacted", "nurturing", "qualified", "disqualified", "converted",
})


def normalize_lead_status(value: str | None) -> str | None:
    """Return canonical lead_status or None if empty/invalid."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    return s if s in LEAD_STATUSES else None


def score_lead_signals(
    args: dict[str, Any] | None = None,
    customer: models.Customer | None = None,
) -> tuple[float, list[str]]:
    """Heuristic 0–100 lead score from explicit score / notes / CRM signals.

    Shared by score_lead / qualify_lead skills (offline, no LLM).
    """
    args = dict(args or {})
    reasons: list[str] = []
    if args.get("score") is not None or args.get("lead_score") is not None:
        try:
            raw = float(
                args.get("score") if args.get("score") is not None else args.get("lead_score")
            )
            score = max(0.0, min(100.0, raw))
            reasons.append(f"explicit score={score:.0f}")
            return score, reasons
        except (TypeError, ValueError):
            pass

    score = 40.0  # baseline warm/unknown
    notes = " ".join(
        str(x or "") for x in (
            args.get("notes"),
            args.get("reason"),
            args.get("context"),
            getattr(customer, "notes", None) if customer else "",
            args.get("budget"),
            args.get("pain_point"),
            args.get("timeline"),
        )
    ).lower()
    account = (
        (args.get("company") or args.get("account_name") or "")
        + " "
        + (getattr(customer, "account_name", None) or "" if customer else "")
    ).strip()
    email = (
        args.get("email") or (getattr(customer, "email", None) or "" if customer else "")
    ).strip()
    annual = float(
        args.get("annual_value")
        or (getattr(customer, "annual_value", None) or 0 if customer else 0)
        or 0
    )

    if email and "@" in email:
        score += 10
        reasons.append("has email")
    if account:
        score += 8
        reasons.append("company/account known")
    if annual >= 50_000:
        score += 20
        reasons.append(f"annual_value={annual:.0f}")
    elif annual >= 10_000:
        score += 12
        reasons.append(f"annual_value={annual:.0f}")
    elif annual > 0:
        score += 5
        reasons.append(f"annual_value={annual:.0f}")

    positive = (
        "budget", "ready", "decision", "enterprise", "urgent", "demo", "proposal",
        "qualified", "hot", "inbound", "warm", "champion", "authority", "need",
        "timeline", "q1", "q2", "q3", "q4", "this quarter", "this month",
    )
    negative = (
        "no budget", "not interested", "unsubscribe", "spam", "student", "cold",
        "tire kicker", "disqualify", "competitor", "junk",
    )
    bad = [w for w in negative if w in notes]
    if bad:
        score -= min(30, 10 * len(bad))
        reasons.append("risk signals: " + ", ".join(bad[:4]))
    # Positive keywords only when not already covered by a risk phrase
    # (e.g. "budget" must not fire inside "no budget")
    hits = [
        w for w in positive
        if w in notes and not any(w in b for b in bad)
    ]
    if hits:
        score += min(25, 5 * len(hits))
        reasons.append("positive signals: " + ", ".join(hits[:5]))

    score = max(0.0, min(100.0, score))
    if not reasons:
        reasons.append("baseline score (limited signals)")
    return score, reasons


def status_from_lead_score(score: float, explicit: str | None = None) -> str:
    """Map numeric score (or explicit status) to a funnel lead_status."""
    if explicit:
        norm = normalize_lead_status(explicit)
        if norm:
            return norm
    if score >= 70:
        return "qualified"
    if score >= 45:
        return "nurturing"
    if score < 25:
        return "disqualified"
    return "contacted"


def letter_grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def set_lead_status(
    db: Session,
    user: models.User,
    customer: models.Customer,
    *,
    lead_status: str,
    lead_score: float | None = None,
    notes: str | None = None,
    disqualified_reason: str | None = None,
    agent_id: int | None = None,
    agent_name: str | None = None,
    activity_title: str | None = None,
    activity_body: str | None = None,
    log_activity: bool = True,
    commit: bool = True,
) -> models.Customer:
    """Set lead_status (+ optional score / disqualified_reason) on an owned customer."""
    status = normalize_lead_status(lead_status)
    if not status:
        raise HTTPException(
            400,
            f"invalid lead_status '{lead_status}'; allowed: {', '.join(sorted(LEAD_STATUSES))}",
        )

    fields: dict[str, Any] = {"lead_status": status}
    if lead_score is not None:
        fields["lead_score"] = lead_score
    if status == "qualified":
        fields["qualified_at"] = datetime.utcnow().isoformat()
    if status == "disqualified" and disqualified_reason is not None:
        fields["disqualified_reason"] = str(disqualified_reason)[:2000]
    notes_s = (notes or "").strip()
    if notes_s:
        who = (agent_name or "agent").strip() or "agent"
        prev = (customer.notes or "").strip()
        stamp = f"[{who}] {notes_s}"
        fields["notes"] = (prev + "\n" + stamp).strip()[-8000:] if prev else stamp

    customer = update_customer_fields(db, user, customer, fields, commit=False)

    # Belt-and-suspenders for qualified_at / disqualified_reason
    if status == "qualified" and not getattr(customer, "qualified_at", None):
        customer.qualified_at = datetime.utcnow()
    if status == "disqualified" and disqualified_reason is not None:
        customer.disqualified_reason = str(disqualified_reason)[:2000]

    if log_activity:
        title = activity_title or f"Lead status → {status}"
        body = activity_body if activity_body is not None else (
            notes_s or disqualified_reason or f"Set by {agent_name or 'agent'}"
        )
        log_customer_activity(
            db, user, customer,
            kind="lead",
            title=title,
            body=str(body or "")[:2000],
            agent_id=agent_id,
            commit=False,
            touch_contact=False,
        )

    customer.updated_at = datetime.utcnow()
    if commit:
        db.commit()
        db.refresh(customer)
    return customer


def qualify_lead(
    db: Session,
    user: models.User,
    customer: models.Customer,
    *,
    args: dict[str, Any] | None = None,
    force_qualified: bool = False,
    agent_id: int | None = None,
    agent_name: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Score + set lead fields. Returns structured result for skills/API."""
    args = dict(args or {})
    score, reasons = score_lead_signals(args, customer)

    explicit = (args.get("lead_status") or "").strip().lower() or None
    # Honor generic "status" only when it is a funnel value
    if not explicit and args.get("status") is not None:
        st = str(args.get("status") or "").strip().lower()
        explicit = st if st in LEAD_STATUSES else None

    if force_qualified:
        new_status = "qualified"
        if score < 70:
            score = max(score, 70.0)
            reasons.append("boosted to meet qualified threshold")
    else:
        new_status = status_from_lead_score(score, explicit)

    notes = (args.get("notes") or args.get("context") or "").strip()
    fields: dict[str, Any] = {
        "lead_score": score,
        "lead_status": new_status,
    }
    if new_status == "qualified":
        fields["qualified_at"] = datetime.utcnow().isoformat()
    if notes:
        prev = (customer.notes or "").strip()
        stamp = f"[qualify] {notes}"
        fields["notes"] = (prev + "\n" + stamp).strip()[-8000:] if prev else stamp

    customer = update_customer_fields(db, user, customer, fields, commit=False)
    if new_status == "qualified" and not getattr(customer, "qualified_at", None):
        customer.qualified_at = datetime.utcnow()

    body_lines = [
        f"Score: {score:.0f}/100 → {new_status}",
        *([f"• {r}" for r in reasons]),
    ]
    if notes:
        body_lines.append(f"Notes: {notes}")
    activity = log_customer_activity(
        db, user, customer,
        kind="lead",
        title=f"Lead qualified: {score:.0f} ({new_status})",
        body="\n".join(body_lines)[:4000],
        agent_id=agent_id,
        commit=False,
        touch_contact=False,
    )

    if commit:
        db.commit()
        db.refresh(customer)
        db.refresh(activity)

    grade = letter_grade(score)
    recommendation = {
        "qualified": "Book discovery / move to Qualified stage and create a deal.",
        "nurturing": "Add to nurture sequence; gather budget & timeline.",
        "contacted": "First touch complete — schedule follow-up.",
        "disqualified": "Park or archive; do not invest outbound cycles.",
        "new": "Run discovery and enrich contact data.",
        "converted": "Hand off to success / fulfillment.",
    }.get(new_status, "Review scorecard and next step.")

    return {
        "ok": True,
        "customer": customer,
        "customer_id": customer.id,
        "customer_name": customer.name,
        "lead_score": float(getattr(customer, "lead_score", None) or score),
        "lead_status": getattr(customer, "lead_status", None) or new_status,
        "qualified_at": getattr(customer, "qualified_at", None),
        "grade": grade,
        "score_reasons": reasons,
        "activity_id": activity.id if activity else None,
        "recommendation": recommendation,
    }


def disqualify_lead(
    db: Session,
    user: models.User,
    customer: models.Customer,
    *,
    reason: str | None = None,
    notes: str | None = None,
    lead_score: float | None = None,
    agent_id: int | None = None,
    agent_name: str | None = None,
    commit: bool = True,
) -> models.Customer:
    """Mark customer lead_status=disqualified and store reason."""
    why = (reason or notes or "").strip()
    return set_lead_status(
        db, user, customer,
        lead_status="disqualified",
        lead_score=lead_score,
        notes=notes or reason,
        disqualified_reason=why or None,
        agent_id=agent_id,
        agent_name=agent_name,
        activity_title="Lead disqualified",
        activity_body=why or f"Disqualified by {agent_name or 'agent'}",
        commit=commit,
    )


def list_leads(
    db: Session,
    user: models.User,
    *,
    q: str | None = None,
    lead_status: str | None = None,
    min_score: float | None = None,
    has_lead_status: bool = False,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[models.Customer], int]:
    """List CRM leads — thin alias of list_customers with lead filters."""
    return list_customers(
        db, user,
        q=q,
        lead_status=lead_status,
        has_lead_status=has_lead_status,
        min_lead_score=min_score,
        limit=limit,
        offset=offset,
    )


def create_customer(
    db: Session,
    user: models.User,
    *,
    name: str,
    email: str = "",
    phone: str = "",
    job_title: str = "",
    account_name: str = "",
    website: str = "",
    industry: str = "",
    address: str = "",
    city: str = "",
    country: str = "",
    status: str = "active",
    source: str = "",
    tags: str = "",
    notes: str = "",
    annual_value: float = 0.0,
    company_id: int | None = None,
    owner_human_id: int | None = None,
    owner_agent_id: int | None = None,
    agent_id: int | None = None,
    commit: bool = True,
) -> models.Customer:
    """Create a CRM customer for the workspace owner."""
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    c = models.Customer(
        owner_user_id=user.id,
        company_id=company_id,
        name=name,
        email=(email or "").strip(),
        phone=(phone or "").strip(),
        job_title=(job_title or "").strip(),
        account_name=(account_name or "").strip(),
        website=(website or "").strip(),
        industry=(industry or "").strip(),
        address=(address or "").strip(),
        city=(city or "").strip(),
        country=(country or "").strip(),
        status=(status or "active").strip() or "active",
        source=(source or "").strip() or ("agent" if agent_id else ""),
        tags=normalize_tags(tags) if tags else "",
        owner_human_id=owner_human_id,
        owner_agent_id=owner_agent_id or agent_id,
        annual_value=float(annual_value or 0),
        notes=(notes or "").strip(),
    )
    db.add(c)
    db.flush()
    db.add(models.CustomerActivity(
        customer_id=c.id,
        owner_user_id=user.id,
        kind="system",
        title="Customer created",
        body=f"{c.name} added to CRM",
        agent_id=agent_id,
    ))
    if commit:
        db.commit()
        db.refresh(c)
    return c


def delete_customer(
    db: Session,
    user: models.User,
    customer: models.Customer,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    """Delete customer and related deals/activities (owner-scoped)."""
    if customer.owner_user_id != user.id and getattr(user, "role", None) != "admin":
        raise HTTPException(404, "Customer not found")
    deal_ids = [d.id for d in db.query(models.Deal).filter_by(customer_id=customer.id).all()]
    db.query(models.CustomerActivity).filter_by(customer_id=customer.id).delete()
    # Null diary links if table exists
    try:
        if hasattr(models, "DiaryEntry"):
            for d in db.query(models.DiaryEntry).filter_by(customer_id=customer.id).all():
                d.customer_id = None
    except Exception:
        pass
    db.query(models.Deal).filter_by(customer_id=customer.id).delete()
    cid, cname = customer.id, customer.name
    db.delete(customer)
    if commit:
        db.commit()
    return {"ok": True, "deleted_customer_id": cid, "name": cname, "deleted_deals": len(deal_ids)}


def delete_deal(
    db: Session,
    user: models.User,
    deal: models.Deal,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    if deal.owner_user_id != user.id and getattr(user, "role", None) != "admin":
        raise HTTPException(404, "Deal not found")
    did, title = deal.id, deal.title
    db.delete(deal)
    if commit:
        db.commit()
    return {"ok": True, "deleted_deal_id": did, "title": title}


def update_deal_fields(
    db: Session,
    user: models.User,
    deal: models.Deal,
    fields: dict[str, Any] | None = None,
    *,
    commit: bool = True,
) -> models.Deal:
    if deal.owner_user_id != user.id and getattr(user, "role", None) != "admin":
        raise HTTPException(404, "Deal not found")
    fields = dict(fields or {})
    for f in ("title", "description", "priority", "currency", "status"):
        if f in fields and fields[f] is not None:
            val = fields[f]
            setattr(deal, f, val.strip() if isinstance(val, str) else val)
    if "value" in fields and fields["value"] is not None:
        deal.value = float(fields["value"])
    if "expected_close" in fields:
        deal.expected_close = parse_dt(fields.get("expected_close"))
    deal.updated_at = datetime.utcnow()
    if commit:
        db.commit()
        db.refresh(deal)
    return deal


def update_customer_fields(
    db: Session,
    user: models.User,
    customer: models.Customer,
    fields: dict[str, Any] | None = None,
    *,
    company_id: Any = ...,
    commit: bool = True,
) -> models.Customer:
    """Apply field updates on an already-owned customer. Normalizes tags."""
    if customer.owner_user_id != user.id and getattr(user, "role", None) != "admin":
        raise HTTPException(404, "Customer not found")
    fields = dict(fields or {})
    for f in _CUSTOMER_STR_FIELDS:
        if f in fields and fields[f] is not None:
            val = fields[f]
            setattr(customer, f, val.strip() if isinstance(val, str) else val)
    if "tags" in fields and fields["tags"] is not None:
        customer.tags = normalize_tags(fields["tags"])
    if "owner_human_id" in fields and fields["owner_human_id"] is not None:
        customer.owner_human_id = fields["owner_human_id"] or None
    if "owner_agent_id" in fields and fields["owner_agent_id"] is not None:
        customer.owner_agent_id = fields["owner_agent_id"] or None
    if "annual_value" in fields and fields["annual_value"] is not None:
        customer.annual_value = float(fields["annual_value"])
    if "budget" in fields and fields["budget"] is not None:
        try:
            customer.budget = float(fields["budget"])
        except (TypeError, ValueError):
            pass
    if "lead_score" in fields and fields["lead_score"] is not None:
        try:
            customer.lead_score = float(fields["lead_score"])
        except (TypeError, ValueError):
            pass
    if "lead_status" in fields and fields["lead_status"] is not None:
        ls = str(fields["lead_status"] or "").strip().lower()
        customer.lead_status = ls
        if ls == "qualified" and not getattr(customer, "qualified_at", None):
            customer.qualified_at = datetime.utcnow()
    if "qualified_at" in fields:
        customer.qualified_at = parse_dt(fields.get("qualified_at")) if fields.get("qualified_at") else None
    if company_id is not ...:
        customer.company_id = company_id
    customer.updated_at = datetime.utcnow()
    if commit:
        db.commit()
        db.refresh(customer)
    return customer


def log_customer_activity(
    db: Session,
    user: models.User,
    customer: models.Customer,
    *,
    kind: str = "note",
    title: str = "",
    body: str = "",
    deal_id: int | None = None,
    agent_id: int | None = None,
    human_id: int | None = None,
    commit: bool = True,
    touch_contact: bool = True,
) -> models.CustomerActivity:
    """Create a customer activity row; optionally refresh last_contacted_at."""
    if customer.owner_user_id != user.id and getattr(user, "role", None) != "admin":
        raise HTTPException(404, "Customer not found")
    kind = (kind or "note").strip()
    title = (title or "").strip() or kind.title()
    body = (body or "").strip()
    a = models.CustomerActivity(
        customer_id=customer.id,
        owner_user_id=user.id,
        kind=kind,
        title=title,
        body=body,
        deal_id=deal_id,
        agent_id=agent_id,
        human_id=human_id,
    )
    db.add(a)
    if touch_contact:
        customer.last_contacted_at = datetime.utcnow()
        customer.updated_at = datetime.utcnow()
    if commit:
        db.commit()
        db.refresh(a)
    return a


_UNSET = object()


def create_deal_for_customer(
    db: Session,
    user: models.User,
    customer: models.Customer,
    *,
    title: str | None = None,
    value: float = 0.0,
    currency: str = "USD",
    priority: str = "medium",
    description: str = "",
    expected_close: str | datetime | None = None,
    pipeline_id: int | None = None,
    stage_id: int | None = None,
    company_id: Any = _UNSET,
    owner_human_id: Any = _UNSET,
    owner_agent_id: Any = _UNSET,
    activity_title: str | None = None,
    activity_body: str | None = None,
    agent_id: int | None = None,
    commit: bool = True,
    strict: bool = True,
) -> models.Deal:
    """Create an open deal on an owned customer (default pipeline/stage if omitted).

    strict=True (HTTP): invalid pipeline/stage raises HTTPException.
    strict=False (skills): invalid stage falls back to first pipeline stage;
    missing pipeline uses default; unowned pipeline raises only when strict.
    """
    if customer.owner_user_id != user.id and getattr(user, "role", None) != "admin":
        raise HTTPException(404, "Customer not found")

    pipe = None
    if pipeline_id is not None:
        try:
            pipe = get_owned_pipeline(db, user, int(pipeline_id))
        except Exception:
            if strict:
                raise
            pipe = None
    if not pipe:
        pipe = ensure_default_pipeline(db, user)

    stage = None
    if stage_id is not None:
        try:
            stage = db.get(models.PipelineStage, int(stage_id))
        except Exception:
            stage = None
        if stage and stage.pipeline_id != pipe.id:
            stage = None
        if stage is None and strict:
            raise HTTPException(400, "Invalid stage for pipeline")
    if not stage:
        stage = (
            db.query(models.PipelineStage)
            .filter_by(pipeline_id=pipe.id)
            .order_by(models.PipelineStage.position)
            .first()
        )
    if not stage:
        raise HTTPException(400, "Pipeline has no stages")

    deal_title = (title or "").strip() or f"Deal · {customer.name}"
    expected = expected_close if isinstance(expected_close, datetime) else parse_dt(
        expected_close if isinstance(expected_close, str) else None
    )
    resolved_company = customer.company_id if company_id is _UNSET else company_id
    resolved_human = customer.owner_human_id if owner_human_id is _UNSET else owner_human_id
    resolved_agent = customer.owner_agent_id if owner_agent_id is _UNSET else owner_agent_id
    d = models.Deal(
        owner_user_id=user.id,
        pipeline_id=pipe.id,
        stage_id=stage.id,
        customer_id=customer.id,
        company_id=resolved_company,
        title=deal_title[:200],
        value=float(value or 0),
        currency=(currency or "USD").strip(),
        status="open",
        priority=priority or "medium",
        expected_close=expected,
        owner_human_id=resolved_human,
        owner_agent_id=resolved_agent,
        description=(description or "").strip(),
    )
    db.add(d)
    db.flush()
    act_title = activity_title or f"Deal created: {deal_title}"
    act_body = activity_body if activity_body is not None else (
        f"Stage: {stage.name} · Value: {d.value} {d.currency}"
    )
    db.add(models.CustomerActivity(
        customer_id=customer.id,
        owner_user_id=user.id,
        kind="deal",
        title=act_title,
        body=act_body,
        deal_id=d.id,
        agent_id=agent_id,
    ))
    customer.updated_at = datetime.utcnow()
    if commit:
        db.commit()
        db.refresh(d)
    return d


def resolve_pipeline_stage(
    db: Session,
    deal: models.Deal,
    *,
    stage_id: int | str | None = None,
    stage_name: str | None = None,
) -> models.PipelineStage | None:
    """Find a stage on the deal's pipeline by id or name (exact then substring)."""
    stage = None
    if stage_id is not None and str(stage_id).strip() != "":
        try:
            stage = db.get(models.PipelineStage, int(stage_id))
        except (TypeError, ValueError):
            stage = None
        if stage and stage.pipeline_id != deal.pipeline_id:
            stage = None
    if not stage and stage_name:
        name = str(stage_name).strip().lower()
        stages = (
            db.query(models.PipelineStage)
            .filter_by(pipeline_id=deal.pipeline_id)
            .all()
        )
        stage = next((s for s in stages if (s.name or "").strip().lower() == name), None)
        if not stage:
            stage = next((s for s in stages if name in (s.name or "").lower()), None)
    return stage


def move_deal(
    db: Session,
    user: models.User,
    deal: models.Deal,
    *,
    stage_id: int | str | None = None,
    stage_name: str | None = None,
    stage: models.PipelineStage | None = None,
    position: int | None = None,
    status: str | None = None,
    lost_reason: str | None = None,
    notes: str | None = None,
    agent_id: int | None = None,
    agent_name: str | None = None,
    activity_title: str | None = None,
    activity_body: str | None = None,
    commit: bool = True,
) -> tuple[models.Deal, models.PipelineStage]:
    """Move a deal to another stage; sync won/lost status from stage_type.

    Shared by HTTP router and agent skills. Raises HTTPException on ownership/stage errors.
    """
    if deal.owner_user_id != user.id and getattr(user, "role", None) != "admin":
        raise HTTPException(404, "Deal not found")
    if stage is None:
        stage = resolve_pipeline_stage(
            db, deal, stage_id=stage_id, stage_name=stage_name,
        )
    if not stage or stage.pipeline_id != deal.pipeline_id:
        raise HTTPException(400, "Stage not in this pipeline")

    old_stage = db.get(models.PipelineStage, deal.stage_id)
    prev_id = deal.stage_id
    deal.stage_id = stage.id
    if position is not None:
        try:
            deal.position = int(position)
        except (TypeError, ValueError):
            pass

    st_type = (stage.stage_type or "open").lower()
    if status:
        deal.status = str(status).strip().lower()
        if deal.status in ("won", "lost") and not deal.closed_at:
            deal.closed_at = datetime.utcnow()
        if deal.status == "open":
            deal.closed_at = None
    elif st_type == "won":
        deal.status = "won"
        deal.closed_at = datetime.utcnow()
    elif st_type == "lost":
        deal.status = "lost"
        deal.closed_at = datetime.utcnow()
        if lost_reason:
            deal.lost_reason = str(lost_reason)[:500]
    else:
        deal.status = "open"
        deal.closed_at = None

    if notes:
        who = agent_name or "agent"
        deal.description = (
            ((deal.description or "") + f"\n[{who}] {notes}").strip()[-8000:]
        )

    deal.updated_at = datetime.utcnow()
    title = activity_title or f"Moved to {stage.name}"
    if activity_body is not None:
        body = activity_body
    else:
        from_name = old_stage.name if old_stage else "?"
        body = f"From {from_name} → {stage.name}"
        if agent_name:
            body = f"Deal #{deal.id} stage {prev_id} → {stage.id} by {agent_name}"
    db.add(models.CustomerActivity(
        customer_id=deal.customer_id,
        owner_user_id=user.id,
        kind="stage",
        title=title,
        body=body,
        deal_id=deal.id,
        agent_id=agent_id,
    ))
    if commit:
        db.commit()
        db.refresh(deal)
    return deal, stage


# Alias used by skills / callers that prefer stage-oriented naming
move_deal_stage = move_deal


def _find_close_stage(
    db: Session,
    deal: models.Deal,
    stage_type: str,
) -> models.PipelineStage | None:
    """Prefer pipeline stage matching stage_type (won/lost)."""
    return (
        db.query(models.PipelineStage)
        .filter_by(pipeline_id=deal.pipeline_id, stage_type=stage_type)
        .order_by(models.PipelineStage.position.desc())
        .first()
    )


def win_deal(
    db: Session,
    user: models.User,
    deal: models.Deal,
    *,
    value: float | None = None,
    notes: str | None = None,
    agent_id: int | None = None,
    agent_name: str | None = None,
    commit: bool = True,
) -> models.Deal:
    """Mark deal won; move to won stage when present. Ownership-checked."""
    if deal.owner_user_id != user.id and getattr(user, "role", None) != "admin":
        raise HTTPException(404, "Deal not found")

    if value is not None:
        try:
            deal.value = float(value)
        except (TypeError, ValueError):
            pass
    if notes:
        who = agent_name or "agent"
        deal.description = (
            ((deal.description or "") + f"\n[Win] {notes}").strip()[-8000:]
        )

    won_stage = _find_close_stage(db, deal, "won")
    if won_stage:
        deal, _stage = move_deal(
            db, user, deal,
            stage=won_stage,
            status="won",
            notes=None,  # already stamped above
            agent_id=agent_id,
            agent_name=agent_name,
            activity_title=f"Deal won: {deal.title}",
            activity_body=f"Won by {agent_name or 'agent'}. Value={deal.value}",
            commit=False,
        )
        # move_deal may have written a "stage" activity; ensure status is won
        deal.status = "won"
        deal.closed_at = deal.closed_at or datetime.utcnow()
    else:
        deal.status = "won"
        deal.closed_at = datetime.utcnow()
        deal.updated_at = datetime.utcnow()
        db.add(models.CustomerActivity(
            customer_id=deal.customer_id,
            owner_user_id=user.id,
            kind="deal",
            title=f"Deal won: {deal.title}",
            body=f"Won by {agent_name or 'agent'}. Value={deal.value}",
            deal_id=deal.id,
            agent_id=agent_id,
        ))

    if commit:
        db.commit()
        db.refresh(deal)
    return deal


def lose_deal(
    db: Session,
    user: models.User,
    deal: models.Deal,
    *,
    lost_reason: str | None = None,
    notes: str | None = None,
    agent_id: int | None = None,
    agent_name: str | None = None,
    commit: bool = True,
) -> models.Deal:
    """Mark deal lost; move to lost stage when present. Ownership-checked."""
    if deal.owner_user_id != user.id and getattr(user, "role", None) != "admin":
        raise HTTPException(404, "Deal not found")

    reason = (lost_reason or notes or "").strip()
    if reason:
        deal.lost_reason = reason[:500]
        deal.description = (
            ((deal.description or "") + f"\n[Lost] {reason}").strip()[-8000:]
        )

    lost_stage = _find_close_stage(db, deal, "lost")
    if lost_stage:
        deal, _stage = move_deal(
            db, user, deal,
            stage=lost_stage,
            status="lost",
            lost_reason=reason or None,
            notes=None,
            agent_id=agent_id,
            agent_name=agent_name,
            activity_title=f"Deal lost: {deal.title}",
            activity_body=f"Lost by {agent_name or 'agent'}. Reason: {reason or '—'}",
            commit=False,
        )
        deal.status = "lost"
        deal.closed_at = deal.closed_at or datetime.utcnow()
    else:
        deal.status = "lost"
        deal.closed_at = datetime.utcnow()
        deal.updated_at = datetime.utcnow()
        db.add(models.CustomerActivity(
            customer_id=deal.customer_id,
            owner_user_id=user.id,
            kind="deal",
            title=f"Deal lost: {deal.title}",
            body=f"Lost by {agent_name or 'agent'}. Reason: {reason or '—'}",
            deal_id=deal.id,
            agent_id=agent_id,
        ))

    if commit:
        db.commit()
        db.refresh(deal)
    return deal

# ── Diary / appointments ──────────────────────────────────────────────────

def diary_out(d: models.DiaryEntry, db: Session) -> dict:
    cust = db.get(models.Customer, d.customer_id)
    human = db.get(models.Human, d.owner_human_id) if d.owner_human_id else None
    agent = db.get(models.Agent, d.owner_agent_id) if d.owner_agent_id else None
    deal = db.get(models.Deal, d.deal_id) if d.deal_id else None
    return {
        "id": d.id,
        "customer_id": d.customer_id,
        "customer_name": cust.name if cust else None,
        "deal_id": d.deal_id,
        "deal_title": deal.title if deal else None,
        "title": d.title,
        "start_at": d.start_at,
        "end_at": d.end_at,
        "location": d.location or "",
        "notes": d.notes or "",
        "status": d.status or "scheduled",
        "owner_human_id": d.owner_human_id,
        "owner_human_name": human.name if human else None,
        "owner_agent_id": d.owner_agent_id,
        "owner_agent_name": agent.name if agent else None,
        "created_at": d.created_at,
        "updated_at": d.updated_at,
        "completed_at": d.completed_at,
    }


def get_owned_diary(db: Session, user: models.User, diary_id: int) -> models.DiaryEntry:
    return require_owned(
        db, models.DiaryEntry, diary_id, user,
        user_field="owner_user_id", not_found="Diary entry not found",
    )


def schedule_meeting(
    db: Session,
    user: models.User,
    customer: models.Customer,
    *,
    title: str | None = None,
    start_at: str | datetime | None = None,
    end_at: str | datetime | None = None,
    location: str = "",
    notes: str = "",
    deal_id: int | None = None,
    owner_human_id: int | None = None,
    owner_agent_id: int | None = None,
    agent_id: int | None = None,
    commit: bool = True,
) -> models.DiaryEntry:
    """Create a diary entry for an owned customer and log a meeting activity."""
    if customer.owner_user_id != user.id and getattr(user, "role", None) != "admin":
        raise HTTPException(404, "Customer not found")
    meeting_title = (title or "").strip() or f"Meeting with {customer.name}"
    start = start_at if isinstance(start_at, datetime) else parse_dt(
        start_at if isinstance(start_at, str) else None
    )
    end = end_at if isinstance(end_at, datetime) else parse_dt(
        end_at if isinstance(end_at, str) else None
    )
    # Soft-validate deal ownership if provided
    if deal_id is not None:
        try:
            deal = get_owned_deal(db, user, int(deal_id))
            if deal.customer_id != customer.id:
                deal_id = None
            else:
                deal_id = deal.id
        except Exception:
            deal_id = None

    d = models.DiaryEntry(
        owner_user_id=user.id,
        customer_id=customer.id,
        deal_id=deal_id,
        title=meeting_title[:200],
        start_at=start,
        end_at=end,
        location=(location or "").strip(),
        notes=(notes or "").strip(),
        status="scheduled",
        owner_human_id=owner_human_id,
        owner_agent_id=owner_agent_id or agent_id,
    )
    db.add(d)
    db.flush()
    log_customer_activity(
        db, user, customer,
        kind="meeting",
        title=f"Scheduled: {d.title}",
        body=f"{start.isoformat() if start else 'TBD'} @ {d.location or '—'}",
        deal_id=d.deal_id,
        agent_id=agent_id,
        commit=False,
        touch_contact=True,
    )
    if commit:
        db.commit()
        db.refresh(d)
    return d


def list_diary(
    db: Session,
    user: models.User,
    *,
    customer_id: int | None = None,
    email: str | None = None,
    status: str | None = None,
    upcoming: bool = False,
    limit: int = 50,
) -> list[models.DiaryEntry]:
    """List diary entries owned by the workspace user."""
    try:
        limit = max(1, min(200, int(limit or 50)))
    except (TypeError, ValueError):
        limit = 50
    q = db.query(models.DiaryEntry).filter_by(owner_user_id=user.id)
    if customer_id is not None:
        try:
            q = q.filter_by(customer_id=int(customer_id))
        except (TypeError, ValueError):
            pass
    elif email:
        cust = find_customer_by_email(db, user, email)
        if cust:
            q = q.filter_by(customer_id=cust.id)
        else:
            return []
    if status:
        q = q.filter_by(status=str(status).strip())
    if upcoming:
        now = datetime.utcnow()
        q = q.filter(
            models.DiaryEntry.status == "scheduled",
            (models.DiaryEntry.start_at >= now) | (models.DiaryEntry.start_at.is_(None)),
        )
    return (
        q.order_by(models.DiaryEntry.start_at.asc().nullslast(), models.DiaryEntry.id.desc())
        .limit(limit)
        .all()
    )


def list_customer_activities(
    db: Session,
    user: models.User,
    customer: models.Customer,
    *,
    kind: str | None = None,
    limit: int = 25,
) -> list[models.CustomerActivity]:
    if customer.owner_user_id != user.id and getattr(user, "role", None) != "admin":
        raise HTTPException(404, "Customer not found")
    try:
        limit = max(1, min(100, int(limit or 25)))
    except (TypeError, ValueError):
        limit = 25
    q = (
        db.query(models.CustomerActivity)
        .filter_by(customer_id=customer.id, owner_user_id=user.id)
    )
    if kind:
        q = q.filter_by(kind=str(kind).strip())
    return q.order_by(models.CustomerActivity.id.desc()).limit(limit).all()


# ── Product catalogue (sales offers; owner-scoped) ────────────────────────

def product_out(p: models.Product, *, full: bool = False) -> dict:
    out = {
        "id": p.id,
        "name": p.name,
        "sku": p.sku or "",
        "kind": p.kind or "product",
        "price": float(p.price or 0),
        "currency": p.currency or "USD",
        "status": p.status or "active",
        "offer": p.offer or "",
        "tags": p.tags or "",
        "company_id": p.company_id,
        "description": (p.description or "") if full else (p.description or "")[:240],
        "benefits": (p.benefits or "") if full else (p.benefits or "")[:200],
        "audience": (p.audience or "") if full else (p.audience or "")[:120],
        "image_url": p.image_url or "",
        "external_source": getattr(p, "external_source", None) or "",
        "external_id": getattr(p, "external_id", None) or "",
    }
    if full:
        out["created_at"] = p.created_at.isoformat() if p.created_at else None
        out["updated_at"] = p.updated_at.isoformat() if p.updated_at else None
    return out


def get_owned_product(db: Session, user: models.User, product_id: int) -> models.Product:
    return require_owned(
        db, models.Product, product_id, user,
        user_field="owner_user_id", not_found="Product not found",
    )


def default_company_id(
    db: Session,
    user: models.User,
    company_id: Any = None,
) -> int | None:
    """Resolve a workspace company id; validates ownership when explicit."""
    try:
        if company_id not in (None, ""):
            cid = int(company_id)
            co = db.get(models.Company, cid)
            if co and co.owner_user_id == user.id:
                return co.id
            return None
    except (TypeError, ValueError):
        pass
    co = (
        db.query(models.Company)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Company.id.asc())
        .first()
    )
    return co.id if co else None


def list_products(
    db: Session,
    user: models.User,
    *,
    q: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    kind: str | None = None,
    offer_only: bool = False,
    company_id: int | None = None,
    limit: int = 30,
) -> list[models.Product]:
    """List products owned by the workspace (never cross-tenant)."""
    try:
        limit = max(1, min(100, int(limit or 30)))
    except (TypeError, ValueError):
        limit = 30
    query = db.query(models.Product).filter_by(owner_user_id=user.id)
    if status:
        query = query.filter_by(status=str(status).strip())
    if kind:
        query = query.filter_by(kind=str(kind).strip())
    if company_id is not None:
        try:
            query = query.filter_by(company_id=int(company_id))
        except (TypeError, ValueError):
            pass
    if q:
        like = f"%{str(q).strip()}%"
        query = query.filter(or_(
            models.Product.name.ilike(like),
            models.Product.sku.ilike(like),
            models.Product.description.ilike(like),
            models.Product.offer.ilike(like),
            models.Product.tags.ilike(like),
        ))
    if tag:
        query = query.filter(models.Product.tags.ilike(f"%{str(tag).strip()}%"))
    if offer_only:
        query = query.filter(models.Product.offer.isnot(None), models.Product.offer != "")
    return query.order_by(models.Product.id.desc()).limit(limit).all()


def create_product(
    db: Session,
    user: models.User,
    *,
    name: str,
    company_id: int | None = None,
    sku: str = "",
    description: str = "",
    kind: str = "product",
    price: float = 0.0,
    currency: str = "USD",
    status: str = "active",
    tags: str = "",
    benefits: str = "",
    audience: str = "",
    offer: str = "",
    image_url: str = "",
    commit: bool = True,
) -> models.Product:
    """Create a product owned by the workspace user."""
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    cid = default_company_id(db, user, company_id)
    if not cid:
        raise HTTPException(400, "No company in workspace — create a company first (Workspace)")
    p = models.Product(
        owner_user_id=user.id,
        company_id=cid,
        name=name[:200],
        sku=(sku or "").strip()[:80],
        description=(description or "").strip()[:8000],
        kind=(kind or "product").strip() or "product",
        price=float(price or 0),
        currency=(currency or "USD").strip() or "USD",
        status=(status or "active").strip() or "active",
        tags=normalize_tags(tags) if tags else "",
        benefits=(benefits or "").strip()[:4000],
        audience=(audience or "").strip()[:500],
        offer=(offer or "").strip()[:1000],
        image_url=(image_url or "").strip()[:500],
    )
    db.add(p)
    if commit:
        db.commit()
        db.refresh(p)
    else:
        db.flush()
    return p


def update_product_fields(
    db: Session,
    user: models.User,
    product: models.Product,
    fields: dict[str, Any] | None = None,
    *,
    commit: bool = True,
) -> models.Product:
    if product.owner_user_id != user.id and getattr(user, "role", None) != "admin":
        raise HTTPException(404, "Product not found")
    fields = dict(fields or {})
    str_fields = (
        "name", "sku", "description", "kind", "currency", "status",
        "benefits", "audience", "offer", "image_url",
    )
    for f in str_fields:
        if f in fields and fields[f] is not None:
            val = fields[f]
            setattr(product, f, val.strip() if isinstance(val, str) else val)
    if "price" in fields and fields["price"] is not None:
        product.price = float(fields["price"])
    if "tags" in fields and fields["tags"] is not None:
        product.tags = normalize_tags(fields["tags"])
    if "company_id" in fields and fields["company_id"] is not None:
        cid = default_company_id(db, user, fields["company_id"])
        if cid:
            product.company_id = cid
    product.updated_at = datetime.utcnow()
    if commit:
        db.commit()
        db.refresh(product)
    return product
