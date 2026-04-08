from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.core.config import settings
from app.infrastructure.http.proxy import forward_request

router = APIRouter()


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


# Supply Reservation Service - Supply reservations
@router.api_route(
    "/api/v1/supply-reservations/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_supply_reservations_path(path: str, request: Request) -> Response:
    target_url = f"{settings.supply_reservation_service_url}/v1/supply-reservations/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/supply-reservations",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_supply_reservations_root(request: Request) -> Response:
    target_url = f"{settings.supply_reservation_service_url}/v1/supply-reservations"
    return await forward_request(target_url, request)
