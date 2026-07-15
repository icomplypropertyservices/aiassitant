from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..auth_utils import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/users")
def users(db: Session = Depends(get_db), admin=Depends(require_admin)):
    out = []
    for u in db.query(models.User).all():
        bal = db.query(models.Balance).filter_by(user_id=u.id).first()
        agents = db.query(models.Agent).filter_by(user_id=u.id).count()
        usage = db.query(models.TokenUsage).filter_by(user_id=u.id).all()
        out.append({"id": u.id, "email": u.email, "name": u.name, "role": u.role, "plan": u.plan,
                    "credits": round(bal.credits, 4) if bal else 0, "agents": agents,
                    "tokens": sum(r.input_tokens + r.output_tokens for r in usage),
                    "spend": round(sum(r.cost for r in usage), 4), "created_at": u.created_at})
    return out

@router.get("/stats")
def stats(db: Session = Depends(get_db), admin=Depends(require_admin)):
    usage = db.query(models.TokenUsage).all()
    return {
        "users": db.query(models.User).count(),
        "agents": db.query(models.Agent).count(),
        "conversations": db.query(models.Conversation).count(),
        "total_tokens": sum(r.input_tokens + r.output_tokens for r in usage),
        "total_revenue": round(sum(r.cost for r in usage), 4),
    }

@router.get("/agents")
def all_agents(db: Session = Depends(get_db), admin=Depends(require_admin)):
    out = []
    for a in db.query(models.Agent).all():
        owner = db.get(models.User, a.user_id)
        out.append({"id": a.id, "name": a.name, "owner": owner.email if owner else "?",
                    "template_type": a.template_type, "model": a.model, "status": a.status,
                    "idle_mode": a.idle_mode})
    return out
