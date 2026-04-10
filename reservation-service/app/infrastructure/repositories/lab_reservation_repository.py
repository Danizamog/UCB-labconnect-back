import httpx

from app.core.config import settings
from app.core.datetime_utils import parse_datetime
from app.infrastructure.pocketbase_base import PocketBaseClient
from app.schemas.lab_reservation import RESERVATION_STATUSES, LabReservationCreate, LabReservationResponse, LabReservationUpdate

_COLLECTION = settings.pb_lab_reservation_collection


def _to_response(record: dict) -> LabReservationResponse:
    return LabReservationResponse(
        id=record.get("id", ""),
        laboratory_id=record.get("laboratory_id", ""),
        area_id=record.get("area_id", ""),
        requested_by=record.get("requested_by", ""),
        purpose=record.get("purpose", ""),
        start_at=record.get("start_at", ""),
        end_at=record.get("end_at", ""),
        status=record.get("status", "pending"),
        attendees_count=record.get("attendees_count"),
        notes=record.get("notes", ""),
        approved_by=record.get("approved_by", ""),
        approved_at=record.get("approved_at", ""),
        cancel_reason=record.get("cancel_reason", ""),
        is_active=bool(record.get("is_active", True)),
        created=record.get("created", ""),
        updated=record.get("updated", ""),
        requested_by_name=record.get("requested_by_name", ""),
        requested_by_email=record.get("requested_by_email", ""),
        station_label=record.get("station_label", ""),
        check_in_at=record.get("check_in_at", ""),
        check_out_at=record.get("check_out_at", ""),
        is_walk_in=bool(record.get("is_walk_in", False)),
        user_modification_count=int(record.get("user_modification_count") or 0),
    )


def _has_overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    a_start = parse_datetime(start_a)
    a_end = parse_datetime(end_a)
    b_start = parse_datetime(start_b)
    b_end = parse_datetime(end_b)
    return a_start < b_end and b_start < a_end


def _escape_filter_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


class LabReservationRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{_COLLECTION}/records"

    def list_all(self, page: int = 1, per_page: int = 200) -> list[LabReservationResponse]:
        items: list[LabReservationResponse] = []
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

    def _build_filter_expression(
        self,
        *,
        laboratory_id: str | None = None,
        day: str | None = None,
        status_filter: str | None = None,
        requested_by: str | None = None,
    ) -> str | None:
        clauses: list[str] = []
        if laboratory_id:
            clauses.append(f'laboratory_id="{_escape_filter_value(str(laboratory_id).strip())}"')
        if status_filter:
            clauses.append(f'status="{_escape_filter_value(str(status_filter).strip())}"')
        if requested_by:
            clauses.append(f'requested_by="{_escape_filter_value(str(requested_by).strip())}"')
        if day:
            clauses.append(f'start_at~"{_escape_filter_value(str(day).strip())}"')

        return " && ".join(clauses) if clauses else None

    @staticmethod
    def _build_sort_expression(sort_by: str, sort_type: str) -> str:
        normalized_sort_by = "start_at" if sort_by == "date" else str(sort_by or "start_at").strip()
        normalized_sort_type = str(sort_type or "ASC").strip().upper()
        return f"-{normalized_sort_by}" if normalized_sort_type == "DESC" else normalized_sort_by

    def list_filtered(
        self,
        *,
        laboratory_id: str | None = None,
        day: str | None = None,
        status_filter: str | None = None,
        requested_by: str | None = None,
        sort_by: str = "start_at",
        sort_type: str = "ASC",
        per_page: int = 200,
    ) -> list[LabReservationResponse]:
        items: list[LabReservationResponse] = []
        current_page = 1
        filter_expression = self._build_filter_expression(
            laboratory_id=laboratory_id,
            day=day,
            status_filter=status_filter,
            requested_by=requested_by,
        )
        sort_expression = self._build_sort_expression(sort_by, sort_type)

        while True:
            data = self._client.request(
                "GET",
                self._base,
                params={
                    "page": current_page,
                    "perPage": per_page,
                    "sort": sort_expression,
                    **({"filter": filter_expression} if filter_expression else {}),
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

        return items

    def search_page(
        self,
        *,
        laboratory_id: str | None = None,
        day: str | None = None,
        status_filter: str | None = None,
        requested_by: str | None = None,
        page_number: int = 0,
        page_size: int = 10,
        sort_by: str = "start_at",
        sort_type: str = "DESC",
    ) -> tuple[list[LabReservationResponse], int]:
        filter_expression = self._build_filter_expression(
            laboratory_id=laboratory_id,
            day=day,
            status_filter=status_filter,
            requested_by=requested_by,
        )
        sort_expression = self._build_sort_expression(sort_by, sort_type)
        data = self._client.request(
            "GET",
            self._base,
            params={
                "page": page_number + 1,
                "perPage": page_size,
                "sort": sort_expression,
                **({"filter": filter_expression} if filter_expression else {}),
            },
        )
        if not isinstance(data, dict):
            return [], 0

        records = data.get("items", [])
        total_items = int(data.get("totalItems", 0) or 0)
        if not isinstance(records, list):
            return [], total_items
        return [_to_response(record) for record in records if isinstance(record, dict)], total_items

    def get_by_id(self, reservation_id: str) -> LabReservationResponse | None:
        try:
            data = self._client.request("GET", f"{self._base}/{reservation_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if not isinstance(data, dict):
            return None
        return _to_response(data)

    def _validate_no_overlap(self, laboratory_id: str, start_at: str, end_at: str, skip_id: str | None = None) -> None:
        for item in self.list_all():
            if item.laboratory_id != laboratory_id:
                continue
            if skip_id and item.id == skip_id:
                continue
            if item.status in {"rejected", "cancelled", "completed", "absent"}:
                continue
            if _has_overlap(start_at, end_at, item.start_at, item.end_at):
                raise ValueError("Existe una reserva activa que se cruza con ese horario")

    def create(self, body: LabReservationCreate, current_user: dict | None = None) -> LabReservationResponse:
        start_at = parse_datetime(body.start_at)
        end_at = parse_datetime(body.end_at)
        if end_at <= start_at:
            raise ValueError("end_at debe ser mayor a start_at")

        payload = body.model_dump()
        payload["status"] = "pending"

        payload["is_active"] = True if payload.get("is_active") is None else bool(payload.get("is_active"))
        payload["user_modification_count"] = int(payload.get("user_modification_count") or 0)
        payload["requested_by"] = payload.get("requested_by") or (current_user or {}).get("user_id") or ""
        if current_user:
            payload["requested_by_name"] = str(current_user.get("name") or current_user.get("username") or "").strip()
            payload["requested_by_email"] = str(current_user.get("email") or "").strip()
        if not payload["requested_by"]:
            raise ValueError("requested_by es requerido")

        self._validate_no_overlap(payload["laboratory_id"], payload["start_at"], payload["end_at"])

        try:
            data = self._client.request("POST", self._base, payload=payload)
        except Exception as exc:
            raise ValueError(f"Error guardando en PocketBase: {str(exc)}") from exc
        
        if not isinstance(data, dict):
            raise ValueError(f"PocketBase devolvio respuesta invalida al crear reserva: {type(data)} - {data}")
        return _to_response(data)

    def update(self, reservation_id: str, body: LabReservationUpdate) -> LabReservationResponse | None:
        existing = self.get_by_id(reservation_id)
        if existing is None:
            return None

        payload = {k: v for k, v in body.model_dump().items() if v is not None}

        next_start = payload.get("start_at", existing.start_at)
        next_end = payload.get("end_at", existing.end_at)
        next_laboratory = payload.get("laboratory_id", existing.laboratory_id)

        if parse_datetime(next_end) <= parse_datetime(next_start):
            raise ValueError("end_at debe ser mayor a start_at")

        if "status" in payload and payload["status"] not in RESERVATION_STATUSES:
            raise ValueError(f"status invalido: {payload['status']}")

        if any(field in payload for field in {"laboratory_id", "start_at", "end_at", "status"}):
            status_to_check = payload.get("status", existing.status)
            if status_to_check not in {"rejected", "cancelled", "completed", "absent"}:
                self._validate_no_overlap(next_laboratory, next_start, next_end, skip_id=reservation_id)

        data = self._client.request("PATCH", f"{self._base}/{reservation_id}", payload=payload)
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar reserva")
        return _to_response(data)

    def delete(self, reservation_id: str) -> bool:
        # DESHABILITADO: Las reservas nunca deben ser borradas
        # Solo deben cambiar de status a 'cancelled' para mantener historial
        raise NotImplementedError(
            "No se pueden borrar reservas. Use update() con status='cancelled' en lugar de delete()."
        )
        # Código antiguo mantenido por referencia pero NUNCA ejecutado:
        # try:
        #     self._client.request("DELETE", f"{self._base}/{reservation_id}")
        # except httpx.HTTPStatusError as exc:
