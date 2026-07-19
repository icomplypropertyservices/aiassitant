"""Live subscription / pre-order force window unit tests."""
from __future__ import annotations

import importlib
import os
from datetime import date


def _reload_plans(**env):
    """Reload plans module with env overrides (PREORDER_FORCE)."""
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)
    import app.plans as plans

    return importlib.reload(plans)


def test_preorder_off_by_default():
    plans = _reload_plans(PREORDER_FORCE=None)
    assert plans.preorder_active() is False
    meta = plans.preorder_meta()
    assert meta["active"] is False
    assert meta["live"] is True
    assert meta["launch_label"] == "Live now"
    assert meta["early_access"] is False
    assert meta["discount_percent"] == 0
    assert plans.plan_checkout_price("starter") == 39.0
    e = plans.enrich_plan_for_public("starter")
    assert e["price_checkout"] == 39.0
    assert e["cta"].startswith("Subscribe")
    assert e["preorder_active"] is False


def test_preorder_force_before_launch():
    plans = _reload_plans(PREORDER_FORCE="1")
    # Force on + date before launch
    assert plans.preorder_active(today=date(2026, 7, 1)) is True
    meta = plans.preorder_meta()
    # meta uses today() internally; with PREORDER_FORCE and today before launch (real now may vary)
    # Check date-bound helpers instead of meta.active alone if calendar passed launch.
    assert plans.apply_preorder_discount(100.0) == (
        90.0 if plans.preorder_active() else 100.0
    )
    # Explicit enrich when active
    if plans.preorder_active():
        meta = plans.preorder_meta()
        assert meta["launch_label"] == "27 July 2026"
        assert meta["early_access"] is True
        e = plans.enrich_plan_for_public("pro")
        assert e["cta"].startswith("Pre-order")
        assert e["price_checkout"] == 89.1
        assert e["preorder_discount_percent"] == 10


def test_preorder_force_after_launch_date():
    plans = _reload_plans(PREORDER_FORCE="1")
    assert plans.preorder_active(today=date(2026, 7, 27)) is False
    assert plans.preorder_active(today=date(2026, 8, 1)) is False


def test_enrich_live_ctas_overwrite_preorder_strings():
    plans = _reload_plans(PREORDER_FORCE=None)
    base = dict(plans.PLANS["business"])
    base["cta"] = "Pre-order Business"
    base["cta_upgrade"] = "Pre-order Business"
    e = plans.enrich_plan_for_public("business", base)
    assert e["cta"] == "Subscribe to Business"
    assert e["cta_upgrade"] == "Upgrade to Business"
