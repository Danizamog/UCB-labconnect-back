from __future__ import annotations

from datetime import date, datetime

import httpx

from app.core.config import settings
from app.core.datetime_utils import combine_date_time, iter_time_ranges, parse_datetime
from app.infrastructure.pocketbase_admin import PocketBaseAdminClient
from app.infrastructure.pocketbase_base import PocketBaseClient
from app.infrastructure.repositories.lab_schedule_repository import LabScheduleRepository
from app.schemas.lab_reservation import RESERVATION_STATUSES, LabReservationCreate, LabReservationResponse, LabReservationUpdate

_COLLECTION = settings.pb_lab_reservation_collection
_FINAL_STATUSES = {"rejected", "cancelled", "completed", "absent"}
_LEGACY_CANCEL_REASON = "Reserva legacy desactivada por horario invalido"


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
    )


def _has_overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    a_start = parse_datetime(start_a)
    a_end = parse_datetime(end_a)
    b_start = parse_datetime(start_b)
    b_end = parse_datetime(end_b)
    return a_start < b_end and b_start < a_end


class LabReservationRepository:
    def __init__(self, client: PocketBaseClient, schedule_repo: LabScheduleRepository | None = None) -> None:
        self._client = client
        self._schedule_repo = schedule_repo
        self._base = f"/api/collections/{_COLLECTION}/records"
        self._users_base = f"/api/collections/{settings.pb_users_collection}/records"
        self._user_cache: dict[str, dict] = {}
        self._schedule_cache: dict[tuple[str, int], tuple[str, str, int]] = {}
        self._admin_client = PocketBaseAdminClient(
            base_url=settings.pocketbase_url,
            auth_identity=settings.pocketbase_auth_identity,
            auth_password=settings.pocketbase_auth_password,
            auth_collection=settings.pocketbase_auth_collection,
            timeout_seconds=settings.pocketbase_timeout_seconds,
        )
        self._ensure_identity_fields()

    def _ensure_identity_fields(self) -> None:
        if not self._admin_client.enabled:
            return

        self._admin_client.ensure_collection_fields(
            _COLLECTION,
            [
                {
                    "name": "requested_by_name",
                    "type": "text",
                    "required": False,
                    "max": 160,
                    "hidden": False,
                    "presentable": False,
                    "autogeneratePattern": "",
                    "pattern": "",
                    "primaryKey": False,
                    "system": False,
                    "min": 0,
                },
                {
                    "name": "requested_by_email",
                    "type": "email",
                    "required": False,
                    "hidden": False,
                    "presentable": False,
                    "onlyDomains": [],
                    "exceptDomains": [],
                    "system": False,
                },
            ],
        )

    def _list_all_records(self, page: int = 1, per_page: int = 200) -> list[dict]:
        items: list[dict] = []
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
            items.extend(record for record in records if isinstance(record, dict))
            total_pages = int(data.get("totalPages", current_page))
            if current_page >= total_pages:
                break
            current_page += 1

        return items

    def _get_user_record(self, user_id: str) -> dict | None:
        normalized = str(user_id or "").strip()
        if not normalized:
            return None

        if normalized in self._user_cache:
            return self._user_cache[normalized]

        try:
            data = self._client.request("GET", f"{self._users_base}/{normalized}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                self._user_cache[normalized] = {}
                return None
            raise

        user_record = data if isinstance(data, dict) else {}
        self._user_cache[normalized] = user_record
        return user_record or None

    def _identity_patch(self, record: dict) -> dict:
        requested_by = str(record.get("requested_by") or "").strip()
        current_name = str(record.get("requested_by_name") or "").strip()
        current_email = str(record.get("requested_by_email") or "").strip()
        if not requested_by or (current_name and current_email):
            return {}

        user_record = self._get_user_record(requested_by)
        if not user_record:
            return {}

        resolved_name = str(user_record.get("name") or user_record.get("username") or "").strip()
        resolved_email = str(user_record.get("email") or user_record.get("username") or "").strip()
        patch: dict[str, str] = {}
        if resolved_name and not current_name:
            patch["requested_by_name"] = resolved_name
        if resolved_email and not current_email:
            patch["requested_by_email"] = resolved_email
        return patch

    def _resolve_schedule_window(self, laboratory_id: str, reservation_day: date) -> tuple[datetime, datetime, int]:
        cache_key = (laboratory_id, reservation_day.weekday())
        cached = self._schedule_cache.get(cache_key)
        if cached is None:
            open_time = "08:00"
            close_time = "20:00"
            slot_minutes = 60
            if self._schedule_repo is not None:
                for item in self._schedule_repo.list_all():
                    if item.laboratory_id == laboratory_id and item.weekday == reservation_day.weekday() and item.is_active:
                        open_time = item.open_time
                        close_time = item.close_time
                        slot_minutes = item.slot_minutes or 60
                        break
            cached = (open_time, close_time, slot_minutes)
            self._schedule_cache[cache_key] = cached

        open_time, close_time, slot_minutes = cached
        return (
            combine_date_time(reservation_day, open_time),
            combine_date_time(reservation_day, close_time),
            slot_minutes,
        )

    def _legacy_invalid_reason(self, record: dict) -> str | None:
        try:
            start_at = parse_datetime(str(record.get("start_at") or ""))
            end_at = parse_datetime(str(record.get("end_at") or ""))
        except ValueError:
            return "Fechas invalidas"

        if end_at <= start_at:
            return "La hora de fin es menor o igual a la hora de inicio"

        if start_at.date() != end_at.date():
            return "La reserva cruza mas de un dia"

        day_start, day_end, slot_minutes = self._resolve_schedule_window(str(record.get("laboratory_id") or ""), start_at.date())
        if start_at < day_start or end_at > day_end:
            return "El horario esta fuera de la ventana operativa del laboratorio"

        slot_ranges = iter_time_ranges(day_start, day_end, slot_minutes)
        if not any(start_at == slot_start and end_at == slot_end for slot_start, slot_end in slot_ranges):
            return f"El horario no respeta bloques validos de {slot_minutes} minutos"

        return None

    def _build_sanitization_patch(self, record: dict) -> dict:
        patch = self._identity_patch(record)

        status = str(record.get("status") or "pending").strip().lower()
        is_active = bool(record.get("is_active", True))
        invalid_reason = self._legacy_invalid_reason(record)
        if invalid_reason and is_active and status not in _FINAL_STATUSES:
            notes = str(record.get("notes") or "").strip()
            audit_note = f"[Sistema] Reserva desactivada por integridad de datos: {invalid_reason}."
            if audit_note not in notes:
                patch["notes"] = f"{notes} {audit_note}".strip()
            patch["is_active"] = False
            patch["status"] = "cancelled"
            if not str(record.get("cancel_reason") or "").strip():
                patch["cancel_reason"] = _LEGACY_CANCEL_REASON

        return patch

    def _is_hidden_legacy_record(self, record: dict) -> bool:
        return (
            not bool(record.get("is_active", True))
            and str(record.get("status") or "").strip().lower() == "cancelled"
            and str(record.get("cancel_reason") or "").strip() == _LEGACY_CANCEL_REASON
        )

    def _normalize_record(self, record: dict, *, persist: bool = True) -> dict:
        patch = self._build_sanitization_patch(record)
        if persist and patch:
            updated = self._client.request("PATCH", f"{self._base}/{record.get('id')}", payload=patch)
            if isinstance(updated, dict):
                merged = dict(updated)
                merged.update(patch)
                return merged

        if patch:
            merged = dict(record)
            merged.update(patch)
            return merged
        return record

    def sanitize_legacy_records(self) -> int:
        sanitized = 0
        for record in self._list_all_records():
            patch = self._build_sanitization_patch(record)
            if not patch:
                continue
            self._client.request("PATCH", f"{self._base}/{record.get('id')}", payload=patch)
            sanitized += 1
        return sanitized

    def list_all(self, page: int = 1, per_page: int = 200) -> list[LabReservationResponse]:
        items: list[LabReservationResponse] = []
        for record in self._list_all_records(page=page, per_page=per_page):
            normalized = self._normalize_record(record)
            if self._is_hidden_legacy_record(normalized):
                continue
            items.append(_to_response(normalized))
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
        return _to_response(self._normalize_record(data))

    def _validate_no_overlap(self, laboratory_id: str, start_at: str, end_at: str, skip_id: str | None = None) -> None:
        for item in self.list_all():
            if item.laboratory_id != laboratory_id:
                continue
            if skip_id and item.id == skip_id:
                continue
            if item.status in _FINAL_STATUSES:
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
        payload["requested_by"] = payload.get("requested_by") or (current_user or {}).get("user_id") or ""
        if current_user:
            payload["requested_by_name"] = str(current_user.get("name") or current_user.get("username") or "").strip()
            payload["requested_by_email"] = str(current_user.get("email") or "").strip()
        if not payload["requested_by"]:
            raise ValueError("requested_by es requerido")

        self._validate_no_overlap(payload["laboratory_id"], payload["start_at"], payload["end_at"])

        data = self._client.request("POST", self._base, payload=payload)
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear reserva")
        return _to_response(self._normalize_record(data, persist=False))

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
            if status_to_check not in _FINAL_STATUSES:
                self._validate_no_overlap(next_laboratory, next_start, next_end, skip_id=reservation_id)

        data = self._client.request("PATCH", f"{self._base}/{reservation_id}", payload=payload)
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar reserva")
        return _to_response(self._normalize_record(data))

    def delete(self, reservation_id: str) -> bool:
        try:
            self._client.request("DELETE", f"{self._base}/{reservation_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise
        return True
