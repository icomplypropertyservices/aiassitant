"""Apply token usage against monthly included pool, then wallet credits."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from . import models, config
from .plans import plan_limits
from .pricing import (
    cost_for,
    estimate_tokens,
    estimate_messages_tokens,
    event_usd,
    event_meter_tokens,
)

# Always take wallet credits (still always advance token meter).
# Voice counts as normal metered tokens (included pool first). Media stays premium.
_ALWAYS_CREDITS_PREFIX = ("premium-", "image", "video", "premium-comm")

# Keep in sync with billing.TRIAL_ENDED_MSG / Subscribe.jsx
TRIAL_ENDED_MSG = "Trial ended — subscribe to unlock full tool access"


def subscription_is_live(user: models.User | None) -> bool:
    """True when the user may use paid product features (agents, AI, plan pools).

    Admins always live. Expired trial/window (subscription_expires_at in the past)
    is NOT live even if the DB still has subscription_active=True (stale row).
    """
    if user is None:
        return False
    if getattr(user, "role", "") == "admin":
        return True
    if not getattr(user, "subscription_active", False):
        return False
    plan = (getattr(user, "plan", None) or "").strip()
    if plan in ("", "none"):
        return False
    exp = getattr(user, "subscription_expires_at", None)
    if exp is not None and exp < datetime.utcnow():
        return False
    return True


def ensure_period(bal: models.Balance, user: models.User) -> bool:
    """Reset monthly counters if a new calendar month started.
    Also heals missing included-token pools for *live* paid/trial plans
    (e.g. plan marked business but tokens_included left at 0).

    Critical: expired trials must NOT get a free monthly token refill just
    because the DB flag subscription_active was left True.
    Returns True if bal was mutated.
    """
    changed = False
    now = datetime.utcnow()
    start = bal.period_start or now
    limits = plan_limits(user.plan or "none")
    expected = int(limits.get("tokens_included") or 0)
    # Live access only — never refill pools for expired trials / cancelled subs
    live = subscription_is_live(user)

    if start.year != now.year or start.month != now.month:
        bal.period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if live:
            bal.tokens_used_period = 0
            bal.tokens_included = expected
        # Non-live: roll the period marker so we don't thrash, but do NOT
        # restore tokens_included or wipe usage (no free refill after expiry).
        changed = True
    else:
        # Heal zero pool when the *live* plan includes tokens
        current = int(bal.tokens_included or 0)
        if live and expected > 0 and current <= 0:
            bal.tokens_included = expected
            if not bal.period_start:
                bal.period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            changed = True
        # If plan was upgraded mid-period to a larger pool, raise included (never shrink mid-period)
        elif live and expected > current > 0:
            bal.tokens_included = expected
            changed = True

    return changed


def heal_subscription_flags(db: Session, user: models.User) -> bool:
    """Keep User plan/flags consistent with real access.

    - Paid plans: clear stray trial-style expiry stamps.
    - Expired trial/window: flip subscription_active=False so gates that only
      read the raw column stop treating the account as active.
    """
    plan = (user.plan or "").strip()
    limits = plan_limits(plan)
    changed = False
    now = datetime.utcnow()
    exp = getattr(user, "subscription_expires_at", None)

    if (
        limits.get("requires_payment")
        and plan not in ("none", "", "trial", "pay_as_you_go")
        and getattr(user, "subscription_active", False)
        and exp is not None
    ):
        # Paid business/pro/starter: open-ended until cancelled (not a 14-day trial stamp)
        user.subscription_expires_at = None
        changed = True
        exp = None

    # Expired time box (trial or any stamped window) with stale active flag
    if (
        getattr(user, "role", "") != "admin"
        and getattr(user, "subscription_active", False)
        and exp is not None
        and exp < now
    ):
        user.subscription_active = False
        changed = True

    return changed


def meter_snapshot(db: Session, user: models.User) -> dict:
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal:
        bal = models.Balance(user_id=user.id, credits=0.0)
        db.add(bal)
        db.commit()
        db.refresh(bal)
    dirty = ensure_period(bal, user)
    dirty = heal_subscription_flags(db, user) or dirty
    if dirty:
        db.commit()
        db.refresh(bal)
        db.refresh(user)
    else:
        db.commit()
    limits = plan_limits(user.plan or "none")
    included = int(bal.tokens_included or 0)
    if included <= 0:
        included = int(limits.get("tokens_included") or 0)
    used = int(bal.tokens_used_period or 0)
    remaining_included = max(0, included - used)
    credits = round(bal.credits or 0.0, 4)
    pct = round(min(100.0, (used / included) * 100), 1) if included else 0.0
    included_exhausted = included > 0 and remaining_included <= 0
    if included <= 0:
        included_exhausted = True
    warn = pct >= 80 if included > 0 else False
    hard_block_soon = pct >= 95 if included > 0 else False
    hard_block = included_exhausted and credits < config.MIN_CREDITS
    if user.role == "admin":
        hard_block = False

    auto_on = bool(getattr(bal, "auto_topup_enabled", False))
    auto_amt = float(getattr(bal, "auto_topup_amount", None) or 25.0)
    auto_cred_th = float(getattr(bal, "auto_topup_threshold_credits", None) or 5.0)
    auto_pct_th = int(getattr(bal, "auto_topup_token_pct", None) or 85)
    low_credits = credits < auto_cred_th
    low_tokens = included > 0 and pct >= auto_pct_th
    needs_topup = hard_block or hard_block_soon or (warn and low_credits) or (
        included_exhausted and low_credits
    ) or (low_tokens and low_credits)

    # Sales urgency tier for popups
    if hard_block:
        urgency = "critical"
        headline = "AI is paused — site still works"
        sales_message = (
            f"You've used your {limits.get('name') or 'plan'} token pool and the credit wallet is empty. "
            "Chat, agent runs, and media need a top-up. "
            "You can still browse agents, CRM, settings, and billing. "
            f"Most teams add ${int(auto_amt)} and keep going."
        )
        cta = f"Top up ${int(auto_amt)} to restart AI"
    elif hard_block_soon or (included_exhausted and credits < 15):
        urgency = "high"
        headline = "You're almost out — don't let agents go dark"
        sales_message = (
            f"{pct:.0f}% of your monthly tokens are already used. "
            "Premium runs and overage need wallet credits. "
            f"Smart teams auto top-up ${int(auto_amt)} so nothing stalls mid-deal."
        )
        cta = f"Keep momentum — top up ${int(auto_amt)}"
    elif warn or low_tokens:
        urgency = "medium"
        headline = "Running hot — top up before you hit the wall"
        sales_message = (
            f"You've used {pct:.0f}% of included tokens this month. "
            "Stay ahead of the limit: add credits or upgrade your plan for a bigger monthly pool. "
            "Your competitors don't pause when tokens run low."
        )
        cta = "Stay ahead — top up credits"
    elif low_credits and included_exhausted:
        urgency = "high"
        headline = "Wallet's light — overage needs fuel"
        sales_message = (
            f"Only ${credits:.2f} left in credits while you're on overage. "
            f"One-click top-up of ${int(auto_amt)} keeps chat, agents, and media flying."
        )
        cta = f"Refill ${int(auto_amt)} now"
    else:
        urgency = "ok"
        sales_message = ""
        headline = ""
        cta = "Top up"

    if hard_block:
        message = sales_message
    elif hard_block_soon:
        message = sales_message
    elif warn:
        message = sales_message
    elif included_exhausted and credits >= config.MIN_CREDITS:
        message = "Included tokens used; usage is billing wallet credits."
    else:
        message = ""

    exp = getattr(user, "subscription_expires_at", None)
    # Align with auth.user_out / subscription_is_live (expired trial → not live)
    plan_id = (user.plan or "").strip() or "none"
    exp_passed = bool(exp is not None and exp < datetime.utcnow() and user.role != "admin")
    subscription_live = subscription_is_live(user)
    needs_subscription = user.role != "admin" and not subscription_live
    # Training library storage quota (plan + purchased add-ons)
    storage = {}
    try:
        from .storage_quota import storage_snapshot
        storage = storage_snapshot(db, user)
    except Exception:
        storage = {}
    if storage.get("hard_block") and urgency == "ok":
        urgency = "medium"
        if not headline:
            headline = "Training storage is full"
            sales_message = storage.get("upgrade_hint") or (
                "Free up files or upgrade storage / plan to keep uploading."
            )
            cta = "Upgrade storage"
        needs_topup = needs_topup or True
    elif storage.get("warn") and urgency == "ok":
        urgency = "medium"
        if not headline:
            headline = "Training storage running low"
            sales_message = storage.get("upgrade_hint") or "Consider a storage add-on or plan upgrade."
            cta = "Get more storage"

    # Trial-ended: free trial used/expired (not paid cancel). Accurate free-grant messaging.
    # Paid cancel → needs_subscription without trial_ended (still "Subscribe").
    trial_ended = bool(
        needs_subscription
        and (
            plan_id == "trial"
            or (exp_passed and plan_id in ("none", "", "trial", "pay_as_you_go"))
            or (
                exp is not None
                and plan_id in ("none", "", "trial", "pay_as_you_go")
                and not limits.get("requires_payment")
            )
        )
    )
    # Frontend CTA: no plan / expired trial → Subscribe; active but low → Billing top-up
    if needs_subscription:
        if trial_ended:
            if not headline or headline == "Choose a plan to unlock agents & AI":
                # Match billing.TRIAL_ENDED_MSG / Subscribe.jsx (402 detail + UI)
                headline = "Trial ended — subscribe to unlock full tool access"
            sales_message = sales_message or (
                "Your free trial is no longer active. Choose Starter, Pro, or Business "
                "(card or crypto). No free wallet credits — paid access unlocks after checkout."
            )
            cta = "Subscribe now"
        elif not headline:
            headline = "Choose a plan to unlock agents & AI"
            sales_message = sales_message or (
                f"Start free trial ({int(limits.get('agents') or 12)} agents · "
                f"{int(limits.get('tokens_included') or 50_000):,} tokens) — no card — "
                "or subscribe for a full monthly pool. Wallet credits are never free-granted in production."
            )
            cta = "Choose a plan"
        if urgency == "ok":
            urgency = "high"
        upgrade_path = "/subscribe"
        primary_cta = {"label": cta, "path": "/subscribe", "action": "subscribe"}
        secondary_cta = None
    elif hard_block or (included_exhausted and low_credits) or needs_topup:
        # Low fuel: clear dual path — buy credits OR upgrade plan
        if hard_block:
            primary_cta = {
                "label": f"Buy credits · top up ${int(auto_amt)}",
                "path": "/billing",
                "action": "topup",
            }
            secondary_cta = {
                "label": "Upgrade plan",
                "path": "/subscribe" if plan_id in ("trial", "starter", "pay_as_you_go", "none") else "/billing",
                "action": "subscribe",
            }
            cta = primary_cta["label"]
        else:
            primary_cta = {
                "label": f"Buy credits · top up ${int(auto_amt)}",
                "path": "/billing",
                "action": "topup",
            }
            secondary_cta = {
                "label": "Upgrade plan",
                "path": "/subscribe" if plan_id in ("trial", "starter", "pay_as_you_go") else "/billing",
                "action": "subscribe",
            }
            if not cta or cta == "Top up":
                cta = primary_cta["label"]
        upgrade_path = (
            "/subscribe"
            if plan_id in ("trial", "starter", "pay_as_you_go") and (warn or hard_block or hard_block_soon)
            else "/billing"
        )
    elif plan_id in ("trial", "starter", "pay_as_you_go") and (warn or hard_block or hard_block_soon):
        upgrade_path = "/subscribe"
        primary_cta = {"label": cta or "Upgrade plan", "path": "/subscribe", "action": "subscribe"}
        secondary_cta = {"label": "Buy credits", "path": "/billing", "action": "topup"}
    else:
        upgrade_path = "/billing"
        primary_cta = None
        secondary_cta = None

    # Null-safe numeric fields for UI formatters (never emit bare None that crashes .toFixed)
    try:
        agents_cap = int(limits.get("agents") or 0)
    except (TypeError, ValueError):
        agents_cap = 0
    try:
        tokens_cap = int(limits.get("tokens_included") or 0)
    except (TypeError, ValueError):
        tokens_cap = 0

    return {
        "plan": user.plan or "none",
        "plan_name": limits.get("name") or "No plan",
        "subscription_active": subscription_live,
        "subscription_expires_at": exp.isoformat() + "Z" if exp else None,
        "needs_subscription": needs_subscription,
        "trial_ended": trial_ended,
        "upgrade_cta_path": upgrade_path or "/subscribe",
        # Structured CTAs for header meter + Billing page (buy credits / subscribe)
        "primary_cta": primary_cta,
        "secondary_cta": secondary_cta,
        "cta_buy_credits_path": "/billing",
        "cta_subscribe_path": "/subscribe",
        "credits": float(credits) if credits is not None else 0.0,
        "tokens_included": int(included or 0),
        "tokens_used_period": int(used or 0),
        "tokens_remaining_included": int(remaining_included or 0),
        "usage_percent": float(pct) if pct is not None else 0.0,
        "warn": bool(warn or storage.get("warn")),
        "hard_block_soon": bool(hard_block_soon),
        "hard_block": bool(hard_block),
        "needs_topup": bool(needs_topup and user.role != "admin"),
        "urgency": urgency or "ok",
        "headline": headline or "",
        "sales_message": sales_message or "",
        "cta": cta or "Top up",
        "message": message or "",
        "storage": storage or {},
        "period_start": bal.period_start.isoformat() if bal.period_start else None,
        "auto_topup": {
            "enabled": auto_on,
            "amount": auto_amt,
            "threshold_credits": auto_cred_th,
            "token_pct": auto_pct_th,
            "should_trigger": bool(
                auto_on
                and user.role != "admin"
                and (low_credits or low_tokens or hard_block or hard_block_soon)
            ),
            "last_at": (
                bal.auto_topup_last_at.isoformat()
                if getattr(bal, "auto_topup_last_at", None)
                else None
            ),
        },
        "suggested_amounts": [10, 25, 50, 100],
        "upgrade_teaser": (
            limits.get("upgrade_teaser")
            or (
                "Pro unlocks 10M tokens, 40 agents, 500 skills/agent, all skill packs."
                if (user.plan or "") in ("trial", "starter", "none")
                else (
                    "Business unlocks 40M tokens, 120 agents, 1,000 skills/agent."
                    if (user.plan or "") == "pro"
                    else None
                )
            )
        ),
        "limits": {
            "agents": agents_cap,
            "companies": int(limits.get("companies") or 0),
            "projects": int(limits.get("projects") or 0),
            "skills_per_agent": int(limits.get("skills_per_agent") or 0),
            "skill_packs": int(limits.get("skill_packs") or 0),
            "prompt_skills": int(limits.get("prompt_skills") or 0),
            "premium_skills": bool(limits.get("premium_skills")),
            "tokens_included": tokens_cap,
        },
        "skills": {
            "enabled_cap": int(limits.get("skills_per_agent") or 0),
            "packs": int(limits.get("skill_packs") or 0),
            "packs_total": 20,
            "catalog_target": 1250,
            "premium": bool(limits.get("premium_skills")),
            # Fail-closed: premium skills never free-run when wallet/billing fails
            "premium_fail_closed": True,
            "premium_note": (
                "Premium skills (email send, image/video, paid comms) charge wallet credits "
                "before run. If billing fails or credits are insufficient, the skill returns "
                "an error — it does not execute free."
            ),
        },
        "billing_policy": {
            "free_wallet_grants": False,  # production never mints free credits
            "trial_agents": agents_cap if plan_id == "trial" else 12,
            "trial_tokens": 50_000,
            "premium_skills_fail_closed": True,
            "premium_skills_fail_closed_note": (
                "Premium skill execution is fail-closed: charge wallet first; on billing failure "
                "or insufficient credits the skill aborts with an error (no free run)."
            ),
            "included_pool_first": True,
            "media_always_wallet": True,
        },
    }


def _always_bill_credits(model: str) -> bool:
    m = (model or "").lower()
    return any(m == p or m.startswith(p) for p in _ALWAYS_CREDITS_PREFIX)


def _normalize_bill_model(model: str | None) -> str:
    """Map any agent/chat model id → billable catalog id (always meters tokens)."""
    try:
        from .agent_scaffold import map_model
        m = map_model(model)
    except Exception:
        m = (model or "fast").lower().strip()
    m = (m or "fast").lower().strip().replace("_", "-")
    # Voice / media / skill meters keep their catalog ids
    if m in (
        "voice-stt", "voice-tts", "voice-call", "image", "video", "premium-comm",
        "skill-read", "skill-write", "skill-action",
        "fast", "quality", "reasoning", "large", "small", "medium",
        "grok-4.3", "grok-max", "grok-4.5",
    ):
        return m
    if m.startswith("voice"):
        return m
    # Grok family → explicit billable ids (do not collapse all to quality)
    if "4.3" in m or m in ("grok-3", "grok"):
        return "grok-4.3"
    if m in ("grok-max",) or "4.5" in m or m.startswith("grok-4.5"):
        return "grok-max"
    if m.startswith("grok"):
        return "grok-4.3"
    return "quality"


def charge_usage(
    db: Session,
    user: models.User,
    model: str,
    input_tokens: int,
    output_tokens: int,
    company_id: int | None = None,
    project_id: int | None = None,
    cost_override: float | None = None,
) -> dict:
    """
    Record usage and ALWAYS advance tokens_used_period (every chat/voice/agent turn).

    cost_override: flat USD for premium media/skills only.
    Voice + managed chat: token pool first, then wallet at PRICING rates.
    """
    bill_model = _normalize_bill_model(model)

    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal:
        bal = models.Balance(user_id=user.id, credits=0.0)
        db.add(bal)
        db.flush()
    ensure_period(bal, user)

    inp = max(0, int(input_tokens or 0))
    out = max(0, int(output_tokens or 0))
    total = inp + out
    if total <= 0:
        total = 1
        out = 1
        inp = 0
    # Floor for real chat/agent turns so tiny under-estimates still meter meaningfully
    # (skills/events pass their own weights; do not inflate fixed cost_override media)
    if cost_override is None and bill_model in (
        "fast", "quality", "reasoning", "large", "small", "medium",
        "grok-4.3", "grok-max", "grok-4.5",
    ):
        floor = 48 if bill_model in ("small", "fast") else 80
        if total < floor:
            # Prefer padding output (what the model "produced")
            out = out + (floor - total)
            total = floor

    if cost_override is not None:
        cost = round(float(cost_override), 6)
    else:
        cost = cost_for(bill_model, inp, out)

    limits = plan_limits(user.plan)
    included = int(bal.tokens_included or limits.get("tokens_included") or 0)
    used = int(bal.tokens_used_period or 0)
    # ALWAYS meter tokens — every voice, chat, agent reply, skill LLM call
    bal.tokens_used_period = used + total

    premium = _always_bill_credits(bill_model) or (
        cost_override is not None and bill_model in ("image", "video", "premium-comm")
    )
    is_admin = user.role == "admin"
    bill_source = "included"

    if is_admin:
        bill_source = "admin"
        applied_cost = 0.0
    elif premium:
        bill_source = "credits"
        bal.credits = max(0.0, (bal.credits or 0.0) - cost)
        applied_cost = cost
    elif included > 0 and used < included:
        bill_source = "included"
        applied_cost = 0.0
        over = max(0, (used + total) - included)
        if over > 0:
            over_cost = cost_for(bill_model, 0, over) if cost_override is None else cost
            bal.credits = max(0.0, (bal.credits or 0.0) - over_cost)
            bill_source = "mixed"
            applied_cost = over_cost
    else:
        bill_source = "credits"
        bal.credits = max(0.0, (bal.credits or 0.0) - cost)
        applied_cost = cost

    row = models.TokenUsage(
        user_id=user.id,
        company_id=company_id,
        project_id=project_id,
        model=bill_model,
        input_tokens=inp,
        output_tokens=out,
        cost=applied_cost,
        bill_source=bill_source,
    )
    db.add(row)
    db.commit()
    return {
        "tokens": total,
        "cost": applied_cost,
        "bill_source": bill_source,
        "credits": round(bal.credits or 0.0, 4),
        "tokens_used_period": bal.tokens_used_period,
        "model": bill_model,
    }


def bill_llm_turn(
    db: Session,
    user: models.User,
    model: str,
    messages: list[dict] | None,
    reply: str,
    *,
    company_id: int | None = None,
    project_id: int | None = None,
    usage: dict | None = None,
) -> dict:
    """Standard charge for any chat/agent LLM completion — always uses tokens.

    Prefer provider ``usage`` (prompt/completion counts) when present; else estimate
    full message list + reply with framing overhead.
    """
    msgs = messages or []
    api_inp = None
    api_out = None
    if isinstance(usage, dict):
        for k in ("prompt_tokens", "input_tokens", "prompt_eval_count"):
            if usage.get(k) is not None:
                try:
                    api_inp = int(usage[k])
                    break
                except (TypeError, ValueError):
                    pass
        for k in ("completion_tokens", "output_tokens", "eval_count"):
            if usage.get(k) is not None:
                try:
                    api_out = int(usage[k])
                    break
                except (TypeError, ValueError):
                    pass
        # Some APIs only send total_tokens
        if api_inp is None and api_out is None and usage.get("total_tokens") is not None:
            try:
                tot = max(1, int(usage["total_tokens"]))
                api_inp = max(1, tot * 2 // 3)
                api_out = max(1, tot - api_inp)
            except (TypeError, ValueError):
                pass

    est_inp = estimate_messages_tokens(msgs) or 1
    est_out = estimate_tokens(reply or "") or 1
    # Take the larger of API vs estimate so we never under-charge when API is low/missing
    if api_inp is not None and api_out is not None:
        inp = max(api_inp, est_inp // 2)  # API trusted, but never less than half estimate
        out = max(api_out, min(est_out, api_out * 2) if api_out > 0 else est_out)
        # Prefer full estimate if API total is suspiciously small vs text size
        if (api_inp + api_out) < max(32, (est_inp + est_out) // 3):
            inp, out = est_inp, est_out
        else:
            inp = max(api_inp, 1)
            out = max(api_out, 1)
            # Still don't go below estimate when reply is long
            if est_out > out * 1.5:
                out = est_out
            if est_inp > inp * 1.5:
                inp = est_inp
    else:
        inp, out = est_inp, est_out

    return charge_usage(
        db, user, model, inp, out,
        company_id=company_id,
        project_id=project_id,
    )


def charge_event(
    db: Session,
    user: models.User,
    kind: str,
    *,
    text: str = "",
    cost_override: float | None = None,
    company_id: int | None = None,
    project_id: int | None = None,
) -> dict:
    """Bill voice / media / premium events — always increments token meter."""
    kind_key = (kind or "usage").replace("_", "-").lower()
    model_map = {
        "voice-stt": "voice-stt",
        "voice_stt": "voice-stt",
        "voice-tts": "voice-tts",
        "voice_tts": "voice-tts",
        "voice-call": "voice-call",
        "voice_call": "voice-call",
        "image": "image",
        "video": "video",
        "premium-comm": "premium-comm",
        "premium-skill": "premium-comm",
        "skill-read": "skill-read",
        "skill-write": "skill-write",
        "skill-action": "skill-action",
        "skill_read": "skill-read",
        "skill_write": "skill-write",
        "skill_action": "skill-action",
    }
    model = model_map.get(kind, model_map.get(kind_key, kind_key))

    base = event_meter_tokens(model)
    tok = estimate_tokens(text) if text else 0
    # Split meter weight; floor at published event weight — never zero.
    # Scale skill text: args+results often under-count if only id is passed.
    weight = max(base, tok, 1)
    if model in ("skill-read", "skill-write", "skill-action") and tok > 0:
        weight = max(weight, base + tok)
    inp = max(1, weight // 2)
    out = max(1, weight - inp)

    # Voice + skill actions: token-pool first (no flat wallet force).
    # Media / premium-comm: flat wallet when EVENT_PRICING has usd.
    if model in ("voice-stt", "voice-tts", "voice-call", "skill-read", "skill-write", "skill-action"):
        flat = cost_override  # usually None → rate-based tokens from included pool
    else:
        flat = cost_override if cost_override is not None else event_usd(model)
    return charge_usage(
        db, user, model, inp, out,
        company_id=company_id,
        project_id=project_id,
        cost_override=flat,
    )


_READ_SKILL_PREFIXES = ("list_", "get_", "search_", "read_")
_READ_SKILL_IDS = frozenset({
    "pipeline_summary", "weekly_review", "get_time", "suggest_times",
    "list_team", "agent_compare", "skill_recommend",
})
_HEAVY_WRITE_IDS = frozenset({
    "spawn_agent", "spawn_team", "spawn_specialist", "clone_agent",
    "execute_goal", "create_skill", "publish_skill_to_bay",
    "generate_content", "research", "summarize",
})


def classify_skill_billing(skill_id: str, meta: dict | None = None) -> str:
    """
    premium | llm | read | write

    premium — wallet credits (cost_credits)
    llm — token bill via bill_llm_turn (chat-quality)
    read — light skill-read meter (included pool first)
    write — skill-write meter (included pool first)
    """
    meta = meta or {}
    if meta.get("premium"):
        return "premium"
    sid = (skill_id or "").strip()
    if meta.get("handler") in ("catalog_deliverable", "created_skill") or sid.startswith("custom_"):
        return "llm"
    if sid.startswith(_READ_SKILL_PREFIXES) or sid in _READ_SKILL_IDS:
        return "read"
    if sid in _HEAVY_WRITE_IDS:
        return "write"
    return "write"


def bill_skill_execution(
    db: Session,
    user: models.User,
    skill_id: str,
    meta: dict | None,
    result: dict | None,
    args: dict | None,
    *,
    company_id: int | None = None,
    project_id: int | None = None,
) -> dict:
    """
    Ensure every successful skill run is metered:
    - premium: already charged wallet (cost_credits) before run
    - llm: use handler-attached usage or bill content length
    - read/write: included token pool first, then wallet at skill-* rates
    """
    meta = meta or {}
    args = args or {}
    result = result if isinstance(result, dict) else {}

    if getattr(user, "role", None) == "admin":
        return {"bill_source": "admin", "cost": 0.0, "tokens": 0, "kind": "admin"}

    kind = classify_skill_billing(skill_id, meta)

    # Premium already charged at execute_skill entry
    if kind == "premium" and args.get("_billed"):
        cost = float(meta.get("cost_credits") or 0.02)
        return {
            "bill_source": "credits",
            "cost": cost,
            "tokens": event_meter_tokens(str(meta.get("meter_kind") or "premium-comm").replace("_", "-")),
            "kind": "premium",
            "already_billed": True,
        }

    # Handler already attached usage (e.g. catalog deliverable / a2a reply)
    if isinstance(result.get("usage"), dict) and result["usage"].get("tokens") is not None:
        return {**result["usage"], "kind": result["usage"].get("kind") or kind}

    # LLM-shaped results without usage — bill as chat tokens
    content = (
        result.get("content")
        or result.get("deliverable")
        or result.get("reply")
        or result.get("reply_text")
        or ""
    )
    if kind == "llm" or (content and len(str(content)) > 80):
        arg_blob = json_dumps_safe(args)[:2000] if args else ""
        usage = bill_llm_turn(
            db, user,
            meta.get("model") or "quality",
            [
                {"role": "system", "content": f"skill:{skill_id}"},
                {"role": "user", "content": arg_blob or skill_id},
            ],
            str(content)[:12_000] or skill_id,
            company_id=company_id,
            project_id=project_id,
        )
        usage["kind"] = "llm"
        return usage

    # Read / write action meters — always hit the pool
    meter_kind = "skill-read" if kind == "read" else "skill-write"
    if meta.get("meter_tokens"):
        try:
            weight = max(10, int(meta["meter_tokens"]))
        except Exception:
            weight = event_meter_tokens(meter_kind)
    else:
        weight = event_meter_tokens(meter_kind)
    # Include result summary so successful writes (CRM ids, etc.) meter fairly
    result_blob = ""
    try:
        result_blob = json_dumps_safe({
            k: result.get(k)
            for k in ("message", "customer_id", "deal_id", "task_id", "memory_id", "ok", "error")
            if result.get(k) is not None
        })[:600]
    except Exception:
        result_blob = str(result.get("message") or "")[:400]
    text = json_dumps_safe(args)[:800] if args else skill_id
    usage = charge_event(
        db, user, meter_kind,
        text=f"{skill_id}:{text}:{result_blob}",
        cost_override=None,  # included pool first
        company_id=company_id,
        project_id=project_id,
    )
    # Ensure floor weight was applied (charge_event uses EVENT base + text)
    if int(usage.get("tokens") or 0) < weight:
        extra = weight - int(usage.get("tokens") or 0)
        try:
            usage2 = charge_usage(
                db, user, meter_kind, extra // 2 or 1, extra - (extra // 2 or 1),
                company_id=company_id, project_id=project_id,
            )
            usage = {
                **usage,
                "tokens": int(usage.get("tokens") or 0) + int(usage2.get("tokens") or 0),
                "cost": float(usage.get("cost") or 0) + float(usage2.get("cost") or 0),
                "tokens_used_period": usage2.get("tokens_used_period"),
                "credits": usage2.get("credits"),
            }
        except Exception:
            pass
    # charge_event may not use our weight if EVENT has meter_tokens — re-charge if needed?
    # EVENT skill-read has 20 tokens; skill-write 50 — good enough
    usage["kind"] = kind
    usage["skill_id"] = skill_id
    return usage


def json_dumps_safe(obj) -> str:
    import json
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return str(obj)[:200]
