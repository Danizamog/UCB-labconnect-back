from __future__ import annotations

import time
from typing import Any

import httpx
from jose import jwt as jose_jwt

from app.core.config import settings

# Renovamos el token de superusuario de PocketBase un poco antes de su `exp`
# para que nunca se use ya caducado (devolveria listados vacios / 401 silenciosos).
_AUTH_TOKEN_REFRESH_MARGIN_SECONDS = 60.0
# Si el token no trae `exp` legible, re-autenticamos al menos cada 30 minutos.
_AUTH_TOKEN_FALLBACK_TTL_SECONDS = 1800.0


def _compute_token_refresh_at(token: str) -> float:
    now = time.time()
    try:
        exp = jose_jwt.get_unverified_claims(token).get("exp")
    except Exception:
        exp = None
    if isinstance(exp, (int, float)) and exp > now:
        return float(exp) - _AUTH_TOKEN_REFRESH_MARGIN_SECONDS
    return now + _AUTH_TOKEN_FALLBACK_TTL_SECONDS


class PocketBaseClient:
    """Admin PocketBase HTTP client with auto-authentication and token refresh.

    Authenticates with the superuser identity so it can read collections whose
    listRule is null (lab_access_session, inventory_loan_records_v2, stock_movement,
    ...). Never forwards an end-user token; authorization is enforced at the
    endpoint layer via ensure_any_permission.
    """

    def __init__(self) -> None:
        self._base_url = settings.pocketbase_url.rstrip("/")
        self._auth_identity = settings.pocketbase_auth_identity
        self._auth_password = settings.pocketbase_auth_password
        self._auth_collection = settings.pocketbase_auth_collection
        self._timeout = settings.pocketbase_timeout_seconds
        self._auth_token: str | None = None
        self._auth_token_refresh_at: float | None = None
        self._client = httpx.Client(
            timeout=httpx.Timeout(self._timeout, connect=min(self._timeout, 5.0)),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    @property
    def enabled(self) -> bool:
        return bool(self._base_url)

    def close(self) -> None:
        self._client.close()

    def _has_credentials(self) -> bool:
        return bool(self._auth_identity and self._auth_password)

    def _store_auth_token(self, token: str) -> None:
        self._auth_token = token
        self._auth_token_refresh_at = _compute_token_refresh_at(token)

    def _token_needs_refresh(self) -> bool:
        if not self._auth_token:
            return True
        if self._auth_token_refresh_at is None:
            return False
        return time.time() >= self._auth_token_refresh_at

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        return headers

    def _authenticate(self) -> None:
        if not self.enabled or not self._has_credentials():
            return

        payload = {"identity": self._auth_identity, "password": self._auth_password}
        endpoints = [f"{self._base_url}/api/collections/{self._auth_collection}/auth-with-password"]
        if self._auth_collection in {"_superusers", "admins"}:
            endpoints.append(f"{self._base_url}/api/admins/auth-with-password")

        last_error: Exception | None = None
        for endpoint in endpoints:
            try:
                response = self._client.post(endpoint, json=payload)
                response.raise_for_status()
                data = response.json() if response.content else {}
                token = data.get("token") if isinstance(data, dict) else None
                if token:
                    self._store_auth_token(token)
                    return
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code == 404:
                    continue
                raise

        if last_error:
            raise last_error
        raise ValueError("No se pudo autenticar contra PocketBase")

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any] | list[Any] | None:
        if not self.enabled:
            raise RuntimeError("PocketBase no esta configurado")

        if self._has_credentials() and self._token_needs_refresh():
            self._authenticate()

        response = self._client.request(method, url, headers=self._headers(), **kwargs)
        if response.status_code == 401 and self._has_credentials():
            self._auth_token = None
            self._authenticate()
            response = self._client.request(method, url, headers=self._headers(), **kwargs)

        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    def get_record(self, collection_name: str, record_id: str) -> dict[str, Any] | None:
        try:
            payload = self._request(
                "GET", f"{self._base_url}/api/collections/{collection_name}/records/{record_id}"
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return payload if isinstance(payload, dict) else None

    def get_collection(self, collection_name: str) -> dict[str, Any] | None:
        try:
            payload = self._request("GET", f"{self._base_url}/api/collections/{collection_name}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return payload if isinstance(payload, dict) else None

    def create_record(self, collection_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request(
            "POST",
            f"{self._base_url}/api/collections/{collection_name}/records",
            json=payload,
        )
        if not isinstance(result, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear el registro")
        return result

    def update_record(self, collection_name: str, record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request(
            "PATCH",
            f"{self._base_url}/api/collections/{collection_name}/records/{record_id}",
            json=payload,
        )
        if not isinstance(result, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar el registro")
        return result

    def list_records(
        self,
        collection_name: str,
        *,
        sort: str | None = None,
        filter: str | None = None,
        per_page: int = 200,
        max_items: int | None = None,
    ) -> list[dict[str, Any]]:
        page = 1
        records: list[dict[str, Any]] = []

        while True:
            params: dict[str, Any] = {"page": page, "perPage": per_page}
            if sort:
                params["sort"] = sort
            if filter:
                params["filter"] = filter

            payload = self._request(
                "GET",
                f"{self._base_url}/api/collections/{collection_name}/records",
                params=params,
            )
            if not isinstance(payload, dict):
                break

            items = payload.get("items", [])
            if not isinstance(items, list):
                break

            records.extend(item for item in items if isinstance(item, dict))
            if max_items is not None and len(records) >= max_items:
                return records[:max_items]
            if page >= int(payload.get("totalPages", 1) or 1):
                break
            page += 1

        return records
