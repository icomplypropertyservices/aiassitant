"""Apply token usage against monthly included pool, then wallet credits."""
from datetime import datetime
from sqlalchemy.orm import Session
from . import models, config
from .plans import plan_limits
from .pricing import cost_for


def ensure_period(bal: models.Balance, user: models.User):
    """Reset monthly counters if a new calendar month started."""
    now = datetime.utcnow()
    start = bal.period_start or now
    if start.year != now.year or start.month != now.month:
        bal.period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        bal.tokens_used_period = 0
        limits = plan_limits(user.plan)
        bal.tokens_included = int(limits.get("tokens_included") or 0)


def meter_snapshot(db: Session, user: models.User) -> dict:
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal:
        bal = models.Balance(user_id=user.id, credits=0.0)
        db.add(bal)
        db.commit()
        db.refresh(bal)
    ensure_period(bal, user)
    db.commit()
    limits = plan_limits(user.plan)
    included = int(bal.tokens_included or limits.get("tokens_included") or 0)
    used = int(bal.tokens_used_period or 0)
    remaining_included = max(0, included - used)
    credits = round(bal.credits or 0.0, 4)
    pct = round(min(100.0, (used / included) * 100), 1) if included else 0.0
    included_exhausted = included > 0 and remaining_included <= 0
    # PAYG / zero-included: treat as exhausted pool so wallet is the gate
    if included <= 0:
        included_exhausted = True
    warn = pct >= 80 if included > 0 else False
    hard_block_soon = pct >= 95 if included > 0 else False
    hard_block = included_exhausted and credits < config.MIN_CREDITS
    if user.role == "admin":
        hard_block = False
    if hard_block:
        message = (
            "Included tokens are used up and wallet credits are too low. "
            "Top up on Billing to continue."
        )
    elif hard_block_soon:
        message = (
            f"You've used {pct}% of included tokens. "
            "Overage will bill wallet credits soon — top up if needed."
        )
    elif warn:
        message = f"You've used {pct}% of your included monthly tokens."
    elif included_exhausted and credits >= config.MIN_CREDITS:
        message = "Included tokens used; usage is billing wallet credits."
    else:
        message = ""
    return {
        "plan": user.plan,
        "plan_name": limits.get("name"),
        "subscription_active": bool(user.subscription_active or user.role == "admin"),
        "credits": credits,
        "tokens_included": included,
        "tokens_used_period": used,
        "tokens_remaining_included": remaining_included,
        "usage_percent": pct,
        "warn": warn,
        "hard_block_soon": hard_block_soon,
        "hard_block": hard_block,
        "message": message,
        "period_start": bal.period_start.isoformat() if bal.period_start else None,
        "limits": {
            "agents": limits.get("agents", 0),
            "companies": limits.get("companies", 0),
            "projects": limits.get("projects", 0),
        },
    }


def charge_usage(
    db: Session,
    user: models.User,
    model: str,
    input_tokens: int,
    output_tokens: int,
    company_id: int | None = None,
    project_id: int | None = None,
) -> dict:
    """Record usage, prefer monthly included tokens, else deduct credits."""
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal:
        bal = models.Balance(user_id=user.id, credits=0.0)
        db.add(bal)
        db.flush()
    ensure_period(bal, user)

    total = int(input_tokens) + int(output_tokens)
    cost = cost_for(model, input_tokens, output_tokens)
    bill_source = "included"
    limits = plan_limits(user.plan)
    included = int(bal.tokens_included or limits.get("tokens_included") or 0)
    used = int(bal.tokens_used_period or 0)

    if included > 0 and used < included:
        # Still inside included pool — no credit charge for VPS-ish usage.
        # Premium models always bill credits for the full cost (pool only covers compute allowance UX).
        bal.tokens_used_period = used + total
        if model.startswith(("claude", "grok")):
            bill_source = "credits"
            bal.credits = max(0.0, (bal.credits or 0.0) - cost)
        else:
            bill_source = "included"
            # Small overage fee only if this push exceeds pool
            over = max(0, (used + total) - included)
            if over > 0:
                over_cost = cost_for(model, 0, over)
                bal.credits = max(0.0, (bal.credits or 0.0) - over_cost)
                bill_source = "mixed"
    else:
        bill_source = "credits"
        bal.tokens_used_period = used + total
        bal.credits = max(0.0, (bal.credits or 0.0) - cost)

    row = models.TokenUsage(
        user_id=user.id,
        company_id=company_id,
        project_id=project_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cost,
        bill_source=bill_source,
    )
    db.add(row)
    db.commit()
    return {
        "tokens": total,
        "cost": cost,
        "bill_source": bill_source,
        "credits": round(bal.credits or 0.0, 4),
        "tokens_used_period": bal.tokens_used_period,
    }
