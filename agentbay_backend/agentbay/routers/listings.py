import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import or_

from ..database import get_db
from .. import models
from ..auth_utils import get_current_user, user_public

router = APIRouter(prefix="/listings", tags=["listings"])


class ListingIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = ""
    kind: str = "product"  # product | service | digital | agent_skill
    price: float = Field(ge=0)
    currency: str = "USD"
    quantity: int = Field(default=1, ge=0)
    category_id: int | None = None
    condition: str = "new"
    image_url: str = ""
    images: list[str] = []
    tags: str = ""
    location: str = ""
    shipping_info: str = ""
    sale_type: str = "buy_now"
    status: str = "active"


class ListingUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    price: float | None = None
    quantity: int | None = None
    category_id: int | None = None
    condition: str | None = None
    image_url: str | None = None
    images: list[str] | None = None
    tags: str | None = None
    location: str | None = None
    shipping_info: str | None = None
    sale_type: str | None = None
    status: str | None = None


def _listing_images(L: models.Listing) -> list[str]:
    imgs: list[str] = []
    raw = getattr(L, "images_json", None) or "[]"
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            imgs = [str(x) for x in parsed if x]
    except Exception:
        pass
    if L.image_url and L.image_url not in imgs:
        imgs = [L.image_url] + imgs
    return imgs


def serialize_listing(L: models.Listing, seller: models.User | None = None) -> dict:
    images = _listing_images(L)
    return {
        "id": L.id,
        "seller_id": L.seller_id,
        "seller": user_public(seller) if seller else None,
        "category_id": L.category_id,
        "title": L.title,
        "description": L.description or "",
        "kind": L.kind,
        "price": L.price,
        "currency": L.currency,
        "quantity": L.quantity,
        "status": L.status,
        "condition": L.condition,
        "image_url": (images[0] if images else "") or (L.image_url or ""),
        "images": images,
        "tags": [t.strip() for t in (L.tags or "").split(",") if t.strip()],
        "location": L.location or "",
        "shipping_info": L.shipping_info or "",
        "sale_type": L.sale_type,
        "views": L.views or 0,
        "source_system": getattr(L, "source_system", None),
        "external_id": getattr(L, "external_id", None),
        "created_at": L.created_at.isoformat() if L.created_at else None,
        "updated_at": L.updated_at.isoformat() if L.updated_at else None,
    }


@router.get("")
def search_listings(
    q: str | None = None,
    category_id: int | None = None,
    kind: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    seller_id: int | None = None,
    status: str = "active",
    sort: str = "newest",  # newest | price_asc | price_desc | popular
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(models.Listing)
    if status:
        query = query.filter(models.Listing.status == status)
    if category_id:
        query = query.filter(models.Listing.category_id == category_id)
    if kind:
        query = query.filter(models.Listing.kind == kind)
    if seller_id:
        query = query.filter(models.Listing.seller_id == seller_id)
    if min_price is not None:
        query = query.filter(models.Listing.price >= min_price)
    if max_price is not None:
        query = query.filter(models.Listing.price <= max_price)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                models.Listing.title.ilike(like),
                models.Listing.description.ilike(like),
                models.Listing.tags.ilike(like),
            )
        )

    if sort == "price_asc":
        query = query.order_by(models.Listing.price.asc())
    elif sort == "price_desc":
        query = query.order_by(models.Listing.price.desc())
    elif sort == "popular":
        query = query.order_by(models.Listing.views.desc())
    else:
        query = query.order_by(models.Listing.id.desc())

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    sellers = {
        u.id: u
        for u in db.query(models.User)
        .filter(models.User.id.in_({r.seller_id for r in rows} or {-1}))
        .all()
    }
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [serialize_listing(r, sellers.get(r.seller_id)) for r in rows],
    }


@router.get("/watchlist/mine")
def my_watchlist(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = (
        db.query(models.Watchlist)
        .filter_by(user_id=user.id)
        .order_by(models.Watchlist.id.desc())
        .all()
    )
    items = []
    for w in rows:
        L = db.get(models.Listing, w.listing_id)
        if L:
            seller = db.get(models.User, L.seller_id)
            items.append(serialize_listing(L, seller))
    return {"items": items}


@router.get("/{listing_id}")
def get_listing(listing_id: int, db: Session = Depends(get_db)):
    L = db.get(models.Listing, listing_id)
    if not L:
        raise HTTPException(404, "Listing not found")
    L.views = (L.views or 0) + 1
    db.commit()
    seller = db.get(models.User, L.seller_id)
    return serialize_listing(L, seller)


@router.post("")
def create_listing(
    data: ListingIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if data.kind not in ("product", "service", "digital", "agent_skill"):
        raise HTTPException(400, "Invalid kind")
    if data.status not in ("active", "draft", "paused"):
        raise HTTPException(400, "Invalid status")
    images = list(data.images or [])
    primary = data.image_url or (images[0] if images else "")
    if primary and primary not in images:
        images = [primary] + images
    L = models.Listing(
        seller_id=user.id,
        category_id=data.category_id,
        title=data.title.strip(),
        description=data.description or "",
        kind=data.kind,
        price=data.price,
        currency=data.currency.upper()[:8],
        quantity=data.quantity,
        status=data.status,
        condition=data.condition,
        image_url=primary or "",
        images_json=json.dumps(images),
        tags=data.tags or "",
        location=data.location or user.location or "",
        shipping_info=data.shipping_info or "",
        sale_type=data.sale_type or "buy_now",
    )
    db.add(L)
    db.commit()
    db.refresh(L)
    return serialize_listing(L, user)


@router.patch("/{listing_id}")
def update_listing(
    listing_id: int,
    data: ListingUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    L = db.get(models.Listing, listing_id)
    if not L:
        raise HTTPException(404, "Listing not found")
    if L.seller_id != user.id and user.account_type != "admin":
        raise HTTPException(403, "Not your listing")
    payload = data.model_dump(exclude_unset=True)
    images = payload.pop("images", None)
    for field, val in payload.items():
        setattr(L, field, val)
    if images is not None:
        L.images_json = json.dumps(images)
        if images and not payload.get("image_url"):
            L.image_url = images[0]
    L.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(L)
    return serialize_listing(L, user)


@router.delete("/{listing_id}")
def delete_listing(
    listing_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    L = db.get(models.Listing, listing_id)
    if not L:
        raise HTTPException(404, "Listing not found")
    if L.seller_id != user.id and user.account_type != "admin":
        raise HTTPException(403, "Not your listing")
    L.status = "paused"
    db.commit()
    return {"ok": True, "status": "paused"}


@router.post("/{listing_id}/watch")
def watch_listing(
    listing_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    L = db.get(models.Listing, listing_id)
    if not L:
        raise HTTPException(404, "Listing not found")
    existing = (
        db.query(models.Watchlist)
        .filter_by(user_id=user.id, listing_id=listing_id)
        .first()
    )
    if existing:
        return {"watching": True}
    db.add(models.Watchlist(user_id=user.id, listing_id=listing_id))
    db.commit()
    return {"watching": True}


@router.delete("/{listing_id}/watch")
def unwatch_listing(
    listing_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = (
        db.query(models.Watchlist)
        .filter_by(user_id=user.id, listing_id=listing_id)
        .first()
    )
    if row:
        db.delete(row)
        db.commit()
    return {"watching": False}



