import asyncio
import logging

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from websockets.asyncio.client import connect as ws_connect

from app.core.config import settings
from app.infrastructure.http.proxy import forward_request

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/v1/ws/reservations")
async def proxy_reservations_ws(websocket: WebSocket) -> None:
    await websocket.accept()

    ws_base = settings.reservations_service_url.replace("http://", "ws://").replace("https://", "wss://")
    target_url = f"{ws_base}/v1/ws/reservations"

    try:
        async with ws_connect(target_url) as upstream:

            async def forward_to_client() -> None:
                async for message in upstream:
                    await websocket.send_text(message if isinstance(message, str) else message.decode())

            async def forward_to_upstream() -> None:
                while True:
                    data = await websocket.receive_text()
                    await upstream.send(data)

            tasks = [
                asyncio.create_task(forward_to_client()),
                asyncio.create_task(forward_to_upstream()),
            ]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WebSocket proxy closed: %s", exc)


# Auth Service
@router.api_route(
    "/api/auth/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_auth(path: str, request: Request) -> Response:
    target_url = f"{settings.auth_service_url}/v1/auth/{path}"
    return await forward_request(target_url, request)


# Users - Auth Service (profileService)
@router.api_route(
    "/api/users/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_users_path(path: str, request: Request) -> Response:
    target_url = f"{settings.auth_service_url}/v1/users/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/users",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_users_root(request: Request) -> Response:
    target_url = f"{settings.auth_service_url}/v1/users/"
    return await forward_request(target_url, request)


# Users v1 - Role Service (rolesService)
@router.api_route(
    "/api/v1/users/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_users_v1_path(path: str, request: Request) -> Response:
    target_url = f"{settings.role_service_url}/v1/roles/users/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/users",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_users_v1_root(request: Request) -> Response:
    target_url = f"{settings.role_service_url}/v1/roles/users"
    return await forward_request(target_url, request)


# Roles - Role Service (rolesService)
@router.api_route(
    "/api/v1/roles/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_roles_path(path: str, request: Request) -> Response:
    target_url = f"{settings.role_service_url}/v1/roles/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/roles",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_roles_root(request: Request) -> Response:
    target_url = f"{settings.role_service_url}/v1/roles/"
    return await forward_request(target_url, request)


# Inventory Service - Assets & Stock items (infrastructureService, reservationsApi)
@router.api_route(
    "/api/inventory/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_inventory_path(path: str, request: Request) -> Response:
    target_url = f"{settings.inventory_service_url}/v1/{path}"
    return await forward_request(target_url, request)


# Inventory Service v1 compatibility (infrastructureService)
@router.api_route(
    "/api/v1/inventory/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_inventory_v1_path(path: str, request: Request) -> Response:
    target_url = f"{settings.inventory_service_url}/v1/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/inventory",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_inventory_v1_root(request: Request) -> Response:
    target_url = f"{settings.inventory_service_url}/v1/"
    return await forward_request(target_url, request)


# Inventory Service - Areas (infrastructureService, reservationsApi)
@router.api_route(
    "/api/v1/areas/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_areas_path(path: str, request: Request) -> Response:
    target_url = f"{settings.inventory_service_url}/v1/areas/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/areas",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_areas_root(request: Request) -> Response:
    target_url = f"{settings.inventory_service_url}/v1/areas"
    return await forward_request(target_url, request)


# Inventory Service - Labs (infrastructureService, reservationsApi)
@router.api_route(
    "/api/v1/labs/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_labs_path(path: str, request: Request) -> Response:
    target_url = f"{settings.inventory_service_url}/v1/laboratories/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/labs",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_labs_root(request: Request) -> Response:
    target_url = f"{settings.inventory_service_url}/v1/laboratories"
    return await forward_request(target_url, request)


# Reservation Service - Reservations
@router.api_route(
    "/api/v1/reservations/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_reservations_path(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/reservations/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/reservations",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_reservations_root(request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/reservations"
    return await forward_request(target_url, request)


# Reservation Service - Lab schedules
@router.api_route(
    "/api/v1/lab-schedules/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_lab_schedules_path(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/lab-schedules/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/lab-schedules",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_lab_schedules_root(request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/lab-schedules"
    return await forward_request(target_url, request)


# Reservation Service - Lab blocks
@router.api_route(
    "/api/v1/lab-blocks/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_lab_blocks_path(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/lab-blocks/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/lab-blocks",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_lab_blocks_root(request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/lab-blocks"
    return await forward_request(target_url, request)


# Reservation Service - Availability
@router.api_route(
    "/api/v1/availability/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_availability_path(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/availability/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/availability",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_availability_root(request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/availability"
    return await forward_request(target_url, request)


# Reservation Service - Tutorial sessions
@router.api_route(
    "/api/v1/tutorial-sessions/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_tutorial_sessions_path(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/tutorial-sessions/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/tutorial-sessions",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_tutorial_sessions_root(request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/tutorial-sessions"
    return await forward_request(target_url, request)


# Reservation Service - Notifications
@router.api_route(
    "/api/v1/notifications/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_notifications_path(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/notifications/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/notifications",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_notifications_root(request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/notifications"
    return await forward_request(target_url, request)


# Reservation Service - Penalties
@router.api_route(
    "/api/v1/penalties/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_penalties_path(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/penalties/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/penalties",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_penalties_root(request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/penalties"
    return await forward_request(target_url, request)
