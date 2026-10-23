from typing import Dict

import httpx
from fastapi import Request
from fastapi.responses import Response


_proxy_client = httpx.AsyncClient(
    timeout=httpx.Timeout(20.0, connect=5.0),
    limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
)


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


async def forward_request(target_url: str, request: Request) -> Response:
    request_headers = dict(request.headers)
    request_headers.pop("host", None)
    request_body = await request.body()

    try:
        upstream_response = await _proxy_client.request(
            method=request.method,
            url=target_url,
            params=request.query_params,
            headers=request_headers,
            content=request_body,
            follow_redirects=True,
        )
    except httpx.RequestError:
        return Response(
            content=b'{"detail":"Servicio no disponible"}',
            status_code=503,
            media_type="application/json",
        )

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=filter_response_headers(dict(upstream_response.headers)),
        media_type=upstream_response.headers.get("content-type"),
    )


async def close_proxy_client() -> None:
    await _proxy_client.aclose()
