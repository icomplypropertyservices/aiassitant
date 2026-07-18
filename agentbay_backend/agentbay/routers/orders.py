from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, config
from ..auth_utils import get_current_user, user_public
from ..order_fulfill import mark_order_paid, release_reservation
from ..stripe_pay import create_checkout_session, construct_webhook_event
from .listings import serialize_listing

router = APIRouter(tags=["orders"])


class BuyIn(BaseModel):
    quantity: int = Field(default=1, ge=1)
    shipping_address: str = ""
    notes: str = ""


class OfferIn(BaseModel):
    amount: float = Field(gt=0)
    message: str = ""


class OrderStatusIn(BaseModel):
    status: str


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = ""


def serialize_order(o: models.Order, listing=None, buyer=None, seller=None) -> dict:
    return {
        "id": o.id,
        "listing_id": o.listing_id,
        "listing": listing,
        "buyer_id": o.buyer_id,
        "buyer": user_public(buyer) if buyer else None,
        "seller_id": o.seller_id,
        "seller": user_public(seller) if seller else None,
        "quantity": o.quantity,
        "unit_price": o.unit_price,
        "total": o.total,
        "currency": o.currency,
        "status": o.status,
        "payment_status": getattr(o, "payment_status", None) or "unpaid",
        "stripe_session_id": getattr(o, "stripe_session_id", None),
        "shipping_address": o.shipping_address or "",
        "notes": o.notes or "",
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


@router.get("/payments/config")
def payments_config():
    return {
        "stripe_enabled": config.stripe_enabled(),
        "demo_checkout": False,
        "currency": config.STRIPE_CURRENCY,
        "mode": "live" if config.stripe_live() else ("test" if config.stripe_enabled() else "disabled"),
        "env": config.APP_ENV,
    }


@router.post("/listings/{listing_id}/buy")
def buy_now(
    listing_id: int,
    data: BuyIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    config.require_payments()

    L = db.get(models.Listing, listing_id)
    if not L or L.status != "active":
        raise HTTPException(404, "Listing not available")
    if L.seller_id == user.id:
        raise HTTPException(400, "Cannot buy your own listing")
    if L.quantity < data.quantity:
        raise HTTPException(400, f"Only {L.quantity} left in stock")

    total = round(L.price * data.quantity, 2)

    # Reserve stock immediately
    L.quantity -= data.quantity
    if L.quantity <= 0:
        L.status = "sold"
        L.quantity = 0
    L.updated_at = datetime.utcnow()

    order = models.Order(
        listing_id=L.id,
        buyer_id=user.id,
        seller_id=L.seller_id,
        quantity=data.quantity,
        unit_price=L.price,
        total=total,
        currency=L.currency,
        status="pending",
        payment_status="pending_checkout",
        reserved_qty=data.quantity,
        shipping_address=data.shipping_address or "",
        notes=data.notes or "",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    seller = db.get(models.User, L.seller_id)

    try:
        session = create_checkout_session(
            order_id=order.id,
            listing_title=L.title,
            amount_usd=L.price,
            quantity=data.quantity,
            buyer_email=user.email,
        )
        order.stripe_session_id = session["session_id"]
        db.commit()
        return {
            "order": serialize_order(order, serialize_listing(L, seller), user, seller),
            "checkout_url": session["url"],
            "payment_mode": "stripe",
            "chat_room_slug": None,
        }
    except Exception as e:
        release_reservation(db, order)
        raise HTTPException(502, f"Stripe checkout failed: {e}")


@router.post("/orders/{order_id}/checkout")
def retry_checkout(
    order_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    config.require_payments()
    order = db.get(models.Order, order_id)
    if not order or order.buyer_id != user.id:
        raise HTTPException(404, "Order not found")
    if order.payment_status == "paid":
        raise HTTPException(400, "Already paid")

    L = db.get(models.Listing, order.listing_id)
    try:
        session = create_checkout_session(
            order_id=order.id,
            listing_title=L.title if L else f"Order {order.id}",
            amount_usd=order.unit_price,
            quantity=order.quantity,
            buyer_email=user.email,
        )
        order.stripe_session_id = session["session_id"]
        order.payment_status = "pending_checkout"
        order.status = "pending"
        db.commit()
        return {
            "payment_mode": "stripe",
            "checkout_url": session["url"],
            "session_id": session["session_id"],
        }
    except Exception as e:
        raise HTTPException(502, f"Stripe checkout failed: {e}")


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
    stripe_signature: str | None = Header(None, alias="Stripe-Signature"),
):
    payload = await request.body()
    if not config.stripe_enabled():
        raise HTTPException(400, "Stripe not configured")
    if not config.STRIPE_WEBHOOK_SECRET or not stripe_signature:
        raise HTTPException(400, "Webhook signature required")
    try:
        event = construct_webhook_event(payload, stripe_signature)
    except Exception as e:
        raise HTTPException(400, f"Webhook error: {e}")

    etype = event["type"] if not isinstance(event, dict) else event.get("type")
    data_obj = (
        event["data"]["object"]
        if not isinstance(event, dict)
        else event.get("data", {}).get("object", {})
    )
    # stripe Event object supports dict-like access
    if not isinstance(data_obj, dict):
        data_obj = dict(data_obj)

    if etype in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        meta = data_obj.get("metadata") or {}
        order_id = meta.get("order_id")
        session_id = data_obj.get("id")
        order = None
        if order_id:
            order = db.get(models.Order, int(order_id))
        if not order and session_id:
            order = (
                db.query(models.Order)
                .filter_by(stripe_session_id=session_id)
                .first()
            )
        if order:
            if not order.stripe_session_id and session_id:
                order.stripe_session_id = session_id
            mark_order_paid(db, order)

    elif etype in ("checkout.session.expired", "checkout.session.async_payment_failed"):
        meta = data_obj.get("metadata") or {}
        order_id = meta.get("order_id")
        if order_id:
            order = db.get(models.Order, int(order_id))
            if order and order.payment_status != "paid":
                release_reservation(db, order)

    return {"received": True}


@router.post("/listings/{listing_id}/offers")
def make_offer(
    listing_id: int,
    data: OfferIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    L = db.get(models.Listing, listing_id)
    if not L or L.status != "active":
        raise HTTPException(404, "Listing not available")
    if L.seller_id == user.id:
        raise HTTPException(400, "Cannot offer on your own listing")
    offer = models.Offer(
        listing_id=L.id,
        buyer_id=user.id,
        amount=data.amount,
        message=data.message or "",
        status="pending",
    )
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return {
        "id": offer.id,
        "listing_id": offer.listing_id,
        "amount": offer.amount,
        "message": offer.message,
        "status": offer.status,
        "created_at": offer.created_at.isoformat() if offer.created_at else None,
    }


@router.post("/offers/{offer_id}/accept")
def accept_offer(
    offer_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    offer = db.get(models.Offer, offer_id)
    if not offer or offer.status != "pending":
        raise HTTPException(404, "Offer not found")
    L = db.get(models.Listing, offer.listing_id)
    if not L or L.seller_id != user.id:
        raise HTTPException(403, "Only the seller can accept")
    if L.quantity < 1:
        raise HTTPException(400, "Out of stock")

    config.require_payments()
    offer.status = "accepted"
    L.quantity -= 1
    if L.quantity <= 0:
        L.status = "sold"
    order = models.Order(
        listing_id=L.id,
        buyer_id=offer.buyer_id,
        seller_id=L.seller_id,
        quantity=1,
        unit_price=offer.amount,
        total=offer.amount,
        currency=L.currency,
        status="pending",
        payment_status="pending_checkout",
        reserved_qty=1,
        notes=f"Accepted offer #{offer.id}",
    )
    db.add(order)
    for o in (
        db.query(models.Offer)
        .filter_by(listing_id=L.id, status="pending")
        .filter(models.Offer.id != offer.id)
        .all()
    ):
        o.status = "rejected"
    db.commit()
    db.refresh(order)

    buyer = db.get(models.User, offer.buyer_id)
    try:
        session = create_checkout_session(
            order_id=order.id,
            listing_title=L.title,
            amount_usd=offer.amount,
            quantity=1,
            buyer_email=buyer.email if buyer else None,
        )
        order.stripe_session_id = session["session_id"]
        db.commit()
        checkout_url = session["url"]
    except Exception as e:
        release_reservation(db, order)
        raise HTTPException(502, f"Stripe checkout failed: {e}")

    return {**serialize_order(order), "checkout_url": checkout_url}


@router.post("/offers/{offer_id}/reject")
def reject_offer(
    offer_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    offer = db.get(models.Offer, offer_id)
    if not offer:
        raise HTTPException(404, "Offer not found")
    L = db.get(models.Listing, offer.listing_id)
    if not L or L.seller_id != user.id:
        raise HTTPException(403, "Only the seller can reject")
    offer.status = "rejected"
    db.commit()
    return {"ok": True, "status": "rejected"}


@router.get("/orders")
def my_orders(
    role: str = "all",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(models.Order)
    if role == "buyer":
        q = q.filter_by(buyer_id=user.id)
    elif role == "seller":
        q = q.filter_by(seller_id=user.id)
    else:
        q = q.filter(
            (models.Order.buyer_id == user.id) | (models.Order.seller_id == user.id)
        )
    rows = q.order_by(models.Order.id.desc()).limit(100).all()
    out = []
    for o in rows:
        L = db.get(models.Listing, o.listing_id)
        seller = db.get(models.User, o.seller_id)
        buyer = db.get(models.User, o.buyer_id)
        listing = serialize_listing(L, seller) if L else None
        out.append(serialize_order(o, listing, buyer, seller))
    return {"items": out}


@router.patch("/orders/{order_id}")
def update_order_status(
    order_id: int,
    data: OrderStatusIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    allowed = {"pending", "paid", "shipped", "completed", "cancelled", "disputed"}
    if data.status not in allowed:
        raise HTTPException(400, f"status must be one of {allowed}")
    o = db.get(models.Order, order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    if user.id not in (o.buyer_id, o.seller_id) and user.account_type != "admin":
        raise HTTPException(403, "Not your order")
    if data.status == "shipped" and o.seller_id != user.id:
        raise HTTPException(403, "Only seller can mark shipped")
    if data.status == "cancelled" and o.payment_status != "paid":
        release_reservation(db, o)
        return serialize_order(o)
    o.status = data.status
    o.updated_at = datetime.utcnow()
    db.commit()
    return serialize_order(o)


@router.post("/orders/{order_id}/review")
def leave_review(
    order_id: int,
    data: ReviewIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    o = db.get(models.Order, order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    if o.buyer_id != user.id:
        raise HTTPException(403, "Only the buyer can review")
    if o.status not in ("completed", "shipped", "paid") or o.payment_status != "paid":
        raise HTTPException(400, "Order not ready for review")
    if db.query(models.Review).filter_by(order_id=order_id).first():
        raise HTTPException(400, "Already reviewed")

    rev = models.Review(
        order_id=order_id,
        reviewer_id=user.id,
        reviewee_id=o.seller_id,
        rating=data.rating,
        comment=data.comment or "",
    )
    db.add(rev)
    seller = db.get(models.User, o.seller_id)
    if seller:
        n = seller.rating_count or 0
        avg = seller.rating_avg or 0.0
        seller.rating_avg = round(((avg * n) + data.rating) / (n + 1), 2)
        seller.rating_count = n + 1
    db.commit()
    db.refresh(rev)
    return {
        "id": rev.id,
        "rating": rev.rating,
        "comment": rev.comment,
        "reviewee_id": rev.reviewee_id,
    }
