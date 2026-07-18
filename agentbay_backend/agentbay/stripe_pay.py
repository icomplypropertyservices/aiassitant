"""Stripe Checkout helpers for marketplace orders."""
from __future__ import annotations

from typing import Any

from . import config


def stripe_client():
    if not config.stripe_enabled():
        return None
    import stripe

    stripe.api_key = config.STRIPE_SECRET_KEY
    return stripe


def create_checkout_session(
    *,
    order_id: int,
    listing_title: str,
    amount_usd: float,
    quantity: int,
    buyer_email: str | None = None,
    success_path: str = "/orders?checkout=success",
    cancel_path: str = "/orders?checkout=cancelled",
) -> dict[str, Any]:
    stripe = stripe_client()
    if not stripe:
        raise RuntimeError("Stripe is not configured")

    unit_cents = max(50, int(round(amount_usd * 100)))  # Stripe min often 50 cents
    success = f"{config.PUBLIC_APP_URL}{success_path}&order_id={order_id}&session_id={{CHECKOUT_SESSION_ID}}"
    cancel = f"{config.PUBLIC_APP_URL}{cancel_path}&order_id={order_id}"

    session = stripe.checkout.Session.create(
        mode="payment",
        success_url=success,
        cancel_url=cancel,
        customer_email=buyer_email or None,
        line_items=[
            {
                "quantity": quantity,
                "price_data": {
                    "currency": config.STRIPE_CURRENCY,
                    "unit_amount": unit_cents,
                    "product_data": {
                        "name": listing_title[:120] or f"Order #{order_id}",
                        "description": f"AgentBay order #{order_id}",
                    },
                },
            }
        ],
        metadata={
            "order_id": str(order_id),
            "app": "agentbay",
        },
    )
    return {
        "session_id": session.id,
        "url": session.url,
        "payment_status": session.payment_status,
    }


def construct_webhook_event(payload: bytes, sig_header: str):
    stripe = stripe_client()
    if not stripe:
        raise RuntimeError("Stripe not configured")
    if not config.STRIPE_WEBHOOK_SECRET:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET not set")
    return stripe.Webhook.construct_event(
        payload, sig_header, config.STRIPE_WEBHOOK_SECRET
    )
