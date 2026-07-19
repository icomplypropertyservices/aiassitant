"""Business CRM: pipelines, customers, deals, activities."""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import get_current_user
from ..live_ops import emit_ops
from ..tags_util import normalize_tags, tags_list
from ..company_scope import resolve_company_id, user_default_company_id
from ..ownership import require_owned
from .. import crm_service
from ..crm_service import (
    DEFAULT_STAGES,
    ensure_default_pipeline as _ensure_default_pipeline,
    customer_out as _customer_out,
    deal_out as _deal_out,
    activity_out as _activity_out,
    list_customers as crm_list_customers,
    update_customer_fields as crm_update_customer_fields,
    log_customer_activity as crm_log_customer_activity,
    create_deal_for_customer as crm_create_deal_for_customer,
    parse_dt as _parse_dt,
)


def _owned_customer(db: Session, customer_id: int, user) -> models.Customer:
    return crm_service.get_owned_customer(db, user, customer_id)


def _owned_pipeline(db: Session, pipeline_id: int, user) -> models.Pipeline:
    return crm_service.get_owned_pipeline(db, user, pipeline_id)

router = APIRouter(prefix="/business", tags=["business"])


# ── Schemas ──────────────────────────────────────────────────────────────

class PipelineIn(BaseModel):
    name: str
    description: str = ""
    kind: str = "sales"
    company_id: int | None = None
    is_default: bool = False


class StageIn(BaseModel):
    name: str
    stage_type: str = "open"
    color: str = "#1668dc"
    position: int | None = None
    probability: int = 0


