from __future__ import annotations

from typing import Any

import httpx


class PocketBaseClient:
    def __init__(
        self,
        *,
        base_url: str,
        auth_token: str | None = None,
        auth_identity: str | None = None,
        auth_password: str | None = None,
        auth_collection: str = "_superusers",
        timeout_seconds: float = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth_token = auth_token
        self._auth_identity = auth_identity
        self._auth_password = auth_password
        self._auth_collection = auth_collection
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 5.0)),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    @property
    def enabled(self) -> bool:
        return bool(self._base_url)

    def close(self) -> None:
        self._client.close()

    def _has_credentials(self) -> bool:
        return bool(self._auth_identity and self._auth_password)

    def _auth_endpoint(self) -> str:
        return f"{self._base_url}/api/collections/{self._auth_collection}/auth-with-password"

    def _headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _authenticate(self) -> None:
        if not self.enabled or not self._has_credentials():
            return

        payload = {"identity": self._auth_identity, "password": self._auth_password}
        endpoints = [self._auth_endpoint()]
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

        extra_headers = kwargs.pop("headers", None)
        # Normalize sort parameter if present in params
        params = kwargs.get("params")
        if params and "sort" in params and params.get("sort"):
            params = dict(params)
            params["sort"] = self._normalize_sort_param(params.get("sort"))
            kwargs["params"] = params

        response = self._client.request(method, url, headers=self._headers(extra_headers), **kwargs)
        if response.status_code == 401 and self._has_credentials():
            self._authenticate()
            response = self._client.request(method, url, headers=self._headers(extra_headers), **kwargs)

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

    def ensure_collection(self, collection_name: str, fields: list[dict[str, Any]]) -> None:
        existing = self.get_collection(collection_name)
        if existing:
            collection_id = existing.get("id") or collection_name
            self._request(
                "PATCH",
                f"{self._base_url}/api/collections/{collection_id}",
                json={"fields": fields},
            )
            return

        payload = {
            "name": collection_name,
            "type": "base",
            "fields": fields,
        }
        self._request("POST", f"{self._base_url}/api/collections", json=payload)

    def list_records(
        self,
        collection_name: str,
        *,
        sort: str | None = "source_id",
        filter: str | None = None,
        per_page: int = 200,
        max_items: int | None = None,
    ) -> list[dict[str, Any]]:
        page = 1
        records: list[dict[str, Any]] = []

        while True:
            params: dict[str, Any] = {"page": page, "perPage": per_page}
            if sort:
                params["sort"] = self._normalize_sort_param(sort)
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
            if page >= int(payload.get("totalPages", 1)):
                break
            page += 1

        return records

    def _normalize_sort_param(self, raw: str | None) -> str | None:
        if not raw:
            return None
        tokens = [t.strip() for t in str(raw).split(",") if t.strip()]
        normalized: list[str] = []
        for token in tokens:
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

    def get_record(self, collection_name: str, record_id: str) -> dict[str, Any] | None:
        try:
            payload = self._request("GET", f"{self._base_url}/api/collections/{collection_name}/records/{record_id}")
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

    def clear_collection_records(self, collection_name: str) -> None:
        for record in self.list_records(collection_name, sort=None):
            record_id = record.get("id")
            if isinstance(record_id, str) and record_id:
                self._request("DELETE", f"{self._base_url}/api/collections/{collection_name}/records/{record_id}")

    def replace_collection_records(self, collection_name: str, records: list[dict[str, Any]]) -> None:
        self.clear_collection_records(collection_name)
        for payload in records:
            self._request("POST", f"{self._base_url}/api/collections/{collection_name}/records", json=payload)
