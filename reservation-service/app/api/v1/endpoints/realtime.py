import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.dependencies import validate_token
from app.realtime.manager import realtime_manager

router = APIRouter(tags=["realtime"])
logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 25.0


def _extract_token(websocket: WebSocket) -> str:
    requested = websocket.headers.get("sec-websocket-protocol") or ""
    for part in (p.strip() for p in requested.split(",")):
        if part.startswith("bearer."):
            return part[len("bearer."):]

    auth_header = websocket.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    return websocket.query_params.get("token", "")


@router.websocket("/ws/reservations")
async def reservations_ws(websocket: WebSocket) -> None:
    token = _extract_token(websocket)
    try:
        user_payload = await asyncio.to_thread(validate_token, token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    ctx = await realtime_manager.connect(websocket, user_payload=user_payload)

    heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket))

    try:
        await websocket.send_json({"type": "connected", "topic": "reservations"})
        while True:
            raw = await websocket.receive_text()
            await _handle_client_message(websocket, raw)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("Realtime ws closed: %s", exc)
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        await realtime_manager.disconnect(websocket)
    _ = ctx


async def _handle_client_message(websocket: WebSocket, raw: str) -> None:
    try:
        message = json.loads(raw)
    except (ValueError, TypeError):
        return

    if not isinstance(message, dict):
        return

    msg_type = str(message.get("type") or "")

    if msg_type == "ping":
        try:
            await websocket.send_json({"type": "pong"})
        except Exception:  # noqa: BLE001
            return
        return

    if msg_type == "subscribe":
        topics = message.get("topics")
        labs = message.get("laboratory_ids")
        await realtime_manager.update_subscription(
            websocket,
            topics=topics if isinstance(topics, list) else None,
            laboratory_ids=labs if isinstance(labs, list) else None,
        )
        return


async def _heartbeat_loop(websocket: WebSocket) -> None:
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            try:
                await websocket.send_json({"type": "ping"})
            except Exception:  # noqa: BLE001
                return
    except asyncio.CancelledError:
        raise