class CustomerIn(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    job_title: str = ""
    account_name: str = ""
    website: str = ""
    industry: str = ""
    address: str = ""
    city: str = ""
    country: str = ""
    status: str = "active"
    source: str = ""
    # comma string or list of tags from Select mode="tags"
    tags: str | list[str] = ""
    company_id: int | None = None
    owner_human_id: int | None = None
    owner_agent_id: int | None = None
    annual_value: float = 0.0
    notes: str = ""


class CustomerUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    job_title: str | None = None
    account_name: str | None = None
    website: str | None = None
    industry: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    status: str | None = None
    source: str | None = None
    tags: str | list[str] | None = None
    company_id: int | None = None
    owner_human_id: int | None = None
    owner_agent_id: int | None = None
    annual_value: float | None = None
    notes: str | None = None




class DealIn(BaseModel):
    title: str
    customer_id: int
    pipeline_id: int | None = None
    stage_id: int | None = None
    value: float = 0.0
    currency: str = "USD"
    priority: str = "medium"
    expected_close: str | None = None  # ISO date
    owner_human_id: int | None = None
    owner_agent_id: int | None = None
    description: str = ""
    company_id: int | None = None


class DealMoveIn(BaseModel):
    stage_id: int
    position: int | None = None
    status: str | None = None  # open | won | lost
    lost_reason: str = ""


class ActivityIn(BaseModel):
    kind: str = "note"
    title: str = ""
    body: str = ""
    deal_id: int | None = None


# ── Helpers ──────────────────────────────────────────────────────────────

CUSTOMER_TAG_PRESETS = [
    "vip", "enterprise", "smb", "startup", "lead", "partner",
    "churn-risk", "renewing", "trial", "warm", "cold", "referral",
]
PRODUCT_TAG_PRESETS = [
    "core", "addon", "featured", "service", "digital", "physical",
    "subscription", "bundle", "new", "sale", "b2b", "b2c",
]


def _normalize_tags(tags):
    return normalize_tags(tags)


def _tags_list(raw):
    return tags_list(raw)


def _resolve_company_id(db, user, company_id, *, required=False):
    return resolve_company_id(db, user, company_id, required=required, resource="customers")


def _stage_out(s: models.PipelineStage) -> dict:
    return {
        "id": s.id,
        "pipeline_id": s.pipeline_id,
        "name": s.name,
        "stage_type": s.stage_type,
        "color": s.color or "#1668dc",
        "position": s.position or 0,
        "probability": s.probability or 0,
    }


def _pipeline_out(p: models.Pipeline, db: Session, *, with_deals: bool = False) -> dict:
    stages = (
        db.query(models.PipelineStage)
        .filter_by(pipeline_id=p.id)
        .order_by(models.PipelineStage.position, models.PipelineStage.id)
        .all()
    )
    deal_count = db.query(models.Deal).filter_by(pipeline_id=p.id).count()
    open_value = (
        db.query(func.coalesce(func.sum(models.Deal.value), 0.0))
        .filter_by(pipeline_id=p.id, status="open")
        .scalar()
    )
    out = {
        "id": p.id,
        "name": p.name,
        "description": p.description or "",
        "kind": p.kind,
        "company_id": p.company_id,
        "is_default": bool(p.is_default),
        "stages": [_stage_out(s) for s in stages],
        "deal_count": deal_count,
        "open_value": float(open_value or 0),
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }
    if with_deals:
        deals = (
            db.query(models.Deal)
            .filter_by(pipeline_id=p.id)
            .order_by(models.Deal.position, models.Deal.id.desc())
            .all()
        )
        out["deals"] = [_deal_out(d, db) for d in deals]
        # group by stage
        by_stage = {s.id: [] for s in stages}
        for d in out["deals"]:
            by_stage.setdefault(d["stage_id"], []).append(d)
        out["board"] = [
            {**_stage_out(s), "deals": by_stage.get(s.id, []), "count": len(by_stage.get(s.id, [])),
             "value": sum(x.get("value") or 0 for x in by_stage.get(s.id, []))}
            for s in stages
        ]
    return out

# ── Overview ─────────────────────────────────────────────────────────────

@router.get("/overview")
def overview(db: Session = Depends(get_db), user=Depends(get_current_user)):
    _ensure_default_pipeline(db, user)
    customers = db.query(models.Customer).filter_by(owner_user_id=user.id).count()
    active = db.query(models.Customer).filter_by(owner_user_id=user.id, status="active").count()
    deals_open = db.query(models.Deal).filter_by(owner_user_id=user.id, status="open").count()
    deals_won = db.query(models.Deal).filter_by(owner_user_id=user.id, status="won").count()
    products = db.query(models.Product).filter_by(owner_user_id=user.id).count()
    products_active = db.query(models.Product).filter_by(owner_user_id=user.id, status="active").count()
    pipeline_value = (
        db.query(func.coalesce(func.sum(models.Deal.value), 0.0))
        .filter_by(owner_user_id=user.id, status="open")
        .scalar()
    )
    won_value = (
        db.query(func.coalesce(func.sum(models.Deal.value), 0.0))
        .filter_by(owner_user_id=user.id, status="won")
        .scalar()
    )
    recent = (
        db.query(models.Customer)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Customer.updated_at.desc())
        .limit(8)
        .all()
    )
    pipelines = (
        db.query(models.Pipeline)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Pipeline.is_default.desc(), models.Pipeline.id)
        .all()
    )
    diary_upcoming = (
        db.query(models.DiaryEntry)
        .filter_by(owner_user_id=user.id, status="scheduled")
        .filter((models.DiaryEntry.start_at >= datetime.utcnow()) | (models.DiaryEntry.start_at.is_(None)))
        .count()
    )
    companies = (
        db.query(models.Company)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Company.id)
        .all()
    )
    return {
        "counts": {
            "customers": customers,
            "customers_active": active,
            "deals_open": deals_open,
            "deals_won": deals_won,
            "products": products,
            "products_active": products_active,
            "pipeline_value": float(pipeline_value or 0),
            "won_value": float(won_value or 0),
            "pipelines": len(pipelines),
            "diary_upcoming": diary_upcoming,
            "companies": len(companies),
        },
        "recent_customers": [_customer_out(c, db, light=True) for c in recent],
        "pipelines": [_pipeline_out(p, db) for p in pipelines],
        "companies": [{"id": c.id, "name": c.name, "industry": c.industry or ""} for c in companies],
        "tag_presets": {
            "customer": CUSTOMER_TAG_PRESETS,
            "product": PRODUCT_TAG_PRESETS,
        },
    }


