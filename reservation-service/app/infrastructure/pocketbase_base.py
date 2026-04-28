import asyncio
import json
import logging
from urllib.parse import urlsplit, parse_qsl
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.infrastructure.local_pocketbase import LocalPocketBaseFallback

logger = logging.getLogger(__name__)


class PocketBaseClient:
    def __init__(self) -> None:
        self._base_url = settings.pocketbase_url.rstrip("/")
        self._auth_identity = settings.pocketbase_auth_identity
        self._auth_password = settings.pocketbase_auth_password
        self._auth_collection = settings.pocketbase_auth_collection
        self._timeout = settings.pocketbase_timeout_seconds
        self._auth_token: str | None = None
        self._fallback = LocalPocketBaseFallback(
            postgres_url=settings.postgres_url,
            namespace=settings.local_data_namespace,
            enabled=settings.data_mode in {"hybrid", "postgres", "local"} or not bool(self._base_url),
        )
        self._client = httpx.Client(
            timeout=httpx.Timeout(self._timeout, connect=min(self._timeout, 5.0)),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    def _has_credentials(self) -> bool:
        return bool(self._auth_identity and self._auth_password)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        return headers

    def _authenticate(self) -> None:
        if not self._has_credentials():
            return

        payload = {"identity": self._auth_identity, "password": self._auth_password}
        endpoint = f"{self._base_url}/api/collections/{self._auth_collection}/auth-with-password"
        endpoints = [endpoint]
        if self._auth_collection in {"_superusers", "admins"}:
            endpoints.append(f"{self._base_url}/api/admins/auth-with-password")

        last_error: Exception | None = None
        for ep in endpoints:
            try:
                response = self._client.post(ep, json=payload, headers={"Content-Type": "application/json"})
                response.raise_for_status()
                data = response.json()
                token = data.get("token") if isinstance(data, dict) else None
                if token:
                    self._auth_token = token
                    return
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code == 404:
                    continue
                raise
            except httpx.HTTPError as exc:
                raise ValueError("No se pudo conectar con PocketBase") from exc

        if last_error:
            raise ValueError("No se pudo autenticar contra PocketBase") from last_error
        raise ValueError("No se pudo autenticar contra PocketBase")

    def _ensure_authenticated(self) -> None:
        if self._has_credentials() and not self._auth_token:
            self._authenticate()

    def _fallback_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict | None = None,
        params: dict | None = None,
    ) -> dict | list | None:
        merged_params = dict(params or {})
        parsed = urlsplit(path)
        normalized_path = parsed.path or path
        if parsed.query:
            merged_params.update(dict(parse_qsl(parsed.query, keep_blank_values=True)))
        return self._fallback.handle(method, normalized_path, payload=payload, params=merged_params)

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        params: dict | None = None,
        retry_on_auth_error: bool = True,
    ) -> dict | list | None:
        if not self._base_url:
            if self._fallback.enabled:
                return self._fallback_request(method, path, payload=payload, params=params)
            raise ValueError("No se pudo conectar con PocketBase")

        self._ensure_authenticated()

        # Normalize sort parameter if provided (accepts 'field', 'field:asc', 'field:desc', 'field,-other')
        if params and "sort" in params and params.get("sort"):
            params = dict(params)
            params["sort"] = self._normalize_sort_param(params.get("sort"))

        url = f"{self._base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        if settings.pocketbase_verbose_request_logs:
            logger.debug("[POCKETBASE] %s %s", method, url)

        try:
            response = self._client.request(method, url, json=payload, headers=self._headers())
            response.raise_for_status()
            raw_body = response.content
            if settings.pocketbase_verbose_request_logs:
                logger.debug("[POCKETBASE SUCCESS] %s %s | Status: %s", method, url, response.status_code)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "[POCKETBASE ERROR] %s %s | Status: %s",
                method,
                url,
                exc.response.status_code,
            )
            if exc.response.status_code == 401 and retry_on_auth_error and self._has_credentials():
                self._auth_token = None
                self._authenticate()
                return self.request(method, path, payload=payload, params=params, retry_on_auth_error=False)
            if self._fallback.enabled and exc.response.status_code >= 500:
                return self._fallback_request(method, path, payload=payload, params=params)
            raise
        except httpx.HTTPError as exc:
            logger.error("[POCKETBASE CONNECTION ERROR] %s %s | Error: %s", method, url, str(exc))
            if self._fallback.enabled:
                return self._fallback_request(method, path, payload=payload, params=params)
            raise ValueError("No se pudo conectar con PocketBase") from exc

        if not raw_body:
            return None
        return json.loads(raw_body.decode("utf-8"))

    async def arequest(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        params: dict | None = None,
        retry_on_auth_error: bool = True,
    ) -> dict | list | None:
        return await asyncio.to_thread(
            self.request,
            method,
            path,
            payload=payload,
            params=params,
            retry_on_auth_error=retry_on_auth_error,
        )

    def close(self) -> None:
        self._client.close()

    def _normalize_sort_param(self, raw: str | None) -> str | None:
        if not raw:
            return None
        tokens = [t.strip() for t in str(raw).split(",") if t.strip()]
        normalized: list[str] = []
        for token in tokens:
            # support prefix -field or +field
            if token.startswith("-") or token.startswith("+"):
                direction = "desc" if token.startswith("-") else "asc"
                field = token.lstrip("+-").strip()
            elif ":" in token:
                parts = token.split(":", 1)
                field = parts[0].strip()
                direction = parts[1].strip().lower()
            else:
                field = token
                direction = "asc"

            if not field:
                continue
            if direction == "desc":
                normalized.append(f"-{field}")
            else:
                normalized.append(field)

        return ",".join(normalized) if normalized else None
