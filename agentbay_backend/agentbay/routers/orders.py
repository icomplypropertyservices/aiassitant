from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, config
from ..auth_utils import get_current_user, user_public
from ..order_fulfill import mark_order_paid, release_reservation, post_order_system_message
from ..stripe_pay import create_checkout_session, construct_webhook_event
from .. import payouts
from .listings import serialize_listing

router = APIRouter(tags=["orders"])


class BuyIn(BaseModel):
    quantity: int = Field(default=1, ge=1)
    shipping_address: str = ""
    notes: str = ""
    # stripe | crypto
    payment_method: str = "stripe"
    crypto_chain: str = ""  # eth | sol | btc | xrp when crypto


class OfferIn(BaseModel):
    amount: float = Field(gt=0)
    message: str = ""


class OrderStatusIn(BaseModel):
    status: str


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = ""


class PayoutProfileIn(BaseModel):
    preferred_method: str | None = "bank"
    bank_account_name: str | None = None
    bank_name: str | None = None
    bank_country: str | None = None
    bank_currency: str | None = None
    bank_iban: str | None = None
    bank_account_number: str | None = None
    bank_routing: str | None = None
    bank_sort_code: str | None = None
    bank_swift: str | None = None
    crypto_eth: str | None = None
    crypto_sol: str | None = None
    crypto_btc: str | None = None
    crypto_xrp: str | None = None
    crypto_xrp_tag: str | None = None
    notes: str | None = None


class CryptoConfirmIn(BaseModel):
    chain: str = Field(..., description="eth | sol | btc | xrp")
    tx_hash: str = Field(..., min_length=8)


class ReleasePayoutIn(BaseModel):
    reference: str = ""
    notes: str = ""
    force: bool = False


def serialize_order(o: models.Order, listing=None, buyer=None, seller=None, db: Session | None = None) -> dict:
    profile = None
    if db is not None:
        profile = db.query(models.SellerPayoutProfile).filter_by(user_id=o.seller_id).first()
    escrow = payouts.escrow_summary(o, profile)
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
        "payment_method": getattr(o, "payment_method", None) or "stripe",
        "crypto_chain": getattr(o, "crypto_chain", None) or "",
        "stripe_session_id": getattr(o, "stripe_session_id", None),
        "shipping_address": o.shipping_address or "",
        "notes": o.notes or "",
        "platform_fee": float(getattr(o, "platform_fee", None) or escrow.get("platform_fee") or 0),
        "seller_net": float(getattr(o, "seller_net", None) or escrow.get("seller_net") or 0),
        "payout_status": getattr(o, "payout_status", None) or "none",
        "escrow": escrow,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


def _crypto_receive(chain: str) -> str:
    chain = (chain or "").lower().strip()
    return {
        "eth": getattr(config, "CRYPTO_ETH_ADDRESS", "") or "",
        "sol": getattr(config, "CRYPTO_SOL_ADDRESS", "") or "",
        "btc": getattr(config, "CRYPTO_BTC_ADDRESS", "") or "",
        "xrp": getattr(config, "CRYPTO_XRP_ADDRESS", "") or "",
    }.get(chain, "")


@router.get("/payments/config")
def payments_config():
    crypto_chains = [
        c for c in ("eth", "sol", "btc", "xrp") if _crypto_receive(c)
    ]
    return {
        "stripe_enabled": config.stripe_enabled(),
        "crypto_enabled": bool(crypto_chains),
        "crypto_chains": crypto_chains,
        "demo_checkout": False,
        "currency": config.STRIPE_CURRENCY,
        "mode": "live" if config.stripe_live() else ("test" if config.stripe_enabled() else "disabled"),
        "env": config.APP_ENV,
        "platform_fee_percent": payouts.platform_fee_rate() * 100,
        "escrow": {
            "enabled": True,
            "release_rule": "Buyer must verify product completion; seller must have bank details (card sales) or crypto wallet (crypto sales). Platform fee deducted from seller payout.",
        },
    }


# ── Seller payout profile (bank + crypto) ──────────────────────────

@router.get("/seller/payout-profile")
def get_payout_profile(db: Session = Depends(get_db), user=Depends(get_current_user)):
    p = payouts.get_or_create_profile(db, user.id)
    db.commit()
    return {
        "profile": payouts.serialize_payout_profile(p, mask=False),
        "required_for_release": {
            "bank": "Required when buyers pay by card/Stripe — payout is bank transfer after verification.",
            "crypto": "Required when buyers pay by crypto — you receive crypto minus platform fee after verification.",
        },
        "platform_fee_percent": payouts.platform_fee_rate() * 100,
    }


