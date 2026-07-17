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

router = APIRouter(prefix="/business", tags=["business"])

DEFAULT_STAGES = [
    ("New lead", "open", "#8c8c8c", 0, 10),
    ("Contacted", "open", "#1668dc", 1, 25),
    ("Qualified", "open", "#13c2c2", 2, 50),
    ("Proposal", "open", "#722ed1", 3, 70),
    ("Negotiation", "open", "#fa8c16", 4, 85),
    ("Won", "won", "#52c41a", 5, 100),
    ("Lost", "lost", "#ff4d4f", 6, 0),
]


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
    tags: str = ""
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
    tags: str | None = None
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

def _parse_dt(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", ""))
    except Exception:
        return None


def _ensure_default_pipeline(db: Session, user: models.User) -> models.Pipeline:
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


def _customer_out(c: models.Customer, db: Session, *, light: bool = False) -> dict:
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
        "tags": [t.strip() for t in (c.tags or "").split(",") if t.strip()],
        "tags_raw": c.tags or "",
        "company_id": c.company_id,
        "company_name": co.name if co else None,
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


def _deal_out(d: models.Deal, db: Session) -> dict:
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


def _activity_out(a: models.CustomerActivity) -> dict:
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


def _owned_customer(db: Session, customer_id: int, user) -> models.Customer:
    c = db.get(models.Customer, customer_id)
    if not c or c.owner_user_id != user.id:
        raise HTTPException(404, "Customer not found")
    return c


def _owned_pipeline(db: Session, pipeline_id: int, user) -> models.Pipeline:
    p = db.get(models.Pipeline, pipeline_id)
    if not p or p.owner_user_id != user.id:
        raise HTTPException(404, "Pipeline not found")
    return p


# ── Overview ─────────────────────────────────────────────────────────────

@router.get("/overview")
def overview(db: Session = Depends(get_db), user=Depends(get_current_user)):
    _ensure_default_pipeline(db, user)
    customers = db.query(models.Customer).filter_by(owner_user_id=user.id).count()
    active = db.query(models.Customer).filter_by(owner_user_id=user.id, status="active").count()
    deals_open = db.query(models.Deal).filter_by(owner_user_id=user.id, status="open").count()
    deals_won = db.query(models.Deal).filter_by(owner_user_id=user.id, status="won").count()
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
    return {
        "counts": {
            "customers": customers,
            "customers_active": active,
            "deals_open": deals_open,
            "deals_won": deals_won,
            "pipeline_value": float(pipeline_value or 0),
            "won_value": float(won_value or 0),
            "pipelines": len(pipelines),
        },
        "recent_customers": [_customer_out(c, db, light=True) for c in recent],
        "pipelines": [_pipeline_out(p, db) for p in pipelines],
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
    query = db.query(models.Customer).filter_by(owner_user_id=user.id)
    if status:
        query = query.filter_by(status=status)
    if company_id is not None:
        query = query.filter_by(company_id=company_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            models.Customer.name.ilike(like),
            models.Customer.email.ilike(like),
            models.Customer.account_name.ilike(like),
            models.Customer.phone.ilike(like),
            models.Customer.tags.ilike(like),
        ))
    if tag:
        query = query.filter(models.Customer.tags.ilike(f"%{tag.strip()}%"))
    total = query.count()
    rows = (
        query.order_by(models.Customer.updated_at.desc(), models.Customer.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
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
    c = models.Customer(
        owner_user_id=user.id,
        company_id=data.company_id,
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
        tags=(data.tags or "").strip(),
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
    }


@router.put("/customers/{customer_id}")
def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    c = _owned_customer(db, customer_id, user)
    fields = (
        "name", "email", "phone", "job_title", "account_name", "website",
        "industry", "address", "city", "country", "status", "source", "tags", "notes",
    )
    for f in fields:
        val = getattr(data, f)
        if val is not None:
            setattr(c, f, val.strip() if isinstance(val, str) else val)
    if data.company_id is not None:
        c.company_id = data.company_id or None
    if data.owner_human_id is not None:
        c.owner_human_id = data.owner_human_id or None
    if data.owner_agent_id is not None:
        c.owner_agent_id = data.owner_agent_id or None
    if data.annual_value is not None:
        c.annual_value = float(data.annual_value)
    c.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(c)
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
    a = models.CustomerActivity(
        customer_id=c.id,
        owner_user_id=user.id,
        kind=(data.kind or "note").strip(),
        title=(data.title or "").strip() or (data.kind or "note").title(),
        body=(data.body or "").strip(),
        deal_id=data.deal_id,
    )
    db.add(a)
    c.last_contacted_at = datetime.utcnow()
    c.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(a)
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
    if data.pipeline_id:
        pipe = _owned_pipeline(db, data.pipeline_id, user)
    else:
        pipe = _ensure_default_pipeline(db, user)
    stage = None
    if data.stage_id:
        stage = db.get(models.PipelineStage, data.stage_id)
        if not stage or stage.pipeline_id != pipe.id:
            raise HTTPException(400, "Invalid stage for pipeline")
    else:
        stage = (
            db.query(models.PipelineStage)
            .filter_by(pipeline_id=pipe.id)
            .order_by(models.PipelineStage.position)
            .first()
        )
    if not stage:
        raise HTTPException(400, "Pipeline has no stages")
    title = (data.title or "").strip() or f"Deal · {cust.name}"
    d = models.Deal(
        owner_user_id=user.id,
        pipeline_id=pipe.id,
        stage_id=stage.id,
        customer_id=cust.id,
        company_id=data.company_id or cust.company_id,
        title=title,
        value=float(data.value or 0),
        currency=(data.currency or "USD").strip(),
        status="open",
        priority=data.priority or "medium",
        expected_close=_parse_dt(data.expected_close),
        owner_human_id=data.owner_human_id or cust.owner_human_id,
        owner_agent_id=data.owner_agent_id or cust.owner_agent_id,
        description=(data.description or "").strip(),
    )
    db.add(d)
    db.flush()
    db.add(models.CustomerActivity(
        customer_id=cust.id,
        owner_user_id=user.id,
        kind="deal",
        title=f"Deal created: {title}",
        body=f"Stage: {stage.name} · Value: {d.value} {d.currency}",
        deal_id=d.id,
    ))
    cust.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(d)
    await emit_ops(
        user.id, kind="action", status="info",
        title=f"Deal: {title}",
        detail=f"{cust.name} · {stage.name}",
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
    d = db.get(models.Deal, deal_id)
    if not d or d.owner_user_id != user.id:
        raise HTTPException(404, "Deal not found")
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
    d = db.get(models.Deal, deal_id)
    if not d or d.owner_user_id != user.id:
        raise HTTPException(404, "Deal not found")
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
    d = db.get(models.Deal, deal_id)
    if not d or d.owner_user_id != user.id:
        raise HTTPException(404, "Deal not found")
    db.query(models.CustomerActivity).filter_by(deal_id=d.id).delete()
    db.delete(d)
    db.commit()
    return {"ok": True}
