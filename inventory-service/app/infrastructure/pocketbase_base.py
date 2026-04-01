import json
from urllib.parse import urlencode

import httpx

from app.core.config import settings


class PocketBaseClient:
    """Base PocketBase HTTP client with auto-authentication and token refresh."""

    def __init__(self) -> None:
        self._base_url = settings.pocketbase_url.rstrip("/")
        self._auth_identity = settings.pocketbase_auth_identity
        self._auth_password = settings.pocketbase_auth_password
        self._auth_collection = settings.pocketbase_auth_collection
        self._timeout = settings.pocketbase_timeout_seconds
        self._auth_token: str | None = None
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

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        params: dict | None = None,
        retry_on_auth_error: bool = True,
    ) -> dict | list | None:
        self._ensure_authenticated()

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
                self._authenticate()
                return self.request(method, path, payload=payload, params=params, retry_on_auth_error=False)
            raise
        except httpx.HTTPError as exc:
            raise ValueError("No se pudo conectar con PocketBase") from exc

        if not raw_body:
            return None
        return json.loads(raw_body.decode("utf-8"))

    def close(self) -> None:
        self._client.close()
