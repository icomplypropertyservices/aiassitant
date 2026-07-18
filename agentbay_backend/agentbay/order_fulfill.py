"""Shared order fulfillment after Stripe payment."""
from datetime import datetime
from sqlalchemy.orm import Session

from . import models


def ensure_order_chat(db: Session, order: models.Order, listing: models.Listing, buyer: models.User):
    slug = f"order-{order.id}"
    room = db.query(models.ChatRoom).filter_by(slug=slug).first()
    if room:
        return slug
    room = models.ChatRoom(
        slug=slug,
        name=f"Order #{order.id}: {listing.title[:40]}",
        description="Private buyer–seller chat for this order",
        room_type="listing",
        post_policy="members",
        created_by=buyer.id,
        listing_id=listing.id,
    )
    db.add(room)
    db.flush()
    for uid in (order.buyer_id, order.seller_id):
        if not db.query(models.RoomMember).filter_by(room_id=room.id, user_id=uid).first():
            db.add(models.RoomMember(room_id=room.id, user_id=uid, role="member"))
    db.add(
        models.ChatMessage(
            room_id=room.id,
            sender_id=buyer.id,
            content=(
                f"Order #{order.id} paid for {order.quantity}× {listing.title} "
                f"(${order.total})."
            ),
            msg_type="system",
        )
    )
    return slug


def mark_order_paid(db: Session, order: models.Order) -> str | None:
    """Finalize stock + chat when payment succeeds. Returns chat room slug."""
    listing = db.get(models.Listing, order.listing_id)
    buyer = db.get(models.User, order.buyer_id)
    if not listing or not buyer:
        return None

    already_paid = order.payment_status == "paid" and order.status in (
        "paid",
        "shipped",
        "completed",
    )
    if already_paid:
        return ensure_order_chat(db, order, listing, buyer)

    # Stock: if reserved_qty set, inventory was already decremented at order create
    if not order.reserved_qty:
        if listing.quantity < order.quantity:
            order.payment_status = "failed"
            order.status = "cancelled"
            order.updated_at = datetime.utcnow()
            db.commit()
            return None
        listing.quantity -= order.quantity
        if listing.quantity <= 0:
            listing.status = "sold"
            listing.quantity = 0
        listing.updated_at = datetime.utcnow()
        order.reserved_qty = order.quantity

    order.payment_status = "paid"
    order.status = "paid"
    order.updated_at = datetime.utcnow()
    slug = ensure_order_chat(db, order, listing, buyer)
    db.commit()
    return slug


def release_reservation(db: Session, order: models.Order):
    """Cancel unpaid order and restore stock if reserved."""
    if order.payment_status == "paid":
        return
    listing = db.get(models.Listing, order.listing_id)
    if listing and order.reserved_qty:
        listing.quantity += order.reserved_qty
        if listing.status == "sold" and listing.quantity > 0:
            listing.status = "active"
        listing.updated_at = datetime.utcnow()
    order.reserved_qty = 0
    order.status = "cancelled"
    order.payment_status = "failed"
    order.updated_at = datetime.utcnow()
    db.commit()
