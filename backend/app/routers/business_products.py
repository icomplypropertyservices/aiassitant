"""Business products catalogue + Shopify sync/push routes."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import get_current_user
from ..live_ops import emit_ops
from ..tags_util import normalize_tags, tags_list
from ..company_scope import resolve_company_id
from ..ownership import require_owned

router = APIRouter(prefix="/business", tags=["business-products"])

PRODUCT_TAG_PRESETS = [
    "core", "addon", "featured", "service", "digital", "physical",
    "subscription", "bundle", "new", "sale", "b2b", "b2c",
]


def _resolve_company_id(db, user, company_id, *, required=False):
    return resolve_company_id(db, user, company_id, required=required, resource="products")


def _owned_product(db: Session, product_id: int, user) -> models.Product:
    return require_owned(
        db, models.Product, product_id, user,
        user_field="owner_user_id", not_found="Product not found",
    )


def _product_out(p: models.Product, db: Session) -> dict:
    co = db.get(models.Company, p.company_id) if p.company_id else None
    return {
        "id": p.id,
        "name": p.name,
        "sku": p.sku or "",
        "description": p.description or "",
        "kind": p.kind or "product",
        "price": float(p.price or 0),
        "currency": p.currency or "USD",
        "status": p.status or "active",
        "tags": tags_list(p.tags),
        "tags_raw": p.tags or "",
        "company_id": p.company_id,
        "company_name": co.name if co else None,
        "external_source": getattr(p, "external_source", None) or "",
        "external_id": getattr(p, "external_id", None) or "",
        "benefits": p.benefits or "",
        "audience": p.audience or "",
        "offer": p.offer or "",
        "image_url": p.image_url or "",
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


class ProductIn(BaseModel):
    name: str
    sku: str = ""
    description: str = ""
    kind: str = "product"
    price: float = 0.0
    currency: str = "USD"
    status: str = "active"
    tags: str | list[str] = ""
    company_id: int | None = None
    benefits: str = ""
    audience: str = ""
    offer: str = ""
    image_url: str = ""


class ProductUpdate(BaseModel):
    name: str | None = None
    sku: str | None = None
    description: str | None = None
    kind: str | None = None
    price: float | None = None
    currency: str | None = None
    status: str | None = None
    tags: str | list[str] | None = None
    company_id: int | None = None
    benefits: str | None = None
    audience: str | None = None
    offer: str | None = None
    image_url: str | None = None


class ShopifySyncIn(BaseModel):
    company_id: int | None = None
    connection_id: int | None = None
    limit: int = 50
    what: str = "all"


# ── Products (company-linked catalogue) ──────────────────────────────────

@router.get("/products")
def list_products(
    q: str | None = None,
    status: str | None = None,
    company_id: int | None = None,
    tag: str | None = None,
    kind: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    query = db.query(models.Product).filter_by(owner_user_id=user.id)
    if status:
        query = query.filter_by(status=status)
    if company_id is not None:
        query = query.filter_by(company_id=company_id)
    if kind:
        query = query.filter_by(kind=kind)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            models.Product.name.ilike(like),
            models.Product.sku.ilike(like),
            models.Product.description.ilike(like),
            models.Product.tags.ilike(like),
        ))
    if tag:
        query = query.filter(models.Product.tags.ilike(f"%{tag.strip()}%"))
    total = query.count()
    rows = (
        query.order_by(models.Product.updated_at.desc(), models.Product.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "products": [_product_out(p, db) for p in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "tag_presets": PRODUCT_TAG_PRESETS,
    }


@router.post("/products")
async def create_product(data: ProductIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    company_id = _resolve_company_id(db, user, data.company_id, required=True)
    p = models.Product(
        owner_user_id=user.id,
        company_id=company_id,
        name=name,
        sku=(data.sku or "").strip(),
        description=(data.description or "").strip(),
        kind=(data.kind or "product").strip() or "product",
        price=float(data.price or 0),
        currency=(data.currency or "USD").strip() or "USD",
        status=(data.status or "active").strip() or "active",
        tags=normalize_tags(data.tags),
        benefits=(data.benefits or "").strip(),
        audience=(data.audience or "").strip(),
        offer=(data.offer or "").strip(),
        image_url=(data.image_url or "").strip(),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    await emit_ops(
        user.id, kind="system", status="info",
        title=f"Product added: {p.name}",
        detail=f"Company #{company_id} · {p.kind} · {normalize_tags(data.tags) or 'no tags'}",
        db=db,
    )
    return _product_out(p, db)


@router.get("/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    p = _owned_product(db, product_id, user)
    return _product_out(p, db)


@router.put("/products/{product_id}")
def update_product(
    product_id: int,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    p = _owned_product(db, product_id, user)
    str_fields = ("name", "sku", "description", "kind", "currency", "status", "benefits", "audience", "offer", "image_url")
    for f in str_fields:
        val = getattr(data, f)
        if val is not None:
            setattr(p, f, val.strip() if isinstance(val, str) else val)
    if data.price is not None:
        p.price = float(data.price)
    if data.tags is not None:
        p.tags = normalize_tags(data.tags)
    if data.company_id is not None:
        p.company_id = _resolve_company_id(db, user, data.company_id or None, required=True)
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    return _product_out(p, db)


@router.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    p = _owned_product(db, product_id, user)
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.post("/shopify/sync")
async def shopify_sync(
    data: ShopifySyncIn = ShopifySyncIn(),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Import Shopify products & customers into Business CRM with tags + company link."""
    from ..shopify_sync import sync_all_shopify, sync_shopify_products, sync_shopify_customers
    what = (data.what or "all").lower().strip()
    if what == "products":
        result = await sync_shopify_products(
            db, user,
            company_id=data.company_id,
            connection_id=data.connection_id,
            limit=data.limit,
        )
    elif what == "customers":
        result = await sync_shopify_customers(
            db, user,
            company_id=data.company_id,
            connection_id=data.connection_id,
            limit=data.limit,
        )
    else:
        result = await sync_all_shopify(
            db, user,
            company_id=data.company_id,
            connection_id=data.connection_id,
            limit=data.limit,
        )
    if result.get("ok"):
        await emit_ops(
            user.id, kind="app", status="done",
            title="Shopify sync",
            detail=result.get("message") or "",
            db=db,
        )
    return result


@router.post("/products/{product_id}/push-shopify")
async def push_product_shopify(
    product_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Push local product tags/name/price to linked Shopify product."""
    from ..shopify_sync import push_product_tags_to_shopify

    result = await push_product_tags_to_shopify(db, user, product_id)
    if result.get("ok"):
        await emit_ops(
            user.id, kind="app", status="done",
            title="Shopify product tags pushed",
            detail=result.get("message") or "",
            db=db,
        )
    return result


@router.post("/customers/{customer_id}/push-shopify")
async def push_customer_shopify(
    customer_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Push local customer tags to linked Shopify customer."""
    from ..shopify_sync import push_customer_tags_to_shopify

    result = await push_customer_tags_to_shopify(db, user, customer_id)
    if result.get("ok"):
        await emit_ops(
            user.id, kind="app", status="done",
            title="Shopify customer tags pushed",
            detail=result.get("message") or "",
            db=db,
        )
    return result


