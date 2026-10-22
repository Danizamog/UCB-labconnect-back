import httpx

from app.infrastructure.cache_utils import TTLCache
from app.infrastructure.pocketbase_base import PocketBaseClient
from app.schemas.area import AreaCreate, AreaResponse, AreaUpdate

_COLLECTION = "area"


def _to_response(record: dict) -> AreaResponse:
    return AreaResponse(
        id=record.get("id", ""),
        name=record.get("name", ""),
        description=record.get("description", ""),
        is_active=bool(record.get("is_active", True)),
        created=record.get("created", ""),
        updated=record.get("updated", ""),
    )


class AreaRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{_COLLECTION}/records"
        self._list_cache = TTLCache[list[AreaResponse]](ttl_seconds=10.0)
        self._detail_cache = TTLCache[AreaResponse | None](ttl_seconds=10.0)

    def _invalidate_cache(self) -> None:
        self._list_cache.invalidate()
        self._detail_cache.invalidate()

    def list_all(self, page: int = 1, per_page: int = 200) -> list[AreaResponse]:
        cache_key = ("list_all", page, per_page)

        def load() -> list[AreaResponse]:
            items: list[AreaResponse] = []
            current_page = page

            while True:
                data = self._client.request("GET", self._base, params={"page": current_page, "perPage": per_page, "sort": "name"})
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

        return self._list_cache.get_or_set(cache_key, load)

    def get_by_id(self, area_id: str) -> AreaResponse | None:
        normalized_id = str(area_id or "").strip()
        if not normalized_id:
            return None

        def load() -> AreaResponse | None:
            try:
                data = self._client.request("GET", f"{self._base}/{normalized_id}")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return None
                raise
            if not isinstance(data, dict):
                return None
            return _to_response(data)

        return self._detail_cache.get_or_set(("detail", normalized_id), load)

    def create(self, body: AreaCreate) -> AreaResponse:
        payload = body.model_dump()
        data = self._client.request("POST", self._base, payload=payload)
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear el area")
        self._invalidate_cache()
        return _to_response(data)

    def update(self, area_id: str, body: AreaUpdate) -> AreaResponse | None:
        existing = self.get_by_id(area_id)
        if existing is None:
            return None
        payload = {k: v for k, v in body.model_dump().items() if v is not None}
        data = self._client.request("PATCH", f"{self._base}/{area_id}", payload=payload)
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar el area")
        self._invalidate_cache()
        return _to_response(data)

    def delete(self, area_id: str) -> bool:
        try:
            self._client.request("DELETE", f"{self._base}/{area_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise
        self._invalidate_cache()
        return True
