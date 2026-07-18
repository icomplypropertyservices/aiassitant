"""Simple in-memory WebSocket room manager."""
from collections import defaultdict
from typing import Dict, Set
from fastapi import WebSocket


class RoomConnectionManager:
    def __init__(self):
        # room_id -> set of websockets
        self.rooms: Dict[int, Set[WebSocket]] = defaultdict(set)
        # websocket -> user_id
        self.users: Dict[WebSocket, int] = {}

    async def connect(self, room_id: int, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.rooms[room_id].add(websocket)
        self.users[websocket] = user_id

    def disconnect(self, room_id: int, websocket: WebSocket):
        self.rooms[room_id].discard(websocket)
        self.users.pop(websocket, None)
        if not self.rooms[room_id]:
            del self.rooms[room_id]

    async def broadcast(self, room_id: int, payload: dict, exclude: WebSocket | None = None):
        dead = []
        for ws in list(self.rooms.get(room_id, set())):
            if ws is exclude:
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(room_id, ws)


manager = RoomConnectionManager()
