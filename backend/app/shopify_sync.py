"""
Sync Shopify products & customers into the user's Business CRM.

- Links every imported row to the user's company (company_id)
- Copies Shopify tags into local Product.tags / Customer.tags
- Stores external_source=shopify + external_id for re-sync / push
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .integration_actions import run_app_action
from .shopify_actions import _shopify_tags_str
from .company_scope import resolve_company_id


def _default_company_id(db: Session, user: models.User, company_id: int | None = None) -> int | None:
    """Resolve company; raise if explicit id is invalid. None if user has no company."""
    return resolve_company_id(
        db, user, company_id, required=False, resource="Shopify sync",
    )


def _shopify_conn(db: Session, user: models.User, connection_id: int | None = None):
    if connection_id:
        row = db.get(models.IntegrationConnection, connection_id)
        if row and row.user_id == user.id and row.app_id == "shopify":
            return row
        return None
    return (
        db.query(models.IntegrationConnection)
        .filter_by(user_id=user.id, app_id="shopify", status="connected")
        .order_by(models.IntegrationConnection.id.desc())
        .first()
    )


def _merge_tags(*parts: str) -> str:
    return _shopify_tags_str(",".join(p for p in parts if p))


async def sync_shopify_products(
    db: Session,
    user: models.User,
    *,
    company_id: int | None = None,
    connection_id: int | None = None,
    limit: int = 50,
    push_missing_tags: bool = False,
) -> dict[str, Any]:
    """Pull Shopify products -> local Product rows (company + tags)."""
    conn = _shopify_conn(db, user, connection_id)
    if not conn:
        return {
            "ok": False,
            "error": "No connected Shopify app. Connect under Settings -> Connected apps.",
        }
    cid = _default_company_id(db, user, company_id)
    if not cid:
        return {
            "ok": False,
            "error": "Create a company in Workspace first - products must link to your company.",
        }

    result = await run_app_action(conn, "get_products", {"limit": min(int(limit or 50), 250)})
    if not result.get("ok"):
        return result

    products = (result.get("data") or {}).get("products") or []
    created = updated = 0
    rows_out = []

    for p in products:
        sid = str(p.get("id") or "")
        if not sid:
            continue
        tags = _shopify_tags_str(p.get("tags") or p.get("tags_list") or "")
        # Always include shopify source tag for filterability
        tags = _merge_tags(tags, "shopify")
        existing = (
            db.query(models.Product)
            .filter_by(
                owner_user_id=user.id,
                external_source="shopify",
                external_id=sid,
            )
            .first()
        )
        price = 0.0
        try:
            price = float(p.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        status = "active"
        st = (p.get("status") or "active").lower()
        if st in ("draft", "archived"):
            status = st
        meta = {
            "shopify_id": sid,
            "handle": p.get("handle"),
            "vendor": p.get("vendor"),
            "product_type": p.get("product_type"),
            "shop_domain": (result.get("data") or {}).get("shop_domain"),
        }
        if existing:
            existing.name = p.get("title") or existing.name
            existing.sku = (p.get("sku") or existing.sku or "")[:120]
            existing.description = p.get("body_html") or existing.description or ""
            existing.price = price
            existing.status = status
            existing.tags = tags
            existing.company_id = cid
            existing.image_url = p.get("image") or existing.image_url or ""
            existing.meta_json = json.dumps(meta)
            existing.updated_at = datetime.utcnow()
            updated += 1
            row = existing
        else:
            row = models.Product(
                owner_user_id=user.id,
                company_id=cid,
                name=(p.get("title") or f"Shopify product {sid}")[:255],
                sku=(p.get("sku") or "")[:120],
                description=p.get("body_html") or "",
                kind="product",
                price=price,
                currency="USD",
                status=status,
                tags=tags,
                image_url=p.get("image") or "",
                external_source="shopify",
                external_id=sid,
                meta_json=json.dumps(meta),
            )
            db.add(row)
            created += 1
        db.flush()
        rows_out.append({
            "id": row.id,
            "external_id": sid,
            "name": row.name,
            "tags": [t.strip() for t in (row.tags or "").split(",") if t.strip()],
            "company_id": row.company_id,
        })

        if push_missing_tags and tags:
            # Optional: no-op if Shopify already has tags - reserved for future
            pass

    conn.last_synced_at = datetime.utcnow()
    db.commit()
    return {
        "ok": True,
        "message": f"Synced {created + updated} products from Shopify ({created} new, {updated} updated)",
        "created": created,
        "updated": updated,
        "company_id": cid,
        "products": rows_out[:50],
        "source": "shopify",
    }


async def sync_shopify_customers(
    db: Session,
    user: models.User,
    *,
    company_id: int | None = None,
    connection_id: int | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Pull Shopify customers -> local Customer rows (company + tags)."""
    conn = _shopify_conn(db, user, connection_id)
    if not conn:
        return {
            "ok": False,
            "error": "No connected Shopify app. Connect under Settings -> Connected apps.",
        }
    cid = _default_company_id(db, user, company_id)
    if not cid:
        return {
            "ok": False,
            "error": "Create a company in Workspace first - customers must link to your company.",
        }

    result = await run_app_action(conn, "get_customers", {"limit": min(int(limit or 50), 250)})
    if not result.get("ok"):
        return result

    customers = (result.get("data") or {}).get("customers") or []
    created = updated = 0
    rows_out = []

    for c in customers:
        sid = str(c.get("id") or "")
        if not sid:
            continue
        tags = _merge_tags(_shopify_tags_str(c.get("tags") or c.get("tags_list") or ""), "shopify")
        email = (c.get("email") or "").strip().lower()
        existing = (
            db.query(models.Customer)
            .filter_by(
                owner_user_id=user.id,
                external_source="shopify",
                external_id=sid,
            )
            .first()
        )
        if not existing and email:
            existing = (
                db.query(models.Customer)
                .filter_by(owner_user_id=user.id)
                .filter(models.Customer.email.ilike(email))
                .first()
            )
        name = (c.get("name") or "").strip() or email or f"Shopify {sid}"
        annual = 0.0
        try:
            annual = float(c.get("total_spent") or 0)
        except (TypeError, ValueError):
            annual = 0.0
        meta = {
            "shopify_id": sid,
            "orders_count": c.get("orders_count"),
            "total_spent": c.get("total_spent"),
        }
        if existing:
            existing.name = name
            if email:
                existing.email = email
            if c.get("phone"):
                existing.phone = c.get("phone") or existing.phone
            existing.tags = _merge_tags(existing.tags or "", tags)
            existing.company_id = existing.company_id or cid
            existing.source = existing.source or "shopify"
            existing.external_source = "shopify"
            existing.external_id = sid
            existing.annual_value = annual or existing.annual_value or 0
            if c.get("note"):
                existing.notes = c.get("note") or existing.notes
            existing.meta_json = json.dumps(meta)
            existing.updated_at = datetime.utcnow()
            updated += 1
            row = existing
        else:
            row = models.Customer(
                owner_user_id=user.id,
                company_id=cid,
                name=name[:255],
                email=email,
                phone=c.get("phone") or "",
                status="active",
                source="shopify",
                tags=tags,
                annual_value=annual,
                notes=c.get("note") or "",
                external_source="shopify",
                external_id=sid,
                meta_json=json.dumps(meta),
            )
            db.add(row)
            created += 1
        db.flush()
        rows_out.append({
            "id": row.id,
            "external_id": sid,
            "name": row.name,
            "email": row.email,
            "tags": [t.strip() for t in (row.tags or "").split(",") if t.strip()],
            "company_id": row.company_id,
        })

    conn.last_synced_at = datetime.utcnow()
    db.commit()
    return {
        "ok": True,
        "message": f"Synced {created + updated} customers from Shopify ({created} new, {updated} updated)",
        "created": created,
        "updated": updated,
        "company_id": cid,
        "customers": rows_out[:50],
        "source": "shopify",
    }