@router.put("/seller/payout-profile")
def put_payout_profile(
    data: PayoutProfileIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    p = payouts.get_or_create_profile(db, user.id)
    fields = data.model_dump(exclude_unset=True)
    for k, v in fields.items():
        if v is None:
            continue
        if hasattr(p, k):
            setattr(p, k, str(v).strip() if isinstance(v, str) else v)
    p.updated_at = datetime.utcnow()
    # Unblock orders waiting on seller details
    waiting = (
        db.query(models.Order)
        .filter_by(seller_id=user.id, payout_status="awaiting_seller_details")
        .all()
    )
    for o in waiting:
        payouts.try_mark_ready_or_awaiting(o, p)
    db.commit()
    db.refresh(p)
    return {
        "ok": True,
        "profile": payouts.serialize_payout_profile(p, mask=False),
        "unblocked_orders": len(waiting),
    }


@router.post("/listings/{listing_id}/buy")
def buy_now(
    listing_id: int,
    data: BuyIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    method = (data.payment_method or "stripe").lower().strip()
    if method not in ("stripe", "crypto", "card"):
        raise HTTPException(400, "payment_method must be stripe or crypto")
    if method == "card":
        method = "stripe"

    L = db.get(models.Listing, listing_id)
    if not L or L.status != "active":
        raise HTTPException(404, "Listing not available")
    if L.seller_id == user.id:
        raise HTTPException(400, "Cannot buy your own listing")
    if L.quantity < data.quantity:
        raise HTTPException(400, f"Only {L.quantity} left in stock")

    total = round(L.price * data.quantity, 2)
    fees = payouts.compute_fees(total)
    chain = (data.crypto_chain or "").lower().strip()

    if method == "crypto":
        if chain not in ("eth", "sol", "btc", "xrp"):
            raise HTTPException(400, "crypto_chain must be eth, sol, btc, or xrp")
        if not _crypto_receive(chain):
            raise HTTPException(503, f"Crypto payouts for {chain.upper()} not configured on server")
    else:
        config.require_payments()

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
        payment_method=method,
        crypto_chain=chain if method == "crypto" else "",
        platform_fee=fees["platform_fee"],
        seller_net=fees["seller_net"],
        payout_status="none",
        reserved_qty=data.quantity,
        shipping_address=data.shipping_address or "",
        notes=data.notes or "",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    seller = db.get(models.User, L.seller_id)

    if method == "crypto":
        addr = _crypto_receive(chain)
        return {
            "order": serialize_order(order, serialize_listing(L, seller), user, seller, db),
            "payment_mode": "crypto",
            "crypto": {
                "chain": chain,
                "address": addr,
                "amount_usd": total,
                "instructions": (
                    f"Send crypto worth ${total:.2f} USD to the {chain.upper()} address, "
                    "then confirm with your tx hash. Funds stay in escrow until you verify completion; "
                    f"seller receives ${fees['seller_net']:.2f} after a {fees['fee_rate']*100:.0f}% platform fee."
                ),
            },
            "chat_room_slug": None,
            "escrow_note": "Seller is paid only after you verify the product is completed.",
        }

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
            "order": serialize_order(order, serialize_listing(L, seller), user, seller, db),
            "checkout_url": session["url"],
            "payment_mode": "stripe",
            "chat_room_slug": None,
            "escrow_note": (
                f"Payment is held in escrow. After you verify completion, seller is paid by bank transfer "
                f"(${fees['seller_net']:.2f} after {fees['fee_rate']*100:.0f}% fee). Seller must provide bank details."
            ),
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
            mark_order_paid(db, order, payment_method="stripe")

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
        out.append(serialize_order(o, listing, buyer, seller, db))
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
    if data.status == "completed":
        # Completing requires buyer verification of product — use confirm-complete
        raise HTTPException(
            400,
            "Use POST /orders/{id}/confirm-complete (buyer verifies product is done). "
            "Payout is released only after verification and seller payout details.",
        )
    if data.status == "cancelled" and o.payment_status != "paid":
        release_reservation(db, o)
        return serialize_order(o, db=db)
    o.status = data.status
    if data.status == "shipped":
        o.seller_delivered_at = datetime.utcnow()
        try:
            post_order_system_message(
                db, o, "Seller marked this order as delivered / shipped. Buyer should verify completion to release payout."
            )
        except Exception:
            pass
    o.updated_at = datetime.utcnow()
    db.commit()
    L = db.get(models.Listing, o.listing_id)
    seller = db.get(models.User, o.seller_id)
    buyer = db.get(models.User, o.buyer_id)
    return serialize_order(o, serialize_listing(L, seller) if L else None, buyer, seller, db)


@router.post("/orders/{order_id}/crypto/confirm")
def confirm_crypto_payment(
    order_id: int,
    data: CryptoConfirmIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Buyer submits tx hash after sending crypto. Marks paid + escrow held."""
    o = db.get(models.Order, order_id)
    if not o or o.buyer_id != user.id:
        raise HTTPException(404, "Order not found")
    if o.payment_status == "paid":
        return {"ok": True, "already_paid": True, "order": serialize_order(o, db=db)}
    chain = (data.chain or o.crypto_chain or "").lower().strip()
    if chain not in ("eth", "sol", "btc", "xrp"):
        raise HTTPException(400, "Invalid chain")
    if not _crypto_receive(chain):
        raise HTTPException(503, "Crypto not configured")
    tx = (data.tx_hash or "").strip()
    if len(tx) < 8:
        raise HTTPException(400, "tx_hash required")

    # Record chain + tx; operational verification can be enhanced with chain RPC later
    o.payment_method = "crypto"
    o.crypto_chain = chain
    o.crypto_tx_hash = tx
    mark_order_paid(db, o, payment_method="crypto", crypto_chain=chain, crypto_tx_hash=tx)
    db.refresh(o)
    L = db.get(models.Listing, o.listing_id)
    seller = db.get(models.User, o.seller_id)
    return {
        "ok": True,
        "order": serialize_order(o, serialize_listing(L, seller) if L else None, user, seller, db),
        "message": (
            "Payment recorded and held in escrow. After the product is completed, "
            "confirm completion so the seller can be paid in crypto (minus platform fee)."
        ),
    }


@router.post("/orders/{order_id}/confirm-complete")
def confirm_complete(
    order_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Buyer verifies the product/service is completed → unlocks seller payout."""
    o = db.get(models.Order, order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    if o.buyer_id != user.id and user.account_type != "admin":
        raise HTTPException(403, "Only the buyer can verify completion")
    if o.payment_status != "paid":
        raise HTTPException(400, "Order is not paid yet")
    if o.buyer_confirmed_at:
        profile = db.query(models.SellerPayoutProfile).filter_by(user_id=o.seller_id).first()
        return {
            "ok": True,
            "already_confirmed": True,
            "order": serialize_order(o, db=db),
            "escrow": payouts.escrow_summary(o, profile),
        }

    o.buyer_confirmed_at = datetime.utcnow()
    if o.status in ("paid", "shipped"):
        o.status = "completed"
    o.updated_at = datetime.utcnow()
    profile = db.query(models.SellerPayoutProfile).filter_by(user_id=o.seller_id).first()
    payouts.try_mark_ready_or_awaiting(o, profile)
    try:
        post_order_system_message(
            db,
            o,
            "Buyer verified product completion. "
            + (
                "Seller payout is ready for release."
                if o.payout_status == "ready"
                else "Waiting for seller to add bank/crypto payout details before release."
            ),
        )
    except Exception:
        pass
    db.commit()
    db.refresh(o)

    # Auto-release when seller details already on file
    released = None
    if o.payout_status == "ready":
        try:
            released = payouts.release_payout(db, o, actor=user, notes="Auto-release after buyer verification")
        except ValueError:
            released = None
            db.refresh(o)

    L = db.get(models.Listing, o.listing_id)
    seller = db.get(models.User, o.seller_id)
    return {
        "ok": True,
        "order": serialize_order(o, serialize_listing(L, seller) if L else None, user, seller, db),
        "auto_released": bool(released and released.get("ok")),
        "payout": released,
        "message": (
            "Thank you — completion verified. "
            + (
                "Seller payout released."
                if released and released.get("ok")
                else "Seller must add bank details (card sale) or crypto wallet (crypto sale) before funds are released."
            )
        ),
    }


@router.post("/orders/{order_id}/release-payout")
def release_order_payout(
    order_id: int,
    data: ReleasePayoutIn | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Release escrowed funds to seller (buyer after verify, seller when ready, or admin)."""
    data = data or ReleasePayoutIn()
    o = db.get(models.Order, order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    is_party = user.id in (o.buyer_id, o.seller_id)
    is_admin = user.account_type == "admin"
    if not is_party and not is_admin:
        raise HTTPException(403, "Not your order")
    if o.payment_status != "paid":
        raise HTTPException(400, "Order not paid")
    if not o.buyer_confirmed_at and not (data.force and is_admin):
        raise HTTPException(400, "Buyer must verify product completion first")

    try:
        result = payouts.release_payout(
            db,
            o,
            actor=user,
            reference=data.reference or "",
            notes=data.notes or "",
            force=bool(data.force and is_admin),
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    L = db.get(models.Listing, o.listing_id)
    seller = db.get(models.User, o.seller_id)
    buyer = db.get(models.User, o.buyer_id)
    return {
        **result,
        "order": serialize_order(o, serialize_listing(L, seller) if L else None, buyer, seller, db),
    }


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
