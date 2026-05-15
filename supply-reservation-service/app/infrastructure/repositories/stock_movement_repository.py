import httpx

from app.infrastructure.pocketbase_base import PocketBaseClient

_COLLECTION = "stock_movement"


class StockMovementRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{_COLLECTION}/records"

    def create(
        self,
        *,
        stock_item_id: str,
        stock_item_name: str,
        movement_type: str,
        quantity_change: int,
        quantity_after: int,
        performed_by: str,
        notes: str = "",
    ) -> dict | None:
        payload = {
            "stock_item_id": stock_item_id,
            "stock_item_name": stock_item_name,
            "movement_type": movement_type,
            "quantity_change": quantity_change,
            "quantity_after": quantity_after,
            "performed_by": performed_by,
            "notes": notes,
        }
        try:
            data = self._client.request("POST", self._base, payload=payload)
        except httpx.HTTPStatusError:
            return None
        if not isinstance(data, dict):
            return None
        return data
