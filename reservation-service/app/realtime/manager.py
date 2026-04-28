from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Iterable

from fastapi import WebSocket

logger = logging.getLogger(__name__)


_MANAGEMENT_PERMISSIONS = {
    "gestionar_reservas",
    "gestionar_reglas_reserva",
    "gestionar_accesos_laboratorio",
    "gestionar_penalizaciones",
    "gestionar_horarios",
}

_PERSONAL_TOPICS = {"user_notification", "user_penalty"}
_OPERATIONS_TOPICS = {"lab_block", "lab_schedule"}
_LAB_SCOPED_TOPICS = {"lab_reservation", "lab_block", "lab_schedule"}

_BROADCAST_SEND_TIMEOUT = 1.0


@dataclass
class ClientContext:
    websocket: WebSocket
    user_id: str = ""
    role: str = "user"
    permissions: frozenset[str] = field(default_factory=frozenset)
    topics: frozenset[str] = field(default_factory=frozenset)
    laboratory_ids: frozenset[str] = field(default_factory=frozenset)

    def is_manager(self) -> bool:
        if self.role == "admin":
            return True
        if "*" in self.permissions:
            return True
        return bool(self.permissions.intersection(_MANAGEMENT_PERMISSIONS))


def _user_can_receive(client: ClientContext, payload: dict) -> bool:
    topic = str(payload.get("topic") or "")

    if client.topics and topic and topic not in client.topics:
        return False

    record = payload.get("record") if isinstance(payload.get("record"), dict) else {}
    record_lab_id = str(record.get("laboratory_id") or "")

    if client.laboratory_ids and topic in _LAB_SCOPED_TOPICS:
        if record_lab_id and record_lab_id not in client.laboratory_ids:
            return False

    recipients = payload.get("recipients")
    if isinstance(recipients, list) and recipients:
        recipient_ids = {str(r) for r in recipients if r}
        if client.user_id and client.user_id in recipient_ids:
            return True
        if client.is_manager():
            return True
        return False

    if topic in _PERSONAL_TOPICS:
        owner = (
            str(record.get("recipient_user_id") or "")
            or str(record.get("user_id") or "")
        )
        if client.user_id and owner and client.user_id == owner:
            return True
        return client.is_manager()

    if topic in _OPERATIONS_TOPICS:
        if client.laboratory_ids and record_lab_id and record_lab_id in client.laboratory_ids:
            return True
        return client.is_manager()

    if topic == "lab_reservation":
        if client.is_manager():
            return True
        if client.laboratory_ids and record_lab_id and record_lab_id in client.laboratory_ids:
            return True
        requested_by = str(record.get("requested_by") or "")
        if client.user_id and requested_by and client.user_id == requested_by:
            return True
        return False

    if topic == "tutorial_session":
        if client.laboratory_ids and record_lab_id and record_lab_id not in client.laboratory_ids:
            return False
        return True

    return client.is_manager()


class RealtimeManager:
    def __init__(self) -> None:
        self._clients: dict[WebSocket, ClientContext] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_payload: dict | None = None) -> ClientContext:
        await websocket.accept(subprotocol=_negotiate_subprotocol(websocket))
        payload = user_payload or {}
        ctx = ClientContext(
            websocket=websocket,
            user_id=str(payload.get("user_id") or ""),
            role=str(payload.get("role") or "user"),
            permissions=frozenset(p for p in (payload.get("permissions") or []) if p),
        )
        async with self._lock:
            self._clients[websocket] = ctx
        return ctx

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.pop(websocket, None)

    async def update_subscription(
        self,
        websocket: WebSocket,
        topics: Iterable[str] | None = None,
        laboratory_ids: Iterable[str] | None = None,
    ) -> None:
        async with self._lock:
            ctx = self._clients.get(websocket)
            if ctx is None:
                return
            next_topics = ctx.topics
            next_labs = ctx.laboratory_ids
            if topics is not None:
                next_topics = frozenset(str(t).strip() for t in topics if str(t).strip())
            if laboratory_ids is not None:
                next_labs = frozenset(str(l).strip() for l in laboratory_ids if str(l).strip())
            self._clients[websocket] = ClientContext(
                websocket=ctx.websocket,
                user_id=ctx.user_id,
                role=ctx.role,
                permissions=ctx.permissions,
                topics=next_topics,
                laboratory_ids=next_labs,
            )

    async def update_topics(self, websocket: WebSocket, topics: Iterable[str]) -> None:
        await self.update_subscription(websocket, topics=topics)

    async def broadcast(self, payload: dict) -> None:
        async with self._lock:
            targets = [ctx for ctx in self._clients.values() if _user_can_receive(ctx, payload)]

        if not targets:
            return

        results = await asyncio.gather(
            *[_safe_send(ctx.websocket, payload) for ctx in targets],
            return_exceptions=False,
        )

        dead = [ctx.websocket for ctx, ok in zip(targets, results) if not ok]
        if not dead:
            return

        async with self._lock:
            for ws in dead:
                self._clients.pop(ws, None)


async def _safe_send(websocket: WebSocket, payload: dict) -> bool:
    try:
        await asyncio.wait_for(websocket.send_json(payload), timeout=_BROADCAST_SEND_TIMEOUT)
        return True
    except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
        logger.debug("Realtime send failed for client: %s", exc)
        return False


def _negotiate_subprotocol(websocket: WebSocket) -> str | None:
    requested = websocket.headers.get("sec-websocket-protocol")
    if not requested:
        return None
    protocols = [p.strip() for p in requested.split(",") if p.strip()]
    for proto in protocols:
        if proto.startswith("bearer.") or proto == "json":
            return proto
    return protocols[0] if protocols else None


realtime_manager = RealtimeManager()
