import httpx

from app.core.config import settings
from app.core.datetime_utils import parse_datetime
from app.infrastructure.pocketbase_base import PocketBaseClient
from app.schemas.lab_block import BLOCK_TYPES, LabBlockCreate, LabBlockResponse, LabBlockUpdate

_COLLECTION = settings.pb_lab_block_collection


def _to_response(record: dict) -> LabBlockResponse:
    return LabBlockResponse(
        id=record.get("id", ""),
        laboratory_id=record.get("laboratory_id", ""),
        start_at=record.get("start_at", ""),
        end_at=record.get("end_at", ""),
        reason=record.get("reason", ""),
        block_type=record.get("block_type", "other"),
        created_by=record.get("created_by", ""),
        is_active=bool(record.get("is_active", True)),
        created=record.get("created", ""),
        updated=record.get("updated", ""),
    )


class LabBlockRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{_COLLECTION}/records"

    def list_all(self, page: int = 1, per_page: int = 200) -> list[LabBlockResponse]:
        items: list[LabBlockResponse] = []
        current_page = page

        while True:
            data = self._client.request(
                "GET",
                self._base,
                params={"page": current_page, "perPage": per_page, "sort": "start_at"},
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

    def get_by_id(self, block_id: str) -> LabBlockResponse | None:
        try:
            data = self._client.request("GET", f"{self._base}/{block_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if not isinstance(data, dict):
            return None
        return _to_response(data)

    def create(self, body: LabBlockCreate) -> LabBlockResponse:
        if body.block_type not in BLOCK_TYPES:
            raise ValueError(f"block_type invalido: {body.block_type}")
        start_at = parse_datetime(body.start_at)
        end_at = parse_datetime(body.end_at)
        if end_at <= start_at:
            raise ValueError("end_at debe ser mayor a start_at")

        payload = body.model_dump()
        payload["is_active"] = True if payload.get("is_active") is None else bool(payload.get("is_active"))
        data = self._client.request("POST", self._base, payload=payload)
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear bloqueo")
        return _to_response(data)

    def update(self, block_id: str, body: LabBlockUpdate) -> LabBlockResponse | None:
        existing = self.get_by_id(block_id)
        if existing is None:
            return None

        payload = {k: v for k, v in body.model_dump().items() if v is not None}
        next_start = payload.get("start_at", existing.start_at)
        next_end = payload.get("end_at", existing.end_at)
        if parse_datetime(next_end) <= parse_datetime(next_start):
            raise ValueError("end_at debe ser mayor a start_at")

        if "block_type" in payload and payload["block_type"] not in BLOCK_TYPES:
            raise ValueError(f"block_type invalido: {payload['block_type']}")

        data = self._client.request("PATCH", f"{self._base}/{block_id}", payload=payload)
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar bloqueo")
        return _to_response(data)

    def delete(self, block_id: str) -> bool:
        try:
            self._client.request("DELETE", f"{self._base}/{block_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise
        return True
