import json
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db, SessionLocal
from .. import models
from ..auth_utils import get_current_user, user_from_ws_token, ensure_credits, accept_and_authenticate_ws
from ..llm import stream_completion, complete, provider_hint
from ..pricing import estimate_tokens
from ..ws import manager
from ..usage_billing import charge_usage, bill_llm_turn
from ..user_keys import credentials_for_user

router = APIRouter(tags=["chat"])


class MessageIn(BaseModel):
    message: str
    model: str = "vps-fast"
    mode: str = "general"
    conversation_id: int | None = None


@router.get("/conversations")
def conversations(db: Session = Depends(get_db), user=Depends(get_current_user)):
    convs = (
        db.query(models.Conversation)
        .filter_by(user_id=user.id)
        .order_by(models.Conversation.id.desc())
        .limit(20)
        .all()
    )
    return [
        {"id": c.id, "title": c.title, "mode": c.mode, "created_at": c.created_at}
        for c in convs
    ]


@router.get("/conversations/{conv_id}/messages")
def conv_messages(conv_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = db.get(models.Conversation, conv_id)
    if not c or c.user_id != user.id:
        return []
    msgs = (
        db.query(models.Message)
        .filter_by(conversation_id=conv_id)
        .order_by(models.Message.id)
        .all()
    )
    return [{"id": m.id, "role": m.role, "content": m.content} for m in msgs]


@router.post("/conversations/messages")
async def post_message(data: MessageIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """REST fallback when WebSocket is unavailable (proxies, mobile, etc.)."""
    text = (data.message or "").strip()
    if not text:
        raise HTTPException(400, "Message is required")
    ensure_credits(db, user.id)

    conv = db.get(models.Conversation, data.conversation_id) if data.conversation_id else None
    if not conv or conv.user_id != user.id:
        conv = models.Conversation(user_id=user.id, title=text[:48], mode=data.mode)
        db.add(conv)
        db.commit()
        db.refresh(conv)

    db.add(models.Message(conversation_id=conv.id, role="user", content=text))
    db.commit()

    history = (
        db.query(models.Message)
        .filter_by(conversation_id=conv.id)
        .order_by(models.Message.id)
        .all()
    )
    llm_messages = [{"role": m.role, "content": m.content} for m in history][-12:]
    creds = credentials_for_user(db, user.id)
    reply = await complete(llm_messages, data.model, data.mode, credentials=creds)

    db.add(models.Message(conversation_id=conv.id, role="assistant", content=reply))
    db.commit()
    charged = bill_llm_turn(db, user, data.model, llm_messages, reply)
    await manager.broadcast(
        f"tokens:{user.id}",
        {
            "event": "usage",
            "tokens": charged["tokens"],
            "cost": charged["cost"],
            "model": charged.get("model") or data.model,
            "tokens_used_period": charged.get("tokens_used_period"),
            "credits": charged.get("credits"),
            "warn": None,
            "hard_block": None,
        },
    )
    return {
        "conversation_id": conv.id,
        "title": conv.title,
        "reply": reply,
        "tokens": charged["tokens"],
        "cost": charged["cost"],
        # Best-effort from selected model + whether user/platform keys exist (not actual fallback path)
        "provider_hint": provider_hint(data.model, creds),
    }


@router.websocket("/ws/chat")
async def ws_chat(ws: WebSocket, token: str = Query("")):
    """Streaming chat WS. Auth: ?token= (legacy/mobile) or first-message {"type":"auth","token":...}."""
    db = SessionLocal()
    user = await accept_and_authenticate_ws(ws, token, db)
    if not user:
        db.close()
        return
    user_id = user.id
    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            text = data.get("message", "").strip()
            model = data.get("model", "vps-fast")
            mode = data.get("mode", "general")
            conv_id = data.get("conversation_id")
            if not text:
                continue

            # Refresh credits each turn (included pool OR wallet — same as REST)
            try:
                ensure_credits(db, user_id)
            except HTTPException as he:
                await ws.send_text(json.dumps({
                    "type": "error",
                    "content": he.detail if isinstance(he.detail, str) else str(he.detail),
                }))
                continue

            conv = db.get(models.Conversation, conv_id) if conv_id else None
            if not conv or conv.user_id != user_id:
                conv = models.Conversation(user_id=user_id, title=text[:48], mode=mode)
                db.add(conv)
                db.commit()
                db.refresh(conv)
                await ws.send_text(json.dumps({
                    "type": "conversation",
                    "conversation_id": conv.id,
                    "title": conv.title,
                }))
            db.add(models.Message(conversation_id=conv.id, role="user", content=text))
            db.commit()

            history = (
                db.query(models.Message)
                .filter_by(conversation_id=conv.id)
                .order_by(models.Message.id)
                .all()
            )
            llm_messages = [{"role": m.role, "content": m.content} for m in history][-12:]

            creds = credentials_for_user(db, user_id)
            reply = ""
            async for chunk in stream_completion(llm_messages, model, mode, credentials=creds):
                reply += chunk
                await ws.send_text(json.dumps({"type": "chunk", "content": chunk}))
            reply = reply.strip()
            db.add(models.Message(conversation_id=conv.id, role="assistant", content=reply))
            db.commit()

            user = db.get(models.User, user_id)
            charged = bill_llm_turn(db, user, model, llm_messages, reply)

            await ws.send_text(json.dumps({
                "type": "done",
                "tokens": charged["tokens"],
                "cost": charged["cost"],
                "conversation_id": conv.id,
                "tokens_used_period": charged.get("tokens_used_period"),
                "credits": charged.get("credits"),
            }))
            await manager.broadcast(
                f"tokens:{user_id}",
                {
                    "event": "usage",
                    "tokens": charged["tokens"],
                    "cost": charged["cost"],
                    "model": charged.get("model") or model,
                    "tokens_used_period": charged.get("tokens_used_period"),
                    "credits": charged.get("credits"),
                },
            )
    except WebSocketDisconnect:
        pass
    finally:
        db.close()
