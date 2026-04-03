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
    )


def _has_overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    a_start = parse_datetime(start_a)
    a_end = parse_datetime(end_a)
    b_start = parse_datetime(start_b)
    b_end = parse_datetime(end_b)
    return a_start < b_end and b_start < a_end


def _extract_http_error_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        payload = exc.response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        detail = payload.get("message") or payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()

        data = payload.get("data")
        if isinstance(data, dict):
            for field_name, field_data in data.items():
                if isinstance(field_data, dict):
                    msg = field_data.get("message")
                    if isinstance(msg, str) and msg.strip():
                        return f"{field_name}: {msg.strip()}"

    return f"PocketBase rechazo la operacion (HTTP {exc.response.status_code})"


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
        payload["status"] = payload.get("status") or "pending"
        if payload["status"] not in RESERVATION_STATUSES:
            raise ValueError(f"status invalido: {payload['status']}")

        payload["is_active"] = True if payload.get("is_active") is None else bool(payload.get("is_active"))
        payload["requested_by"] = payload.get("requested_by") or (current_user or {}).get("user_id") or ""
        if not payload["requested_by"]:
            raise ValueError("requested_by es requerido")

        self._validate_no_overlap(payload["laboratory_id"], payload["start_at"], payload["end_at"])

        try:
            data = self._client.request("POST", self._base, payload=payload)
        except httpx.HTTPStatusError as exc:
            raise ValueError(_extract_http_error_detail(exc)) from exc
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear reserva")
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

        try:
            data = self._client.request("PATCH", f"{self._base}/{reservation_id}", payload=payload)
        except httpx.HTTPStatusError as exc:
            raise ValueError(_extract_http_error_detail(exc)) from exc
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar reserva")
        return _to_response(data)

    def delete(self, reservation_id: str) -> bool:
        try:
            self._client.request("DELETE", f"{self._base}/{reservation_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise
        return True
