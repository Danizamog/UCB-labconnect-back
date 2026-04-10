from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.dependencies import validate_token
from app.realtime.manager import realtime_manager

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/reservations")
async def reservations_ws(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token", "")
    try:
        validate_token(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await realtime_manager.connect(websocket)

    try:
        await websocket.send_json({"type": "connected", "topic": "reservations"})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await realtime_manager.disconnect(websocket)
    except Exception:
        await realtime_manager.disconnect(websocket)
