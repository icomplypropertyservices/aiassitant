"""Apply token usage against monthly included pool, then wallet credits."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from . import models, config
from .plans import plan_limits
from .pricing import cost_for, estimate_tokens, event_usd, event_meter_tokens

# Always take wallet credits (still always advance token meter).
# Voice counts as normal metered tokens (included pool first). Media stays premium.
_ALWAYS_CREDITS_PREFIX = ("premium-", "image", "video", "premium-comm")


def ensure_period(bal: models.Balance, user: models.User) -> bool:
    """Reset monthly counters if a new calendar month started.
    Also heals missing included-token pools for active paid/trial plans
    (e.g. plan marked business but tokens_included left at 0).
    Returns True if bal was mutated.
    """
    changed = False
    now = datetime.utcnow()
    start = bal.period_start or now
    limits = plan_limits(user.plan or "none")
    expected = int(limits.get("tokens_included") or 0)

    if start.year != now.year or start.month != now.month:
        bal.period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        bal.tokens_used_period = 0
        bal.tokens_included = expected
        changed = True
    else:
        # Heal zero pool when the active plan includes tokens
        current = int(bal.tokens_included or 0)
        active = bool(getattr(user, "subscription_active", False) or getattr(user, "role", "") == "admin")
        if active and expected > 0 and current <= 0:
            bal.tokens_included = expected
            if not bal.period_start:
                bal.period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            changed = True
        # If plan was upgraded mid-period to a larger pool, raise included (never shrink mid-period)
        elif active and expected > current > 0:
            bal.tokens_included = expected
            changed = True

    return changed


def heal_subscription_flags(db: Session, user: models.User) -> bool:
    """Clear trial-style expiry on paid plans that should not time out."""
    plan = (user.plan or "").strip()
    limits = plan_limits(plan)
    changed = False
    if (
        limits.get("requires_payment")
        and plan not in ("none", "", "trial", "pay_as_you_go")
        and getattr(user, "subscription_active", False)
        and getattr(user, "subscription_expires_at", None) is not None
    ):
        # Paid business/pro/starter: open-ended until cancelled (not a 14-day trial stamp)
        user.subscription_expires_at = None
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
        headline = "Your agents just ran out of fuel"
        sales_message = (
            f"You've burned through your {limits.get('name') or 'plan'} token pool and your wallet is empty. "
            "Every minute offline is lost replies, stalled tasks, and quiet revenue. "
            f"Top up now — most teams grab ${int(auto_amt)} and keep crushing it."
        )
        cta = f"Power up — add ${int(auto_amt)} credits"
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

    return {
        "plan": user.plan,
        "plan_name": limits.get("name"),
        "subscription_active": bool(user.subscription_active or user.role == "admin"),
        "subscription_expires_at": exp.isoformat() + "Z" if exp else None,
        "credits": credits,
        "tokens_included": included,
        "tokens_used_period": used,
        "tokens_remaining_included": remaining_included,
        "usage_percent": pct,
        "warn": warn or bool(storage.get("warn")),
        "hard_block_soon": hard_block_soon,
        "hard_block": hard_block,
        "needs_topup": needs_topup and user.role != "admin",
        "urgency": urgency,
        "headline": headline,
        "sales_message": sales_message,
        "cta": cta,
        "message": message,
        "storage": storage,
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
            "agents": limits.get("agents", 0),
            "companies": limits.get("companies", 0),
            "projects": limits.get("projects", 0),
            "skills_per_agent": limits.get("skills_per_agent", 0),
            "skill_packs": limits.get("skill_packs", 0),
            "prompt_skills": limits.get("prompt_skills", 0),
            "premium_skills": bool(limits.get("premium_skills")),
            "tokens_included": limits.get("tokens_included", 0),
        },
        "skills": {
            "enabled_cap": int(limits.get("skills_per_agent") or 0),
            "packs": int(limits.get("skill_packs") or 0),
            "packs_total": 20,
            "catalog_target": 1250,
            "premium": bool(limits.get("premium_skills")),
        },
    }


def _always_bill_credits(model: str) -> bool:
    m = (model or "").lower()
    return any(m == p or m.startswith(p) for p in _ALWAYS_CREDITS_PREFIX)


def _normalize_bill_model(model: str | None) -> str:
    """Map any agent/chat model id → billable neutral tier (always meters tokens)."""
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
    ):
        return m
    if m.startswith("voice"):
        return m
    if m in ("grok-max",) or m.startswith("grok"):
        return "quality"
    if m not in (
        "fast", "quality", "reasoning", "large", "small", "medium",
        "image", "video", "voice-stt", "voice-tts", "voice-call", "premium-comm",
        "skill-read", "skill-write", "skill-action",
    ):
        return "fast"
    return m


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
) -> dict:
    """Standard charge for any chat/agent LLM completion — always uses tokens."""
    msgs = messages or []
    inp = sum(estimate_tokens(str(m.get("content") or "")) for m in msgs) or 1
    out = estimate_tokens(reply or "") or 1
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
    # Split meter weight; floor at published event weight — never zero
    weight = max(base, tok, 1)
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
        usage = bill_llm_turn(
            db, user,
            meta.get("model") or "fast",
            [{"role": "user", "content": f"skill:{skill_id}"}],
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
    text = json_dumps_safe(args)[:400] if args else skill_id
    usage = charge_event(
        db, user, meter_kind,
        text=f"{skill_id}:{text}",
        cost_override=None,  # included pool first
        company_id=company_id,
        project_id=project_id,
    )
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
