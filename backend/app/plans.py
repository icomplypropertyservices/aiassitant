"""Public subscription plans + token allowances. Prices in USD/month."""

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
    },
    "trial": {
        "name": "Free trial",
        "price": 0,
        "currency": "usd",
        "blurb": "Try the product — 50,000 tokens, 1 company, 2 projects",
        "tokens_included": 50_000,
        "agents": 3,
        "companies": 1,
        "projects": 2,
        "features": [
            "50k tokens / month (VPS models)",
            "1 company · 2 projects",
            "3 AI agents",
            "Templates + live chat",
        ],
        "public": True,
        "requires_payment": False,
        "highlight": False,
    },
    "starter": {
        "name": "Starter",
        "price": 39,
        "currency": "usd",
        "blurb": "For freelancers & small trades — serious volume at a fair price",
        "tokens_included": 2_000_000,
        "agents": 5,
        "companies": 1,
        "projects": 10,
        "features": [
            "2M tokens / month included",
            "1 company · 10 projects",
            "5 AI agents",
            "Email delivery (with Resend key)",
            "Clear usage meter",
        ],
        "public": True,
        "requires_payment": True,
        "highlight": False,
    },
    "pro": {
        "name": "Pro",
        "price": 99,
        "currency": "usd",
        "blurb": "Growing teams — more agents, more projects, priority models",
        "tokens_included": 10_000_000,
        "agents": 20,
        "companies": 3,
        "projects": 50,
        "features": [
            "10M tokens / month included",
            "3 companies · 50 projects",
            "20 AI agents",
            "Premium models (Claude / Grok) at listed rates",
            "Priority support",
        ],
        "public": True,
        "requires_payment": True,
        "highlight": True,
    },
    "business": {
        "name": "Business",
        "price": 249,
        "currency": "usd",
        "blurb": "Agencies & multi-brand ops — high volume + markup-friendly usage",
        "tokens_included": 40_000_000,
        "agents": 100,
        "companies": 15,
        "projects": 200,
        "features": [
            "40M tokens / month included",
            "15 companies · 200 projects",
            "100 AI agents",
            "Best effective rate on VPS / Qwen",
            "Dedicated onboarding path",
        ],
        "public": True,
        "requires_payment": True,
        "highlight": False,
    },
    "pay_as_you_go": {
        "name": "Pay as you go",
        "price": 0,
        "currency": "usd",
        "blurb": "No monthly fee — top up credits, pay only for tokens you burn",
        "tokens_included": 0,
        "agents": 10,
        "companies": 1,
        "projects": 5,
        "features": [
            "No monthly commitment",
            "Top up $10–$1000",
            "1 company · 5 projects · 10 agents",
            "All models at public rates",
        ],
        # Hidden from public plan lists / marketing (not offered at launch)
        "public": False,
        "requires_payment": False,
        "highlight": False,
    },
}


def public_plans() -> dict:
    return {k: v for k, v in PLANS.items() if v.get("public")}


def plan_limits(plan_id: str) -> dict:
    return PLANS.get(plan_id) or PLANS["none"]
