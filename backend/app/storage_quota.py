"""User training-library storage monitoring, plan limits, and upgrade add-ons."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models
from .plans import plan_limits, STORAGE_ADDONS, storage_bytes_for_plan


def GB(n: float) -> int:
    return int(n * 1024 * 1024 * 1024)


def fmt_bytes(n: int | float | None) -> str:
    n = float(n or 0)
    if n < 1024:
        return f"{int(n)} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / (1024 ** 2):.1f} MB"
    return f"{n / (1024 ** 3):.2f} GB"


def user_storage_used_bytes(db: Session, user_id: int) -> int:
    """Sum KnowledgeFile.size_bytes for this user (training library)."""
    total = (
        db.query(func.coalesce(func.sum(models.KnowledgeFile.size_bytes), 0))
        .filter(models.KnowledgeFile.user_id == user_id)
        .scalar()
    )
    return int(total or 0)


def user_storage_bonus_bytes(db: Session, user: models.User) -> int:
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal:
        return 0
    return int(getattr(bal, "storage_bonus_bytes", None) or 0)


def user_storage_limit_bytes(db: Session, user: models.User) -> int:
    """Plan base + purchased bonus. Admins unlimited (0 = unlimited sentinel)."""
    if getattr(user, "role", None) == "admin":
        return 0  # unlimited
    plan = user.plan or "none"
    base = storage_bytes_for_plan(plan)
    bonus = user_storage_bonus_bytes(db, user)
    return int(base + bonus)


def storage_snapshot(db: Session, user: models.User) -> dict[str, Any]:
    used = user_storage_used_bytes(db, user.id)
    limit = user_storage_limit_bytes(db, user)
    bonus = user_storage_bonus_bytes(db, user)
    plan = user.plan or "none"
    limits = plan_limits(plan)
    plan_bytes = storage_bytes_for_plan(plan)
    unlimited = limit == 0 and getattr(user, "role", None) == "admin"
    if unlimited:
        pct = 0.0
        remaining = None
        warn = False
        hard = False
    else:
        pct = round(min(100.0, (used / limit) * 100), 1) if limit > 0 else (100.0 if used > 0 else 0.0)
        remaining = max(0, limit - used)
        warn = pct >= 80 if limit > 0 else used > 0
        hard = used >= limit if limit > 0 else False

    next_plan = limits.get("next_plan")
    upgrade_hint = None
    if hard or warn:
        if next_plan:
            np = plan_limits(next_plan)
            upgrade_hint = (
                f"Upgrade to {np.get('name') or next_plan} for "
                f"{fmt_bytes(storage_bytes_for_plan(next_plan))} plan storage, "
                "or buy a storage add-on."
            )
        else:
            upgrade_hint = "Buy a storage add-on pack to expand your library."

    return {
        "used_bytes": used,
        "used_human": fmt_bytes(used),
        "limit_bytes": None if unlimited else limit,
        "limit_human": "Unlimited" if unlimited else fmt_bytes(limit),
        "remaining_bytes": remaining,
        "remaining_human": "Unlimited" if unlimited else fmt_bytes(remaining or 0),
        "plan_bytes": plan_bytes,
        "plan_human": fmt_bytes(plan_bytes),
        "bonus_bytes": bonus,
        "bonus_human": fmt_bytes(bonus),
        "usage_percent": pct,
        "warn": warn and not unlimited,
        "hard_block": hard and not unlimited,
        "unlimited": unlimited,
        "plan": plan,
        "plan_name": limits.get("name"),
        "next_plan": next_plan,
        "upgrade_hint": upgrade_hint,
        "addons": list_storage_addons_public(),
    }


def assert_storage_allows(
    db: Session,
    user: models.User,
    additional_bytes: int,
    *,
    replace_bytes: int = 0,
) -> dict[str, Any]:
    """
    Raise HTTP 402/403-style 400 if adding `additional_bytes` would exceed quota.
    `replace_bytes` is size being replaced (e.g. note content update).
    """
    if getattr(user, "role", None) == "admin":
        return storage_snapshot(db, user)

    add = max(0, int(additional_bytes or 0))
    repl = max(0, int(replace_bytes or 0))
    net = max(0, add - repl)
    if net <= 0:
        return storage_snapshot(db, user)

    snap = storage_snapshot(db, user)
    limit = snap.get("limit_bytes") or 0
    used = int(snap.get("used_bytes") or 0)
    if limit <= 0 and not snap.get("unlimited"):
        raise HTTPException(
            402,
            detail={
                "error": "storage_limit",
                "message": (
                    "No storage included on your plan. "
                    "Upgrade your plan or buy a storage add-on."
                ),
                "storage": snap,
            },
        )
    if used - repl + add > limit:
        raise HTTPException(
            402,
            detail={
                "error": "storage_limit",
                "message": (
                    f"Storage full: {snap['used_human']} of {snap['limit_human']} used. "
                    f"Need {fmt_bytes(add)} free. "
                    + (snap.get("upgrade_hint") or "Upgrade plan or buy more storage.")
                ),
                "storage": snap,
                "needed_bytes": add,
            },
        )
    return snap


def grant_storage_addon(db: Session, user: models.User, addon_id: str) -> dict[str, Any]:
    addon = STORAGE_ADDONS.get(addon_id)
    if not addon:
        raise ValueError(f"Unknown storage add-on: {addon_id}")
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal:
        bal = models.Balance(user_id=user.id, credits=0.0, storage_bonus_bytes=0)
        db.add(bal)
        db.flush()
    add_bytes = int(addon.get("bytes") or 0)
    bal.storage_bonus_bytes = int(getattr(bal, "storage_bonus_bytes", None) or 0) + add_bytes
    db.flush()
    return {
        "ok": True,
        "addon_id": addon_id,
        "added_bytes": add_bytes,
        "added_human": fmt_bytes(add_bytes),
        "bonus_bytes": int(bal.storage_bonus_bytes or 0),
        "storage": storage_snapshot(db, user),
    }


def list_storage_addons_public() -> list[dict[str, Any]]:
    out = []
    for aid, a in STORAGE_ADDONS.items():
        if not a.get("public", True):
            continue
        out.append({
            "id": aid,
            "name": a.get("name"),
            "blurb": a.get("blurb"),
            "price_usd": float(a.get("price_usd") or 0),
            "gb": a.get("gb"),
            "bytes": int(a.get("bytes") or 0),
            "human": fmt_bytes(a.get("bytes") or 0),
            "cta": a.get("cta") or f"Add {a.get('gb')} GB",
        })
    return sorted(out, key=lambda x: (x.get("price_usd") or 0, x.get("gb") or 0))
