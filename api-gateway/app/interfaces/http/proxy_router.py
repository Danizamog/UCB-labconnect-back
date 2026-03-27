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


# Reservations Service - Availability (reservationsApi)
@router.api_route(
    "/api/availability/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_availability_path(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/availability/{path}"
    return await forward_request(target_url, request)


# Reservations Service - Class Tutorials (classTutorialService, reservationsApi)
@router.api_route(
    "/api/class-tutorials/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_class_tutorials_path(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/class-tutorials/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/class-tutorials",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_class_tutorials_root(request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/class-tutorials/"
    return await forward_request(target_url, request)


# Reservations Service - Practice Planning (reservationsApi)
@router.api_route(
    "/api/v1/practice-planning/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_practice_planning_path(path: str, request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/practice-planning/{path}"
    return await forward_request(target_url, request)


@router.api_route(
    "/api/v1/practice-planning",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_practice_planning_root(request: Request) -> Response:
    target_url = f"{settings.reservations_service_url}/v1/practice-planning/"
    return await forward_request(target_url, request)
