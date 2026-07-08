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
        start_time=record.get("start_time", ""),
        end_time=record.get("end_time", ""),
        subject=record.get("subject", ""),
        description=record.get("description", ""),
        is_active=bool(record.get("is_active", True)),
        teacher_id=str(record.get("teacher_id") or ""),
        teacher_name=str(record.get("teacher_name") or ""),
        created=record.get("created", ""),
        updated=record.get("updated", ""),
    )


class LabScheduleRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{_COLLECTION}/records"

    def _list_with_filter(self, filter_expr: str, sort: str = "weekday,start_time") -> list[LabScheduleResponse]:
        items: list[LabScheduleResponse] = []
        page = 1
        per_page = 200
        while True:
            data = self._client.request(
                "GET",
                self._base,
                params={"page": page, "perPage": per_page, "sort": sort, "filter": filter_expr},
            )
            if not isinstance(data, dict):
                break
            records = data.get("items", [])
            if not isinstance(records, list) or not records:
                break
            items.extend(_to_response(r) for r in records if isinstance(r, dict))
            total_pages = int(data.get("totalPages", page))
            if page >= total_pages:
                break
            page += 1
        return items

    def list_active_for_laboratory_weekday(self, laboratory_id: str, weekday: int) -> list[LabScheduleResponse]:
        normalized_laboratory_id = str(laboratory_id or "").strip()
        if not normalized_laboratory_id:
            return []
        filter_expr = (
            f'laboratory_id="{_escape_filter_value(normalized_laboratory_id)}" '
            f'&& weekday={int(weekday)} && is_active=true'
        )
        return self._list_with_filter(filter_expr)

    def list_for_laboratory(self, laboratory_id: str) -> list[LabScheduleResponse]:
        normalized_laboratory_id = str(laboratory_id or "").strip()
        if not normalized_laboratory_id:
            return []
        filter_expr = f'laboratory_id="{_escape_filter_value(normalized_laboratory_id)}"'
        return self._list_with_filter(filter_expr)

    def list_for_teacher(self, teacher_id: str) -> list[LabScheduleResponse]:
        normalized_teacher_id = str(teacher_id or "").strip()
        if not normalized_teacher_id:
            return []
        filter_expr = f'teacher_id="{_escape_filter_value(normalized_teacher_id)}" && is_active=true'
        return self._list_with_filter(filter_expr)

    def list_all_active(self) -> list[LabScheduleResponse]:
        """Trae todos los horarios activos en un solo round-trip.

        Usado por analytics para evitar N x M queries cuando se calcula la
        ocupacion semanal/mensual por laboratorio.
        """
        return self._list_with_filter("is_active=true", sort="laboratory_id,weekday,start_time")

    def list_all(self, page: int = 1, per_page: int = 200) -> list[LabScheduleResponse]:
        items: list[LabScheduleResponse] = []
        current_page = page

        while True:
            data = self._client.request(
                "GET",
                self._base,
                params={"page": current_page, "perPage": per_page, "sort": "laboratory_id,weekday,start_time"},
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
        payload = body.model_dump(exclude_none=True)
        payload.setdefault("description", "")
        payload.setdefault("teacher_id", "")
        payload.setdefault("teacher_name", "")
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
        if not payload:
            return existing

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
