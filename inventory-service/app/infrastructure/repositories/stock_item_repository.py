import httpx

from app.infrastructure.cache_utils import TTLCache
from app.infrastructure.pocketbase_base import PocketBaseClient
from app.schemas.stock_item import StockItemCreate, StockItemResponse, StockItemUpdate

_COLLECTION = "stock_item"


def _to_response(record: dict) -> StockItemResponse:
    expand = record.get("expand") or {}
    laboratory_name: str | None = None
    if isinstance(expand, dict):
        lab_record = expand.get("laboratory_id")
        if isinstance(lab_record, dict):
            laboratory_name = lab_record.get("name") or None

    return StockItemResponse(
        id=record.get("id", ""),
        name=record.get("name", ""),
        category=record.get("category", ""),
        unit=record.get("unit", ""),
        quantity_available=int(record.get("quantity_available", 0)),
        minimum_stock=int(record.get("minimum_stock", 0)),
        laboratory_id=record.get("laboratory_id", ""),
        laboratory_name=laboratory_name,
        description=record.get("description", ""),
        created=record.get("created", ""),
        updated=record.get("updated", ""),
    )


class StockItemRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{_COLLECTION}/records"
        self._list_cache = TTLCache[list[StockItemResponse]](ttl_seconds=5.0)
        self._detail_cache = TTLCache[StockItemResponse | None](ttl_seconds=5.0)

    def _invalidate_cache(self) -> None:
        self._list_cache.invalidate()
        self._detail_cache.invalidate()

    @staticmethod
    def _escape_filter_value(value: str) -> str:
        return str(value or "").replace("\\", "\\\\").replace('"', '\\"')

    def list_by_laboratories(self, laboratory_ids: list[str], per_page: int = 200) -> list[StockItemResponse]:
        normalized = [str(lid or "").strip() for lid in laboratory_ids if str(lid or "").strip()]
        if not normalized:
            return []

        filter_expression = " || ".join(
            f'laboratory_id="{self._escape_filter_value(lid)}"' for lid in normalized
        )

        items: list[StockItemResponse] = []
        current_page = 1
        while True:
            data = self._client.request(
                "GET",
                self._base,
                params={
                    "page": current_page,
                    "perPage": per_page,
                    "expand": "laboratory_id",
                    "filter": filter_expression,
                },
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

        items.sort(key=lambda x: (x.name or "").lower())
        return items

    def list_all(self, page: int = 1, per_page: int = 200) -> list[StockItemResponse]:
        cache_key = ("list_all", page, per_page)

        def load() -> list[StockItemResponse]:
            items: list[StockItemResponse] = []
            current_page = page

            while True:
                data = self._client.request(
                    "GET",
                    self._base,
                    params={"page": current_page, "perPage": per_page, "expand": "laboratory_id"},
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

            items.sort(key=lambda x: (x.name or "").lower())
            return items

        return self._list_cache.get_or_set(cache_key, load)

    def list_low_stock(self, per_page: int = 200) -> list[StockItemResponse]:
        items: list[StockItemResponse] = []
        current_page = 1
        filter_expression = "minimum_stock>0 && quantity_available<=minimum_stock"

        while True:
            data = self._client.request(
                "GET",
                self._base,
                params={
                    "page": current_page,
                    "perPage": per_page,
                    "expand": "laboratory_id",
                    "filter": filter_expression,
                },
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

        items.sort(key=lambda x: (x.name or "").lower())
        return items

    def get_by_id(self, item_id: str) -> StockItemResponse | None:
        normalized_id = str(item_id or "").strip()
        if not normalized_id:
            return None

        def load() -> StockItemResponse | None:
            try:
                data = self._client.request("GET", f"{self._base}/{normalized_id}", params={"expand": "laboratory_id"})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return None
                raise
            if not isinstance(data, dict):
                return None
            return _to_response(data)

        return self._detail_cache.get_or_set(("detail", normalized_id), load)

    def get_by_id_fresh(self, item_id: str) -> StockItemResponse | None:
        normalized_id = str(item_id or "").strip()
        if not normalized_id:
            return None
        self._detail_cache.invalidate(predicate=lambda k: k == ("detail", normalized_id))
        return self.get_by_id(normalized_id)

    def create(self, body: StockItemCreate) -> StockItemResponse:
        payload = body.model_dump()
        data = self._client.request("POST", self._base, payload=payload, params={"expand": "laboratory_id"})
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear el stock item")
        self._invalidate_cache()
        return _to_response(data)

    def update(self, item_id: str, body: StockItemUpdate) -> StockItemResponse | None:
        existing = self.get_by_id(item_id)
        if existing is None:
            return None
        payload = {k: v for k, v in body.model_dump().items() if v is not None}
        data = self._client.request("PATCH", f"{self._base}/{item_id}", payload=payload, params={"expand": "laboratory_id"})
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar el stock item")
        self._invalidate_cache()
        return _to_response(data)

    def delete(self, item_id: str) -> bool:
        try:
            self._client.request("DELETE", f"{self._base}/{item_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise
        self._invalidate_cache()
        return True
