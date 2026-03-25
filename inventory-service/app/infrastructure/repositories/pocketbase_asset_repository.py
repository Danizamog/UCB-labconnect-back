import httpx
from typing import Any

from app.domain.entities.asset import Asset


class PocketBaseAssetRepository:
    def __init__(
        self,
        base_url: str,
        collection: str = "assets",
        auth_token: str | None = None,
        auth_identity: str | None = None,
        auth_password: str | None = None,
        auth_collection: str = "_superusers",
        timeout_seconds: float = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._collection = collection
        self._timeout = timeout_seconds
        self._auth_identity = auth_identity
        self._auth_password = auth_password
        self._auth_collection = auth_collection
        self._auth_token = auth_token

    def _build_headers(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        merged_headers = dict(headers or {})
        if self._auth_token:
            merged_headers["Authorization"] = f"Bearer {self._auth_token}"
        return merged_headers

    def _has_credentials(self) -> bool:
        return bool(self._auth_identity and self._auth_password)

    def _auth_endpoint(self) -> str:
        return f"{self._base_url}/api/collections/{self._auth_collection}/auth-with-password"

    def _authenticate(self) -> None:
        if not self._has_credentials():
            return

        payload = {
            "identity": self._auth_identity,
            "password": self._auth_password,
        }

        auth_endpoints = [self._auth_endpoint()]
        if self._auth_collection in {"_superusers", "admins"}:
            auth_endpoints.append(f"{self._base_url}/api/admins/auth-with-password")

        last_exception: Exception | None = None
        for endpoint in auth_endpoints:
            try:
                response = httpx.request("POST", endpoint, json=payload, timeout=self._timeout)
                response.raise_for_status()
                data = response.json() if response.content else {}
                token = data.get("token") if isinstance(data, dict) else None
                if not token:
                    raise ValueError("PocketBase no devolvió token en auth-with-password")
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

    def _records_endpoint(self) -> str:
        return f"{self._base_url}/api/collections/{self._collection}/records"

    def _request(self, method: str, url: str, **kwargs) -> dict | list | None:
        headers = kwargs.pop("headers", {})

        if not self._auth_token and self._has_credentials():
            self._authenticate()

        response = httpx.request(
            method,
            url,
            headers=self._build_headers(headers),
            timeout=self._timeout,
            **kwargs,
        )

        if response.status_code == 401 and self._has_credentials():
            self._authenticate()
            response = httpx.request(
                method,
                url,
                headers=self._build_headers(headers),
                timeout=self._timeout,
                **kwargs,
            )

        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    @staticmethod
    def _to_asset(record: dict) -> Asset:
        return Asset(
            id=record.get("id"),
            name=record.get("name", ""),
            category=record.get("category", ""),
            description=record.get("description"),
            serial_number=record.get("serial_number"),
            laboratory_id=record.get("laboratory_id"),
            location=record.get("location"),
            status=record.get("status", "available"),
            item_type=record.get("item_type", "equipo"),
            brand=record.get("brand"),
            model=record.get("model"),
            quantity=record.get("quantity"),
            unit=record.get("unit"),
            expiry_date=record.get("expiry_date"),
            provider=record.get("provider"),
            concentration=record.get("concentration"),
        )

    def list_all(self) -> list[Asset]:
        assets: list[Asset] = []
        page = 1

        while True:
            payload = self._request(
                "GET",
                self._records_endpoint(),
                params={"page": page, "perPage": 200},
            )
            
            if not isinstance(payload, dict):
                return assets

            items = payload.get("items", [])
            assets.extend(self._to_asset(item) for item in items)

            if page >= int(payload.get("totalPages", 1)):
                break
            page += 1

        return assets

    def create(self, asset: Asset) -> Asset:
        payload = {
            "name": asset.name,
            "category": asset.category,
            "description": asset.description,
            "serial_number": asset.serial_number,
            "laboratory_id": asset.laboratory_id,
            "location": asset.location,
            "status": asset.status,
            "item_type": asset.item_type,
            "brand": asset.brand,
            "model": asset.model,
            "quantity": asset.quantity,
            "unit": asset.unit,
            "expiry_date": asset.expiry_date,
            "provider": asset.provider,
            "concentration": asset.concentration,
        }

        response_data = self._request(
            "POST",
            self._records_endpoint(),
            json=payload,
        )

        if not isinstance(response_data, dict):
            raise ValueError("PocketBase no devolvió un registro válido")

        return self._to_asset(response_data)

    def get_by_id(self, asset_id: str) -> Asset | None:
        try:
            response_data = self._request(
                "GET",
                f"{self._records_endpoint()}/{asset_id}",
            )

            if not isinstance(response_data, dict):
                return None

            return self._to_asset(response_data)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    def update(self, asset: Asset) -> Asset:
        if not asset.id:
            raise ValueError("Asset ID es requerido para actualizar")

        payload = {
            "name": asset.name,
            "category": asset.category,
            "description": asset.description,
            "serial_number": asset.serial_number,
            "laboratory_id": asset.laboratory_id,
            "status": asset.status,
            "item_type": asset.item_type,
        }

        if asset.location is not None and str(asset.location).strip():
            payload["location"] = str(asset.location).strip()
        if asset.brand:
            payload["brand"] = asset.brand
        if asset.model:
            payload["model"] = asset.model
        if asset.quantity is not None:
            payload["quantity"] = asset.quantity
        if asset.unit:
            payload["unit"] = asset.unit
        if asset.expiry_date:
            payload["expiry_date"] = asset.expiry_date
        if asset.provider:
            payload["provider"] = asset.provider
        if asset.concentration:
            payload["concentration"] = asset.concentration

        response_data = self._request(
            "PATCH",
            f"{self._records_endpoint()}/{asset.id}",
            json=payload,
        )

        if not isinstance(response_data, dict):
            raise ValueError("PocketBase no devolvió un registro válido")

        return self._to_asset(response_data)

    def delete(self, asset_id: str) -> None:
        self._request(
            "DELETE",
            f"{self._records_endpoint()}/{asset_id}",
        )
