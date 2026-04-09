from __future__ import annotations

import logging
from datetime import date, datetime

import httpx

from app.core.config import settings
from app.core.datetime_utils import combine_date_time, iter_time_ranges, now_local_naive, parse_datetime
from app.infrastructure.pocketbase_admin import PocketBaseAdminClient
from app.infrastructure.pocketbase_base import PocketBaseClient
from app.infrastructure.repositories.lab_schedule_repository import LabScheduleRepository
from app.schemas.lab_reservation import RESERVATION_STATUSES, LabReservationCreate, LabReservationResponse, LabReservationUpdate

_COLLECTION = settings.pb_lab_reservation_collection
_FINAL_STATUSES = {"rejected", "cancelled", "completed", "absent"}
_LEGACY_CANCEL_REASON = "Reserva legacy desactivada por horario invalido"
logger = logging.getLogger(__name__)


def _text(record: dict, field: str, default: str = "") -> str:
    value = record.get(field, default)
    if value is None:
        return default
    return str(value)


def _to_response(record: dict) -> LabReservationResponse:
    return LabReservationResponse(
        id=_text(record, "id"),
        laboratory_id=_text(record, "laboratory_id"),
        area_id=_text(record, "area_id"),
        requested_by=_text(record, "requested_by"),
        purpose=_text(record, "purpose"),
        start_at=_text(record, "start_at"),
        end_at=_text(record, "end_at"),
        status=_text(record, "status", "pending") or "pending",
        attendees_count=record.get("attendees_count"),
        notes=_text(record, "notes"),
        approved_by=_text(record, "approved_by"),
        approved_at=_text(record, "approved_at"),
        cancel_reason=_text(record, "cancel_reason"),
        is_active=bool(record.get("is_active", True)),
        created=_text(record, "created"),
        updated=_text(record, "updated"),
        requested_by_name=_text(record, "requested_by_name"),
        requested_by_email=_text(record, "requested_by_email"),
        station_label=_text(record, "station_label"),
        check_in_at=_text(record, "check_in_at"),
        check_out_at=_text(record, "check_out_at"),
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
        try:
            self._ensure_identity_fields()
        except Exception as exc:  # pragma: no cover - startup resilience for unavailable external DB
            logger.warning("No se pudieron asegurar campos de identidad de reservas: %s", exc)

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

    def _list_remote_records(self, page: int = 1, per_page: int = 200) -> list[dict]:
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

    def _list_local_records(self, page: int = 1, per_page: int = 200) -> list[dict]:
        try:
            data = self._client.fallback_request(
                "GET",
                self._base,
                params={"page": page, "perPage": per_page, "sort": "start_at"},
            )
        except ValueError:
            return []
        if not isinstance(data, dict):
            return []
        records = data.get("items", [])
        return [record for record in records if isinstance(record, dict)]

    def _list_all_records(self, page: int = 1, per_page: int = 200) -> list[tuple[dict, bool]]:
        merged: dict[str, tuple[dict, bool]] = {}

        for record in self._list_remote_records(page=page, per_page=per_page):
            record_id = str(record.get("id") or "").strip()
            if record_id:
                merged[record_id] = (record, True)

        for record in self._list_local_records(page=page, per_page=per_page):
            record_id = str(record.get("id") or "").strip()
            if record_id:
                # Los registros locales representan operaciones operativas cuando PocketBase remoto
                # no pudo aceptarlas; deben prevalecer para que la UI vea el estado real actual.
                merged[record_id] = (record, False)

        return [item for item in merged.values()]

    def _get_remote_record(self, record_id: str) -> dict | None:
        try:
            data = self._client.request("GET", f"{self._base}/{record_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return data if isinstance(data, dict) else None

    def _get_local_record(self, record_id: str) -> dict | None:
        try:
            data = self._client.fallback_request("GET", f"{self._base}/{record_id}")
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def _get_user_record(self, user_id: str) -> dict | None:
        normalized = str(user_id or "").strip()
        if not normalized:
            return None

        if normalized in self._user_cache:
            return self._user_cache[normalized]

        user_record: dict | None = None
        try:
            data = self._client.request("GET", f"{self._users_base}/{normalized}")
            if isinstance(data, dict):
                user_record = data
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise

        if not user_record:
            try:
                local_record = self._client.fallback_request("GET", f"{self._users_base}/{normalized}")
            except ValueError:
                local_record = None
            if isinstance(local_record, dict):
                user_record = local_record

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
        if bool(record.get("is_walk_in", False)):
            return None

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

    def _build_auto_completion_patch(self, record: dict, *, now: datetime | None = None) -> dict:
        current_status = str(record.get("status") or "").strip().lower()
        is_active = bool(record.get("is_active", True))
        if not is_active and current_status == "completed":
            return {}

        if current_status in {"rejected", "cancelled", "absent"}:
            return {}

        try:
            end_at = parse_datetime(str(record.get("end_at") or ""))
        except ValueError:
            return {}

        now_value = now or now_local_naive()
        if end_at > now_value:
            return {}

        patch: dict[str, object] = {}
        if current_status != "completed":
            patch["status"] = "completed"
        if is_active:
            patch["is_active"] = False

        return patch

    def _is_hidden_legacy_record(self, record: dict) -> bool:
        return (
            not bool(record.get("is_active", True))
            and str(record.get("status") or "").strip().lower() == "cancelled"
            and str(record.get("cancel_reason") or "").strip() == _LEGACY_CANCEL_REASON
        )

    def _normalize_record(self, record: dict, *, persist: bool = True) -> dict:
        patch = self._build_sanitization_patch(record)
        completion_patch = self._build_auto_completion_patch(record)
        for key, value in completion_patch.items():
            patch.setdefault(key, value)
        if persist and patch:
            try:
                updated = self._client.request(
                    "PATCH",
                    f"{self._base}/{record.get('id')}",
                    payload=patch,
                    fallback_on_status_codes={400, 404, 422},
                )
            except httpx.HTTPError:
                updated = None
            if isinstance(updated, dict):
                merged = dict(updated)
                merged.update(patch)
                return merged

        if patch:
            merged = dict(record)
            merged.update(patch)
            return merged
        return record

    def auto_complete_expired_reservations(self, *, now: datetime | None = None) -> int:
        completed = 0
        now_value = now or now_local_naive()

        for record, persist in self._list_all_records():
            patch = self._build_auto_completion_patch(record, now=now_value)
            if not patch:
                continue

            if persist:
                self._client.request("PATCH", f"{self._base}/{record.get('id')}", payload=patch)
            else:
                self._client.fallback_request("PATCH", f"{self._base}/{record.get('id')}", payload=patch)

            completed += 1

        return completed

    def sanitize_legacy_records(self) -> int:
        sanitized = 0
        for record, persist in self._list_all_records():
            patch = self._build_sanitization_patch(record)
            if not patch:
                continue
            if persist:
                self._client.request("PATCH", f"{self._base}/{record.get('id')}", payload=patch)
            else:
                self._client.fallback_request("PATCH", f"{self._base}/{record.get('id')}", payload=patch)
            sanitized += 1
        return sanitized

    def list_all(self, page: int = 1, per_page: int = 200) -> list[LabReservationResponse]:
        items: list[LabReservationResponse] = []
        for record, persist in self._list_all_records(page=page, per_page=per_page):
            normalized = self._normalize_record(record, persist=persist)
            if self._is_hidden_legacy_record(normalized):
                continue
            items.append(_to_response(normalized))
        return items

    def get_by_id(self, reservation_id: str) -> LabReservationResponse | None:
        remote_record = self._get_remote_record(reservation_id)
        local_record = self._get_local_record(reservation_id)
        data = local_record or remote_record
        if not data:
            return None
        return _to_response(self._normalize_record(data, persist=bool(remote_record and not local_record)))

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

    def create(
        self,
        body: LabReservationCreate,
        current_user: dict | None = None,
        *,
        status_override: str | None = None,
        skip_overlap_validation: bool = False,
        extra_payload: dict | None = None,
    ) -> LabReservationResponse:
        start_at = parse_datetime(body.start_at)
        end_at = parse_datetime(body.end_at)
        if end_at <= start_at:
            raise ValueError("end_at debe ser mayor a start_at")

        payload = body.model_dump()
        payload["status"] = status_override or "pending"
        if payload["status"] not in RESERVATION_STATUSES:
            raise ValueError(f"status invalido: {payload['status']}")

        payload["is_active"] = True if payload.get("is_active") is None else bool(payload.get("is_active"))
        payload["requested_by"] = payload.get("requested_by") or (current_user or {}).get("user_id") or ""
        if current_user:
            payload["requested_by_name"] = str(current_user.get("name") or current_user.get("username") or "").strip()
            payload["requested_by_email"] = str(current_user.get("email") or "").strip()
        if not payload["requested_by"]:
            raise ValueError("requested_by es requerido")

        if extra_payload:
            payload.update({key: value for key, value in extra_payload.items() if value is not None})

        if not skip_overlap_validation:
            self._validate_no_overlap(payload["laboratory_id"], payload["start_at"], payload["end_at"])

        data = self._client.request("POST", self._base, payload=payload, fallback_on_status_codes={400, 404, 422})
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

        data = self._client.request(
            "PATCH",
            f"{self._base}/{reservation_id}",
            payload=payload,
            fallback_on_status_codes={400, 404, 422},
        )
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al actualizar reserva")
        return _to_response(self._normalize_record(data))

    def delete(self, reservation_id: str) -> bool:
        try:
            self._client.request("DELETE", f"{self._base}/{reservation_id}", fallback_on_status_codes={404})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise
        return True
