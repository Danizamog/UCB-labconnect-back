from __future__ import annotations

import httpx

from app.core.config import settings
from app.infrastructure.pocketbase_base import PocketBaseClient


class LaboratoryAccessRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{settings.pb_laboratory_collection}/records"
        self._inventory_service_url = settings.inventory_service_url

    def _get_from_inventory_service(self, laboratory_id: str) -> dict | None:
        if not self._inventory_service_url:
            return None

        try:
            response = httpx.get(f"{self._inventory_service_url}/v1/laboratories", timeout=5.0)
            response.raise_for_status()
        except httpx.HTTPError:
            return None

        payload = response.json()
        if not isinstance(payload, list):
            return None

        normalized_id = str(laboratory_id or "").strip()
        for item in payload:
            if not isinstance(item, dict):
                continue
            if str(item.get("id") or "").strip() != normalized_id:
                continue

            return {
                "id": normalized_id,
                "name": item.get("name") or "",
                "location": item.get("location") or "",
                "capacity": item.get("capacity") or 0,
                "description": item.get("description") or "",
                "is_active": item.get("is_active", True),
                "area_id": item.get("area_id") or "",
                "allowed_roles": item.get("allowed_roles") or [],
                "allowed_user_ids": item.get("allowed_user_ids") or [],
                "required_permissions": item.get("required_permissions") or [],
            }

        return None

    def list_all(self, page: int = 1, per_page: int = 200) -> list[dict]:
        items: list[dict] = []
        current_page = page

        while True:
            data = self._client.request(
                "GET",
                self._base,
                params={"page": current_page, "perPage": per_page, "sort": "name", "expand": "area_id"},
            )
            if not isinstance(data, dict):
                break

            records = data.get("items", [])
            if not isinstance(records, list) or not records:
                break

            items.extend(record for record in records if isinstance(record, dict))
            total_pages = int(data.get("totalPages", current_page))
            if current_page >= total_pages:
                break
            current_page += 1

        return items

    def get_by_id(self, laboratory_id: str) -> dict | None:
        lab_id = str(laboratory_id or "").strip()
        if not lab_id:
            return None
        try:
            data = self._client.request("GET", f"{self._base}/{lab_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return self._get_from_inventory_service(lab_id)
            raise

        if isinstance(data, dict):
            return data

        return self._get_from_inventory_service(lab_id)
