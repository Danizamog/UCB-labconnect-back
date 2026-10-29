from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Iterable

from fastapi import WebSocket

logger = logging.getLogger(__name__)


_MANAGEMENT_PERMISSIONS = {"gestionar_reservas", "gestionar_accesos_laboratorio"}
_LAB_SCOPED_TOPICS = {"lab_reservation", "lab_block", "lab_schedule", "lab_access"}

_BROADCAST_SEND_TIMEOUT = 1.0


@dataclass
class ClientContext:
    websocket: WebSocket
    user_id: str = ""
    role: str = "user"
    permissions: frozenset[str] = field(default_factory=frozenset)
    topics: frozenset[str] = field(default_factory=frozenset)
    laboratory_ids: frozenset[str] = field(default_factory=frozenset)
    managed_laboratory_ids: frozenset[str] = field(default_factory=frozenset)

    def is_manager(self) -> bool:
        return bool(self.permissions.intersection(_MANAGEMENT_PERMISSIONS))


def _in_management_scope(client: ClientContext, record: dict) -> bool:
    return "gestionar_estructura_laboratorios" in client.permissions or str(record.get("laboratory_id") or "") in client.managed_laboratory_ids


def _private_reservation_reader(client: ClientContext, record: dict) -> bool:
    owner = str(record.get("requested_by") or "")
    return bool(client.user_id and owner == client.user_id) or (client.is_manager() and _in_management_scope(client, record))


def _user_can_receive(client: ClientContext, payload: dict) -> bool:
    topic = str(payload.get("topic") or "")
    if client.topics and topic not in client.topics:
        return False
    record = payload.get("record") if isinstance(payload.get("record"), dict) else {}
    lab_id = str(record.get("laboratory_id") or "")
    if client.laboratory_ids and topic in _LAB_SCOPED_TOPICS and lab_id and lab_id not in client.laboratory_ids:
        return False
    if topic in {"user_notification", "user_penalty"}:
        owner = str(record.get("recipient_user_id") or record.get("user_id") or "")
        if client.user_id and owner == client.user_id:
            return True
        recipients = payload.get("recipients") or []
        if client.user_id and client.user_id in recipients:
            return True
        return owner == "__operations__" and client.is_manager() and "gestionar_estructura_laboratorios" in client.permissions
    if topic == "lab_access":
        return "gestionar_accesos_laboratorio" in client.permissions and _in_management_scope(client, record)
    if topic in {"lab_reservation", "lab_block"}:
        # El calendario necesita invalidaciones de disponibilidad; se sanitizan abajo.
        return True
    if topic in {"lab_schedule", "tutorial_session"} and payload.get("action") == "delete":
        return True
    if topic == "lab_schedule":
        return (record.get("teacher_id") == client.user_id or "aprobar_clases" in client.permissions
                or "gestionar_horarios_laboratorio" in client.permissions
                or (record.get("is_active") is True and record.get("approval_status") == "approved"))
    if topic == "tutorial_session":
        return (record.get("tutor_id") == client.user_id or "aprobar_tutorias" in client.permissions
                or (record.get("is_published") is True and record.get("approval_status") == "approved"))
    return False


def _visible_payload(client: ClientContext, payload: dict) -> dict:
    topic = payload.get("topic")
    record = payload.get("record") if isinstance(payload.get("record"), dict) else {}
    if topic == "lab_reservation" and not _private_reservation_reader(client, record):
        allowed = {"id", "laboratory_id", "start_at", "end_at", "status", "is_active", "requires_full_lab"}
    elif topic == "lab_block" and "gestionar_reglas_reserva" not in client.permissions:
        allowed = {"id", "laboratory_id", "start_at", "end_at", "is_active", "block_type"}
    elif topic == "tutorial_session" and not (record.get("tutor_id") == client.user_id or "aprobar_tutorias" in client.permissions):
        return {**payload, "record": {key: value for key, value in record.items() if key not in {"enrolled_students", "tutor_observation", "tutor_email"}}}
    else:
        return payload
    return {key: value for key, value in payload.items() if key != "recipients"} | {"record": {key: value for key, value in record.items() if key in allowed}}


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
        if ctx.is_manager() and "gestionar_estructura_laboratorios" not in ctx.permissions:
            from app.application.container import laboratory_access_repo
            labs = await asyncio.to_thread(laboratory_access_repo.list_all)
            ctx.managed_laboratory_ids = frozenset(str(lab.get("id") or "") for lab in labs if str(lab.get("manager") or "") == ctx.user_id)
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
                managed_laboratory_ids=ctx.managed_laboratory_ids,
            )

    async def update_topics(self, websocket: WebSocket, topics: Iterable[str]) -> None:
        await self.update_subscription(websocket, topics=topics)

    async def broadcast(self, payload: dict) -> None:
        async with self._lock:
            targets = [ctx for ctx in self._clients.values() if _user_can_receive(ctx, payload)]

        if not targets:
            return

        results = await asyncio.gather(
            *[_safe_send(ctx.websocket, _visible_payload(ctx, payload)) for ctx in targets],
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
