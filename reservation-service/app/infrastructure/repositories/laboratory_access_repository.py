from __future__ import annotations

import httpx

from app.core.config import settings
from app.infrastructure.pocketbase_base import PocketBaseClient


class LaboratoryAccessRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{settings.pb_laboratory_collection}/records"

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
                return None
            raise
        return data if isinstance(data, dict) else None
