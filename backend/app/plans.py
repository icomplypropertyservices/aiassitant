"""Public subscription plans + token allowances. Prices in USD/month.

Customer-facing copy stays provider-neutral: managed/premium model tiers
(Fast / Quality / Reasoning / Large) and included token pools only.

Pre-order window (until launch): 10% off paid plans + early access.
Launch date: 27 July 2026.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

# Order for UI cards
PLAN_ORDER = ("trial", "starter", "pro", "business")

# ── Pre-order / launch ──────────────────────────────────────────────────────
# Pre-orders open now; public launch 27 July 2026. Pre-orders get 10% off and early access.
LAUNCH_DATE = date(2026, 7, 27)
PREORDER_DISCOUNT_PERCENT = 10

MODEL_AVAILABILITY = {
    "grok": {
        "status": "api_only",
        "label": "Grok (xAI API)",
        "blurb": "Available via API only — platform key or your own xAI API key in Settings.",
    },
    "claude": {
        "status": "coming_soon",
        "label": "Claude (Anthropic)",
        "blurb": "Coming soon.",
    },
    "vps": {
        "status": "coming_soon",
        "label": "VPS / small models",
        "blurb": "Coming soon — small models only on the VPS fleet when live.",
    },
}


def preorder_active(today: date | None = None) -> bool:
    """True until the calendar launch day (exclusive of launch day full price)."""
    d = today or datetime.now(timezone.utc).date()
    return d < LAUNCH_DATE


def preorder_meta() -> dict:
    active = preorder_active()
    return {
        "active": active,
        "launch_date": LAUNCH_DATE.isoformat(),
        "launch_label": "27 July 2026",
        "discount_percent": PREORDER_DISCOUNT_PERCENT if active else 0,
        "early_access": active,
        "cta_label": "Pre-order" if active else "Create account",
        "headline": (
            f"Pre-order now — {PREORDER_DISCOUNT_PERCENT}% off + early access"
            if active
            else "Choose your plan"
        ),
        "blurb": (
            f"Launch 27 July 2026. Pre-orders get {PREORDER_DISCOUNT_PERCENT}% off paid plans "
            "and early access before open."
            if active
            else "Pay with card (Stripe) or crypto (ETH / SOL / BTC / XRP)."
        ),
        "payments": {
            "stripe": True,
            "crypto": True,
            "chains": ["ETH", "SOL", "BTC", "XRP"],
        },
        "models": MODEL_AVAILABILITY,
    }


def apply_preorder_discount(list_price: float) -> float:
    """Return checkout price after pre-order discount (if active)."""
    price = float(list_price or 0)
    if price <= 0 or not preorder_active():
        return round(price, 2)
    return round(price * (1 - PREORDER_DISCOUNT_PERCENT / 100.0), 2)


def plan_checkout_price(plan_id: str) -> float:
    """USD amount charged for a plan (pre-order discount applied when active)."""
    return apply_preorder_discount(float(plan_limits(plan_id).get("price") or 0))


PLANS = {
    "none": {
        "name": "No plan",
        "price": 0,
        "currency": "usd",
        "blurb": "Choose a plan to start",
        "tokens_included": 0,
        "agents": 0,
        "companies": 0,
        "projects": 0,
        "features": [],
        "public": False,
        "requires_payment": False,
        "cta": "Choose a plan",
        "badge": None,
        "upgrade_teaser": "Pick a plan to unlock agents and tokens.",
        "next_plan": "trial",
    },
    "trial": {
        "name": "Free trial",
        "price": 0,
        "currency": "usd",
        "blurb": "Try the full product — no card required to start.",
        "tokens_included": 50_000,
        "agents": 3,
        "companies": 1,
        "projects": 2,
        "features": [
            "50,000 tokens in your included pool this month",
            "1 company · 2 projects",
            "Up to 3 AI agents",
            "Managed Fast & Quality models",
            "Live chat + templates",
        ],
        "teasers": [
            "See real agents before you pay",
            "Upgrade anytime — tokens reset monthly on paid plans",
        ],
        "public": True,
        "requires_payment": False,
        "highlight": False,
        "badge": "Try free",
        "cta": "Start free",
        "cta_upgrade": "Start free",
        "upgrade_teaser": "Need more power? Starter includes 2M tokens — 40× this trial.",
        "next_plan": "starter",
        "sort": 0,
    },
    "starter": {
        "name": "Starter",
        "price": 39,
        "currency": "usd",
        "blurb": "Freelancers & small teams — serious volume at a clear monthly price.",
        "tokens_included": 2_000_000,
        "agents": 5,
        "companies": 1,
        "projects": 10,
        "features": [
            "2M tokens / month included pool",
            "1 company · 10 projects",
            "Up to 5 AI agents",
            "Managed Fast & Quality models",
            "Usage meter always visible",
            "Email outbound when connected",
        ],
        "teasers": [
            "Best first paid step after trial",
            "Overage only if you burn past 2M",
        ],
        "public": True,
        "requires_payment": True,
        "highlight": False,
        "badge": None,
        "cta": "Pre-order Starter",
        "cta_upgrade": "Pre-order Starter",
        "upgrade_teaser": "Pro unlocks 10M tokens, 20 agents, and 3 companies.",
        "next_plan": "pro",
        "sort": 1,
    },
    "pro": {
        "name": "Pro",
        "price": 99,
        "currency": "usd",
        "blurb": "Growing teams — more agents, more projects, full model ladder.",
        "tokens_included": 10_000_000,
        "agents": 20,
        "companies": 3,
        "projects": 50,
        "features": [
            "10M tokens / month included pool",
            "3 companies · 50 projects",
            "Up to 20 AI agents",
            "Full managed model ladder (Fast → Large)",
            "Premium Reasoning & Large tiers",
            "Priority support queue",
            "Wallet top-ups for overage & media",
        ],
        "teasers": [
            "Most popular for active ops teams",
            "5× tokens vs Starter",
        ],
        "public": True,
        "requires_payment": True,
        "highlight": True,
        "badge": "Most popular",
        "cta": "Pre-order Pro",
        "cta_upgrade": "Pre-order Pro",
        "upgrade_teaser": "Business unlocks 40M tokens and 100 agents for agencies.",
        "next_plan": "business",
        "sort": 2,
    },
    "business": {
        "name": "Business",
        "price": 249,
        "currency": "usd",
        "blurb": "Agencies & multi-brand ops — high volume and room to scale.",
        "tokens_included": 40_000_000,
        "agents": 100,
        "companies": 15,
        "projects": 200,
        "features": [
            "40M tokens / month included pool",
            "15 companies · 200 projects",
            "Up to 100 AI agents",
            "Best included-pool rate at high volume",
            "Full managed + premium model ladder",
            "Media events included in platform usage",
            "Dedicated onboarding path",
        ],
        "teasers": [
            "Run multiple client workspaces",
            "Lowest effective cost per token when you use the included pool",
        ],
        "public": True,
        "requires_payment": True,
        "highlight": False,
        "badge": "Scale",
        "cta": "Pre-order Business",
        "cta_upgrade": "Pre-order Business",
        "upgrade_teaser": "You're on the top public tier — top up wallet for spikes.",
        "next_plan": None,
        "sort": 3,
    },
    "pay_as_you_go": {
        "name": "Pay as you go",
        "price": 0,
        "currency": "usd",
        "blurb": "No monthly fee — top up credits only.",
        "tokens_included": 0,
        "agents": 10,
        "companies": 1,
        "projects": 5,
        "features": [
            "No monthly commitment",
            "Top up $10–$1,000",
            "1 company · 5 projects · 10 agents",
            "Managed models at public rates",
        ],
        "teasers": [],
        "public": False,
        # Wallet-funded: no free activation / free $5 in production (billing.choose_plan enforces)
        "requires_payment": True,
        "highlight": False,
        "badge": None,
        "cta": "Use wallet only",
        "cta_upgrade": "Switch to wallet",
        "upgrade_teaser": None,
        "next_plan": "starter",
        "sort": 99,
    },
}


def public_plans() -> dict:
    items = {k: v for k, v in PLANS.items() if v.get("public")}
    return dict(sorted(items.items(), key=lambda kv: kv[1].get("sort", 50)))


def plan_limits(plan_id: str) -> dict:
    return PLANS.get(plan_id) or PLANS["none"]


def enrich_plan_for_public(plan_id: str, p: dict | None = None) -> dict:
    """Attach pre-order pricing fields for UI / checkout display."""
    base = dict(p or plan_limits(plan_id))
    list_price = float(base.get("price") or 0)
    checkout = apply_preorder_discount(list_price)
    active = preorder_active()
    base["price_list"] = list_price
    base["price"] = list_price  # list price stays for comparison
    base["price_checkout"] = checkout
    base["preorder_active"] = active
    base["preorder_discount_percent"] = PREORDER_DISCOUNT_PERCENT if active and list_price > 0 else 0
    if active and list_price > 0:
        base["price_display"] = checkout
        base["preorder_savings"] = round(list_price - checkout, 2)
        if not (base.get("badge") and base.get("highlight")):
            base["badge"] = base.get("badge") or f"{PREORDER_DISCOUNT_PERCENT}% off pre-order"
        # Prefer pre-order CTAs while window is open
        name = base.get("name") or plan_id.title()
        if base.get("requires_payment"):
            base["cta"] = base.get("cta") or f"Pre-order {name}"
            base["cta_upgrade"] = base.get("cta_upgrade") or f"Pre-order {name}"
    else:
        base["price_display"] = list_price
        base["preorder_savings"] = 0
        # Post-launch CTAs
        if base.get("requires_payment") and str(base.get("cta") or "").lower().startswith("pre-order"):
            name = base.get("name") or plan_id.title()
            base["cta"] = f"Get {name}"
            base["cta_upgrade"] = f"Upgrade to {name}"
    return base


def plan_rank(plan_id: str) -> int:
    order = {pid: i for i, pid in enumerate(PLAN_ORDER)}
    return order.get(plan_id, -1)


def is_upgrade(from_plan: str, to_plan: str) -> bool:
    return plan_rank(to_plan) > plan_rank(from_plan)


def effective_included_rate(plan_id: str) -> float | None:
    """USD per 1M tokens if the full included pool is used (marketing helper)."""
    p = plan_limits(plan_id)
    tokens = int(p.get("tokens_included") or 0)
    # Use checkout price so pre-order messaging matches what people pay
    price = plan_checkout_price(plan_id) if preorder_active() else float(p.get("price") or 0)
    if tokens <= 0 or price <= 0:
        return None
    return round(price / (tokens / 1_000_000), 2)
