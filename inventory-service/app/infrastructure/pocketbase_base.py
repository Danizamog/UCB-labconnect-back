import json
import time
from json import JSONDecodeError
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.infrastructure.local_pocketbase import LocalPocketBaseFallback


class PocketBaseClient:
    """Base PocketBase HTTP client with auto-authentication and token refresh."""

    def __init__(self) -> None:
        self._base_url = settings.pocketbase_url.rstrip("/")
        self._auth_identity = settings.pocketbase_auth_identity
        self._auth_password = settings.pocketbase_auth_password
        self._auth_collection = settings.pocketbase_auth_collection
        self._timeout = settings.pocketbase_timeout_seconds
        self._auth_token: str | None = None
        self._data_mode = settings.data_mode
        self._primary_offline_until = 0.0
        self._primary_retry_seconds = max(float(settings.pocketbase_retry_seconds), 1.0)
        self._fallback = LocalPocketBaseFallback(
            postgres_url=settings.postgres_url,
            namespace=settings.local_data_namespace,
            enabled=settings.data_mode in {"hybrid", "postgres", "local"},
        )
        self._client = httpx.Client(
            timeout=httpx.Timeout(self._timeout, connect=min(self._timeout, 5.0)),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    def _use_local_only(self) -> bool:
        return self._data_mode in {"postgres", "local"} or not self._base_url

    def _primary_is_paused(self) -> bool:
        return time.monotonic() < self._primary_offline_until

    def _mark_primary_offline(self) -> None:
        self._auth_token = None
        self._primary_offline_until = time.monotonic() + self._primary_retry_seconds

    def _mark_primary_online(self) -> None:
        self._primary_offline_until = 0.0

    def _fallback_request(self, method: str, path: str, payload: dict | None, params: dict | None):
        if not self._fallback.enabled:
            raise ValueError("No se pudo conectar con PocketBase")
        return self._fallback.handle(method, path, payload=payload, params=params)

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

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        params: dict | None = None,
        retry_on_auth_error: bool = True,
    ) -> dict | list | None:
        if self._use_local_only() or self._primary_is_paused():
            return self._fallback_request(method, path, payload, params)

        try:
            self._ensure_authenticated()
        except (ValueError, httpx.HTTPError, httpx.HTTPStatusError):
            self._mark_primary_offline()
            return self._fallback_request(method, path, payload, params)

        url = f"{self._base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        try:
            response = self._client.request(method, url, json=payload, headers=self._headers())
            response.raise_for_status()
            raw_body = response.content
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401 and retry_on_auth_error and self._has_credentials():
                self._auth_token = None
                try:
                    self._authenticate()
                except (ValueError, httpx.HTTPError, httpx.HTTPStatusError):
                    self._mark_primary_offline()
                    return self._fallback_request(method, path, payload, params)
                return self.request(method, path, payload=payload, params=params, retry_on_auth_error=False)
            raise
        except httpx.HTTPError:
            self._mark_primary_offline()
            return self._fallback_request(method, path, payload, params)

        if not raw_body:
            return None
        try:
            result = json.loads(raw_body.decode("utf-8"))
        except (JSONDecodeError, UnicodeDecodeError):
            self._mark_primary_offline()
            return self._fallback_request(method, path, payload, params)

        self._mark_primary_online()
        if method.upper() in {"GET", "POST", "PATCH", "DELETE"}:
            try:
                self._fallback.sync_pending(base_url=self._base_url, client=self._client, headers_factory=self._headers)
            except Exception:
                pass
        return result

    def close(self) -> None:
        self._client.close()
