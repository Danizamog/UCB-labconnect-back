from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.infrastructure.pocketbase_base import PocketBaseClient
from app.schemas.asset import ASSET_STATUSES, AssetCreate, AssetResponse, AssetStatusHistoryEntry, AssetUpdate

_COLLECTION = "asset"


def _to_response(record: dict) -> AssetResponse:
    expand = record.get("expand") or {}
    laboratory_name: str | None = None
    if isinstance(expand, dict):
        lab_record = expand.get("laboratory_id")
        if isinstance(lab_record, dict):
            laboratory_name = lab_record.get("name") or None

    return AssetResponse(
        id=record.get("id", ""),
        name=record.get("name", ""),
        category=record.get("category", ""),
        location=record.get("location", ""),
        description=record.get("description", ""),
        serial_number=record.get("serial_number", ""),
        laboratory_id=record.get("laboratory_id", ""),
        laboratory_name=laboratory_name,
        status=record.get("status", "available"),
        status_updated_at=record.get("status_updated_at", ""),
        status_updated_by=record.get("status_updated_by", ""),
        created=record.get("created", ""),
        updated=record.get("updated", ""),
    )


def _to_history_entry(record: dict) -> AssetStatusHistoryEntry:
    return AssetStatusHistoryEntry(
        id=record.get("id", ""),
        asset_id=record.get("asset_id", ""),
        previous_status=record.get("previous_status") or "",
        next_status=record.get("next_status") or "available",
        changed_by=record.get("changed_by") or "sistema",
        changed_at=record.get("changed_at") or record.get("created") or "",
        notes=(record.get("notes") or "").strip(),
    )


class AssetRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{_COLLECTION}/records"
        self._history_base = f"/api/collections/{settings.pb_asset_status_logs_collection}/records"

    def list_all(self, page: int = 1, per_page: int = 50) -> list[AssetResponse]:
        items: list[AssetResponse] = []
        current_page = page

        while True:
            data = self._client.request(
                "GET",
                self._base,
                params={"page": current_page, "perPage": per_page, "sort": "name", "expand": "laboratory_id"},
            )
            if not isinstance(data, dict):
                break
            records = data.get("items", [])
            if not isinstance(records, list) or not records:
                break
            items.extend(_to_response(r) for r in records if isinstance(r, dict))
            total_pages = int(data.get("totalPages", current_page))
            if current_page >= total_pages:
                break
            current_page += 1

        return items

    def get_by_id(self, asset_id: str) -> AssetResponse | None:
        try:
            data = self._client.request("GET", f"{self._base}/{asset_id}", params={"expand": "laboratory_id"})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if not isinstance(data, dict):
            return None
        return _to_response(data)

    def create(self, body: AssetCreate) -> AssetResponse:
        if body.status not in ASSET_STATUSES:
            raise ValueError(f"Estado invalido: {body.status!r}. Valores permitidos: {sorted(ASSET_STATUSES)}")
        payload = body.model_dump()
        data = self._client.request("POST", self._base, payload=payload, params={"expand": "laboratory_id"})
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear el asset")
        return _to_response(data)

    def update(self, asset_id: str, body: AssetUpdate) -> AssetResponse | None:
        existing = self.get_by_id(asset_id)
        if existing is None:
            return None
        if body.status is not None and body.status not in ASSET_STATUSES:
            raise ValueError(f"Estado invalido: {body.status!r}. Valores permitidos: {sorted(ASSET_STATUSES)}")
        payload = {k: v for k, v in body.model_dump().items() if v is not None}
        data = self._client.request("PATCH", f"{self._base}/{asset_id}", payload=payload, params={"expand": "laboratory_id"})
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar el asset")
        return _to_response(data)

    def update_status(self, asset_id: str, status: str, changed_by: str, notes: str = "") -> AssetResponse | None:
        existing = self.get_by_id(asset_id)
        if existing is None:
            return None
        if status not in ASSET_STATUSES:
            raise ValueError(f"Estado invalido: {status!r}. Valores permitidos: {sorted(ASSET_STATUSES)}")

        changed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        payload = {
            "status": status,
            "status_updated_at": changed_at,
            "status_updated_by": changed_by,
        }
        data = self._client.request("PATCH", f"{self._base}/{asset_id}", payload=payload, params={"expand": "laboratory_id"})
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar el estado del asset")

        # Guardamos el historial incluso cuando el estado se repite, para auditar observaciones de mantenimiento/daño.
        self._client.request(
            "POST",
            self._history_base,
            payload={
                "asset_id": asset_id,
                "previous_status": existing.status,
                "next_status": status,
                "changed_by": changed_by,
                "changed_at": changed_at,
                "notes": notes.strip(),
            },
        )

        return _to_response(data)

    def list_status_history(self, asset_id: str, limit: int = 100) -> list[AssetStatusHistoryEntry]:
        try:
            data = self._client.request(
                "GET",
                self._history_base,
                params={
                    "filter": f'asset_id = "{asset_id}"',
                    "sort": "-changed_at,-created",
                    "page": 1,
                    "perPage": max(1, min(limit, 200)),
                },
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return []
            raise

        if not isinstance(data, dict):
            return []

        records = data.get("items", [])
        if not isinstance(records, list):
            return []

        return [_to_history_entry(record) for record in records if isinstance(record, dict)]

    def delete(self, asset_id: str) -> bool:
        try:
            self._client.request("DELETE", f"{self._base}/{asset_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise
        return True
