from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.dependencies import decode_user_payload
from app.realtime.hub import realtime_hub


router = APIRouter(tags=["realtime"])


@router.websocket("/ws/reservations")
async def reservations_websocket(
    websocket: WebSocket,
    token: str = Query(default=""),
):
    try:
        user_payload = decode_user_payload(token)
    except Exception:
        await websocket.close(code=1008)
        return

    await realtime_hub.connect(websocket)
    await websocket.send_json(
        {
            "channel": "reservations",
            "event_type": "connected",
            "entity": "socket",
            "payload": {"username": user_payload.get("username")},
        }
    )

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        realtime_hub.disconnect(websocket)
    except Exception:
        realtime_hub.disconnect(websocket)
