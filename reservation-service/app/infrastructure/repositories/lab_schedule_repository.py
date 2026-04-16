import httpx

from app.core.config import settings
from app.infrastructure.pocketbase_base import PocketBaseClient
from app.schemas.lab_schedule import LabScheduleCreate, LabScheduleResponse, LabScheduleUpdate

_COLLECTION = settings.pb_lab_schedule_collection


def _escape_filter_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _to_response(record: dict) -> LabScheduleResponse:
    return LabScheduleResponse(
        id=record.get("id", ""),
        laboratory_id=record.get("laboratory_id", ""),
        weekday=int(record.get("weekday", 0)),
        open_time=record.get("open_time", "08:00"),
        close_time=record.get("close_time", "20:00"),
        slot_minutes=int(record.get("slot_minutes", 60) or 60),
        is_active=bool(record.get("is_active", True)),
        created=record.get("created", ""),
        updated=record.get("updated", ""),
    )


class LabScheduleRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{_COLLECTION}/records"

    def get_active_for_laboratory_weekday(self, laboratory_id: str, weekday: int) -> LabScheduleResponse | None:
        normalized_laboratory_id = str(laboratory_id or "").strip()
        if not normalized_laboratory_id:
            return None

        data = self._client.request(
            "GET",
            self._base,
            params={
                "page": 1,
                "perPage": 1,
                "filter": (
                    f'laboratory_id="{_escape_filter_value(normalized_laboratory_id)}" '
                    f'&& weekday={int(weekday)} && is_active=true'
                ),
            },
        )
        if not isinstance(data, dict):
            return None

        records = data.get("items", [])
        if not isinstance(records, list) or not records:
            return None

        first_record = records[0]
        if not isinstance(first_record, dict):
            return None
        return _to_response(first_record)

    def list_all(self, page: int = 1, per_page: int = 100) -> list[LabScheduleResponse]:
        items: list[LabScheduleResponse] = []
        current_page = page

        while True:
            data = self._client.request(
                "GET",
                self._base,
                params={"page": current_page, "perPage": per_page, "sort": "laboratory_id,weekday"},
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

    def get_by_id(self, schedule_id: str) -> LabScheduleResponse | None:
        try:
            data = self._client.request("GET", f"{self._base}/{schedule_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if not isinstance(data, dict):
            return None
        return _to_response(data)

    def create(self, body: LabScheduleCreate) -> LabScheduleResponse:
        if body.weekday < 0 or body.weekday > 6:
            raise ValueError("weekday debe estar entre 0 y 6")

        payload = body.model_dump()
        payload["slot_minutes"] = int(payload.get("slot_minutes") or 60)
        payload["is_active"] = True if payload.get("is_active") is None else bool(payload.get("is_active"))

        data = self._client.request("POST", self._base, payload=payload)
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear horario")
        return _to_response(data)

    def update(self, schedule_id: str, body: LabScheduleUpdate) -> LabScheduleResponse | None:
        existing = self.get_by_id(schedule_id)
        if existing is None:
            return None

        payload = {k: v for k, v in body.model_dump().items() if v is not None}
        if "weekday" in payload and (payload["weekday"] < 0 or payload["weekday"] > 6):
            raise ValueError("weekday debe estar entre 0 y 6")

        data = self._client.request("PATCH", f"{self._base}/{schedule_id}", payload=payload)
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar horario")
        return _to_response(data)

    def delete(self, schedule_id: str) -> bool:
        try:
            self._client.request("DELETE", f"{self._base}/{schedule_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise
        return True