# ── Pipelines ────────────────────────────────────────────────────────────

@router.get("/pipelines")
def list_pipelines(db: Session = Depends(get_db), user=Depends(get_current_user)):
    _ensure_default_pipeline(db, user)
    rows = (
        db.query(models.Pipeline)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Pipeline.is_default.desc(), models.Pipeline.id)
        .all()
    )
    return {"pipelines": [_pipeline_out(p, db) for p in rows]}


@router.post("/pipelines")
def create_pipeline(data: PipelineIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    if data.is_default:
        for p in db.query(models.Pipeline).filter_by(owner_user_id=user.id, is_default=True):
            p.is_default = False
    p = models.Pipeline(
        owner_user_id=user.id,
        company_id=data.company_id,
        name=name,
        description=(data.description or "").strip(),
        kind=(data.kind or "sales").strip(),
        is_default=bool(data.is_default),
    )
    db.add(p)
    db.flush()
    for name_s, st, color, pos, prob in DEFAULT_STAGES:
        db.add(models.PipelineStage(
            pipeline_id=p.id, name=name_s, stage_type=st,
            color=color, position=pos, probability=prob,
        ))
    db.commit()
    db.refresh(p)
    return _pipeline_out(p, db)


@router.get("/pipelines/{pipeline_id}")
def get_pipeline(pipeline_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    p = _owned_pipeline(db, pipeline_id, user)
    return _pipeline_out(p, db, with_deals=True)


@router.put("/pipelines/{pipeline_id}")
def update_pipeline(
    pipeline_id: int,
    data: PipelineIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    p = _owned_pipeline(db, pipeline_id, user)
    p.name = (data.name or p.name).strip()
    p.description = (data.description or "").strip()
    p.kind = (data.kind or p.kind).strip()
    p.company_id = data.company_id
    if data.is_default:
        for other in db.query(models.Pipeline).filter_by(owner_user_id=user.id, is_default=True):
            if other.id != p.id:
                other.is_default = False
        p.is_default = True
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    return _pipeline_out(p, db)


@router.delete("/pipelines/{pipeline_id}")
def delete_pipeline(pipeline_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    p = _owned_pipeline(db, pipeline_id, user)
    if p.is_default:
        raise HTTPException(400, "Cannot delete the default pipeline")
    # Move deals? block if any
    n = db.query(models.Deal).filter_by(pipeline_id=p.id).count()
    if n:
        raise HTTPException(400, f"Pipeline has {n} deals — move or delete them first")
    db.query(models.PipelineStage).filter_by(pipeline_id=p.id).delete()
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.post("/pipelines/{pipeline_id}/stages")
def add_stage(pipeline_id: int, data: StageIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    p = _owned_pipeline(db, pipeline_id, user)
    max_pos = (
        db.query(func.coalesce(func.max(models.PipelineStage.position), -1))
        .filter_by(pipeline_id=p.id)
        .scalar()
    )
    s = models.PipelineStage(
        pipeline_id=p.id,
        name=(data.name or "").strip(),
        stage_type=data.stage_type or "open",
        color=data.color or "#1668dc",
        position=data.position if data.position is not None else int(max_pos) + 1,
        probability=max(0, min(100, int(data.probability or 0))),
    )
    if not s.name:
        raise HTTPException(400, "name required")
    db.add(s)
    db.commit()
    db.refresh(s)
    return _stage_out(s)


# ── Customers ────────────────────────────────────────────────────────────

@router.get("/customers")
def list_customers(
    q: str | None = None,
    status: str | None = None,
    company_id: int | None = None,
    tag: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    rows, total = crm_list_customers(
        db, user, q=q, status=status, tag=tag, company_id=company_id,
        limit=limit, offset=offset,
    )
    return {
        "customers": [_customer_out(c, db, light=True) for c in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/customers")
async def create_customer(data: CustomerIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    company_id = _resolve_company_id(db, user, data.company_id, required=False)
    c = models.Customer(
        owner_user_id=user.id,
        company_id=company_id,
        name=name,
        email=(data.email or "").strip(),
        phone=(data.phone or "").strip(),
        job_title=(data.job_title or "").strip(),
        account_name=(data.account_name or "").strip(),
        website=(data.website or "").strip(),
        industry=(data.industry or "").strip(),
        address=(data.address or "").strip(),
        city=(data.city or "").strip(),
        country=(data.country or "").strip(),
        status=data.status or "active",
        source=(data.source or "").strip(),
        tags=_normalize_tags(data.tags),
        owner_human_id=data.owner_human_id,
        owner_agent_id=data.owner_agent_id,
        annual_value=float(data.annual_value or 0),
        notes=(data.notes or "").strip(),
    )
    db.add(c)
    db.flush()
    db.add(models.CustomerActivity(
        customer_id=c.id,
        owner_user_id=user.id,
        kind="system",
        title="Customer created",
        body=f"{c.name} added to CRM",
    ))
    db.commit()
    db.refresh(c)
    await emit_ops(
        user.id, kind="system", status="info",
        title=f"Customer added: {c.name}",
        detail=c.account_name or c.email or "",
        db=db,
    )
    return _customer_out(c, db)


@router.get("/customers/{customer_id}")
def get_customer(customer_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = _owned_customer(db, customer_id, user)
    deals = (
        db.query(models.Deal)
        .filter_by(customer_id=c.id)
        .order_by(models.Deal.updated_at.desc())
        .all()
    )
    acts = (
        db.query(models.CustomerActivity)
        .filter_by(customer_id=c.id)
        .order_by(models.CustomerActivity.id.desc())
        .limit(50)
        .all()
    )
    tasks = (
        db.query(models.Task)
        .filter(
            models.Task.user_id == user.id,
            models.Task.labels.ilike(f"%customer:{c.id}%"),
        )
        .order_by(models.Task.id.desc())
        .limit(20)
        .all()
    )
    diary = (
        db.query(models.DiaryEntry)
        .filter_by(customer_id=c.id)
        .order_by(models.DiaryEntry.start_at.asc().nullslast(), models.DiaryEntry.id.desc())
        .limit(30)
        .all()
    )
    return {
        **_customer_out(c, db),
        "deals": [_deal_out(d, db) for d in deals],
        "activities": [_activity_out(a) for a in acts],
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "agent_id": t.agent_id,
                "human_id": getattr(t, "human_id", None),
            }
            for t in tasks
        ],
        "diary": [_diary_out(d, db) for d in diary],
    }


@router.put("/customers/{customer_id}")
def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    c = _owned_customer(db, customer_id, user)
    payload = data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else data.dict(exclude_unset=True)
    company_kw = {}
    if "company_id" in payload:
        company_kw["company_id"] = _resolve_company_id(
            db, user, payload.pop("company_id") or None, required=False,
        )
    c = crm_update_customer_fields(db, user, c, payload, **company_kw)
    return _customer_out(c, db)


@router.delete("/customers/{customer_id}")
def delete_customer(customer_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = _owned_customer(db, customer_id, user)
    deal_ids = [d.id for d in db.query(models.Deal).filter_by(customer_id=c.id).all()]
    db.query(models.CustomerActivity).filter_by(customer_id=c.id).delete()
    db.query(models.Deal).filter_by(customer_id=c.id).delete()
    db.delete(c)
    db.commit()
    return {"ok": True, "deleted_deals": len(deal_ids)}


@router.post("/customers/{customer_id}/activities")
async def add_activity(
    customer_id: int,
    data: ActivityIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    c = _owned_customer(db, customer_id, user)
    a = crm_log_customer_activity(
        db, user, c,
        kind=data.kind or "note",
        title=data.title or "",
        body=data.body or "",
        deal_id=data.deal_id,
    )
    await emit_ops(
        user.id, kind="action", status="info",
        title=f"{c.name}: {a.title}",
        detail=(a.body or "")[:200],
        db=db,
    )
    return _activity_out(a)


# ── Deals ────────────────────────────────────────────────────────────────

@router.get("/deals")
def list_deals(
    pipeline_id: int | None = None,
    customer_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(models.Deal).filter_by(owner_user_id=user.id)
    if pipeline_id is not None:
        q = q.filter_by(pipeline_id=pipeline_id)
    if customer_id is not None:
        q = q.filter_by(customer_id=customer_id)
    if status:
        q = q.filter_by(status=status)
    rows = q.order_by(models.Deal.updated_at.desc()).limit(200).all()
    return {"deals": [_deal_out(d, db) for d in rows]}


@router.post("/deals")
async def create_deal(data: DealIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    cust = _owned_customer(db, data.customer_id, user)
    deal_company = _resolve_company_id(
        db, user, data.company_id or cust.company_id, required=False,
    )
    d = crm_create_deal_for_customer(
        db, user, cust,
        title=data.title,
        value=float(data.value or 0),
        currency=data.currency or "USD",
        priority=data.priority or "medium",
        description=data.description or "",
        expected_close=data.expected_close,
        pipeline_id=data.pipeline_id,
        stage_id=data.stage_id,
        company_id=deal_company,
        owner_human_id=data.owner_human_id or cust.owner_human_id,
        owner_agent_id=data.owner_agent_id or cust.owner_agent_id,
    )
    stage = db.get(models.PipelineStage, d.stage_id)
    await emit_ops(
        user.id, kind="action", status="info",
        title=f"Deal: {d.title}",
        detail=f"{cust.name} · {stage.name if stage else ''}",
        db=db,
    )
    return _deal_out(d, db)


@router.put("/deals/{deal_id}/move")
async def move_deal(
    deal_id: int,
    data: DealMoveIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    d = require_owned(
        db, models.Deal, deal_id, user,
        user_field='owner_user_id', not_found="Deal not found",
    )
    stage = db.get(models.PipelineStage, data.stage_id)
    if not stage or stage.pipeline_id != d.pipeline_id:
        raise HTTPException(400, "Stage not in this pipeline")
    old_stage = db.get(models.PipelineStage, d.stage_id)
    d.stage_id = stage.id
    if data.position is not None:
        d.position = data.position
    # Auto status from stage type
    if data.status:
        d.status = data.status
    elif stage.stage_type == "won":
        d.status = "won"
        d.closed_at = datetime.utcnow()
    elif stage.stage_type == "lost":
        d.status = "lost"
        d.closed_at = datetime.utcnow()
        d.lost_reason = data.lost_reason or d.lost_reason
    else:
        d.status = "open"
        d.closed_at = None
    d.updated_at = datetime.utcnow()
    db.add(models.CustomerActivity(
        customer_id=d.customer_id,
        owner_user_id=user.id,
        kind="stage",
        title=f"Moved to {stage.name}",
        body=f"From {old_stage.name if old_stage else '?'} → {stage.name}",
        deal_id=d.id,
    ))
    db.commit()
    db.refresh(d)
    await emit_ops(
        user.id, kind="action", status="done",
        title=f"Deal moved: {d.title}",
        detail=stage.name,
        db=db,
    )
    return _deal_out(d, db)


@router.put("/deals/{deal_id}")
def update_deal(
    deal_id: int,
    data: DealIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    d = require_owned(
        db, models.Deal, deal_id, user,
        user_field='owner_user_id', not_found="Deal not found",
    )
    if data.title:
        d.title = data.title.strip()
    d.value = float(data.value if data.value is not None else d.value)
    d.currency = data.currency or d.currency
    d.priority = data.priority or d.priority
    d.description = data.description if data.description is not None else d.description
    d.expected_close = _parse_dt(data.expected_close) if data.expected_close is not None else d.expected_close
    if data.owner_human_id is not None:
        d.owner_human_id = data.owner_human_id or None
    if data.owner_agent_id is not None:
        d.owner_agent_id = data.owner_agent_id or None
    d.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(d)
    return _deal_out(d, db)


@router.delete("/deals/{deal_id}")
def delete_deal(deal_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    d = require_owned(
        db, models.Deal, deal_id, user,
        user_field='owner_user_id', not_found="Deal not found",
    )
    db.query(models.CustomerActivity).filter_by(deal_id=d.id).delete()
    db.delete(d)
    db.commit()
    return {"ok": True}


# ── Diary / Appointments (arrange diaries for customers) ─────────────────

class DiaryIn(BaseModel):
    customer_id: int
    title: str
    start_at: str | None = None  # ISO
    end_at: str | None = None
    location: str = ""
    notes: str = ""
    owner_human_id: int | None = None
    owner_agent_id: int | None = None
    deal_id: int | None = None


class DiaryUpdate(BaseModel):
    title: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    location: str | None = None
    notes: str | None = None
    status: str | None = None  # scheduled | completed | cancelled | no_show
    owner_human_id: int | None = None
    owner_agent_id: int | None = None
    deal_id: int | None = None


def _diary_out(d: models.DiaryEntry, db: Session) -> dict:
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


@router.get("/diary")
def list_diary(
    customer_id: int | None = None,
    status: str | None = None,
    upcoming: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(models.DiaryEntry).filter_by(owner_user_id=user.id)
    if customer_id is not None:
        q = q.filter_by(customer_id=customer_id)
    if status:
        q = q.filter_by(status=status)
    if upcoming:
        now = datetime.utcnow()
        q = q.filter(
            models.DiaryEntry.status == "scheduled",
            (models.DiaryEntry.start_at >= now) | (models.DiaryEntry.start_at.is_(None)),
        )
    rows = q.order_by(models.DiaryEntry.start_at.asc().nullslast(), models.DiaryEntry.id.desc()).limit(200).all()
    return {"diary": [_diary_out(d, db) for d in rows]}


@router.post("/diary")
async def create_diary(data: DiaryIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    cust = _owned_customer(db, data.customer_id, user)
    start = _parse_dt(data.start_at)
    end = _parse_dt(data.end_at)
    if not (data.title or "").strip():
        raise HTTPException(400, "title required")
    d = models.DiaryEntry(
        owner_user_id=user.id,
        customer_id=cust.id,
        deal_id=data.deal_id,
        title=data.title.strip(),
        start_at=start,
        end_at=end,
        location=(data.location or "").strip(),
        notes=(data.notes or "").strip(),
        status="scheduled",
        owner_human_id=data.owner_human_id,
        owner_agent_id=data.owner_agent_id,
    )
    db.add(d)
    db.flush()
    # Log as activity too
    db.add(models.CustomerActivity(
        customer_id=cust.id,
        owner_user_id=user.id,
        kind="meeting",
        title=f"Diary: {d.title}",
        body=f"Scheduled {start.isoformat() if start else 'TBD'} @ {d.location or '—'}",
        deal_id=d.deal_id,
    ))
    cust.last_contacted_at = datetime.utcnow()
    db.commit()
    db.refresh(d)
    await emit_ops(user.id, kind="action", status="info", title=f"Diary set: {d.title}", detail=cust.name, db=db)
    return _diary_out(d, db)


@router.put("/diary/{diary_id}")
def update_diary(diary_id: int, data: DiaryUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    d = require_owned(
        db, models.DiaryEntry, diary_id, user,
        user_field='owner_user_id', not_found="Diary entry not found",
    )
    if data.title is not None:
        d.title = data.title.strip()
    if data.start_at is not None:
        d.start_at = _parse_dt(data.start_at)
    if data.end_at is not None:
        d.end_at = _parse_dt(data.end_at)
    if data.location is not None:
        d.location = data.location.strip()
    if data.notes is not None:
        d.notes = data.notes.strip()
    if data.status is not None:
        d.status = data.status
        if data.status in ("completed", "cancelled", "no_show"):
            d.completed_at = datetime.utcnow()
    if data.owner_human_id is not None:
        d.owner_human_id = data.owner_human_id or None
    if data.owner_agent_id is not None:
        d.owner_agent_id = data.owner_agent_id or None
    if data.deal_id is not None:
        d.deal_id = data.deal_id
    d.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(d)
    return _diary_out(d, db)


@router.delete("/diary/{diary_id}")
def delete_diary(diary_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    d = require_owned(
        db, models.DiaryEntry, diary_id, user,
        user_field='owner_user_id', not_found="Diary entry not found",
    )
    db.delete(d)
    db.commit()
    return {"ok": True}
