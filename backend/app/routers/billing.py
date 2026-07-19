import os
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..database import get_db, SessionLocal
from .. import models, config
from ..auth_utils import get_current_user, user_from_ws_token, accept_and_authenticate_ws
from ..ws import manager
from ..pricing import MODEL_LABELS, PRICING, format_token_count, public_rates
from ..plans import (
    PLANS,
    TRIAL_DAYS,
    STORAGE_ADDONS,
    public_plans,
    plan_limits,
    is_upgrade,
    effective_included_rate,
    preorder_active,
    preorder_meta,
    plan_checkout_price,
    plan_annual_list_price,
    normalize_billing_interval,
    enrich_plan_for_public,
)
from ..usage_billing import meter_snapshot, ensure_period
from .. import crypto_payments as crypto_pay
from ..storage_quota import (
    storage_snapshot,
    list_storage_addons_public,
    grant_storage_addon,
)

router = APIRouter(prefix="/billing", tags=["billing"])

PLAN_PRICE_IDS = {
    "starter": config.STRIPE_PRICE_STARTER,
    "pro": config.STRIPE_PRICE_PRO,
    "business": config.STRIPE_PRICE_BUSINESS,
}
PLAN_PRICE_IDS_ANNUAL = {
    "starter": getattr(config, "STRIPE_PRICE_STARTER_ANNUAL", "") or "",
    "pro": getattr(config, "STRIPE_PRICE_PRO_ANNUAL", "") or "",
    "business": getattr(config, "STRIPE_PRICE_BUSINESS_ANNUAL", "") or "",
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


def _wallets_enabled() -> bool:
    """Apple Pay + Google Pay ride on card when domain is verified in Stripe Dashboard."""
    raw = (getattr(config, "STRIPE_WALLETS_ENABLED", None) or os.getenv("STRIPE_WALLETS_ENABLED", "1"))
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def _checkout_wallet_kwargs(*, mode: str = "payment") -> dict:
    """
    Enable Apple Pay, Google Pay, and Link on Stripe Checkout.

    Wallets show automatically under the card payment method when:
      - Domain is registered in Stripe → Settings → Payment methods → Apple Pay
      - Customer device supports the wallet (Safari/iOS for Apple Pay, Chrome/Android for Google Pay)
      - Checkout is HTTPS on a verified domain (aibusinessagent.xyz)

    We explicitly pass payment_method_types so wallets are not disabled by Dashboard-only filters.
    """
    if not _wallets_enabled():
        return {"payment_method_types": ["card"]}
    # card → Apple Pay + Google Pay; link → Stripe Link (1-click email wallet)
    types = ["card", "link"]
    kwargs: dict = {
        "payment_method_types": types,
        "payment_method_options": {
            "card": {
                # Wallets + cards; 3DS only when required
                "request_three_d_secure": "automatic",
            },
        },
    }
    # Subscriptions: save card/wallet for renewals
    if mode == "subscription":
        kwargs["payment_method_collection"] = "always"
    return kwargs


def _merge_checkout_kwargs(base: dict, *, mode: str) -> dict:
    """Merge wallet payment methods into a Checkout Session.create dict."""
    out = dict(base)
    for k, v in _checkout_wallet_kwargs(mode=mode).items():
        if k not in out:
            out[k] = v
    return out


def _plan_line_item(plan: str, limits: dict, interval: str = "month") -> dict:
    """Prefer configured Stripe Price ID; else inline recurring price_data.

    interval: month | year (annual = 10× monthly ≈ 2 months free).
    Live mode: full list price, mode=subscription at Checkout.
    """
    iv = normalize_billing_interval(interval)
    amount = plan_checkout_price(plan, iv)
    if amount <= 0:
        amount = float(limits.get("price") or 0) if iv == "month" else plan_annual_list_price(plan)
    if amount <= 0:
        raise HTTPException(400, "Plan has no price for Stripe checkout")

    # Fixed Price IDs when configured (must match interval in Stripe Dashboard)
    if not preorder_active():
        if iv == "year":
            price_id = (PLAN_PRICE_IDS_ANNUAL.get(plan) or "").strip()
        else:
            price_id = (PLAN_PRICE_IDS.get(plan) or "").strip()
        if price_id:
            return {"price": price_id, "quantity": 1}

    name = limits.get("name") or plan.title()
    list_m = float(limits.get("price") or 0)
    if iv == "year":
        annual_full = round(list_m * 12, 2) if list_m else 0
        save = round(annual_full - amount, 2) if annual_full > amount else 0
        desc = (
            f"Annual subscription · billed once per year · "
            f"save ${save:.0f} vs monthly ({list_m:.0f}×12). Access starts on payment. "
            f"{limits.get('blurb') or ''}"
        )
        product_name = f"AI Business Assistant — {name} (Annual)"
        stripe_interval = "year"
    else:
        desc = f"Monthly subscription · access starts on payment. {limits.get('blurb') or ''}"
        product_name = f"AI Business Assistant — {name} (Monthly)"
        stripe_interval = "month"
        if preorder_active() and list_m > amount:
            desc = (
                f"Pre-order · 10% off (list ${list_m:.0f}/mo) · early access · "
                f"launch 27 July 2026. {desc}"
            )
            product_name = f"AI Business Assistant — {name} (Pre-order 10% off)"

    return {
        "price_data": {
            "currency": "usd",
            "product_data": {
                "name": product_name,
                "description": desc[:500],
            },
            "unit_amount": int(round(amount * 100)),
            "recurring": {"interval": stripe_interval},
        },
        "quantity": 1,
    }


def _checkout_urls(path_success: str = "/billing", path_cancel: str = "/billing"):
    """Build Stripe return URLs under the product SPA (/agents/… in production)."""
    base = (config.FRONTEND_URL or "").rstrip("/") or "http://localhost:5173"
    # Avoid double /agents when callers pass /agents/billing
    def _join(path: str) -> str:
        p = (path or "/billing").strip() or "/billing"
        if not p.startswith("/"):
            p = f"/{p}"
        if base.endswith("/agents") and p.startswith("/agents/"):
            p = p[len("/agents"):]
        return f"{base}{p}"

    # {CHECKOUT_SESSION_ID} is expanded by Stripe — enables confirm without webhook
    success = f"{_join(path_success)}?checkout=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel = f"{_join(path_cancel)}?checkout=cancelled"
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
    elif kind == "storage":
        u = db.get(models.User, user_id)
        if not u:
            raise HTTPException(404, "User not found")
        addon_id = (meta.get("addon_id") or meta.get("plan") or "").strip()
        if addon_id not in STORAGE_ADDONS:
            raise HTTPException(400, f"Unknown storage add-on: {addon_id}")
        grant_storage_addon(db, u, addon_id)
        plan = addon_id  # store addon id in StripeCheckout.plan for audit
        amount = float(STORAGE_ADDONS[addon_id].get("price_usd") or 0)
        if amount <= 0:
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
    # Mobile shell tags (ios | android | web | native)
    platform: str | None = None
    client: str | None = None  # mobile | web


class StorageAddonIn(BaseModel):
    addon_id: str = Field(..., description="storage_5gb | storage_25gb | storage_100gb")


class AutoTopupIn(BaseModel):
    enabled: bool = False
    amount: float = Field(25.0, ge=5, le=500)
    threshold_credits: float = Field(5.0, ge=0, le=500)
    token_pct: int = Field(85, ge=50, le=99)


class PlanIn(BaseModel):
    plan: str
    company_name: str | None = None  # optional: create first company on subscribe
    # month (default) | year — annual Stripe subscription (10× monthly)
    interval: str = "month"
    billing_interval: str | None = None  # alias
    platform: str | None = None  # ios | android | web | native
    client: str | None = None  # mobile | web


class CheckoutConfirmIn(BaseModel):
    session_id: str | None = None


class CryptoInvoiceIn(BaseModel):
    chain: str = Field(..., description="eth | sol | xrp")
    kind: str = Field("plan", description="plan | topup")
    plan: str | None = None
    company_name: str | None = None
    amount: float | None = Field(None, description="USD amount for topup")


class CryptoVerifyIn(BaseModel):
    tx_hash: str | None = None
    public_id: str | None = None


@router.get("/native/products")
def native_store_products():
    """
    Product IDs for App Store Connect + Google Play Console.
    Create these as auto-renewing subscriptions (plans) or consumables (credits).
    """
    products = []
    for plan_id in ("starter", "pro", "business"):
        lim = plan_limits(plan_id)
        price = float(lim.get("price") or 0)
        annual = round(price * 10, 2) if price else 0
        for interval, amount, suffix in (
            ("month", price, "month"),
            ("year", annual, "year"),
        ):
            if amount <= 0:
                continue
            products.append({
                "key": f"{plan_id}_{suffix}",
                "kind": "subscription",
                "plan": plan_id,
                "interval": interval,
                "price_usd": amount,
                "apple_product_id": f"com.icomply.aibusinessassistant.{plan_id}.{suffix}",
                "google_product_id": f"{plan_id}_{suffix}",
                "name": f"{lim.get('name') or plan_id.title()} ({'Annual' if interval == 'year' else 'Monthly'})",
            })
    for amt in (10, 25, 50, 100):
        products.append({
            "key": f"credits_{amt}",
            "kind": "topup",
            "amount_usd": amt,
            "apple_product_id": f"com.icomply.aibusinessassistant.credits.{amt}",
            "google_product_id": f"credits_{amt}",
            "name": f"${amt} wallet credits",
        })
    return {
        "bundle_id": "com.icomply.aibusinessassistant",
        "scheme": "aiba",
        "checkout_mode": "stripe_browser",  # in-app system browser; optional IAP later
        "products": products,
        "notes": (
            "Mobile apps open Stripe Checkout in the system browser. "
            "Optionally mirror the same SKUs as StoreKit / Play Billing products for pure IAP."
        ),
    }


@router.get("/apple-pay-domain", response_class=PlainTextResponse)
def apple_pay_domain_association():
    """
    Apple Pay domain verification file content (also served at
    /.well-known/apple-developer-merchantid-domain-association via root rewrite if configured).

    Set STRIPE_APPLE_PAY_DOMAIN_ASSOCIATION to the full file body from Stripe Dashboard
    (Settings → Payment methods → Apple Pay → Add domain → download).
    """
    body = (getattr(config, "STRIPE_APPLE_PAY_DOMAIN_ASSOCIATION", None) or "").strip()
    if not body:
        body = (os.getenv("STRIPE_APPLE_PAY_DOMAIN_ASSOCIATION") or "").strip()
    if not body:
        raise HTTPException(
            404,
            "Set STRIPE_APPLE_PAY_DOMAIN_ASSOCIATION to the domain association file from Stripe "
            "(Dashboard → Settings → Payment methods → Apple Pay → your domain).",
        )
    return PlainTextResponse(body, media_type="text/plain")


@router.get("/plans")
def plans():
    """Public tiers with upgrade teasers — login / subscribe / billing."""
    out = {}
    for key, p in public_plans().items():
        row = enrich_plan_for_public(key, p)
        rate = effective_included_rate(key)
        if rate is not None:
            row["effective_usd_per_1m"] = rate
            row["value_line"] = f"As low as ${rate}/1M if you use the full included pool"
        else:
            row["effective_usd_per_1m"] = None
            row["value_line"] = "Free to start — upgrade when you need volume"
        out[key] = row
    # Attach launch / pre-order meta at top-level via special key (UI may ignore)
    return out


@router.get("/preorder")
def preorder_status():
    """Public pre-order / launch window + model availability for marketing & app."""
    return preorder_meta()


@router.get("/rates")
def rates():
    """Public token rates ($ / 1M tokens) — neutral names only."""
    rows = public_rates()
    return {
        "currency": "usd",
        "unit": "per_1m_tokens",
        "note": (
            "Included monthly tokens cover managed chat until the pool is used. "
            "Overage and media bill your credit wallet at these rates."
        ),
        "rates": rows,
    }


@router.get("/meter")
def meter(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Clear customer-facing token + credit meter."""
    snap = meter_snapshot(db, user)
    snap["tokens_included_label"] = format_token_count(snap["tokens_included"])
    snap["tokens_used_label"] = format_token_count(snap["tokens_used_period"])
    snap["tokens_remaining_label"] = format_token_count(snap["tokens_remaining_included"])
    return snap


@router.post("/reconcile-plan")
def reconcile_plan(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """
    Sync included token pool (and paid-plan expiry flags) from the user's plan.
    Fixes profiles that show plan=business but Tokens 0/0 after a partial activate.
    """
    from ..usage_billing import ensure_period, heal_subscription_flags

    u = db.get(models.User, user.id) or user
    bal = db.query(models.Balance).filter_by(user_id=u.id).first()
    if not bal:
        bal = models.Balance(user_id=u.id, credits=0.0)
        db.add(bal)
        db.flush()
    limits = plan_limits(u.plan or "none")
    expected = int(limits.get("tokens_included") or 0)
    before = int(bal.tokens_included or 0)
    # Force-apply plan pool for active subscriptions
    if u.subscription_active or u.role == "admin":
        if expected > 0:
            bal.tokens_included = expected
        if not bal.period_start:
            from datetime import datetime as _dt
            bal.period_start = _dt.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ensure_period(bal, u)
    heal_subscription_flags(db, u)
    db.commit()
    db.refresh(u)
    db.refresh(bal)
    snap = meter_snapshot(db, u)
    return {
        "ok": True,
        "plan": u.plan,
        "tokens_included_before": before,
        "tokens_included_after": int(bal.tokens_included or 0),
        "expected_from_plan": expected,
        "subscription_expires_at": (
            u.subscription_expires_at.isoformat() + "Z"
            if getattr(u, "subscription_expires_at", None)
            else None
        ),
        "meter": snap,
        "message": (
            f"Token pool set to {expected:,} for plan {u.plan}."
            if expected
            else "Plan has no included tokens (wallet / PAYG)."
        ),
    }


@router.get("/payment-options")
def payment_options():
    """Public-ish status: card (Stripe sandbox/live) + crypto availability."""
    mode = _stripe_mode()
    po = preorder_meta()
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
                "starter_annual": bool(getattr(config, "STRIPE_PRICE_STARTER_ANNUAL", "")),
                "pro_annual": bool(getattr(config, "STRIPE_PRICE_PRO_ANNUAL", "")),
                "business_annual": bool(getattr(config, "STRIPE_PRICE_BUSINESS_ANNUAL", "")),
            },
            # Works with secret key alone via price_data when price IDs missing
            "ready": _stripe_ready(),
            "intervals": ["month", "year"],
            "wallets": {
                "enabled": _wallets_enabled() and _stripe_ready(),
                "apple_pay": _wallets_enabled() and _stripe_ready(),
                "google_pay": _wallets_enabled() and _stripe_ready(),
                "link": _wallets_enabled() and _stripe_ready(),
                "label": "Apple Pay · Google Pay · Link · Card",
                "setup_hint": (
                    "In Stripe Dashboard → Settings → Payment methods: enable Apple Pay & Google Pay, "
                    "then add domain aibusinessagent.xyz (and www). Host the Apple domain association "
                    "file if Stripe asks (see /api/billing/apple-pay-domain)."
                ),
            },
            "label": (
                "Apple Pay · Google Pay · Card (Stripe test)"
                if mode == "test"
                else (
                    "Apple Pay · Google Pay · Card (Stripe live)"
                    if mode == "live"
                    else "Apple Pay · Google Pay · Card (Stripe)"
                )
            ),
            "test_card_hint": (
                "Use card 4242 4242 4242 4242, any future expiry, any CVC, any ZIP. "
                "Apple Pay / Google Pay appear in Checkout when the device supports them (even in test mode)."
                if mode == "test"
                else "Apple Pay and Google Pay appear on Checkout when available on your device."
            ),
        },
        "crypto": {
            "enabled": crypto_pay.crypto_enabled(),
            "chains": [c["id"] for c in crypto_pay.available_chains()],
            "label": "Crypto (ETH / SOL / BTC / XRP)",
            "ready": crypto_pay.crypto_enabled(),
        },
        "email": {
            "resend_platform": bool(getattr(config, "RESEND_API_KEY", "")),
            "resend_from": (getattr(config, "RESEND_FROM", "") or "")[:80] or None,
            "label": "Email (Resend API / SMTP)",
        },
        "preorder": po,
        "billing_intervals": ["month", "year"],
        "annual_label": "Pay annually — 2 months free",
        "ready_for_payments": _stripe_ready() or crypto_pay.crypto_enabled(),
    }


@router.get("/storage")
def billing_storage(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """User storage usage, plan limit, bonus packs, and upgrade options."""
    snap = storage_snapshot(db, user)
    return {
        **snap,
        "addons": list_storage_addons_public(),
        "upgrade_plan": plan_limits(user.plan or "none").get("next_plan"),
    }


@router.get("/storage-addons")
def billing_storage_addons():
    return {"addons": list_storage_addons_public()}


@router.post("/storage-addon")
def buy_storage_addon(
    data: StorageAddonIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Start Stripe checkout (or dev grant) for a permanent storage expansion pack."""
    addon_id = (data.addon_id or "").strip()
    addon = STORAGE_ADDONS.get(addon_id)
    if not addon or not addon.get("public", True):
        raise HTTPException(400, f"Unknown storage add-on: {addon_id}")
    price = float(addon.get("price_usd") or 0)
    if price <= 0:
        raise HTTPException(400, "Add-on has no price")

    stripe = _stripe()
    if stripe:
        success, cancel = _checkout_urls("/billing", "/billing")
        try:
            session = stripe.checkout.Session.create(
                **_merge_checkout_kwargs(
                    {
                        "mode": "payment",
                        "line_items": [{
                            "price_data": {
                                "currency": "usd",
                                "product_data": {
                                    "name": addon.get("name") or f"Storage {addon_id}",
                                    "description": addon.get("blurb") or f"+{addon.get('gb')} GB training storage",
                                },
                                "unit_amount": int(round(price * 100)),
                            },
                            "quantity": 1,
                        }],
                        "success_url": success,
                        "cancel_url": cancel,
                        "customer_email": user.email,
                        "metadata": {
                            "kind": "storage",
                            "user_id": str(user.id),
                            "addon_id": addon_id,
                            "amount": str(price),
                        },
                    },
                    mode="payment",
                )
            )
        except Exception as e:
            raise HTTPException(502, f"Stripe Checkout error: {e}") from e
        return {
            "checkout_url": session.url,
            "session_id": session.id,
            "provider": "stripe",
            "stripe_mode": _stripe_mode(),
            "addon_id": addon_id,
            "price_usd": price,
        }

    if config.IS_PRODUCTION:
        raise HTTPException(
            503,
            "Stripe is not configured. Set STRIPE_SECRET_KEY or contact support to expand storage.",
        )
    # Dev / sandbox without Stripe: grant immediately
    result = grant_storage_addon(db, user, addon_id)
    db.commit()
    return {
        "ok": True,
        "provider": "dev",
        "message": f"Dev grant: {result.get('added_human')} storage added",
        **result,
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
                **_merge_checkout_kwargs(
                    {
                        "mode": "payment",
                        "line_items": [{
                            "price_data": {
                                "currency": "usd",
                                "product_data": {"name": "AI Business Assistant credit top-up"},
                                "unit_amount": int(round(data.amount * 100)),
                            },
                            "quantity": 1,
                        }],
                        "success_url": success,
                        "cancel_url": cancel,
                        "customer_email": user.email,
                        "metadata": {
                            "kind": "topup",
                            "user_id": str(user.id),
                            "amount": str(data.amount),
                            "platform": (data.platform or "web")[:32],
                            "client": (data.client or "web")[:32],
                        },
                    },
                    mode="payment",
                )
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


@router.get("/auto-topup")
def get_auto_topup(db: Session = Depends(get_db), user=Depends(get_current_user)):
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal:
        bal = models.Balance(user_id=user.id, credits=0.0)
        db.add(bal)
        db.commit()
        db.refresh(bal)
    snap = meter_snapshot(db, user)
    return {
        "enabled": bool(getattr(bal, "auto_topup_enabled", False)),
        "amount": float(getattr(bal, "auto_topup_amount", None) or 25),
        "threshold_credits": float(getattr(bal, "auto_topup_threshold_credits", None) or 5),
        "token_pct": int(getattr(bal, "auto_topup_token_pct", None) or 85),
        "last_at": (
            bal.auto_topup_last_at.isoformat()
            if getattr(bal, "auto_topup_last_at", None)
            else None
        ),
        "meter": snap,
    }


@router.put("/auto-topup")
def put_auto_topup(
    data: AutoTopupIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal:
        bal = models.Balance(user_id=user.id, credits=0.0)
        db.add(bal)
        db.flush()
    bal.auto_topup_enabled = bool(data.enabled)
    bal.auto_topup_amount = float(data.amount)
    bal.auto_topup_threshold_credits = float(data.threshold_credits)
    bal.auto_topup_token_pct = int(data.token_pct)
    db.commit()
    return {
        "ok": True,
        "enabled": bal.auto_topup_enabled,
        "amount": bal.auto_topup_amount,
        "threshold_credits": bal.auto_topup_threshold_credits,
        "token_pct": bal.auto_topup_token_pct,
        "message": (
            f"Auto top-up ON — we'll prompt a ${int(data.amount)} refill when credits "
            f"drop below ${data.threshold_credits:.0f} or tokens hit {data.token_pct}%."
            if data.enabled
            else "Auto top-up off. You can still top up anytime."
        ),
    }


@router.post("/auto-topup/trigger")
def trigger_auto_topup(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """
    If auto-topup is enabled and balance is low, start a Stripe Checkout top-up.
    Called by the app when the salesy popup fires or meter says should_trigger.
    Rate-limited to once per 10 minutes per user.
    """
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal or not getattr(bal, "auto_topup_enabled", False):
        raise HTTPException(400, "Auto top-up is not enabled")
    snap = meter_snapshot(db, user)
    if not (snap.get("auto_topup") or {}).get("should_trigger") and not snap.get("needs_topup"):
        return {
            "ok": False,
            "skipped": True,
            "message": "Balance looks fine — no top-up needed yet.",
            "meter": snap,
        }
    last = getattr(bal, "auto_topup_last_at", None)
    if last and (datetime.utcnow() - last).total_seconds() < 600:
        return {
            "ok": False,
            "skipped": True,
            "message": "Top-up already started recently — finish checkout or wait a few minutes.",
            "meter": snap,
        }
    amount = float(getattr(bal, "auto_topup_amount", None) or 25)
    amount = max(5.0, min(500.0, amount))
    # Reuse topup path
    stripe = _stripe()
    if stripe:
        success, cancel = _checkout_urls("/billing", "/billing")
        try:
            session = stripe.checkout.Session.create(
                **_merge_checkout_kwargs(
                    {
                        "mode": "payment",
                        "line_items": [{
                            "price_data": {
                                "currency": "usd",
                                "product_data": {
                                    "name": "AI Assistant auto top-up",
                                    "description": f"Wallet refill ${amount:.0f} — keep agents running",
                                },
                                "unit_amount": int(round(amount * 100)),
                            },
                            "quantity": 1,
                        }],
                        "success_url": success,
                        "cancel_url": cancel,
                        "customer_email": user.email,
                        "metadata": {
                            "kind": "topup",
                            "user_id": str(user.id),
                            "amount": str(amount),
                            "auto": "1",
                        },
                    },
                    mode="payment",
                )
            )
        except Exception as e:
            raise HTTPException(502, f"Stripe Checkout error: {e}") from e
        bal.auto_topup_last_at = datetime.utcnow()
        db.commit()
        return {
            "ok": True,
            "checkout_url": session.url,
            "session_id": session.id,
            "amount": amount,
            "provider": "stripe",
            "sales_message": snap.get("sales_message"),
            "headline": snap.get("headline"),
        }
    if config.IS_PRODUCTION:
        raise HTTPException(503, "Stripe not configured for auto top-up")
    bal.credits = float(bal.credits or 0) + amount
    bal.auto_topup_last_at = datetime.utcnow()
    db.commit()
    return {
        "ok": True,
        "dev_mode": True,
        "amount": amount,
        "credits": round(bal.credits, 4),
        "message": f"Dev auto top-up +${amount:.0f}",
    }


# TRIAL_DAYS imported from plans (single source of truth with agent/company caps)
TRIAL_ENDED_MSG = "Trial ended — choose a paid plan"


def _trial_live(user: models.User) -> bool:
    """True when user is on an unexpired free trial."""
    if (user.plan or "") != "trial" or not user.subscription_active:
        return False
    exp = getattr(user, "subscription_expires_at", None)
    if exp is None:
        return False
    return exp > datetime.utcnow()


def _had_or_has_trial(db: Session, user: models.User) -> bool:
    """
    One-shot trial detection without a dedicated column:
    - currently on plan trial, or
    - subscription_expires_at was set (timed trial window), or
    - balance still shows the trial token pool after a prior activation
      while still on none / trial / pay_as_you_go.
    """
    if (user.plan or "") == "trial":
        return True
    if getattr(user, "subscription_expires_at", None) is not None:
        return True
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    trial_tokens = int(plan_limits("trial").get("tokens_included") or 50_000)
    if bal and int(bal.tokens_included or 0) == trial_tokens:
        if (user.plan or "") in ("none", "", "trial", "pay_as_you_go"):
            return True
    return False


def _activate_plan(db: Session, user: models.User, plan: str, company_name: str | None = None):
    """Activate a plan (trial / paid post-checkout). Commits plan+balance first.

    Company bootstrap is best-effort in a follow-up commit so a company table
    glitch cannot leave a new register stuck on plan=none (ensure-orchestrator 402).
    """
    if plan not in PLANS or plan == "none":
        raise HTTPException(400, "Unknown plan")
    limits = plan_limits(plan)
    u = db.get(models.User, user.id)
    if u is None:
        raise HTTPException(404, "User not found")
    u.plan = plan
    u.subscription_active = True
    # Free trial: one-shot 14-day window (set only when missing)
    if plan == "trial":
        if not getattr(u, "subscription_expires_at", None):
            u.subscription_expires_at = datetime.utcnow() + timedelta(days=TRIAL_DAYS)
    elif limits.get("requires_payment"):
        # Paid plans are not time-boxed by trial expiry
        u.subscription_expires_at = None
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal:
        bal = models.Balance(user_id=user.id, credits=0.0)
        db.add(bal)
        db.flush()
    bal.tokens_included = int(limits.get("tokens_included") or 0)
    bal.tokens_used_period = 0
    bal.period_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Welcome credits only in non-production — never mint free wallet credits in prod
    if not config.IS_PRODUCTION:
        if plan == "trial" and (bal.credits or 0) < 2:
            bal.credits = max(bal.credits or 0, 2.0)
        if plan == "pay_as_you_go" and (bal.credits or 0) < 5:
            bal.credits = max(bal.credits or 0, 5.0)
    # Commit plan + balance before optional company so register never loses trial
    db.commit()
    db.refresh(u)

    # Bootstrap first company if requested or none exist (non-fatal)
    try:
        existing = db.query(models.Company).filter_by(owner_user_id=u.id).count()
        if existing == 0:
            name = (company_name or f"{u.name or 'My'} company").strip() or "My company"
            db.add(models.Company(owner_user_id=u.id, name=name, industry=""))
            db.commit()
    except Exception:
        db.rollback()
    return u


@router.post("/plan")
def choose_plan(data: PlanIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if data.plan not in public_plans() and data.plan not in ("trial", "pay_as_you_go"):
        if data.plan not in PLANS:
            raise HTTPException(400, "Unknown plan")
    stripe = _stripe()
    limits = plan_limits(data.plan)
    needs_payment = bool(limits.get("requires_payment"))

    # ── Free trial: one-shot + 14-day expiry (no token refill on re-POST) ──
    if data.plan == "trial":
        u = db.get(models.User, user.id) or user
        # Legacy: plan=trial but never got expires_at — stamp 14d once, no pool reset
        if (u.plan or "") == "trial" and not getattr(u, "subscription_expires_at", None):
            u.subscription_active = True
            u.subscription_expires_at = datetime.utcnow() + timedelta(days=TRIAL_DAYS)
            db.commit()
            db.refresh(u)
            out = {
                "plan": u.plan,
                "subscription_active": bool(u.subscription_active),
                "subscription_expires_at": u.subscription_expires_at.isoformat() + "Z",
                "already_active": True,
                "meter": meter_snapshot(db, u),
            }
            out["dev_mode"] = not config.IS_PRODUCTION
            return out
        if _trial_live(u):
            # Still in active trial — return current state, do not reset pool
            out = {
                "plan": u.plan,
                "subscription_active": bool(u.subscription_active),
                "subscription_expires_at": (
                    u.subscription_expires_at.isoformat() + "Z"
                    if getattr(u, "subscription_expires_at", None)
                    else None
                ),
                "already_active": True,
                "meter": meter_snapshot(db, u),
            }
            out["dev_mode"] = not config.IS_PRODUCTION
            return out
        if _had_or_has_trial(db, u):
            # Used or expired trial — refuse fresh 50k activation
            raise HTTPException(402, TRIAL_ENDED_MSG)
        u = _activate_plan(db, user, "trial", data.company_name)
        out = {
            "plan": u.plan,
            "subscription_active": True,
            "subscription_expires_at": (
                u.subscription_expires_at.isoformat() + "Z"
                if getattr(u, "subscription_expires_at", None)
                else None
            ),
            "already_active": False,
            "meter": meter_snapshot(db, u),
        }
        out["dev_mode"] = not config.IS_PRODUCTION
        return out

    # Production: pay_as_you_go is wallet-only — no free activation / free $5 mint
    if data.plan == "pay_as_you_go" and config.IS_PRODUCTION:
        raise HTTPException(
            402,
            "Pay as you go requires a credit top-up via card (Stripe) or crypto. "
            "Free activation and free wallet credits are not available in production.",
        )

    # Paid plans: live Stripe Checkout (mode=subscription). Monthly or annual.
    # Annual = 10× monthly (~2 months free). pay_as_you_go is wallet top-up only.
    if needs_payment and stripe and data.plan != "pay_as_you_go":
        interval = normalize_billing_interval(data.interval or data.billing_interval or "month")
        success, cancel = _checkout_urls("/billing", "/subscribe")
        try:
            line_item = _plan_line_item(data.plan, limits, interval=interval)
            amount = plan_checkout_price(data.plan, interval)
            meta = {
                "kind": "plan",
                "user_id": str(user.id),
                "plan": data.plan,
                "company_name": data.company_name or "",
                "preorder": "0",
                "list_price": str(limits.get("price") or ""),
                "checkout_price": str(amount),
                "billing_mode": "subscription",
                "interval": interval,
                "platform": (data.platform or "web")[:32],
                "client": (data.client or "web")[:32],
            }
            session_kwargs = _merge_checkout_kwargs(
                {
                    "mode": "subscription",
                    "line_items": [line_item],
                    "success_url": success,
                    "cancel_url": cancel,
                    "customer_email": user.email,
                    "metadata": meta,
                    "allow_promotion_codes": True,
                    "subscription_data": {
                        "metadata": {
                            "user_id": str(user.id),
                            "plan": data.plan,
                            "kind": "plan",
                            "interval": interval,
                            "platform": (data.platform or "web")[:32],
                        },
                    },
                },
                mode="subscription",
            )
            session = stripe.checkout.Session.create(**session_kwargs)
        except Exception as e:
            raise HTTPException(502, f"Stripe Checkout error: {e}") from e
        unit = "/yr" if interval == "year" else "/mo"
        return {
            "checkout_url": session.url,
            "session_id": session.id,
            "provider": "stripe",
            "stripe_mode": _stripe_mode(),
            "crypto_available": crypto_pay.crypto_enabled(),
            "preorder": False,
            "live_subscription": True,
            "interval": interval,
            "amount_usd": amount,
            "list_price_usd": float(limits.get("price") or 0),
            "list_price_annual_usd": plan_annual_list_price(data.plan),
            "message": (
                f"Redirecting to Stripe for {limits.get('name') or data.plan} "
                f"{'annual' if interval == 'year' else 'monthly'} subscription "
                f"(${amount:.0f}{unit})."
            ),
        }

    # Production: no free activate for paid plans without Stripe
    if needs_payment and config.IS_PRODUCTION:
        if crypto_pay.crypto_enabled():
            raise HTTPException(
                402,
                "Card payments unavailable — pay with crypto (ETH, SOL, BTC, or XRP) on Billing / Subscribe, "
                "or set STRIPE_SECRET_KEY (sk_test_… for sandbox).",
            )
        raise HTTPException(
            503,
            "Payments not configured. Set STRIPE_SECRET_KEY=sk_test_… for Stripe sandbox "
            "or CRYPTO_*_ADDRESS for crypto.",
        )

    # Dev (or free plans e.g. trial): activate without Checkout
    u = _activate_plan(db, user, data.plan, data.company_name)
    out = {
        "plan": u.plan,
        "subscription_active": True,
        "meter": meter_snapshot(db, u),
    }
    # Only mark dev_mode when this path actually free-granted without payment rails
    if not config.IS_PRODUCTION:
        out["dev_mode"] = True
    else:
        out["dev_mode"] = False
    return out


@router.post("/checkout/confirm")
def confirm_checkout(
    session_id: str | None = Query(None, description="Stripe Checkout Session id (cs_test_… / cs_live_…)"),
    data: CheckoutConfirmIn | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Fulfill a Checkout session after redirect (works without webhooks — ideal for sandbox testing).
    success_url includes session_id={CHECKOUT_SESSION_ID}.
    Accepts ?session_id= or JSON {\"session_id\": \"cs_…\"} (mobile clients).
    """
    sid = (session_id or (getattr(data, "session_id", None) if data else None) or "").strip()
    if not sid:
        raise HTTPException(400, "session_id required")
    stripe = _stripe()
    if not stripe:
        raise HTTPException(503, "Stripe not configured")
    try:
        session = stripe.checkout.Session.retrieve(sid)
    except Exception as e:
        raise HTTPException(400, f"Could not load Checkout session: {e}") from e
    sess = session if isinstance(session, dict) else session.to_dict()
    meta = sess.get("metadata") or {}
    if str(meta.get("user_id") or "") != str(user.id):
        raise HTTPException(403, "This checkout session belongs to another account")
    result = _fulfill_stripe_session(db, sess)
    u = db.get(models.User, user.id)
    # Paid plan activation clears trial expiry; force open-ended subscription access
    if u and result.get("kind") == "plan" and (u.plan or "") not in ("trial", "none", ""):
        u.subscription_active = True
        u.subscription_expires_at = None
        db.commit()
        db.refresh(u)
    return {
        "ok": True,
        "result": result,
        "stripe_mode": _stripe_mode(),
        "plan": u.plan if u else None,
        "plan_name": (plan_limits(u.plan).get("name") if u else None),
        "subscription_active": bool(u and u.subscription_active),
        "needs_subscription": bool(
            u and (
                not u.subscription_active
                or (u.plan or "") in (None, "", "none")
            )
            and getattr(u, "role", "") != "admin"
        ),
        "meter": meter_snapshot(db, u) if u else None,
        "message": (
            f"Subscription active: {plan_limits(u.plan).get('name') or u.plan}"
            if u and u.subscription_active
            else "Payment recorded"
        ),
    }


def _stripe_customer_id_for_user(stripe, user) -> str | None:
    """
    Resolve Stripe Customer id for portal access.
    Prefer metadata user_id match, then email, then Search API fallback.
    """
    email = (getattr(user, "email", None) or "").strip()
    uid = str(user.id)
    email_match = None

    if email:
        try:
            listed = stripe.Customer.list(email=email, limit=20)
            rows = listed.get("data") if isinstance(listed, dict) else list(listed.data or [])
            for c in rows:
                cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
                meta = c.get("metadata") if isinstance(c, dict) else getattr(c, "metadata", None)
                if hasattr(meta, "to_dict"):
                    meta = meta.to_dict()
                meta = dict(meta or {})
                if str(meta.get("user_id") or "") == uid:
                    return cid
                if cid and not email_match:
                    email_match = cid
        except Exception:
            pass

    try:
        # Stripe Search (may be unavailable on older API / some accounts)
        found = stripe.Customer.search(query=f"metadata['user_id']:'{uid}'", limit=1)
        rows = found.get("data") if isinstance(found, dict) else list(found.data or [])
        if rows:
            c0 = rows[0]
            return c0.get("id") if isinstance(c0, dict) else getattr(c0, "id", None)
    except Exception:
        pass

    return email_match


@router.post("/portal")
def billing_portal(user=Depends(get_current_user)):
    """
    Create a Stripe Customer Portal session so the user can manage subscription,
    payment methods, and invoices. Returns {url}.
    """
    stripe = _stripe()
    if not stripe:
        raise HTTPException(503, "Stripe is not configured. Set STRIPE_SECRET_KEY.")
    customer_id = _stripe_customer_id_for_user(stripe, user)
    if not customer_id:
        raise HTTPException(
            400,
            "No Stripe customer found for this account. Subscribe or complete a card payment first, "
            "then use Manage subscription to update billing details.",
        )
    base = (config.FRONTEND_URL or "").rstrip("/") or "http://localhost:5173"
    return_url = f"{base}/billing"
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
    except Exception as e:
        raise HTTPException(502, f"Stripe Customer Portal error: {e}") from e
    url = session.url if hasattr(session, "url") else (session.get("url") if isinstance(session, dict) else None)
    if not url:
        raise HTTPException(502, "Stripe portal session missing url")
    return {"url": url}


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
        "storage": snap.get("storage") or storage_snapshot(db, user),
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
        # Pre-order: charge discounted price (10% off until launch)
        amount_usd = plan_checkout_price(plan)
        if amount_usd <= 0:
            amount_usd = float(limits.get("price") or 0)
        if amount_usd <= 0 and not limits.get("requires_payment"):
            # Free plan — activate immediately without crypto (same trial one-shot rules)
            if plan == "trial":
                u = db.get(models.User, user.id) or user
                if _trial_live(u):
                    return {
                        "activated": True,
                        "already_active": True,
                        "plan": u.plan,
                        "subscription_active": bool(u.subscription_active),
                        "subscription_expires_at": (
                            u.subscription_expires_at.isoformat() + "Z"
                            if getattr(u, "subscription_expires_at", None)
                            else None
                        ),
                        "meter": meter_snapshot(db, u),
                    }
                if _had_or_has_trial(db, u):
                    raise HTTPException(402, TRIAL_ENDED_MSG)
            u = _activate_plan(db, user, plan, company_name or None)
            return {
                "activated": True,
                "plan": u.plan,
                "subscription_active": True,
                "subscription_expires_at": (
                    u.subscription_expires_at.isoformat() + "Z"
                    if getattr(u, "subscription_expires_at", None)
                    else None
                ),
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
    """Token usage meter WS. Auth: ?token= (legacy/mobile) or first-message {"type":"auth","token":...}."""
    db = SessionLocal()
    user = await accept_and_authenticate_ws(ws, token, db)
    db.close()
    if not user:
        return
    channel = f"tokens:{user.id}"
    manager.register(channel, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(channel, ws)
