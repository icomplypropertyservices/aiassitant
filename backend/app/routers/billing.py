from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..database import get_db, SessionLocal
from .. import models, config
from ..auth_utils import get_current_user, user_from_ws_token
from ..ws import manager
from ..pricing import MODEL_LABELS, PRICING, format_token_count
from ..plans import PLANS, public_plans, plan_limits
from ..usage_billing import meter_snapshot, ensure_period
from .. import crypto_payments as crypto_pay

router = APIRouter(prefix="/billing", tags=["billing"])

PLAN_PRICE_IDS = {
    "starter": config.STRIPE_PRICE_STARTER,
    "pro": config.STRIPE_PRICE_PRO,
    "business": config.STRIPE_PRICE_BUSINESS,
}


def _stripe():
    if not config.STRIPE_SECRET_KEY:
        return None
    import stripe
    stripe.api_key = config.STRIPE_SECRET_KEY
    return stripe


def _stripe_mode() -> str | None:
    """Return 'test' | 'live' | None from secret key prefix."""
    key = (config.STRIPE_SECRET_KEY or "").strip()
    if not key:
        return None
    if key.startswith("sk_test"):
        return "test"
    if key.startswith("sk_live"):
        return "live"
    return "unknown"


def _stripe_ready() -> bool:
    return bool(config.STRIPE_SECRET_KEY)


def _plan_line_item(plan: str, limits: dict) -> dict:
    """Prefer configured Price ID; otherwise inline price_data (sandbox-friendly)."""
    price_id = (PLAN_PRICE_IDS.get(plan) or "").strip()
    if price_id:
        return {"price": price_id, "quantity": 1}
    amount = float(limits.get("price") or 0)
    if amount <= 0:
        raise HTTPException(400, "Plan has no price for Stripe checkout")
    name = limits.get("name") or plan.title()
    return {
        "price_data": {
            "currency": "usd",
            "product_data": {
                "name": f"AI Business Assistant — {name}",
                "description": limits.get("blurb") or f"{name} monthly subscription",
            },
            "unit_amount": int(round(amount * 100)),
            "recurring": {"interval": "month"},
        },
        "quantity": 1,
    }


def _checkout_urls(path_success: str = "/billing", path_cancel: str = "/billing"):
    base = (config.FRONTEND_URL or "").rstrip("/") or "http://localhost:5173"
    # {CHECKOUT_SESSION_ID} is expanded by Stripe — enables confirm without webhook
    success = f"{base}{path_success}?checkout=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel = f"{base}{path_cancel}?checkout=cancelled"
    return success, cancel


def _session_as_dict(session) -> dict:
    if isinstance(session, dict):
        return session
    if hasattr(session, "to_dict"):
        return session.to_dict()
    try:
        return dict(session)
    except Exception:
        return {
            "id": getattr(session, "id", None),
            "status": getattr(session, "status", None),
            "payment_status": getattr(session, "payment_status", None),
            "amount_total": getattr(session, "amount_total", None),
            "metadata": dict(getattr(session, "metadata", None) or {}),
        }


def _fulfill_stripe_session(db: Session, session) -> dict:
    """Apply top-up or plan from a completed Stripe Checkout session. Idempotent."""
    session = _session_as_dict(session)
    meta = session.get("metadata") or {}
    if hasattr(meta, "to_dict"):
        meta = meta.to_dict()
    meta = dict(meta or {})
    user_id = int(meta.get("user_id", 0) or 0)
    if not user_id:
        raise HTTPException(400, "Session missing user_id metadata")
    kind = meta.get("kind") or ""
    payment_status = session.get("payment_status") or ""
    status = session.get("status") or ""
    session_id = session.get("id") or ""
    if not session_id:
        raise HTTPException(400, "Session missing id")

    prior = db.query(models.StripeCheckout).filter_by(session_id=session_id).first()
    if prior:
        return {
            "kind": prior.kind,
            "plan": prior.plan or None,
            "amount": prior.amount_usd,
            "user_id": prior.user_id,
            "already_fulfilled": True,
        }

    ok = payment_status in ("paid", "no_payment_required") or status == "complete"
    if not ok:
        raise HTTPException(
            400,
            f"Checkout not paid yet (status={status}, payment={payment_status})",
        )

    amount = 0.0
    plan = ""
    if kind == "topup":
        amount = float(meta.get("amount", 0) or 0)
        if amount <= 0:
            amount = float(session.get("amount_total") or 0) / 100.0
        bal = db.query(models.Balance).filter_by(user_id=user_id).first()
        if not bal:
            bal = models.Balance(user_id=user_id, credits=0.0)
            db.add(bal)
            db.flush()
        bal.credits = float(bal.credits or 0) + amount
        db.flush()
    elif kind == "plan":
        u = db.get(models.User, user_id)
        if not u:
            raise HTTPException(404, "User not found")
        plan = meta.get("plan") or "starter"
        _activate_plan(db, u, plan, meta.get("company_name") or None)
        u = db.get(models.User, user_id)
        if u and hasattr(u, "subscription_expires_at"):
            u.subscription_expires_at = None
            db.flush()
        amount = float(session.get("amount_total") or 0) / 100.0
    else:
        raise HTTPException(400, f"Unknown checkout kind: {kind}")

    db.add(
        models.StripeCheckout(
            session_id=session_id,
            user_id=user_id,
            kind=kind,
            plan=plan,
            amount_usd=amount,
            mode=_stripe_mode() or "",
        )
    )
    db.commit()
    return {"kind": kind, "plan": plan or None, "amount": amount, "user_id": user_id}


