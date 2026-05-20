from __future__ import annotations

from typing import Any

import httpx


class PocketBaseAdminClient:
    @staticmethod
    def _merge_collection_fields(existing_fields: list[dict[str, Any]], fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged_by_name: dict[str, dict[str, Any]] = {}
        ordered_names: list[str] = []

        for field in existing_fields:
            if not isinstance(field, dict):
                continue
            name = str(field.get("name") or "").strip()
            if not name:
                continue
            merged_by_name[name] = field
            ordered_names.append(name)

        for field in fields:
            if not isinstance(field, dict):
                continue
            name = str(field.get("name") or "").strip()
            if not name:
                continue
            if name not in merged_by_name:
                ordered_names.append(name)
            merged_by_name[name] = {**merged_by_name.get(name, {}), **field}

        return [merged_by_name[name] for name in ordered_names if name in merged_by_name]

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
        self._collection_id_cache: dict[str, str] = {}
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 5.0)),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    @property
    def enabled(self) -> bool:
        return bool(self._base_url)

    def _has_credentials(self) -> bool:
        return bool(self._auth_identity and self._auth_password)

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
            raise RuntimeError("PocketBase no esta configurado")

        if not self._auth_token and self._has_credentials():
            self._authenticate()

        response = self._client.request(method, url, headers=self._headers(), **kwargs)
        if response.status_code == 401 and self._has_credentials():
            self._authenticate()
            response = self._client.request(method, url, headers=self._headers(), **kwargs)

        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    def get_collection(self, collection_name: str) -> dict[str, Any] | None:
        try:
            payload = self._request("GET", f"{self._base_url}/api/collections/{collection_name}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return payload if isinstance(payload, dict) else None

    def _resolve_collection_ref(self, collection_name: str) -> str:
        # Las colecciones de PocketBase no cambian de id en runtime, asi que
        # cacheamos el mapeo nombre -> id para evitar un GET extra por cada
        # list/get/create/update_record.
        cached = self._collection_id_cache.get(collection_name)
        if cached:
            return cached

        collection = self.get_collection(collection_name)
        if not collection:
            return collection_name
        resolved = str(collection.get("id") or collection_name)
        self._collection_id_cache[collection_name] = resolved
        return resolved

    def ensure_collection(self, collection_name: str, fields: list[dict[str, Any]]) -> None:
        existing = self.get_collection(collection_name)
        if existing:
            collection_id = existing.get("id") or collection_name
            existing_fields = existing.get("fields") if isinstance(existing.get("fields"), list) else []
            merged_fields = self._merge_collection_fields(existing_fields, fields)
            self._request("PATCH", f"{self._base_url}/api/collections/{collection_id}", json={"fields": merged_fields})
            return

        self._request(
            "POST",
            f"{self._base_url}/api/collections",
            json={"name": collection_name, "type": "base", "fields": fields},
        )

    def list_records(
        self,
        collection_name: str,
        *,
        sort: str | None = "-created",
        filter: str | None = None,
        per_page: int = 200,
        max_items: int | None = None,
    ) -> list[dict[str, Any]]:
        collection_ref = self._resolve_collection_ref(collection_name)
        page = 1
        records: list[dict[str, Any]] = []
        while True:
            params: dict[str, Any] = {"page": page, "perPage": per_page}
            if sort:
                params["sort"] = sort
            if filter:
                params["filter"] = filter
            payload = self._request("GET", f"{self._base_url}/api/collections/{collection_ref}/records", params=params)
            if not isinstance(payload, dict):
                break
            items = payload.get("items", [])
            if not isinstance(items, list):
                break
            records.extend(item for item in items if isinstance(item, dict))
            if max_items is not None and max_items > 0 and len(records) >= max_items:
                return records[:max_items]
            if page >= int(payload.get("totalPages", 1)):
                break
            page += 1
        return records

    def get_record(self, collection_name: str, record_id: str) -> dict[str, Any] | None:
        collection_ref = self._resolve_collection_ref(collection_name)
        try:
            payload = self._request("GET", f"{self._base_url}/api/collections/{collection_ref}/records/{record_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return payload if isinstance(payload, dict) else None

    def create_record(self, collection_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        collection_ref = self._resolve_collection_ref(collection_name)
        result = self._request("POST", f"{self._base_url}/api/collections/{collection_ref}/records", json=payload)
        if not isinstance(result, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear el registro")
        return result

    def update_record(self, collection_name: str, record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        collection_ref = self._resolve_collection_ref(collection_name)
        result = self._request("PATCH", f"{self._base_url}/api/collections/{collection_ref}/records/{record_id}", json=payload)
        if not isinstance(result, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar el registro")
        return result
