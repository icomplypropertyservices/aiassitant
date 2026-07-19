"""AgentBay seller payouts / escrow.

Flow
----
1. Buyer pays (Stripe card or crypto) → funds held in escrow (payout_status=held).
2. Seller delivers / marks shipped.
3. Buyer verifies product is completed (confirm-complete).
4. Platform releases payout to seller ONLY after verification:
   - Card/bank payment → bank transfer (seller must have bank details).
   - Crypto payment → crypto payout to seller wallet, minus platform fee.

Sellers must provide payout details before release can complete.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models, config


# Order lifecycle for escrow:
# status: pending → paid → shipped → completed
# payout_status: none | held | awaiting_seller_details | ready | released | failed


def platform_fee_rate() -> float:
    try:
        return max(0.0, min(0.5, float(getattr(config, "PLATFORM_FEE_PERCENT", 10) or 10) / 100.0))
    except Exception:
        return 0.10


def compute_fees(total: float) -> dict[str, float]:
    total = round(float(total or 0), 2)
    rate = platform_fee_rate()
    fee = round(total * rate, 2)
    net = round(max(0.0, total - fee), 2)
    return {
        "gross": total,
        "fee_rate": rate,
        "platform_fee": fee,
        "seller_net": net,
    }


def serialize_payout_profile(p: models.SellerPayoutProfile | None, *, mask: bool = True) -> dict | None:
    if not p:
        return None

    def _mask(s: str, keep: int = 4) -> str:
        s = (s or "").strip()
        if not s or not mask:
            return s
        if len(s) <= keep:
            return "•" * len(s)
        return ("•" * max(0, len(s) - keep)) + s[-keep:]

    bank_ok = bool(
        (p.bank_account_name or "").strip()
        and (p.bank_name or "").strip()
        and (p.bank_account_number or p.bank_iban or "").strip()
    )
    crypto_ok = bool(
        (p.crypto_eth or "").strip()
        or (p.crypto_sol or "").strip()
        or (p.crypto_btc or "").strip()
        or (p.crypto_xrp or "").strip()
    )
    return {
        "id": p.id,
        "user_id": p.user_id,
        "preferred_method": p.preferred_method or "bank",
        "bank_account_name": p.bank_account_name or "",
        "bank_name": p.bank_name or "",
        "bank_country": p.bank_country or "",
        "bank_currency": p.bank_currency or "USD",
        "bank_iban": _mask(p.bank_iban or "", 6) if mask else (p.bank_iban or ""),
        "bank_account_number": _mask(p.bank_account_number or "", 4) if mask else (p.bank_account_number or ""),
        "bank_routing": _mask(p.bank_routing or "", 4) if mask else (p.bank_routing or ""),
        "bank_sort_code": _mask(p.bank_sort_code or "", 4) if mask else (p.bank_sort_code or ""),
        "bank_swift": _mask(p.bank_swift or "", 4) if mask else (p.bank_swift or ""),
        "crypto_eth": _mask(p.crypto_eth or "", 6) if mask else (p.crypto_eth or ""),
        "crypto_sol": _mask(p.crypto_sol or "", 6) if mask else (p.crypto_sol or ""),
        "crypto_btc": _mask(p.crypto_btc or "", 6) if mask else (p.crypto_btc or ""),
        "crypto_xrp": _mask(p.crypto_xrp or "", 6) if mask else (p.crypto_xrp or ""),
        "crypto_xrp_tag": p.crypto_xrp_tag or "",
        "notes": p.notes or "",
        "bank_ready": bank_ok,
        "crypto_ready": crypto_ok,
        "ready_for_bank": bank_ok,
        "ready_for_crypto": crypto_ok,
        "updated_at": p.updated_at.isoformat() + "Z" if p.updated_at else None,
    }


def get_or_create_profile(db: Session, user_id: int) -> models.SellerPayoutProfile:
    row = db.query(models.SellerPayoutProfile).filter_by(user_id=user_id).first()
    if row:
        return row
    row = models.SellerPayoutProfile(user_id=user_id)
    db.add(row)
    db.flush()
    return row


def profile_ready_for_method(p: models.SellerPayoutProfile | None, method: str) -> tuple[bool, str]:
    if not p:
        return False, "Seller has not added payout details"
    method = (method or "bank").lower()
    if method in ("bank", "stripe", "card", "transfer"):
        if not (p.bank_account_name or "").strip():
            return False, "Bank account name required"
        if not (p.bank_name or "").strip():
            return False, "Bank name required"
        if not (p.bank_account_number or p.bank_iban or "").strip():
            return False, "Bank account number or IBAN required"
        return True, "ok"
    if method in ("crypto", "eth", "sol", "btc", "xrp"):
        chain = method if method in ("eth", "sol", "btc", "xrp") else ""
        # Prefer preferred chain from order later; any wallet = ready for crypto
        has = any(
            (getattr(p, f"crypto_{c}", None) or "").strip()
            for c in ("eth", "sol", "btc", "xrp")
        )
        if chain:
            has = bool((getattr(p, f"crypto_{chain}", None) or "").strip())
            if not has:
                return False, f"Seller crypto address for {chain.upper()} is required"
        if not has:
            return False, "Seller crypto wallet address required"
        return True, "ok"
    return False, f"Unknown payout method: {method}"


def apply_escrow_on_paid(order: models.Order, *, payment_method: str = "stripe", crypto_chain: str = "") -> None:
    """Call when buyer payment succeeds — hold funds for seller until verification."""
    fees = compute_fees(order.total)
    order.payment_method = (payment_method or "stripe").lower()
    if crypto_chain:
        order.crypto_chain = crypto_chain.lower()
    order.platform_fee = fees["platform_fee"]
    order.seller_net = fees["seller_net"]
    order.payout_status = "held"
    order.escrow_held_at = datetime.utcnow()
    order.updated_at = datetime.utcnow()


def escrow_summary(order: models.Order, profile: models.SellerPayoutProfile | None = None) -> dict[str, Any]:
    fees = {
        "gross": float(order.total or 0),
        "platform_fee": float(getattr(order, "platform_fee", None) or 0),
        "seller_net": float(getattr(order, "seller_net", None) or 0),
        "fee_rate": platform_fee_rate(),
    }
    if not fees["seller_net"] and fees["gross"]:
        fees = compute_fees(fees["gross"])

    method = (getattr(order, "payment_method", None) or "stripe").lower()
    payout_via = "crypto" if method == "crypto" else "bank"
    ready, reason = profile_ready_for_method(
        profile,
        order.crypto_chain if payout_via == "crypto" and getattr(order, "crypto_chain", None) else payout_via,
    )
    verified = bool(getattr(order, "buyer_confirmed_at", None))
    return {
        "payment_method": method,
        "crypto_chain": getattr(order, "crypto_chain", None) or "",
        "payout_via": payout_via,
        "payout_status": getattr(order, "payout_status", None) or "none",
        "platform_fee": fees["platform_fee"],
        "seller_net": fees["seller_net"],
        "fee_percent": round(platform_fee_rate() * 100, 2),
        "buyer_confirmed": verified,
        "buyer_confirmed_at": (
            order.buyer_confirmed_at.isoformat() + "Z"
            if getattr(order, "buyer_confirmed_at", None)
            else None
        ),
        "seller_delivered": bool(getattr(order, "seller_delivered_at", None)),
        "payout_released_at": (
            order.payout_released_at.isoformat() + "Z"
            if getattr(order, "payout_released_at", None)
            else None
        ),
        "payout_reference": getattr(order, "payout_reference", None) or "",
        "seller_payout_ready": ready,
        "seller_payout_blocker": None if ready else reason,
        "can_release": bool(
            verified
            and order.payment_status == "paid"
            and (getattr(order, "payout_status", None) or "") in ("held", "awaiting_seller_details", "ready", "failed")
            and ready
        ),
        "release_hint": _release_hint(order, verified, ready, reason, payout_via),
    }


def _release_hint(order, verified: bool, ready: bool, reason: str, payout_via: str) -> str:
    if getattr(order, "payout_status", None) == "released":
        return "Payout already released to seller."
    if order.payment_status != "paid":
        return "Waiting for buyer payment."
    if not verified:
        return "Waiting for buyer to verify the product is completed."
    if not ready:
        return f"Seller must add payout details: {reason}"
    if payout_via == "crypto":
        return "Ready for crypto payout (order total minus platform fee)."
    return "Ready for bank transfer payout to seller."


def try_mark_ready_or_awaiting(order: models.Order, profile: models.SellerPayoutProfile | None) -> None:
    """After buyer verifies, set payout_status to ready or awaiting_seller_details."""
    if getattr(order, "payout_status", None) == "released":
        return
    if not getattr(order, "buyer_confirmed_at", None):
        return
    method = (getattr(order, "payment_method", None) or "stripe").lower()
    payout_via = "crypto" if method == "crypto" else "bank"
    chain = (getattr(order, "crypto_chain", None) or "").lower()
    check = chain if payout_via == "crypto" and chain else payout_via
    ready, _ = profile_ready_for_method(profile, check)
    order.payout_status = "ready" if ready else "awaiting_seller_details"
    order.updated_at = datetime.utcnow()


def release_payout(
    db: Session,
    order: models.Order,
    *,
    actor: models.User,
    reference: str = "",
    notes: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Release escrowed funds to seller after verification.

    Marks payout released and records method. Actual bank/crypto rails are
    operational (recorded for admin ops); no private keys are used here.
    """
    if order.payment_status != "paid":
        raise ValueError("Order is not paid")
    if getattr(order, "payout_status", None) == "released":
        return {"ok": True, "already_released": True, "payout": escrow_summary(order)}

    if not getattr(order, "buyer_confirmed_at", None) and not force:
        raise ValueError("Buyer has not verified product completion yet")

    profile = db.query(models.SellerPayoutProfile).filter_by(user_id=order.seller_id).first()
    method = (getattr(order, "payment_method", None) or "stripe").lower()
    payout_via = "crypto" if method == "crypto" else "bank"
    chain = (getattr(order, "crypto_chain", None) or "").lower()
    check = chain if payout_via == "crypto" and chain else payout_via
    ready, reason = profile_ready_for_method(profile, check)
    if not ready and not force:
        order.payout_status = "awaiting_seller_details"
        order.updated_at = datetime.utcnow()
        db.commit()
        raise ValueError(reason)

    fees = compute_fees(order.total)
    order.platform_fee = fees["platform_fee"]
    order.seller_net = fees["seller_net"]
    order.payout_status = "released"
    order.payout_method = payout_via
    order.payout_reference = (reference or "").strip()[:120] or f"auto-{order.id}-{int(datetime.utcnow().timestamp())}"
    order.payout_notes = (notes or "").strip()[:500]
    order.payout_released_at = datetime.utcnow()
    order.payout_released_by = actor.id
    if order.status not in ("completed", "cancelled", "disputed"):
        order.status = "completed"
    order.updated_at = datetime.utcnow()

    # Destination snapshot (masked in API later)
    dest = {}
    if profile and payout_via == "bank":
        dest = {
            "type": "bank",
            "account_name": profile.bank_account_name,
            "bank_name": profile.bank_name,
            "iban_or_account": profile.bank_iban or profile.bank_account_number,
            "currency": profile.bank_currency or order.currency,
        }
    elif profile and payout_via == "crypto":
        c = chain or "eth"
        addr = getattr(profile, f"crypto_{c}", None) or profile.crypto_eth or profile.crypto_sol or profile.crypto_btc or profile.crypto_xrp
        dest = {
            "type": "crypto",
            "chain": c,
            "address": addr,
            "amount_usd": fees["seller_net"],
            "fee_usd": fees["platform_fee"],
            "note": "Seller receives gross minus platform fee in crypto",
        }
    order.payout_destination_json = __import__("json").dumps(dest)

    # System chat note
    try:
        from .order_fulfill import post_order_system_message
        post_order_system_message(
            db,
            order,
            (
                f"Payout released to seller via {payout_via}. "
                f"Net ${fees['seller_net']:.2f} (fee ${fees['platform_fee']:.2f}). "
                f"Ref: {order.payout_reference}"
            ),
        )
    except Exception:
        pass

    db.commit()
    return {
        "ok": True,
        "payout_status": "released",
        "payout_via": payout_via,
        "platform_fee": fees["platform_fee"],
        "seller_net": fees["seller_net"],
        "reference": order.payout_reference,
        "destination": dest,
    }
