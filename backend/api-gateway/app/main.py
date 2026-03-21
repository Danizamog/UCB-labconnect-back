import os
from typing import Dict

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response

from app.routers.availability import router as availability_router
from app.routers.classes import router as classes_router

AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8001")

app = FastAPI(title="LabConnect API Gateway", version="1.0.0")

app.include_router(availability_router)
app.include_router(classes_router)


def filter_response_headers(headers: Dict[str, str]) -> Dict[str, str]:
    excluded = {
        "content-encoding",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "upgrade",
    }
    return {key: value for key, value in headers.items() if key.lower() not in excluded}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api-gateway"}


@app.api_route(
    "/api/auth/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_auth(path: str, request: Request) -> Response:
    target_url = f"{AUTH_SERVICE_URL}/{path}"
    request_headers = dict(request.headers)
    request_headers.pop("host", None)
    request_body = await request.body()

    async with httpx.AsyncClient(timeout=20.0) as client:
        upstream_response = await client.request(
            method=request.method,
            url=target_url,
            params=request.query_params,
            headers=request_headers,
            content=request_body,
        )

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=filter_response_headers(dict(upstream_response.headers)),
        media_type=upstream_response.headers.get("content-type"),
    )
