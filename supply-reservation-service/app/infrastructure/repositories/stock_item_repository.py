import httpx

from app.core.config import settings
from app.infrastructure.pocketbase_base import PocketBaseClient


class StockItemRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{settings.pb_stock_items_collection}/records"

    def get_raw_by_id(self, item_id: str) -> dict | None:
        try:
            data = self._client.request("GET", f"{self._base}/{item_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if not isinstance(data, dict):
            return None
        return data

    def update_available_quantity(self, item_id: str, quantity_available: int) -> dict | None:
        try:
            data = self._client.request(
                "PATCH",
                f"{self._base}/{item_id}",
                payload={"quantity_available": max(0, int(quantity_available))},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if not isinstance(data, dict):
            return None
        return data
