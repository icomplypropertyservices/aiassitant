"""Critical user billing: trial expiry must not keep access or free token refills."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app import models
from app.usage_billing import (
    ensure_period,
    heal_subscription_flags,
    meter_snapshot,
    subscription_is_live,
    TRIAL_ENDED_MSG,
)
from app.auth_utils import ensure_credits


def _user(db, **kwargs):
    defaults = dict(
        email=f"bill_{kwargs.get('id', 'x')}@example.com",
        name="Bill Test",
        password_hash="x",
        role="user",
        plan="trial",
        subscription_active=True,
        email_verified=True,
    )
    defaults.update(kwargs)
    # unique email
    if "email" not in kwargs:
        defaults["email"] = f"bill_{datetime.utcnow().timestamp()}_{id(defaults)}@example.com"
    u = models.User(**defaults)
    db.add(u)
    db.flush()
    return u


def _bal(db, user, **kwargs):
    defaults = dict(
        user_id=user.id,
        credits=0.0,
        tokens_included=50_000,
        tokens_used_period=0,
        period_start=datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0),
    )
    defaults.update(kwargs)
    b = models.Balance(**defaults)
    db.add(b)
    db.flush()
    return b


def test_subscription_is_live_expired_trial(db):
    past = datetime.utcnow() - timedelta(days=1)
    u = _user(db, plan="trial", subscription_active=True, subscription_expires_at=past)
    assert subscription_is_live(u) is False


def test_subscription_is_live_active_trial(db):
    future = datetime.utcnow() + timedelta(days=7)
    u = _user(db, plan="trial", subscription_active=True, subscription_expires_at=future)
    assert subscription_is_live(u) is True


def test_heal_expires_stale_trial_flag(db):
    past = datetime.utcnow() - timedelta(days=2)
    u = _user(db, plan="trial", subscription_active=True, subscription_expires_at=past)
    assert heal_subscription_flags(db, u) is True
    assert u.subscription_active is False
    assert subscription_is_live(u) is False


def test_heal_clears_paid_expiry_stamp(db):
    u = _user(
        db,
        plan="pro",
        subscription_active=True,
        subscription_expires_at=datetime.utcnow() + timedelta(days=5),
    )
    assert heal_subscription_flags(db, u) is True
    assert u.subscription_expires_at is None
    assert subscription_is_live(u) is True


def test_ensure_period_no_refill_for_expired_trial(db):
    past = datetime.utcnow() - timedelta(days=1)
    u = _user(db, plan="trial", subscription_active=True, subscription_expires_at=past)
    # Stale active flag + exhausted pool from last month period
    last_month = (datetime.utcnow().replace(day=1) - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    bal = _bal(
        db,
        u,
        tokens_included=0,
        tokens_used_period=50_000,
        period_start=last_month,
    )
    ensure_period(bal, u)
    # Must NOT restore 50k free tokens for expired trial
    assert int(bal.tokens_included or 0) == 0
    assert int(bal.tokens_used_period or 0) == 50_000


def test_ensure_period_refills_live_paid_on_month_roll(db):
    u = _user(
        db,
        plan="starter",
        subscription_active=True,
        subscription_expires_at=None,
    )
    last_month = (datetime.utcnow().replace(day=1) - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    bal = _bal(
        db,
        u,
        tokens_included=100,
        tokens_used_period=100,
        period_start=last_month,
    )
    ensure_period(bal, u)
    assert int(bal.tokens_included or 0) >= 2_000_000
    assert int(bal.tokens_used_period or 0) == 0


def test_meter_snapshot_trial_ended(db):
    past = datetime.utcnow() - timedelta(days=1)
    u = _user(db, plan="trial", subscription_active=True, subscription_expires_at=past)
    _bal(db, u)
    db.commit()
    snap = meter_snapshot(db, u)
    assert snap["needs_subscription"] is True
    assert snap["trial_ended"] is True
    assert snap["subscription_active"] is False
    # Heal should have flipped the DB flag
    db.refresh(u)
    assert u.subscription_active is False


def test_ensure_credits_blocks_expired_trial(db):
    past = datetime.utcnow() - timedelta(days=1)
    u = _user(db, plan="trial", subscription_active=True, subscription_expires_at=past)
    _bal(db, u, tokens_included=50_000, tokens_used_period=0)
    db.commit()
    with pytest.raises(HTTPException) as ei:
        ensure_credits(db, u.id)
    assert ei.value.status_code == 402
    detail = ei.value.detail
    if isinstance(detail, dict):
        assert detail.get("code") == "trial_ended"
        assert TRIAL_ENDED_MSG in str(detail.get("message") or "")
    else:
        assert TRIAL_ENDED_MSG in str(detail)
    db.refresh(u)
    assert u.subscription_active is False
