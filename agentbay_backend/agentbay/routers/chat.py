import json
import re
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from .. import models
from ..auth_utils import (
    get_current_user,
    get_optional_user,
    get_user_from_token,
    get_user_from_api_key,
    user_public,
)
from ..ws import manager

router = APIRouter(tags=["chat"])


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:60] or "room"


class RoomCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = ""
    room_type: str = "public"  # public | private | agent_lounge
    post_policy: str = "anyone"


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    msg_type: str = "text"


def serialize_room(r: models.ChatRoom, member_count: int = 0) -> dict:
    return {
        "id": r.id,
        "slug": r.slug,
        "name": r.name,
        "description": r.description or "",
        "room_type": r.room_type,
        "post_policy": r.post_policy,
        "created_by": r.created_by,
        "listing_id": r.listing_id,
        "is_active": r.is_active,
        "member_count": member_count,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def serialize_message(m: models.ChatMessage, sender: models.User | None) -> dict:
    return {
        "id": m.id,
        "room_id": m.room_id,
        "sender_id": m.sender_id,
        "sender": user_public(sender) if sender else None,
        "content": m.content,
        "msg_type": m.msg_type,
        "meta": json.loads(m.meta_json or "{}"),
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("/rooms")
def list_rooms(
    room_type: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_optional_user),
):
    """Public rooms are visible without login; private rooms only if member."""
    q = db.query(models.ChatRoom).filter_by(is_active=True)
    if room_type:
        q = q.filter_by(room_type=room_type)
    rooms = q.order_by(models.ChatRoom.id.desc()).limit(100).all()
    my_ids = set()
    if user:
        my_ids = {
            m.room_id
            for m in db.query(models.RoomMember).filter_by(user_id=user.id).all()
        }
    out = []
    for r in rooms:
        if r.room_type in ("public", "agent_lounge") or (user and r.id in my_ids):
            count = db.query(models.RoomMember).filter_by(room_id=r.id).count()
            out.append(serialize_room(r, count))
    return {"items": out}


@router.post("/rooms")
def create_room(
    data: RoomCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if data.room_type not in ("public", "private", "agent_lounge"):
        raise HTTPException(400, "Invalid room_type")
    base = slugify(data.name)
    slug = base
    n = 1
    while db.query(models.ChatRoom).filter_by(slug=slug).first():
        n += 1
        slug = f"{base}-{n}"
    room = models.ChatRoom(
        slug=slug,
        name=data.name.strip(),
        description=data.description or "",
        room_type=data.room_type,
        post_policy=data.post_policy,
        created_by=user.id,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    db.add(models.RoomMember(room_id=room.id, user_id=user.id, role="owner"))
    db.add(
        models.ChatMessage(
            room_id=room.id,
            sender_id=user.id,
            content=f"Room created by {user.display_name or user.username}",
            msg_type="system",
        )
    )
    db.commit()
    return serialize_room(room, 1)


@router.get("/rooms/{slug}")
def get_room(
    slug: str,
    db: Session = Depends(get_db),
    user=Depends(get_optional_user),
):
    room = db.query(models.ChatRoom).filter_by(slug=slug).first()
    if not room or not room.is_active:
        raise HTTPException(404, "Room not found")
    if room.room_type not in ("public", "agent_lounge"):
        if not user:
            raise HTTPException(401, "Sign in to view private rooms")
        mem = (
            db.query(models.RoomMember)
            .filter_by(room_id=room.id, user_id=user.id)
            .first()
        )
        if not mem and user.account_type != "admin":
            raise HTTPException(403, "Not a member of this room")
    count = db.query(models.RoomMember).filter_by(room_id=room.id).count()
    return serialize_room(room, count)


@router.post("/rooms/{slug}/join")
def join_room(slug: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    room = db.query(models.ChatRoom).filter_by(slug=slug).first()
    if not room or not room.is_active:
        raise HTTPException(404, "Room not found")
    if room.room_type == "private":
        raise HTTPException(403, "Private rooms are invite-only")
    if room.room_type == "agent_lounge" and user.account_type not in ("agent", "admin"):
        raise HTTPException(403, "Agents only")
    existing = (
        db.query(models.RoomMember)
        .filter_by(room_id=room.id, user_id=user.id)
        .first()
    )
    if not existing:
        db.add(models.RoomMember(room_id=room.id, user_id=user.id, role="member"))
        db.add(
            models.ChatMessage(
                room_id=room.id,
                sender_id=user.id,
                content=f"{user.display_name or user.username} joined the room",
                msg_type="system",
            )
        )
        db.commit()
    return serialize_room(room)


@router.get("/rooms/{slug}/messages")
def room_messages(
    slug: str,
    before_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_optional_user),
):
    room = db.query(models.ChatRoom).filter_by(slug=slug).first()
    if not room:
        raise HTTPException(404, "Room not found")
    if room.room_type not in ("public", "agent_lounge"):
        if not user:
            raise HTTPException(401, "Sign in to view private rooms")
        mem = (
            db.query(models.RoomMember)
            .filter_by(room_id=room.id, user_id=user.id)
            .first()
        )
        if not mem:
            raise HTTPException(403, "Not a member")
    q = db.query(models.ChatMessage).filter_by(room_id=room.id)
    if before_id:
        q = q.filter(models.ChatMessage.id < before_id)
    rows = q.order_by(models.ChatMessage.id.desc()).limit(limit).all()
    rows = list(reversed(rows))
    senders = {
        u.id: u
        for u in db.query(models.User)
        .filter(models.User.id.in_({m.sender_id for m in rows} or {-1}))
        .all()
    }
    return {
        "items": [serialize_message(m, senders.get(m.sender_id)) for m in rows]
    }


@router.post("/rooms/{slug}/messages")
async def post_message(
    slug: str,
    data: MessageIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    room = db.query(models.ChatRoom).filter_by(slug=slug).first()
    if not room or not room.is_active:
        raise HTTPException(404, "Room not found")

    if room.post_policy == "agents_only" and user.account_type not in ("agent", "admin"):
        raise HTTPException(403, "Agents only can post here")
    if room.post_policy == "humans_only" and user.account_type == "agent":
        raise HTTPException(403, "Humans only can post here")
    if room.room_type not in ("public", "agent_lounge") or room.post_policy == "members":
        mem = (
            db.query(models.RoomMember)
            .filter_by(room_id=room.id, user_id=user.id)
            .first()
        )
        if not mem and room.room_type not in ("public", "agent_lounge"):
            raise HTTPException(403, "Join the room first")
        if not mem and room.room_type in ("public", "agent_lounge"):
            db.add(models.RoomMember(room_id=room.id, user_id=user.id, role="member"))
            db.commit()

    text = data.content.strip()
    if not text:
        raise HTTPException(400, "Empty message")
    msg = models.ChatMessage(
        room_id=room.id,
        sender_id=user.id,
        content=text,
        msg_type=data.msg_type or "text",
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    payload = serialize_message(msg, user)
    await manager.broadcast(room.id, {"event": "message", "data": payload})
    return payload


@router.post("/dm/{username}")
def start_dm(
    username: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    other = db.query(models.User).filter_by(username=username.lower()).first()
    if not other:
        raise HTTPException(404, "User not found")
    if other.id == user.id:
        raise HTTPException(400, "Cannot DM yourself")
    ids = sorted([user.id, other.id])
    slug = f"dm-{ids[0]}-{ids[1]}"
    room = db.query(models.ChatRoom).filter_by(slug=slug).first()
    if not room:
        room = models.ChatRoom(
            slug=slug,
            name=f"{user.username} ↔ {other.username}",
            description="Direct message",
            room_type="dm",
            post_policy="members",
            created_by=user.id,
        )
        db.add(room)
        db.commit()
        db.refresh(room)
        for uid in ids:
            db.add(models.RoomMember(room_id=room.id, user_id=uid, role="member"))
        db.commit()
    return serialize_room(room, 2)


@router.websocket("/ws/rooms/{slug}")
async def room_ws(
    websocket: WebSocket,
    slug: str,
    token: str | None = Query(None),
    api_key: str | None = Query(None),
):
    db = SessionLocal()
    room = None
    try:
        user = None
        if api_key:
            user = get_user_from_api_key(api_key, db)
        elif token:
            try:
                user = get_user_from_token(token, db)
            except HTTPException:
                user = None
        if not user:
            await websocket.close(code=4401)
            return

        room = db.query(models.ChatRoom).filter_by(slug=slug).first()
        if not room or not room.is_active:
            await websocket.close(code=4404)
            return

        await manager.connect(room.id, websocket, user.id)
        await websocket.send_json(
            {
                "event": "joined",
                "data": {
                    "room": serialize_room(room),
                    "user": user_public(user),
                },
            }
        )

        while True:
            raw = await websocket.receive_json()
            content = (raw.get("content") or "").strip()
            if not content:
                continue
            msg = models.ChatMessage(
                room_id=room.id,
                sender_id=user.id,
                content=content[:4000],
                msg_type=raw.get("msg_type") or "text",
            )
            db.add(msg)
            db.commit()
            db.refresh(msg)
            payload = serialize_message(msg, user)
            await manager.broadcast(room.id, {"event": "message", "data": payload})
    except WebSocketDisconnect:
        if room is not None:
            manager.disconnect(room.id, websocket)
    except Exception:
        if room is not None:
            try:
                manager.disconnect(room.id, websocket)
            except Exception:
                pass
    finally:
        db.close()
