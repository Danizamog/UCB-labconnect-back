from __future__ import annotations

import asyncio
from fastapi import WebSocket


class RealtimeManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, payload: dict) -> None:
        async with self._lock:
            clients = list(self._connections)

        dead_clients: list[WebSocket] = []
        for client in clients:
            try:
                await client.send_json(payload)
            except Exception:
                dead_clients.append(client)

        if not dead_clients:
            return

        async with self._lock:
            for client in dead_clients:
                self._connections.discard(client)


realtime_manager = RealtimeManager()
