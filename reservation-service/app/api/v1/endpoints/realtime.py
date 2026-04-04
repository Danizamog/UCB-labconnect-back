from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.realtime.manager import realtime_manager

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/reservations")
async def reservations_ws(websocket: WebSocket) -> None:
    await realtime_manager.connect(websocket)
    await websocket.send_json({"type": "connected", "topic": "reservations"})

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await realtime_manager.disconnect(websocket)
    except Exception:
        await realtime_manager.disconnect(websocket)
