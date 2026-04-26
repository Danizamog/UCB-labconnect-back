import datetime

import httpx

from app.infrastructure.pocketbase_base import PocketBaseClient

_COLLECTION = "stock_movement"


class StockMovementRecord:
    def __init__(self, data: dict) -> None:
        self.id: str = data.get("id", "")
        self.stock_item_id: str = data.get("stock_item_id", "")
        self.stock_item_name: str = data.get("stock_item_name", "")
        self.movement_type: str = data.get("movement_type", "")
        self.quantity_change: int = int(data.get("quantity_change", 0))
        self.quantity_after: int = int(data.get("quantity_after", 0))
        self.performed_by: str = data.get("performed_by", "")
        self.notes: str = data.get("notes", "")
        self.created_at: str = data.get("created", "") or datetime.datetime.utcnow().isoformat() + "Z"


class StockMovementRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{_COLLECTION}/records"

    def create(
        self,
        stock_item_id: str,
        stock_item_name: str,
        movement_type: str,
        quantity_change: int,
        quantity_after: int,
        performed_by: str,
        notes: str = "",
    ) -> StockMovementRecord:
        payload = {
            "stock_item_id": stock_item_id,
            "stock_item_name": stock_item_name,
            "movement_type": movement_type,
            "quantity_change": quantity_change,
            "quantity_after": quantity_after,
            "performed_by": performed_by,
            "notes": notes,
        }
        data = self._client.request("POST", self._base, payload=payload)
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear el movimiento")
        return StockMovementRecord(data)

    def list_recent(
        self,
        limit: int = 40,
        stock_item_id: str | None = None,
    ) -> list[StockMovementRecord]:
        params: dict = {
            "perPage": min(limit, 200),
            "page": 1,
        }
        if stock_item_id:
            params["filter"] = f'stock_item_id = "{stock_item_id}"'

        try:
            data = self._client.request("GET", self._base, params=params)
        except httpx.HTTPStatusError:
            return []

        if not isinstance(data, dict):
            return []

        records = data.get("items", [])
        if not isinstance(records, list):
            return []

        result = [StockMovementRecord(r) for r in records if isinstance(r, dict)]
        # Ordenar del más reciente al más antiguo usando el campo created_at
        result.sort(key=lambda r: r.created_at, reverse=True)
        return result[:limit]

