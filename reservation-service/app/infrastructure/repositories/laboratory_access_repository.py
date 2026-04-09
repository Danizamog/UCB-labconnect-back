from __future__ import annotations

import httpx

from app.core.config import settings
from app.infrastructure.pocketbase_base import PocketBaseClient


class LaboratoryAccessRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{settings.pb_laboratory_collection}/records"

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
