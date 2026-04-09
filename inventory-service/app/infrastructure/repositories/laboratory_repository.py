import httpx

from app.infrastructure.pocketbase_base import PocketBaseClient
from app.schemas.laboratory import LaboratoryCreate, LaboratoryResponse, LaboratoryUpdate

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
        created=record.get("created", ""),
        updated=record.get("updated", ""),
    )


class LaboratoryRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{_COLLECTION}/records"

    def list_all(self, page: int = 1, per_page: int = 50) -> list[LaboratoryResponse]:
        items: list[LaboratoryResponse] = []
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
            items.extend(_to_response(r) for r in records if isinstance(r, dict))
            total_pages = int(data.get("totalPages", current_page))
            if current_page >= total_pages:
                break
            current_page += 1

        return items

    def get_by_id(self, lab_id: str) -> LaboratoryResponse | None:
        try:
            data = self._client.request("GET", f"{self._base}/{lab_id}", params={"expand": "area_id"})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if not isinstance(data, dict):
            return None
        return _to_response(data)

    def create(self, body: LaboratoryCreate) -> LaboratoryResponse:
        payload = body.model_dump()
        data = self._client.request("POST", self._base, payload=payload, params={"expand": "area_id"})
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear el laboratorio")
        return _to_response(data)

    def update(self, lab_id: str, body: LaboratoryUpdate) -> LaboratoryResponse | None:
        existing = self.get_by_id(lab_id)
        if existing is None:
            return None
        payload = {k: v for k, v in body.model_dump().items() if v is not None}
        data = self._client.request("PATCH", f"{self._base}/{lab_id}", payload=payload, params={"expand": "area_id"})
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar el laboratorio")
        return _to_response(data)

    def delete(self, lab_id: str) -> bool:
        try:
            self._client.request("DELETE", f"{self._base}/{lab_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise
        return True
