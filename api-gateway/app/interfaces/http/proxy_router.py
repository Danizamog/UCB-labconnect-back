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
    "/api/roles/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_roles(path: str, request: Request) -> Response:
    target_url = f"{settings.role_service_url}/v1/roles/{path}"
    return await forward_request(target_url, request)
