import httpx

from app.infrastructure.cache_utils import TTLCache
from app.infrastructure.pocketbase_base import PocketBaseClient
from app.schemas.laboratory import (
    LaboratoryCreate,
    LaboratoryResponse,
    LaboratoryUpdate,
    PaginatedLaboratoryResponse,
)

_COLLECTION = "laboratory"


def _to_response(record: dict) -> LaboratoryResponse:
    expand = record.get("expand") or {}
    area_name: str | None = None
    if isinstance(expand, dict):
        area_record = expand.get("area_id")
        if isinstance(area_record, dict):
            area_name = area_record.get("name") or None

    return LaboratoryResponse(
        id=record.get("id", ""),
        name=record.get("name", ""),
        location=record.get("location", ""),
        capacity=int(record.get("capacity", 0)),
        description=record.get("description", ""),
        is_active=bool(record.get("is_active", True)),
        area_id=record.get("area_id", ""),
        area_name=area_name,
        manager=str(record.get("manager") or ""),
        created=record.get("created", ""),
        updated=record.get("updated", ""),
    )


class LaboratoryRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{_COLLECTION}/records"
        self._list_cache = TTLCache[list[LaboratoryResponse]](ttl_seconds=10.0)
        self._detail_cache = TTLCache[LaboratoryResponse | None](ttl_seconds=10.0)

    def _invalidate_cache(self) -> None:
        self._list_cache.invalidate()
        self._detail_cache.invalidate()

    def list_all(
        self,
        page: int = 1,
        per_page: int = 200,
        search: str | None = None,
        area_id: str | None = None,
    ) -> list[LaboratoryResponse]:
        cache_key = ("list_all", page, per_page, search, area_id)

        def load() -> list[LaboratoryResponse]:
            items: list[LaboratoryResponse] = []
            current_page = page

            clauses = []
            if search:
                clauses.append(f'name ~ "{search}"')
            if area_id:
                clauses.append(f'area_id = "{area_id}"')

            filter_expr = " && ".join(clauses) if clauses else ""

            while True:
                params = {
                    "page": current_page,
                    "perPage": per_page,
                    "sort": "name",
                    "expand": "area_id",
                }
                if filter_expr:
                    params["filter"] = filter_expr

                data = self._client.request(
                    "GET",
                    self._base,
                    params=params,
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

        return self._list_cache.get_or_set(cache_key, load)

    def list_paginated(
        self,
        *,
        page: int = 1,
        per_page: int = 12,
        search: str | None = None,
        area_id: str | None = None,
    ) -> PaginatedLaboratoryResponse:
        normalized_page = max(int(page or 1), 1)
        normalized_per_page = max(min(int(per_page or 12), 200), 1)

        clauses: list[str] = []
        normalized_search = (search or "").strip()
        if normalized_search:
            escaped = normalized_search.replace('"', '\\"')
            clauses.append(
                f'(name ~ "{escaped}" || location ~ "{escaped}" || description ~ "{escaped}")'
            )
        if area_id:
            clauses.append(f'area_id = "{area_id}"')

        params: dict[str, object] = {
            "page": normalized_page,
            "perPage": normalized_per_page,
            "sort": "name",
            "expand": "area_id",
        }
        if clauses:
            params["filter"] = " && ".join(clauses)

        data = self._client.request("GET", self._base, params=params)
        if not isinstance(data, dict):
            return PaginatedLaboratoryResponse(
                items=[],
                page=normalized_page,
                per_page=normalized_per_page,
                total_items=0,
                total_pages=0,
            )

        records = data.get("items", [])
        items = [
            _to_response(record)
            for record in records
            if isinstance(record, dict)
        ] if isinstance(records, list) else []

        return PaginatedLaboratoryResponse(
            items=items,
            page=int(data.get("page", normalized_page) or normalized_page),
            per_page=int(data.get("perPage", normalized_per_page) or normalized_per_page),
            total_items=int(data.get("totalItems", 0) or 0),
            total_pages=int(data.get("totalPages", 0) or 0),
        )

    def get_by_id(self, lab_id: str) -> LaboratoryResponse | None:
        normalized_id = str(lab_id or "").strip()
        if not normalized_id:
            return None

        def load() -> LaboratoryResponse | None:
            try:
                data = self._client.request("GET", f"{self._base}/{normalized_id}", params={"expand": "area_id"})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return None
                raise
            if not isinstance(data, dict):
                return None
            return _to_response(data)

        return self._detail_cache.get_or_set(("detail", normalized_id), load)

    def create(self, body: LaboratoryCreate) -> LaboratoryResponse:
        payload = body.model_dump()
        data = self._client.request("POST", self._base, payload=payload, params={"expand": "area_id"})
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear el laboratorio")
        self._invalidate_cache()
        return _to_response(data)

    def update(self, lab_id: str, body: LaboratoryUpdate) -> LaboratoryResponse | None:
        existing = self.get_by_id(lab_id)
        if existing is None:
            return None
        payload = {k: v for k, v in body.model_dump().items() if v is not None}
        data = self._client.request("PATCH", f"{self._base}/{lab_id}", payload=payload, params={"expand": "area_id"})
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar el laboratorio")
        self._invalidate_cache()
        return _to_response(data)

    def delete(self, lab_id: str) -> bool:
        try:
            self._client.request("DELETE", f"{self._base}/{lab_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise
        self._invalidate_cache()
        return True
