from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.core.config import settings
from app.infrastructure.http.proxy import forward_request

router = APIRouter()


@router.api_route(
    "/api/auth/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_auth(path: str, request: Request) -> Response:
    target_url = f"{settings.auth_service_url}/v1/auth/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/inventory/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_inventory(path: str, request: Request) -> Response:
    target_url = f"{settings.inventory_service_url}/v1/inventory/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/availability/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_availability(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/availability/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/availability",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_availability_root(request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/availability"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/classes/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_classes(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/classes/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/classes",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_classes_root(request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/classes"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/class-tutorials/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_class_tutorials(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/class-tutorials/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/class-tutorials",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_class_tutorials_root(request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/class-tutorials/"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/users/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_users(path: str, request: Request) -> Response:
    target_url = f"{settings.auth_service_url}/v1/users/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/users",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_users_root(request: Request) -> Response:
    target_url = f"{settings.auth_service_url}/v1/users/"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/roles/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_roles(path: str, request: Request) -> Response:
    target_url = f"{settings.role_service_url}/v1/roles/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/roles",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_roles_root(request: Request) -> Response:
    target_url = f"{settings.role_service_url}/v1/roles/"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/roles/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_roles_legacy(path: str, request: Request) -> Response:
    target_url = f"{settings.role_service_url}/v1/roles/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/roles",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_roles_legacy_root(request: Request) -> Response:
    target_url = f"{settings.role_service_url}/v1/roles/"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/users/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_users_legacy(path: str, request: Request) -> Response:
    target_url = f"{settings.role_service_url}/v1/roles/users/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/users",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_users_legacy_root(request: Request) -> Response:
    target_url = f"{settings.role_service_url}/v1/roles/users"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/areas/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_areas(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/areas/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/areas",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_areas_root(request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/areas/"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/labs/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_labs(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/labs/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/labs",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_labs_root(request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/labs/"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/practice-planning/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_practice_planning(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/practice-planning/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/practice-planning",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_practice_planning_root(request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/practice-planning/"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/reservations/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_reservations(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/{path}"
    return await forward_request(target_url, request)
