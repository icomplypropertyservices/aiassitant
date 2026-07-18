from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import user_public

router = APIRouter(tags=["catalog"])


@router.get("/categories")
def categories(db: Session = Depends(get_db)):
    rows = (
        db.query(models.Category)
        .order_by(models.Category.sort_order, models.Category.name)
        .all()
    )
    return {
        "items": [
            {
                "id": c.id,
                "slug": c.slug,
                "name": c.name,
                "description": c.description or "",
                "icon": c.icon or "",
            }
            for c in rows
        ]
    }


@router.get("/agents")
def list_agents(db: Session = Depends(get_db)):
    """Public directory of agent accounts."""
    rows = (
        db.query(models.User)
        .filter_by(account_type="agent", is_active=True)
        .order_by(models.User.rating_avg.desc())
        .limit(100)
        .all()
    )
    out = []
    for u in rows:
        active = (
            db.query(models.Listing)
            .filter_by(seller_id=u.id, status="active")
            .count()
        )
        d = user_public(u)
        d["active_listings"] = active
        out.append(d)
    return {"items": out}


@router.get("/stats")
def marketplace_stats(db: Session = Depends(get_db)):
    return {
        "listings_active": db.query(models.Listing).filter_by(status="active").count(),
        "users": db.query(models.User).filter_by(is_active=True).count(),
        "agents": db.query(models.User)
        .filter_by(account_type="agent", is_active=True)
        .count(),
        "orders": db.query(models.Order).count(),
        "rooms": db.query(models.ChatRoom).filter_by(is_active=True).count(),
    }
