"""AgentBay marketplace bridge endpoints for the AI Business Assistant UI/API."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..ownership import require_owned
from .. import models, config
from ..auth_utils import get_current_user
from .. import agentbay_bridge

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


class PublishIn(BaseModel):
    price: float | None = Field(default=None, ge=0)
    title: str | None = None
    description: str | None = None


@router.get("/status")
def marketplace_status(user=Depends(get_current_user)):
    return {
        "enabled": agentbay_bridge.enabled(),
        "auto_publish": config.AGENTBAY_AUTO_PUBLISH,
        "agentbay_url": config.AGENTBAY_URL,
        "public_url": getattr(config, "AGENTBAY_PUBLIC_URL", None) or "https://aibusinessagent.xyz/bay",
        "default_price": config.AGENTBAY_DEFAULT_PRICE,
    }


@router.get("/subcontractors")
def marketplace_subcontractors(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Hired AgentBay skills/agents (paid orders) for this account."""
    from ..human_service import list_agentbay_subcontractors
    return list_agentbay_subcontractors(db, user)


@router.post("/agents/{agent_id}/publish")
async def publish_one(
    agent_id: int,
    data: PublishIn | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    a = require_owned(
        db, models.Agent, agent_id, user,
        user_field='user_id', not_found="Agent not found",
    )
    data = data or PublishIn()
    extra = {}
    if data.title:
        extra["title"] = data.title
    if data.description:
        extra["description"] = data.description
    result = await agentbay_bridge.publish_agent(
        a, db, price=data.price, extra_listing=extra or None
    )
    if not result.get("ok"):
        raise HTTPException(502, result.get("error") or "Publish failed")
    return result


@router.post("/publish-all")
async def publish_all(db: Session = Depends(get_db), user=Depends(get_current_user)):
    if not agentbay_bridge.enabled():
        raise HTTPException(400, "AgentBay bridge not configured (AGENTBAY_URL + AGENTBAY_BRIDGE_SECRET)")
    return await agentbay_bridge.publish_all_user_agents(db, user.id)
