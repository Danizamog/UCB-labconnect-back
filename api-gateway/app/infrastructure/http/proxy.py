from typing import Dict

import httpx
from fastapi import Request
from fastapi.responses import Response


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
