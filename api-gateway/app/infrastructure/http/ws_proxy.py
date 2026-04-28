import asyncio
import logging

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

_FORWARDED_HEADERS = (
    "authorization",
    "cookie",
    "user-agent",
    "x-forwarded-for",
    "x-forwarded-proto",
    "x-real-ip",
)


def _build_target_ws_url(http_base_url: str, path: str) -> str:
    base = http_base_url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    return f"{base}{path}"


def _extract_subprotocols(websocket: WebSocket) -> list[str]:
    raw = websocket.headers.get("sec-websocket-protocol") or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


def _build_upstream_headers(websocket: WebSocket) -> list[tuple[str, str]]:
    headers: list[tuple[str, str]] = []
    for name in _FORWARDED_HEADERS:
        value = websocket.headers.get(name)
        if value:
            headers.append((name, value))

    client = websocket.client
    if client and client.host:
        existing_xff = websocket.headers.get("x-forwarded-for")
        xff_value = f"{existing_xff}, {client.host}" if existing_xff else client.host
        headers.append(("x-forwarded-for", xff_value))

    return headers


async def proxy_websocket(websocket: WebSocket, target_url: str) -> None:
    subprotocols = _extract_subprotocols(websocket)
    upstream_headers = _build_upstream_headers(websocket)

    try:
        upstream = await websockets.connect(
            target_url,
            subprotocols=subprotocols or None,
            additional_headers=upstream_headers,
            open_timeout=10,
            ping_interval=None,
            max_size=None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("WS upstream connect failed (%s): %s", target_url, exc)
        await websocket.close(code=1011)
        return

    accepted_subprotocol = upstream.subprotocol
    await websocket.accept(subprotocol=accepted_subprotocol)

    async def client_to_upstream() -> None:
        try:
            while True:
                message = await websocket.receive()
                msg_type = message.get("type")
                if msg_type == "websocket.disconnect":
                    return
                if "text" in message and message["text"] is not None:
                    await upstream.send(message["text"])
                elif "bytes" in message and message["bytes"] is not None:
                    await upstream.send(message["bytes"])
        except WebSocketDisconnect:
            return
        except ConnectionClosed:
            return
        except Exception as exc:  # noqa: BLE001
            logger.debug("WS client->upstream error: %s", exc)

    async def upstream_to_client() -> None:
        try:
            async for data in upstream:
                if isinstance(data, bytes):
                    await websocket.send_bytes(data)
                else:
                    await websocket.send_text(data)
        except ConnectionClosed:
            return
        except Exception as exc:  # noqa: BLE001
            logger.debug("WS upstream->client error: %s", exc)

    task_c2u = asyncio.create_task(client_to_upstream())
    task_u2c = asyncio.create_task(upstream_to_client())

    try:
        done, pending = await asyncio.wait(
            {task_c2u, task_u2c}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in pending:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
    finally:
        try:
            await upstream.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
