"""Public subscription plans + token allowances. Prices in USD/month.

Customer-facing copy stays provider-neutral: managed/premium model tiers
(Fast / Quality / Reasoning / Large) and included token pools only.

Live mode: paid plans are real monthly Stripe/crypto subscriptions at list price.
Pre-order discount is permanently off (see preorder_active).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

# Order for UI cards
PLAN_ORDER = ("trial", "starter", "pro", "business")

# ── Free trial product caps (source of truth for register + billing + meter) ─
# Trial is intentionally generous enough to try hierarchy + multi-company before pay.
TRIAL_TOKENS_INCLUDED = 50_000
TRIAL_AGENTS = 12
TRIAL_COMPANIES = 2
TRIAL_PROJECTS = 3
TRIAL_DAYS = 14

# ── Skills model (catalog is ~1,250+ skills: core + 20×50 mega packs) ─────────
# Plans do NOT hide the catalog — agents *enable* skills up to a cap.
# skill_packs = domain packs (sales, support, ops, …) the plan can fully unlock.
# skills_per_agent = max simultaneously enabled skills on one agent.
# prompt_skills = how many enabled skills are listed in the LLM system prompt.
CATALOG_SKILL_TARGET = 1_250  # marketing + capacity planning number
SKILL_PACKS_TOTAL = 20
SKILLS_PER_PACK = 50

# Training library storage (GB) included with each plan — not cloud Dropbox/GCS free quota
# (those use the customer's own cloud accounts; local+indexed text still counts against us).
TRIAL_STORAGE_GB = 0.5
STARTER_STORAGE_GB = 5
PRO_STORAGE_GB = 25
BUSINESS_STORAGE_GB = 100
PAYG_STORAGE_GB = 2


def _gb_to_bytes(gb: float) -> int:
    return int(float(gb or 0) * 1024 * 1024 * 1024)


def storage_bytes_for_plan(plan_id: str) -> int:
    p = PLANS.get(plan_id) or PLANS["none"]
    if "storage_bytes" in p:
        return int(p.get("storage_bytes") or 0)
    return _gb_to_bytes(float(p.get("storage_gb") or 0))


# One-time storage expansion packs (permanent bonus on Balance.storage_bonus_bytes)
STORAGE_ADDONS: dict[str, dict] = {
    "storage_5gb": {
        "name": "+5 GB storage",
        "blurb": "Permanent training-library expansion — never expires.",
        "gb": 5,
        "bytes": _gb_to_bytes(5),
        "price_usd": 9,
        "public": True,
        "cta": "Add 5 GB",
    },
    "storage_25gb": {
        "name": "+25 GB storage",
        "blurb": "Best value for growing knowledge bases and multi-agent training.",
        "gb": 25,
        "bytes": _gb_to_bytes(25),
        "price_usd": 29,
        "public": True,
        "cta": "Add 25 GB",
    },
    "storage_100gb": {
        "name": "+100 GB storage",
        "blurb": "Agency / multi-brand libraries and heavy document ops.",
        "gb": 100,
        "bytes": _gb_to_bytes(100),
        "price_usd": 79,
        "public": True,
        "cta": "Add 100 GB",
    },
}

# ── Pre-order / launch (disabled — live subscriptions) ──────────────────────
# Historical launch marker only. Pre-order discount is OFF so Stripe Checkout
# charges full list price as a real monthly subscription (mode=subscription).
LAUNCH_DATE = date(2026, 7, 27)
PREORDER_DISCOUNT_PERCENT = 10
# Set PREORDER_FORCE=1 only to temporarily re-open the pre-order discount window.
PREORDER_FORCE = (os.getenv("PREORDER_FORCE") or "").strip().lower() in ("1", "true", "yes")

# Annual = 10× monthly (≈2 months free / ~17% off vs paying monthly all year)
ANNUAL_MONTHS_BILLED = 10
ANNUAL_LABEL = "2 months free"

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
    """Live mode: pre-order is off unless PREORDER_FORCE=1 and before LAUNCH_DATE.

    Production default: always False so customers buy real monthly subscriptions
    (full list price), not prepay/pre-order.
    """
    if not PREORDER_FORCE:
        return False
    d = today or datetime.now(timezone.utc).date()
    return d < LAUNCH_DATE


def preorder_meta() -> dict:
    active = preorder_active()
    return {
        "active": active,
        "live": not active,
        "launch_date": LAUNCH_DATE.isoformat(),
        "launch_label": "27 July 2026" if active else "Live now",
        "discount_percent": PREORDER_DISCOUNT_PERCENT if active else 0,
        "early_access": bool(active),
        "cta_label": "Pre-order" if active else "Create account",
        "headline": (
            f"Pre-order now — {PREORDER_DISCOUNT_PERCENT}% off + early access"
            if active
            else "Subscribe — live monthly plans"
        ),
        "blurb": (
            f"Launch 27 July 2026. Pre-orders get {PREORDER_DISCOUNT_PERCENT}% off paid plans "
            "and early access before open."
            if active
            else (
                "Live subscriptions at full list price. Pay monthly with card (Stripe) "
                "or crypto (ETH / SOL / BTC / XRP). Access starts as soon as payment confirms."
            )
        ),
        "payments": {
            "stripe": True,
            "crypto": True,
            "chains": ["ETH", "SOL", "BTC", "XRP"],
            "mode": "subscription",
        },
        "models": MODEL_AVAILABILITY,
    }


def apply_preorder_discount(list_price: float) -> float:
    """Return checkout price (list price when live; discounted only if pre-order forced on)."""
    price = float(list_price or 0)
    if price <= 0 or not preorder_active():
        return round(price, 2)
    return round(price * (1 - PREORDER_DISCOUNT_PERCENT / 100.0), 2)


def plan_annual_list_price(plan_id: str) -> float:
    """List annual price (10× monthly = 2 months free vs 12× monthly)."""
    monthly = float(plan_limits(plan_id).get("price") or 0)
    if monthly <= 0:
        return 0.0
    return round(monthly * ANNUAL_MONTHS_BILLED, 2)


def plan_checkout_price(plan_id: str, interval: str = "month") -> float:
    """USD charged for a plan at checkout (month | year). Pre-order discount if forced on."""
    iv = (interval or "month").strip().lower()
    if iv in ("year", "annual", "yearly"):
        base = plan_annual_list_price(plan_id)
    else:
        base = float(plan_limits(plan_id).get("price") or 0)
    return apply_preorder_discount(base)


def normalize_billing_interval(interval: str | None) -> str:
    iv = (interval or "month").strip().lower()
    if iv in ("year", "annual", "yearly", "y", "yr"):
        return "year"
    return "month"


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
        "storage_gb": 0,
        # Skills (enabled caps — catalog remains browsable after you have a plan)
        "skills_per_agent": 0,
        "skill_packs": 0,
        "prompt_skills": 0,
        "premium_skills": False,
        "features": [],
        "public": False,
        "requires_payment": False,
        "cta": "Choose a plan",
        "badge": None,
        "upgrade_teaser": "Pick a plan to unlock agents, skills, and tokens.",
        "next_plan": "trial",
    },
    "trial": {
        "name": "Free trial",
        "price": 0,
        "currency": "usd",
        "blurb": "Try multi-agent ops + skill packs — no card required to start.",
        "tokens_included": TRIAL_TOKENS_INCLUDED,
        "agents": TRIAL_AGENTS,
        "companies": TRIAL_COMPANIES,
        "projects": TRIAL_PROJECTS,
        "storage_gb": TRIAL_STORAGE_GB,
        "trial_days": TRIAL_DAYS,
        # Enough to feel the 1,000-skill platform without matching paid volume
        "skills_per_agent": 120,
        "skill_packs": 6,
        "prompt_skills": 40,
        "premium_skills": False,
        "features": [
            f"{TRIAL_TOKENS_INCLUDED:,} tokens / month included pool",
            f"{TRIAL_COMPANIES} companies · {TRIAL_PROJECTS} projects · {TRIAL_AGENTS} agents",
            f"Up to 120 skills enabled per agent (of ~{CATALOG_SKILL_TARGET:,} catalog)",
            f"{6} of {SKILL_PACKS_TOTAL} domain skill packs",
            f"{TRIAL_STORAGE_GB} GB training storage",
            "Managed Fast & Quality models",
            "Live chat, hierarchy, meetings",
        ],
        "teasers": [
            "See real agents + skill packs before you pay",
            "Upgrade anytime — tokens reset monthly on paid plans",
        ],
        "public": True,
        "requires_payment": False,
        "highlight": True,
        "badge": "Try free",
        "cta": "Start free trial",
        "cta_upgrade": "Start free trial",
        "upgrade_teaser": "Starter: 2M tokens, 15 agents, 200 skills/agent, 12 packs.",
        "next_plan": "starter",
        "sort": 0,
    },
    "starter": {
        "name": "Starter",
        "price": 39,
        "currency": "usd",
        "blurb": "Freelancers & small teams — agents + hundreds of skills at a clear price.",
        "tokens_included": 2_000_000,
        "agents": 15,
        "companies": 2,
        "projects": 15,
        "storage_gb": STARTER_STORAGE_GB,
        "skills_per_agent": 200,
        "skill_packs": 12,
        "prompt_skills": 48,
        "premium_skills": False,
        "features": [
            "2M tokens / month included pool",
            "2 companies · 15 projects · 15 AI agents",
            "Up to 200 skills enabled per agent",
            f"12 of {SKILL_PACKS_TOTAL} domain skill packs (~{12 * SKILLS_PER_PACK} pack skills)",
            f"Full catalog browse (~{CATALOG_SKILL_TARGET:,} skills)",
            f"{STARTER_STORAGE_GB} GB training storage",
            "Managed Fast & Quality models",
            "Email outbound when SMTP/Resend connected",
        ],
        "teasers": [
            "Best first paid step after trial",
            "Hundreds of skills ready to enable per agent",
        ],
        "public": True,
        "requires_payment": True,
        "highlight": False,
        "badge": None,
        "cta": "Subscribe to Starter",
        "cta_upgrade": "Upgrade to Starter",
        "upgrade_teaser": "Pro: 10M tokens, 40 agents, 500 skills/agent, all 20 packs.",
        "next_plan": "pro",
        "sort": 1,
    },
    "pro": {
        "name": "Pro",
        "price": 99,
        "currency": "usd",
        "blurb": "Growing teams — full skill catalog, more agents, full model ladder.",
        "tokens_included": 10_000_000,
        "agents": 40,
        "companies": 5,
        "projects": 60,
        "storage_gb": PRO_STORAGE_GB,
        "skills_per_agent": 500,
        "skill_packs": SKILL_PACKS_TOTAL,  # all 20 packs
        "prompt_skills": 56,
        "premium_skills": True,
        "features": [
            "10M tokens / month included pool",
            "5 companies · 60 projects · 40 AI agents",
            "Up to 500 skills enabled per agent",
            f"All {SKILL_PACKS_TOTAL} domain packs (~{SKILL_PACKS_TOTAL * SKILLS_PER_PACK} pack skills)",
            f"Full ~{CATALOG_SKILL_TARGET:,}-skill catalog + premium skills",
            f"{PRO_STORAGE_GB} GB training storage",
            "Full managed model ladder (Fast → Large / Reasoning)",
            "Wallet top-ups for overage & media",
        ],
        "teasers": [
            "Most popular for active multi-agent ops",
            "All skill packs unlocked",
        ],
        "public": True,
        "requires_payment": True,
        "highlight": True,
        "badge": "Most popular",
        "cta": "Subscribe to Pro",
        "cta_upgrade": "Upgrade to Pro",
        "upgrade_teaser": "Business: 40M tokens, 120 agents, 1,000 skills/agent for agencies.",
        "next_plan": "business",
        "sort": 2,
    },
    "business": {
        "name": "Business",
        "price": 249,
        "currency": "usd",
        "blurb": "Agencies & multi-brand ops — max agents and full skill enablement.",
        "tokens_included": 40_000_000,
        "agents": 120,
        "companies": 20,
        "projects": 250,
        "storage_gb": BUSINESS_STORAGE_GB,
        "skills_per_agent": 1_000,
        "skill_packs": SKILL_PACKS_TOTAL,
        "prompt_skills": 64,
        "premium_skills": True,
        "features": [
            "40M tokens / month included pool",
            "20 companies · 250 projects · 120 AI agents",
            "Up to 1,000 skills enabled per agent",
            f"All {SKILL_PACKS_TOTAL} packs + full ~{CATALOG_SKILL_TARGET:,} catalog",
            f"{BUSINESS_STORAGE_GB} GB training storage",
            "Best included-pool rate at high volume",
            "Premium models + media in platform usage",
            "Dedicated onboarding path",
        ],
        "teasers": [
            "Run multiple client workspaces at scale",
            "Enable essentially the whole skill library per agent",
        ],
        "public": True,
        "requires_payment": True,
        "highlight": False,
        "badge": "Scale",
        "cta": "Subscribe to Business",
        "cta_upgrade": "Upgrade to Business",
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
        "agents": 12,
        "companies": 1,
        "projects": 8,
        "storage_gb": PAYG_STORAGE_GB,
        "skills_per_agent": 150,
        "skill_packs": 8,
        "prompt_skills": 40,
        "premium_skills": True,
        "features": [
            "No monthly commitment",
            "Top up $10–$1,000",
            f"{PAYG_STORAGE_GB} GB training storage",
            "1 company · 8 projects · 12 agents",
            "Up to 150 skills enabled per agent",
            "Managed models at public rates",
        ],
        "teasers": [],
        "public": False,
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


def plan_skill_caps(plan_id: str | None) -> dict:
    """
    How skills work on a plan (used by agent skill enablement + UI).

    - catalog: always full browse once user has any active plan (trial+)
    - skills_per_agent: hard max enabled skills stored on AgentSkillState
    - skill_packs: domain packs the plan can fully unlock (of SKILL_PACKS_TOTAL)
    - prompt_skills: max skill lines injected into the LLM system prompt
    - premium_skills: whether premium/metered skills may be enabled
    """
    p = plan_limits(plan_id or "none")
    return {
        "catalog_size_target": CATALOG_SKILL_TARGET,
        "skill_packs_total": SKILL_PACKS_TOTAL,
        "skills_per_pack": SKILLS_PER_PACK,
        "skills_per_agent": int(p.get("skills_per_agent") or 0),
        "skill_packs": int(p.get("skill_packs") or 0),
        "prompt_skills": int(p.get("prompt_skills") or 0) or 40,
        "premium_skills": bool(p.get("premium_skills")),
        "agents": int(p.get("agents") or 0),
        "tokens_included": int(p.get("tokens_included") or 0),
    }


def max_enabled_skills(plan_id: str | None) -> int:
    """Hard cap for enabled skills on a single agent for this plan."""
    return int(plan_skill_caps(plan_id).get("skills_per_agent") or 0)


def enrich_plan_for_public(plan_id: str, p: dict | None = None) -> dict:
    """Attach checkout pricing fields for UI (monthly + annual)."""
    base = dict(p or plan_limits(plan_id))
    list_price = float(base.get("price") or 0)
    annual_list = plan_annual_list_price(plan_id)
    checkout_m = apply_preorder_discount(list_price)
    checkout_y = apply_preorder_discount(annual_list)
    active = preorder_active()
    base["price_list"] = list_price
    base["price"] = list_price  # monthly list for comparison
    base["price_checkout"] = checkout_m
    base["price_monthly"] = list_price
    base["price_annual"] = annual_list
    base["price_annual_checkout"] = checkout_y
    # Equivalent monthly if paid yearly (for UI comparison)
    base["price_annual_per_month"] = (
        round(annual_list / 12.0, 2) if annual_list > 0 else 0.0
    )
    base["annual_months_billed"] = ANNUAL_MONTHS_BILLED
    base["annual_savings_vs_monthly"] = (
        round(list_price * 12 - annual_list, 2) if list_price > 0 else 0.0
    )
    base["annual_label"] = ANNUAL_LABEL
    base["billing_intervals"] = ["month", "year"] if list_price > 0 else ["month"]
    base["preorder_active"] = active
    base["live_subscription"] = not active
    base["preorder_discount_percent"] = PREORDER_DISCOUNT_PERCENT if active and list_price > 0 else 0
    if active and list_price > 0:
        base["price_display"] = checkout_m
        base["preorder_savings"] = round(list_price - checkout_m, 2)
        if not (base.get("badge") and base.get("highlight")):
            base["badge"] = f"{PREORDER_DISCOUNT_PERCENT}% off pre-order"
        name = base.get("name") or plan_id.title()
        if base.get("requires_payment"):
            base["cta"] = f"Pre-order {name}"
            base["cta_upgrade"] = f"Pre-order {name}"
    else:
        base["price_display"] = list_price
        base["preorder_savings"] = 0
        if base.get("requires_payment"):
            name = base.get("name") or plan_id.title()
            cta = str(base.get("cta") or "")
            if not cta or cta.lower().startswith("pre-order"):
                base["cta"] = f"Subscribe to {name}"
            up = str(base.get("cta_upgrade") or "")
            if not up or up.lower().startswith("pre-order"):
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
