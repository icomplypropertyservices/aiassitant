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

def ensure_default_pipeline(db: Session, user: models.User) -> models.Pipeline:
    p = (
        db.query(models.Pipeline)
        .filter_by(owner_user_id=user.id, is_default=True)
        .first()
    )
    if p:
        return p
    p = (
        db.query(models.Pipeline)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Pipeline.id)
        .first()
    )
    if p:
        p.is_default = True
        db.commit()
        return p
    p = models.Pipeline(
        owner_user_id=user.id,
        name="Sales pipeline",
        description="Default sales pipeline",
        kind="sales",
        is_default=True,
    )
    db.add(p)
    db.flush()
    for name, st, color, pos, prob in DEFAULT_STAGES:
        db.add(models.PipelineStage(
            pipeline_id=p.id, name=name, stage_type=st,
            color=color, position=pos, probability=prob,
        ))
    db.commit()
    db.refresh(p)
    return p


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
)


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
