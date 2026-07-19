"""My Human provisioning, message box, and AgentBay subcontractor visibility."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import models


def ensure_my_human(db: Session, user: models.User) -> models.Human:
    """
    Every account gets exactly one primary human ("My Human").
    Used as the default delegate for human tasks with AI agents.
    """
    existing = (
        db.query(models.Human)
        .filter_by(owner_user_id=user.id, is_my_human=True)
        .order_by(models.Human.id)
        .first()
    )
    if existing:
        return existing

    # Prefer a human that already matches the account email
    email = (user.email or "").strip().lower()
    by_email = None
    if email:
        by_email = (
            db.query(models.Human)
            .filter(
                models.Human.owner_user_id == user.id,
                models.Human.email.ilike(email),
            )
            .order_by(models.Human.id)
            .first()
        )
    # Else first human on the account
    first = (
        db.query(models.Human)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Human.id)
        .first()
    )
    pick = by_email or first
    if pick:
        # Clear any stale flags then set this one
        db.query(models.Human).filter_by(owner_user_id=user.id, is_my_human=True).update(
            {"is_my_human": False}, synchronize_session=False
        )
        pick.is_my_human = True
        if not (pick.role_title or "").strip():
            pick.role_title = "My Human · Primary operator"
        if not (pick.email or "").strip() and email:
            pick.email = email
        pick.updated_at = datetime.utcnow()
        db.flush()
        return pick

    # Create brand-new My Human from account profile
    name = (user.name or "").strip() or (email.split("@")[0] if email else "My Human")
    if name.lower() in ("my human",):
        name = email.split("@")[0].replace(".", " ").title() if email else "Account owner"
    h = models.Human(
        owner_user_id=user.id,
        name=name[:120],
        email=email,
        phone="",
        role_title="My Human · Primary operator",
        skills="delegation, coordination, approvals",
        status="active",
        capacity=20,
        permission_level="admin",
        escalate_when="on_blocked",
        escalate_to="owner",
        notes=(
            "Auto-created primary human for this account. "
            "Agents assign human work here; My Human can delegate to other teammates and AI agents."
        ),
        is_my_human=True,
    )
    db.add(h)
    db.flush()
    return h


def set_my_human(db: Session, user: models.User, human_id: int) -> models.Human:
    h = db.get(models.Human, human_id)
    if not h or h.owner_user_id != user.id:
        raise ValueError("Human not found")
    db.query(models.Human).filter_by(owner_user_id=user.id, is_my_human=True).update(
        {"is_my_human": False}, synchronize_session=False
    )
    h.is_my_human = True
    if not (h.role_title or "").strip() or "my human" not in (h.role_title or "").lower():
        base = (h.role_title or "").strip()
        h.role_title = f"{base} · My Human".strip(" ·") if base else "My Human · Primary operator"
    h.updated_at = datetime.utcnow()
    db.flush()
    return h


def post_human_message(
    db: Session,
    *,
    user: models.User,
    human_id: int,
    content: str,
    sender_role: str = "owner",
    sender_agent_id: int | None = None,
    related_human_id: int | None = None,
    task_id: int | None = None,
    kind: str = "message",
) -> models.HumanMessage:
    content = (content or "").strip()
    if not content:
        raise ValueError("content required")
    h = db.get(models.Human, human_id)
    if not h or h.owner_user_id != user.id:
        raise ValueError("Human not found")
    role = (sender_role or "owner").lower()
    if role not in ("owner", "agent", "human", "system"):
        role = "owner"
    msg = models.HumanMessage(
        user_id=user.id,
        human_id=h.id,
        sender_role=role,
        sender_agent_id=sender_agent_id,
        related_human_id=related_human_id,
        task_id=task_id,
        content=content[:20000],
        kind=(kind or "message")[:40],
    )
    db.add(msg)
    db.flush()
    return msg


def list_human_messages(
    db: Session,
    user: models.User,
    human_id: int,
    *,
    limit: int = 80,
) -> list[dict[str, Any]]:
    h = db.get(models.Human, human_id)
    if not h or h.owner_user_id != user.id:
        raise ValueError("Human not found")
    rows = (
        db.query(models.HumanMessage)
        .filter_by(user_id=user.id, human_id=human_id)
        .order_by(models.HumanMessage.id.desc())
        .limit(min(200, max(1, limit)))
        .all()
    )
    out = []
    for m in reversed(rows):
        agent_name = None
        if m.sender_agent_id:
            a = db.get(models.Agent, m.sender_agent_id)
            agent_name = a.name if a else None
        related_name = None
        if m.related_human_id:
            rh = db.get(models.Human, m.related_human_id)
            related_name = rh.name if rh else None
        out.append({
            "id": m.id,
            "human_id": m.human_id,
            "sender_role": m.sender_role,
            "sender_agent_id": m.sender_agent_id,
            "sender_agent_name": agent_name,
            "related_human_id": m.related_human_id,
            "related_human_name": related_name,
            "task_id": m.task_id,
            "content": m.content,
            "kind": m.kind,
            "read_at": m.read_at.isoformat() + "Z" if m.read_at else None,
            "created_at": m.created_at.isoformat() + "Z" if m.created_at else None,
        })
    return out


def mark_messages_read(db: Session, user: models.User, human_id: int) -> int:
    now = datetime.utcnow()
    q = (
        db.query(models.HumanMessage)
        .filter_by(user_id=user.id, human_id=human_id)
        .filter(models.HumanMessage.read_at.is_(None))
    )
    n = 0
    for m in q.all():
        m.read_at = now
        n += 1
    db.flush()
    return n


def list_agentbay_subcontractors(db: Session, user: models.User) -> dict[str, Any]:
    """
    Hired AgentBay listings (paid/active orders) for this account — shown as subcontractors.
    Uses shared Postgres bay_* tables when present; degrades gracefully.
    """
    email = (user.email or "").strip().lower()
    items: list[dict[str, Any]] = []
    try:
        # Prefer main_user_id link; fall back to email match on bay_users
        sql = text(
            """
            SELECT
              o.id AS order_id,
              o.status AS order_status,
              o.payment_status,
              o.quantity,
              o.total,
              o.currency,
              o.created_at AS ordered_at,
              l.id AS listing_id,
              l.title AS listing_title,
              l.kind AS listing_kind,
              l.description AS listing_description,
              l.external_id AS listing_external_id,
              l.source_system AS listing_source,
              seller.id AS seller_id,
              seller.display_name AS seller_name,
              seller.username AS seller_username,
              seller.email AS seller_email
            FROM bay_orders o
            JOIN bay_listings l ON l.id = o.listing_id
            JOIN bay_users buyer ON buyer.id = o.buyer_id
            LEFT JOIN bay_users seller ON seller.id = o.seller_id
            WHERE (
              buyer.main_user_id = :uid
              OR lower(buyer.email) = :email
            )
              AND coalesce(o.payment_status, '') IN ('paid', 'complete', 'completed')
            ORDER BY o.id DESC
            LIMIT 100
            """
        )
        rows = db.execute(sql, {"uid": user.id, "email": email}).mappings().all()
        for r in rows:
            items.append({
                "order_id": r["order_id"],
                "status": r["order_status"],
                "payment_status": r["payment_status"],
                "quantity": r["quantity"],
                "total": float(r["total"] or 0),
                "currency": r["currency"] or "USD",
                "ordered_at": r["ordered_at"].isoformat() + "Z" if r["ordered_at"] else None,
                "listing_id": r["listing_id"],
                "title": r["listing_title"] or "AgentBay listing",
                "kind": r["listing_kind"] or "skill",
                "description": (r["listing_description"] or "")[:400],
                "external_id": r["listing_external_id"],
                "source_system": r["listing_source"],
                "seller": {
                    "id": r["seller_id"],
                    "name": r["seller_name"] or r["seller_username"] or "Seller",
                    "email": r["seller_email"] or "",
                },
                "role": "subcontractor",
                "bay_url": f"/bay/orders/{r['order_id']}",
            })
    except Exception as e:
        return {
            "subcontractors": [],
            "count": 0,
            "available": False,
            "error": str(e)[:200],
            "hint": "AgentBay orders table not reachable — hire skills at /bay",
        }

    return {
        "subcontractors": items,
        "count": len(items),
        "available": True,
        "browse_url": "/bay/browse",
        "orders_url": "/bay",
    }
