from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..auth_utils import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("/")
def dashboard(db: Session = Depends(get_db), user=Depends(get_current_user)):
    today = datetime.utcnow().date()
    conv_ids = [c.id for c in db.query(models.Conversation).filter_by(user_id=user.id).all()]
    msgs_today = 0
    if conv_ids:
        msgs_today = db.query(models.Message).filter(
            models.Message.conversation_id.in_(conv_ids)).filter(
            models.Message.created_at >= datetime(today.year, today.month, today.day)).count()
    usage = db.query(models.TokenUsage).filter_by(user_id=user.id).all()
    tokens = sum(r.input_tokens + r.output_tokens for r in usage)
    cost = round(sum(r.cost for r in usage), 4)
    active_agents = db.query(models.Agent).filter_by(user_id=user.id, status="active").count()
    recent = db.query(models.Conversation).filter_by(user_id=user.id).order_by(models.Conversation.id.desc()).limit(5).all()
    return {
        "messages_today": msgs_today, "tokens_used": tokens, "active_agents": active_agents, "estimated_cost": cost,
        "recent_conversations": [{"id": c.id, "title": c.title, "created_at": c.created_at} for c in recent],
    }
