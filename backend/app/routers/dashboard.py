from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..auth_utils import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/")
def dashboard(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Fast dashboard aggregates — no full-table loads."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Messages today: join filter without loading all conversations
    msgs_today = (
        db.query(func.count(models.Message.id))
        .join(models.Conversation, models.Message.conversation_id == models.Conversation.id)
        .filter(
            models.Conversation.user_id == user.id,
            models.Message.created_at >= today_start,
        )
        .scalar()
    ) or 0

    # Token sums in SQL (portable across SQLite/Postgres)
    inp = (
        db.query(func.coalesce(func.sum(models.TokenUsage.input_tokens), 0))
        .filter(models.TokenUsage.user_id == user.id)
        .scalar()
    ) or 0
    outp = (
        db.query(func.coalesce(func.sum(models.TokenUsage.output_tokens), 0))
        .filter(models.TokenUsage.user_id == user.id)
        .scalar()
    ) or 0
    cost_raw = (
        db.query(func.coalesce(func.sum(models.TokenUsage.cost), 0.0))
        .filter(models.TokenUsage.user_id == user.id)
        .scalar()
    ) or 0
    tokens = int(inp) + int(outp)
    cost = round(float(cost_raw), 4)

    active_agents = (
        db.query(func.count(models.Agent.id))
        .filter_by(user_id=user.id, status="active")
        .scalar()
    ) or 0

    recent = (
        db.query(models.Conversation.id, models.Conversation.title, models.Conversation.created_at)
        .filter_by(user_id=user.id)
        .order_by(models.Conversation.id.desc())
        .limit(5)
        .all()
    )
    return {
        "messages_today": int(msgs_today),
        "tokens_used": tokens,
        "active_agents": int(active_agents),
        "estimated_cost": cost,
        "recent_conversations": [
            {"id": c.id, "title": c.title, "created_at": c.created_at} for c in recent
        ],
    }
