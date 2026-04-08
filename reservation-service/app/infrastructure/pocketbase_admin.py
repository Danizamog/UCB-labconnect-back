from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.infrastructure.local_pocketbase import LocalPocketBaseFallback


class PocketBaseAdminClient:
    def __init__(
        self,
        *,
        base_url: str,
        auth_identity: str | None = None,
        auth_password: str | None = None,
        auth_collection: str = "_superusers",
        timeout_seconds: float = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth_token: str | None = None
        self._auth_identity = auth_identity
        self._auth_password = auth_password
        self._auth_collection = auth_collection
        self._data_mode = settings.data_mode
        self._primary_offline_until = 0.0
        self._primary_retry_seconds = max(float(settings.pocketbase_retry_seconds), 1.0)
        self._fallback = LocalPocketBaseFallback(
            postgres_url=settings.postgres_url,
            namespace=settings.local_data_namespace,
            enabled=settings.data_mode in {"hybrid", "postgres", "local"},
        )
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 5.0)),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    @property
    def enabled(self) -> bool:
        return bool(self._base_url)

    def _has_credentials(self) -> bool:
        return bool(self._auth_identity and self._auth_password)

    def _primary_is_paused(self) -> bool:
        return time.monotonic() < self._primary_offline_until

    def _mark_primary_offline(self) -> None:
        self._auth_token = None
        self._primary_offline_until = time.monotonic() + self._primary_retry_seconds

    def _mark_primary_online(self) -> None:
        self._primary_offline_until = 0.0

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

        last_exception: Exception | None = None
        for endpoint in endpoints:
            try:
                response = self._client.post(endpoint, json=payload)
                response.raise_for_status()
                data = response.json() if response.content else {}
                token = data.get("token") if isinstance(data, dict) else None
                if token:
                    self._auth_token = token
                    return
            except httpx.HTTPStatusError as exc:
                last_exception = exc
                if exc.response.status_code == 404:
                    continue
                raise

        if last_exception:
            raise last_exception
        raise ValueError("No se pudo autenticar contra PocketBase")

    def _request(self, method: str, url: str, **kwargs) -> dict[str, Any] | list[Any] | None:
        if not self.enabled:
            return self._fallback_request(method, url, kwargs)

        if self._data_mode in {"postgres", "local"} or self._primary_is_paused():
            return self._fallback_request(method, url, kwargs)

        try:
            if not self._auth_token and self._has_credentials():
                self._authenticate()
        except (ValueError, httpx.HTTPError, httpx.HTTPStatusError):
            self._mark_primary_offline()
            return self._fallback_request(method, url, kwargs)

        try:
            response = self._client.request(method, url, headers=self._headers(), **kwargs)
            if response.status_code == 401 and self._has_credentials():
                try:
                    self._authenticate()
                except (ValueError, httpx.HTTPError, httpx.HTTPStatusError):
                    self._mark_primary_offline()
                    return self._fallback_request(method, url, kwargs)
                response = self._client.request(method, url, headers=self._headers(), **kwargs)

            response.raise_for_status()
            if not response.content:
                return None
            payload = response.json()
            self._mark_primary_online()
            return payload
        except (ValueError, httpx.HTTPError, httpx.HTTPStatusError):
            self._mark_primary_offline()
            return self._fallback_request(method, url, kwargs)

    def _fallback_request(self, method: str, url: str, kwargs: dict[str, Any]) -> dict[str, Any] | list[Any] | None:
        if not self._fallback.enabled:
            raise RuntimeError("PocketBase no esta configurado")
        parsed = urlparse(url)
        path = parsed.path or url
        return self._fallback.handle(
            method,
            path,
            payload=kwargs.get("json"),
            params=kwargs.get("params"),
        )

    def get_collection(self, collection_name: str) -> dict[str, Any] | None:
        try:
            payload = self._request("GET", f"{self._base_url}/api/collections/{collection_name}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return payload if isinstance(payload, dict) else None

    def ensure_collection(self, collection_name: str, fields: list[dict[str, Any]]) -> None:
        existing = self.get_collection(collection_name)
        if existing:
            collection_id = existing.get("id") or collection_name
            self._request("PATCH", f"{self._base_url}/api/collections/{collection_id}", json={"fields": fields})
            return

        self._request(
            "POST",
            f"{self._base_url}/api/collections",
            json={"name": collection_name, "type": "base", "fields": fields},
        )

    def ensure_collection_fields(self, collection_name: str, fields_to_add: list[dict[str, Any]]) -> None:
        existing = self.get_collection(collection_name)
        if not existing:
            self.ensure_collection(collection_name, fields_to_add)
            return

        existing_fields = existing.get("fields", [])
        if not isinstance(existing_fields, list):
            existing_fields = []

        existing_names = {
            str(field.get("name") or "").strip()
            for field in existing_fields
            if isinstance(field, dict)
        }

        merged_fields = list(existing_fields)
        changed = False
        for field in fields_to_add:
            name = str(field.get("name") or "").strip()
            if not name or name in existing_names:
                continue
            merged_fields.append(field)
            existing_names.add(name)
            changed = True

        if not changed:
            return

        collection_id = existing.get("id") or collection_name
        self._request("PATCH", f"{self._base_url}/api/collections/{collection_id}", json={"fields": merged_fields})

    def list_records(
        self,
        collection_name: str,
        *,
        sort: str | None = "-created",
        filter: str | None = None,
        per_page: int = 200,
    ) -> list[dict[str, Any]]:
        page = 1
        records: list[dict[str, Any]] = []
        while True:
            params: dict[str, Any] = {"page": page, "perPage": per_page}
            if sort:
                params["sort"] = sort
            if filter:
                params["filter"] = filter
            payload = self._request("GET", f"{self._base_url}/api/collections/{collection_name}/records", params=params)
            if not isinstance(payload, dict):
                break
            items = payload.get("items", [])
            if not isinstance(items, list):
                break
            records.extend(item for item in items if isinstance(item, dict))
            if page >= int(payload.get("totalPages", 1)):
                break
            page += 1
        return records

    def get_record(self, collection_name: str, record_id: str) -> dict[str, Any] | None:
        try:
            payload = self._request("GET", f"{self._base_url}/api/collections/{collection_name}/records/{record_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return payload if isinstance(payload, dict) else None

    def create_record(self, collection_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request("POST", f"{self._base_url}/api/collections/{collection_name}/records", json=payload)
        if not isinstance(result, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear el registro")
        return result

    def update_record(self, collection_name: str, record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request("PATCH", f"{self._base_url}/api/collections/{collection_name}/records/{record_id}", json=payload)
        if not isinstance(result, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar el registro")
        return result
