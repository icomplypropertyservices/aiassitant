import json
from collections import defaultdict
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self.channels: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, channel: str, ws: WebSocket):
        await ws.accept()
        self.channels[channel].append(ws)

    def disconnect(self, channel: str, ws: WebSocket):
        if ws in self.channels.get(channel, []):
            self.channels[channel].remove(ws)

    async def broadcast(self, channel: str, data: dict):
        dead = []
        for ws in self.channels.get(channel, []):
            try:
                await ws.send_text(json.dumps(data, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(channel, ws)

manager = ConnectionManager()