async def push_product_tags_to_shopify(
    db: Session,
    user: models.User,
    product_id: int,
    *,
    connection_id: int | None = None,
) -> dict[str, Any]:
    """Push local Product.tags (and name/price) to Shopify product."""
    prod = db.get(models.Product, product_id)
    if not prod or prod.owner_user_id != user.id:
        return {"ok": False, "error": "Product not found"}
    if (prod.external_source or "") != "shopify" or not prod.external_id:
        return {"ok": False, "error": "Product is not linked to Shopify (sync from Shopify first)"}
    conn = _shopify_conn(db, user, connection_id)
    if not conn:
        return {"ok": False, "error": "No connected Shopify app"}
    result = await run_app_action(
        conn,
        "update_product",
        {
            "product_id": prod.external_id,
            "title": prod.name,
            "tags": prod.tags or "",
            "description": prod.description or "",
            "price": prod.price,
            "status": prod.status if prod.status in ("active", "draft", "archived") else "active",
        },
    )
    return result


async def push_customer_tags_to_shopify(
    db: Session,
    user: models.User,
    customer_id: int,
    *,
    connection_id: int | None = None,
) -> dict[str, Any]:
    """Push local Customer.tags to Shopify customer."""
    cust = db.get(models.Customer, customer_id)
    if not cust or cust.owner_user_id != user.id:
        return {"ok": False, "error": "Customer not found"}
    if (cust.external_source or "") != "shopify" or not cust.external_id:
        return {"ok": False, "error": "Customer is not linked to Shopify (sync from Shopify first)"}
    conn = _shopify_conn(db, user, connection_id)
    if not conn:
        return {"ok": False, "error": "No connected Shopify app"}
    parts = (cust.name or "").split(None, 1)
    first = parts[0] if parts else ""
    last = parts[1] if len(parts) > 1 else ""
    result = await run_app_action(
        conn,
        "update_customer",
        {
            "customer_id": cust.external_id,
            "email": cust.email or None,
            "first_name": first or None,
            "last_name": last or None,
            "phone": cust.phone or None,
            "tags": cust.tags or "",
            "note": cust.notes or None,
        },
    )
    return result


async def sync_all_shopify(
    db: Session,
    user: models.User,
    *,
    company_id: int | None = None,
    connection_id: int | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    products = await sync_shopify_products(
        db, user, company_id=company_id, connection_id=connection_id, limit=limit,
    )
    customers = await sync_shopify_customers(
        db, user, company_id=company_id, connection_id=connection_id, limit=limit,
    )
    ok = bool(products.get("ok")) and bool(customers.get("ok"))
    return {
        "ok": ok,
        "message": (
            f"Shopify sync · products: {products.get('message')} · customers: {customers.get('message')}"
            if ok
            else products.get("error") or customers.get("error") or "Sync failed"
        ),
        "products": products,
        "customers": customers,
        "company_id": products.get("company_id") or customers.get("company_id"),
    }

