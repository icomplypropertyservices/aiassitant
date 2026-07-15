from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db, SessionLocal
from .. import models, config
from ..auth_utils import get_current_user, user_from_ws_token
from ..ws import manager
from ..pricing import MODEL_LABELS, PRICING, format_token_count
from ..plans import PLANS, public_plans, plan_limits
from ..usage_billing import meter_snapshot, ensure_period

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


class TopupIn(BaseModel):
    amount: float


class PlanIn(BaseModel):
    plan: str
    company_name: str | None = None  # optional: create first company on subscribe


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


@router.post("/topup")
def topup(data: TopupIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if data.amount < 1 or data.amount > 1000:
        raise HTTPException(400, "Top-up must be between $1 and $1000")
    stripe = _stripe()
    if stripe:
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
            success_url=f"{config.FRONTEND_URL}/billing?checkout=success",
            cancel_url=f"{config.FRONTEND_URL}/billing?checkout=cancelled",
            customer_email=user.email,
            metadata={"kind": "topup", "user_id": str(user.id), "amount": str(data.amount)},
        )
        return {"checkout_url": session.url}
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
    price_id = PLAN_PRICE_IDS.get(data.plan, "")
    limits = plan_limits(data.plan)
    needs_payment = bool(limits.get("requires_payment"))

    # Production: paid plans must go through Stripe Checkout — never free-activate.
    if needs_payment and config.IS_PRODUCTION:
        if not stripe or not price_id:
            raise HTTPException(503, "Stripe not configured for this plan")
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{config.FRONTEND_URL}/billing?checkout=success",
            cancel_url=f"{config.FRONTEND_URL}/subscribe?checkout=cancelled",
            customer_email=user.email,
            metadata={
                "kind": "plan",
                "user_id": str(user.id),
                "plan": data.plan,
                "company_name": data.company_name or "",
            },
        )
        return {"checkout_url": session.url}

    if stripe and price_id and needs_payment:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{config.FRONTEND_URL}/billing?checkout=success",
            cancel_url=f"{config.FRONTEND_URL}/subscribe?checkout=cancelled",
            customer_email=user.email,
            metadata={
                "kind": "plan",
                "user_id": str(user.id),
                "plan": data.plan,
                "company_name": data.company_name or "",
            },
        )
        return {"checkout_url": session.url}

    # Dev (or free plans): activate without Checkout
    u = _activate_plan(db, user, data.plan, data.company_name)
    return {
        "plan": u.plan,
        "subscription_active": True,
        "dev_mode": not bool(stripe and price_id),
        "meter": meter_snapshot(db, u),
    }


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    stripe = _stripe()
    if config.IS_PRODUCTION:
        if not stripe or not config.STRIPE_WEBHOOK_SECRET:
            raise HTTPException(400, "Webhook not configured")
        sig = request.headers.get("stripe-signature", "")
        try:
            event = stripe.Webhook.construct_event(payload, sig, config.STRIPE_WEBHOOK_SECRET)
        except Exception:
            raise HTTPException(400, "Invalid webhook signature")
    elif stripe and config.STRIPE_WEBHOOK_SECRET:
        sig = request.headers.get("stripe-signature", "")
        try:
            event = stripe.Webhook.construct_event(payload, sig, config.STRIPE_WEBHOOK_SECRET)
        except Exception:
            raise HTTPException(400, "Invalid webhook signature")
    else:
        # Dev only: accept unsigned JSON for local testing
        import json
        try:
            event = json.loads(payload)
        except Exception:
            raise HTTPException(400, "Invalid payload")
    if event.get("type") == "checkout.session.completed":
        session = event["data"]["object"]
        meta = session.get("metadata", {}) or {}
        user_id = int(meta.get("user_id", 0) or 0)
        if user_id:
            if meta.get("kind") == "topup":
                amount = float(meta.get("amount", 0) or 0)
                bal = db.query(models.Balance).filter_by(user_id=user_id).first()
                if not bal:
                    bal = models.Balance(user_id=user_id, credits=0.0)
                    db.add(bal)
                bal.credits += amount
                db.commit()
            elif meta.get("kind") == "plan":
                u = db.get(models.User, user_id)
                if u:
                    _activate_plan(db, u, meta.get("plan", "starter"), meta.get("company_name") or None)
    return {"received": True}


@router.get("/balance")
def balance(db: Session = Depends(get_db), user=Depends(get_current_user)):
    snap = meter_snapshot(db, user)
    return {
        "credits": snap["credits"],
        "plan": user.plan,
        "subscription_active": snap["subscription_active"],
        "stripe_live": bool(config.STRIPE_SECRET_KEY),
        "tokens_included": snap["tokens_included"],
        "tokens_used_period": snap["tokens_used_period"],
        "tokens_remaining_included": snap["tokens_remaining_included"],
        "usage_percent": snap["usage_percent"],
    }


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