class TopupIn(BaseModel):
    amount: float


class PlanIn(BaseModel):
    plan: str
    company_name: str | None = None  # optional: create first company on subscribe


class CryptoInvoiceIn(BaseModel):
    chain: str = Field(..., description="eth | sol | xrp")
    kind: str = Field("plan", description="plan | topup")
    plan: str | None = None
    company_name: str | None = None
    amount: float | None = Field(None, description="USD amount for topup")


class CryptoVerifyIn(BaseModel):
    tx_hash: str | None = None
    public_id: str | None = None


@router.get("/plans")
def plans():
    """Public — shown on login / subscribe without auth."""
    return public_plans()


@router.get("/rates")
def rates():
    """Public token rates ($ / 1M tokens) for transparency."""
    return {
        "currency": "usd",
        "unit": "per_1m_tokens",
        "rates": [
            {"id": k, "label": MODEL_LABELS.get(k, k), "usd_per_1m": v}
            for k, v in PRICING.items()
        ],
    }


@router.get("/meter")
def meter(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Clear customer-facing token + credit meter."""
    snap = meter_snapshot(db, user)
    snap["tokens_included_label"] = format_token_count(snap["tokens_included"])
    snap["tokens_used_label"] = format_token_count(snap["tokens_used_period"])
    snap["tokens_remaining_label"] = format_token_count(snap["tokens_remaining_included"])
    return snap


@router.get("/payment-options")
def payment_options():
    """Public-ish status: card (Stripe sandbox/live) + crypto availability."""
    mode = _stripe_mode()
    return {
        "stripe": {
            "enabled": _stripe_ready(),
            "mode": mode,  # test | live | unknown | null
            "sandbox": mode == "test",
            "webhook_configured": bool(config.STRIPE_WEBHOOK_SECRET),
            "price_ids": {
                "starter": bool(config.STRIPE_PRICE_STARTER),
                "pro": bool(config.STRIPE_PRICE_PRO),
                "business": bool(config.STRIPE_PRICE_BUSINESS),
            },
            # Works with secret key alone via price_data when price IDs missing
            "ready": _stripe_ready(),
            "label": (
                "Card (Stripe test / sandbox)"
                if mode == "test"
                else ("Card (Stripe live)" if mode == "live" else "Card (Stripe)")
            ),
            "test_card_hint": (
                "Use card 4242 4242 4242 4242, any future expiry, any CVC, any ZIP."
                if mode == "test"
                else None
            ),
        },
        "crypto": {
            "enabled": crypto_pay.crypto_enabled(),
            "chains": [c["id"] for c in crypto_pay.available_chains()],
            "label": "Crypto (ETH / SOL / XRP)",
        },
    }


@router.post("/topup")
def topup(data: TopupIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if data.amount < 1 or data.amount > 1000:
        raise HTTPException(400, "Top-up must be between $1 and $1000")
    stripe = _stripe()
    if stripe:
        success, cancel = _checkout_urls("/billing", "/billing")
        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": "AI Business Assistant credit top-up"},
                        "unit_amount": int(round(data.amount * 100)),
                    },
                    "quantity": 1,
                }],
                success_url=success,
                cancel_url=cancel,
                customer_email=user.email,
                metadata={"kind": "topup", "user_id": str(user.id), "amount": str(data.amount)},
            )
        except Exception as e:
            raise HTTPException(502, f"Stripe Checkout error: {e}") from e
        return {
            "checkout_url": session.url,
            "session_id": session.id,
            "provider": "stripe",
            "stripe_mode": _stripe_mode(),
        }
    # Production never grants free credits without Stripe (crypto is separate endpoint)
    if config.IS_PRODUCTION:
        raise HTTPException(
            503,
            "Stripe is not configured. Set STRIPE_SECRET_KEY (use sk_test_… for sandbox) "
            "or top up with crypto.",
        )
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal:
        bal = models.Balance(user_id=user.id, credits=0.0)
        db.add(bal)
    bal.credits += data.amount
    db.commit()
    return {"credits": round(bal.credits, 4), "dev_mode": True}


def _activate_plan(db: Session, user: models.User, plan: str, company_name: str | None = None):
    if plan not in PLANS or plan == "none":
        raise HTTPException(400, "Unknown plan")
    limits = plan_limits(plan)
    u = db.get(models.User, user.id)
    u.plan = plan
    u.subscription_active = True
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal:
        bal = models.Balance(user_id=user.id, credits=0.0)
        db.add(bal)
        db.flush()
    bal.tokens_included = int(limits.get("tokens_included") or 0)
    bal.tokens_used_period = 0
    bal.period_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Welcome credits for paid / trial
    if plan == "trial" and (bal.credits or 0) < 2:
        bal.credits = max(bal.credits or 0, 2.0)
    if plan == "pay_as_you_go" and (bal.credits or 0) < 5:
        bal.credits = max(bal.credits or 0, 5.0)
    # Bootstrap first company if requested or none exist
    existing = db.query(models.Company).filter_by(owner_user_id=user.id).count()
    if existing == 0:
        name = (company_name or f"{u.name or 'My'} company").strip() or "My company"
        db.add(models.Company(owner_user_id=user.id, name=name, industry=""))
    db.commit()
    return u


@router.post("/plan")
def choose_plan(data: PlanIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if data.plan not in public_plans() and data.plan not in ("trial", "pay_as_you_go"):
        if data.plan not in PLANS:
            raise HTTPException(400, "Unknown plan")
    stripe = _stripe()
    limits = plan_limits(data.plan)
    needs_payment = bool(limits.get("requires_payment"))

    # Paid plans: Stripe Checkout when key present (sandbox or live)
    if needs_payment and stripe:
        success, cancel = _checkout_urls("/billing", "/subscribe")
        try:
            line_item = _plan_line_item(data.plan, limits)
            session = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[line_item],
                success_url=success,
                cancel_url=cancel,
                customer_email=user.email,
                metadata={
                    "kind": "plan",
                    "user_id": str(user.id),
                    "plan": data.plan,
                    "company_name": data.company_name or "",
                },
                allow_promotion_codes=True,
            )
        except Exception as e:
            raise HTTPException(502, f"Stripe Checkout error: {e}") from e
        return {
            "checkout_url": session.url,
            "session_id": session.id,
            "provider": "stripe",
            "stripe_mode": _stripe_mode(),
            "crypto_available": crypto_pay.crypto_enabled(),
        }

    # Production: no free activate for paid plans without Stripe
    if needs_payment and config.IS_PRODUCTION:
        if crypto_pay.crypto_enabled():
            raise HTTPException(
                402,
                "Card payments unavailable — pay with crypto (ETH, SOL, or XRP) on Billing / Subscribe, "
                "or set STRIPE_SECRET_KEY (sk_test_… for sandbox).",
            )
        raise HTTPException(
            503,
            "Payments not configured. Set STRIPE_SECRET_KEY=sk_test_… for Stripe sandbox "
            "or CRYPTO_*_ADDRESS for crypto.",
        )

    # Dev (or free plans): activate without Checkout
    u = _activate_plan(db, user, data.plan, data.company_name)
    return {
        "plan": u.plan,
        "subscription_active": True,
        "dev_mode": True,
        "meter": meter_snapshot(db, u),
    }


@router.post("/checkout/confirm")
def confirm_checkout(
    session_id: str = Query(..., description="Stripe Checkout Session id (cs_test_… / cs_live_…)"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Fulfill a Checkout session after redirect (works without webhooks — ideal for sandbox testing).
    success_url includes session_id={CHECKOUT_SESSION_ID}.
    """
    stripe = _stripe()
    if not stripe:
        raise HTTPException(503, "Stripe not configured")
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        raise HTTPException(400, f"Could not load Checkout session: {e}") from e
    sess = session if isinstance(session, dict) else session.to_dict()
    meta = sess.get("metadata") or {}
    if str(meta.get("user_id") or "") != str(user.id):
        raise HTTPException(403, "This checkout session belongs to another account")
    result = _fulfill_stripe_session(db, sess)
    u = db.get(models.User, user.id)
    return {
        "ok": True,
        "result": result,
        "stripe_mode": _stripe_mode(),
        "plan": u.plan if u else None,
        "subscription_active": bool(u.subscription_active) if u else False,
        "meter": meter_snapshot(db, u) if u else None,
    }


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Stripe webhook (recommended for production).
    Sandbox can rely on /billing/checkout/confirm after redirect if webhook not set yet.
    Endpoint: POST /api/billing/webhook  (events: checkout.session.completed)
    """
    payload = await request.body()
    stripe = _stripe()
    if not stripe:
        raise HTTPException(503, "Stripe not configured")

    etype = None
    sess = None
    if config.STRIPE_WEBHOOK_SECRET:
        sig = request.headers.get("stripe-signature", "")
        try:
            event = stripe.Webhook.construct_event(payload, sig, config.STRIPE_WEBHOOK_SECRET)
        except Exception:
            raise HTTPException(400, "Invalid webhook signature")
        etype = event["type"] if isinstance(event, dict) else event.type
        data_obj = event["data"]["object"] if isinstance(event, dict) else event.data.object
        sess = _session_as_dict(data_obj)
    elif config.IS_PRODUCTION and _stripe_mode() == "live":
        raise HTTPException(400, "Webhook not configured — set STRIPE_WEBHOOK_SECRET for live mode")
    else:
        # Sandbox without webhook secret: accept JSON body for local Stripe CLI testing
        import json
        try:
            event = json.loads(payload)
        except Exception:
            raise HTTPException(
                400,
                "Invalid payload. Set STRIPE_WEBHOOK_SECRET or use Checkout confirm redirect for sandbox.",
            )
        etype = event.get("type")
        sess = _session_as_dict((event.get("data") or {}).get("object") or {})

    if etype == "checkout.session.completed" and sess:
        try:
            _fulfill_stripe_session(db, sess)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Fulfillment failed: {e}") from e
    return {"received": True, "type": etype}


@router.get("/balance")
def balance(db: Session = Depends(get_db), user=Depends(get_current_user)):
    snap = meter_snapshot(db, user)
    mode = _stripe_mode()
    return {
        "credits": snap["credits"],
        "plan": user.plan,
        "subscription_active": snap["subscription_active"],
        "stripe_live": _stripe_ready(),  # legacy name: means "stripe configured"
        "stripe_enabled": _stripe_ready(),
        "stripe_mode": mode,
        "stripe_sandbox": mode == "test",
        "crypto_enabled": crypto_pay.crypto_enabled(),
        "crypto_chains": [c["id"] for c in crypto_pay.available_chains()],
        "tokens_included": snap["tokens_included"],
        "tokens_used_period": snap["tokens_used_period"],
        "tokens_remaining_included": snap["tokens_remaining_included"],
        "usage_percent": snap["usage_percent"],
        "subscription_expires_at": (
            user.subscription_expires_at.isoformat() + "Z"
            if getattr(user, "subscription_expires_at", None)
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Crypto payments (ETH / SOL / XRP)
# ---------------------------------------------------------------------------

@router.get("/crypto/options")
def crypto_options():
    """Public: which chains are configured + live USD prices."""
    chains = crypto_pay.available_chains()
    prices = {}
    try:
        prices = crypto_pay.fetch_usd_prices()
    except Exception:
        prices = {}
    for c in chains:
        c["usd_price"] = prices.get(c["id"])
    return {
        "enabled": crypto_pay.crypto_enabled(),
        "chains": chains,
        "prices_usd": prices,
        "invoice_ttl_minutes": int(getattr(config, "CRYPTO_INVOICE_TTL_MIN", 60) or 60),
    }


def _fulfill_crypto_invoice(db: Session, inv: models.CryptoInvoice) -> models.CryptoInvoice:
    """Mark paid and grant plan / credits. Idempotent."""
    if inv.status == "paid":
        return inv
    user = db.get(models.User, inv.user_id)
    if not user:
        raise HTTPException(404, "User missing for invoice")
    if inv.kind == "topup":
        bal = db.query(models.Balance).filter_by(user_id=user.id).first()
        if not bal:
            bal = models.Balance(user_id=user.id, credits=0.0)
            db.add(bal)
            db.flush()
        bal.credits = float(bal.credits or 0) + float(inv.amount_usd or 0)
    else:
        plan = inv.plan or "starter"
        _activate_plan(db, user, plan, inv.company_name or None)
    inv.status = "paid"
    inv.paid_at = datetime.utcnow()
    db.commit()
    db.refresh(inv)
    return inv


@router.post("/crypto/invoice")
def create_crypto_invoice(
    data: CryptoInvoiceIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if not crypto_pay.crypto_enabled():
        raise HTTPException(
            503,
            "Crypto payments not configured. Set CRYPTO_ETH_ADDRESS / CRYPTO_SOL_ADDRESS / CRYPTO_XRP_ADDRESS.",
        )
    chain = (data.chain or "").lower().strip()
    if chain not in crypto_pay.CHAINS:
        raise HTTPException(400, "chain must be eth, sol, or xrp")
    addr = crypto_pay.receive_address(chain)
    if not addr:
        raise HTTPException(400, f"{chain.upper()} receive address not configured")

    kind = (data.kind or "plan").lower().strip()
    if kind not in ("plan", "topup"):
        raise HTTPException(400, "kind must be plan or topup")

    amount_usd = 0.0
    plan = ""
    company_name = (data.company_name or "").strip()
    if kind == "topup":
        amount_usd = float(data.amount or 0)
        if amount_usd < 1 or amount_usd > 1000:
            raise HTTPException(400, "Top-up must be between $1 and $1000")
    else:
        plan = (data.plan or "").strip()
        if plan not in PLANS or plan == "none":
            raise HTTPException(400, "Unknown plan")
        limits = plan_limits(plan)
        amount_usd = float(limits.get("price") or 0)
        if amount_usd <= 0 and not limits.get("requires_payment"):
            # Free plan — activate immediately without crypto
            u = _activate_plan(db, user, plan, company_name or None)
            return {
                "activated": True,
                "plan": u.plan,
                "subscription_active": True,
                "meter": meter_snapshot(db, u),
            }
        if amount_usd <= 0:
            raise HTTPException(400, "Plan has no crypto price")

    try:
        base_crypto = crypto_pay.usd_to_crypto(chain, amount_usd)
    except Exception as e:
        raise HTTPException(502, f"Could not price crypto: {e}")

    # Expire older pending invoices for same user/chain (keep board clean)
    now = datetime.utcnow()
    stale = (
        db.query(models.CryptoInvoice)
        .filter_by(user_id=user.id, status="pending")
        .all()
    )
    for s in stale:
        if s.expires_at and s.expires_at < now:
            s.status = "expired"
    db.flush()

    inv = models.CryptoInvoice(
        public_id=crypto_pay.new_public_id(),
        user_id=user.id,
        chain=chain,
        kind=kind,
        plan=plan,
        company_name=company_name,
        amount_usd=round(amount_usd, 2),
        amount_crypto=base_crypto,
        asset_symbol=crypto_pay.CHAINS[chain]["symbol"],
        receive_address=addr,
        dest_tag=None,
        status="pending",
        expires_at=crypto_pay.invoice_expires_at(),
    )
    db.add(inv)
    db.flush()
    # Unique amount (ETH/SOL) or destination tag (XRP)
    inv.amount_crypto = crypto_pay.unique_amount(chain, base_crypto, inv.id)
    if chain == "xrp":
        inv.dest_tag = 100_000 + inv.id
    db.commit()
    db.refresh(inv)
    return crypto_pay.serialize_invoice(inv)


@router.get("/crypto/invoices")
def list_crypto_invoices(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
):
    rows = (
        db.query(models.CryptoInvoice)
        .filter_by(user_id=user.id)
        .order_by(models.CryptoInvoice.id.desc())
        .limit(limit)
        .all()
    )
    return {"invoices": [crypto_pay.serialize_invoice(r) for r in rows]}


@router.get("/crypto/invoice/{public_id}")
def get_crypto_invoice(
    public_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    inv = db.query(models.CryptoInvoice).filter_by(public_id=public_id, user_id=user.id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    # Auto-expire
    if inv.status == "pending" and inv.expires_at and inv.expires_at < datetime.utcnow():
        inv.status = "expired"
        db.commit()
    return crypto_pay.serialize_invoice(inv)


@router.post("/crypto/invoice/{public_id}/verify")
def verify_crypto_invoice(
    public_id: str,
    data: CryptoVerifyIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    inv = db.query(models.CryptoInvoice).filter_by(public_id=public_id, user_id=user.id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv.status == "paid":
        return {"status": "paid", "invoice": crypto_pay.serialize_invoice(inv), "already_paid": True}
    if inv.status == "expired" or (inv.expires_at and inv.expires_at < datetime.utcnow()):
        inv.status = "expired"
        db.commit()
        raise HTTPException(410, "Invoice expired — create a new one")
    if inv.status not in ("pending", "confirming"):
        raise HTTPException(400, f"Invoice status is {inv.status}")

    tx_hash = (data.tx_hash or inv.tx_hash or "").strip()
    result = None
    if tx_hash:
        # Prevent double-spend of same tx across invoices
        other = (
            db.query(models.CryptoInvoice)
            .filter(
                models.CryptoInvoice.tx_hash == tx_hash,
                models.CryptoInvoice.status == "paid",
                models.CryptoInvoice.id != inv.id,
            )
            .first()
        )
        if other:
            raise HTTPException(400, "This transaction was already used for another invoice")
        result = crypto_pay.verify_payment(
            inv.chain,
            receive_address=inv.receive_address,
            amount_crypto=float(inv.amount_crypto),
            dest_tag=inv.dest_tag,
            tx_hash=tx_hash,
        )
    else:
        # Best-effort scan (XRP destination tag)
        result = crypto_pay.scan_recent_for_invoice(
            inv.chain,
            receive_address=inv.receive_address,
            amount_crypto=float(inv.amount_crypto),
            dest_tag=inv.dest_tag,
            since=inv.created_at,
        )
        if not result:
            raise HTTPException(
                400,
                "Provide tx_hash (transaction hash / signature). Auto-scan only works for XRP with destination tags.",
            )

    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Payment not verified")

    inv.tx_hash = result.get("tx_hash") or tx_hash
    inv.status = "confirming"
    db.commit()
    inv = _fulfill_crypto_invoice(db, inv)
    u = db.get(models.User, user.id)
    return {
        "status": "paid",
        "invoice": crypto_pay.serialize_invoice(inv),
        "verification": {k: result.get(k) for k in ("actual", "confirmations", "tx_hash") if k in result},
        "meter": meter_snapshot(db, u) if u else None,
        "plan": u.plan if u else None,
        "subscription_active": bool(u.subscription_active) if u else False,
    }


@router.post("/crypto/invoice/{public_id}/cancel")
def cancel_crypto_invoice(
    public_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    inv = db.query(models.CryptoInvoice).filter_by(public_id=public_id, user_id=user.id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv.status == "paid":
        raise HTTPException(400, "Already paid")
    inv.status = "cancelled"
    db.commit()
    return crypto_pay.serialize_invoice(inv)


@router.get("/usage")
def usage(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(models.TokenUsage).filter_by(user_id=user.id).all()
    total_tokens = sum(r.input_tokens + r.output_tokens for r in rows)
    total_cost = sum(r.cost for r in rows)
    by_model = {}
    for r in rows:
        m = by_model.setdefault(
            r.model,
            {"label": MODEL_LABELS.get(r.model, r.model), "tokens": 0, "cost": 0.0},
        )
        m["tokens"] += r.input_tokens + r.output_tokens
        m["cost"] = round(m["cost"] + r.cost, 6)
    days = []
    for i in range(6, -1, -1):
        day = (datetime.utcnow() - timedelta(days=i)).date()
        drows = [r for r in rows if r.created_at and r.created_at.date() == day]
        days.append({
            "day": day.strftime("%a"),
            "tokens": sum(r.input_tokens + r.output_tokens for r in drows),
            "cost": round(sum(r.cost for r in drows), 6),
        })
    meter = meter_snapshot(db, user)
    return {
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 6),
        "by_model": by_model,
        "daily": days,
        "meter": {
            **meter,
            "tokens_included_label": format_token_count(meter["tokens_included"]),
            "tokens_used_label": format_token_count(meter["tokens_used_period"]),
            "tokens_remaining_label": format_token_count(meter["tokens_remaining_included"]),
        },
    }


@router.websocket("/ws/tokens")
async def tokens_ws(ws: WebSocket, token: str = Query("")):
    db = SessionLocal()
    user = user_from_ws_token(token, db)
    db.close()
    if not user:
        await ws.close(code=4401)
        return
    channel = f"tokens:{user.id}"
    await manager.connect(channel, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(channel, ws)
