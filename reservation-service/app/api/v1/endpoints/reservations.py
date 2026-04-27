import asyncio
import logging
import math
import re
from calendar import monthrange
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

logger = logging.getLogger(__name__)

from app.application.container import lab_access_session_repo, lab_reservation_repo, tutorial_session_repo, user_penalty_repo
from app.application.container import lab_block_repo, lab_schedule_repo, laboratory_access_repo
from app.application.laboratory_access import ensure_user_can_reserve_laboratory
from app.core.datetime_utils import combine_date_time, iter_time_ranges, now_local_naive, parse_datetime
from app.core.dependencies import ensure_any_permission, get_current_user
from app.notifications.store import OPERATIONS_RECIPIENT_ID, notification_store
from app.realtime.manager import realtime_manager
from app.schemas.agenda_summary import AgendaSummaryResponse
from app.schemas.lab_reservation import (
    LabReservationCreate,
    PaginatedLabReservationResponse,
    LabReservationResponse,
    LabReservationStatusUpdate,
    LabReservationUpdate,
    OccupancyDashboardResponse,
    ReservationAccessUpdate,
    WalkInReservationCreate,
)
from app.schemas.tutorial_session import TutorialSessionResponse

router = APIRouter(prefix="/reservations", tags=["reservations"])
_USER_RESERVATION_MODIFICATION_WINDOW_SECONDS = 2 * 60 * 60
_ABSENT_GRACE_PERIOD_SECONDS = 15 * 60
_MANAGEMENT_PERMISSIONS = {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"}
_FINAL_RESERVATION_STATUSES = {"rejected", "cancelled", "completed", "absent"}
_WHERE_PATTERN = re.compile(r"^(?P<field>[a-zA-Z_][a-zA-Z0-9_]*)(?P<operator>>=|<=|!=|=|~|>|<)(?P<value>.+)$")
_SUPPORTED_SORT_FIELDS = {
    "start_at",
    "end_at",
    "status",
    "purpose",
    "requested_by",
    "requested_by_name",
    "requested_by_email",
    "laboratory_id",
    "created",
    "updated",
    "date",
}


def _is_history_reservation(reservation: LabReservationResponse, reference_now: datetime | None = None) -> bool:
    now = reference_now or now_local_naive()

    try:
        start_at = parse_datetime(reservation.start_at)
        end_at = parse_datetime(reservation.end_at)
    except Exception:
        return False

    if end_at <= now:
        return True

    return reservation.status in _FINAL_RESERVATION_STATUSES and start_at <= now


def _max_allowed_reservation_date(base_day):
    next_month = base_day.month + 1
    year = base_day.year
    if next_month > 12:
        next_month = 1
        year += 1

    day = min(base_day.day, monthrange(year, next_month)[1])
    return base_day.replace(year=year, month=next_month, day=day)


def _has_schedule_overlap(start_at: datetime, end_at: datetime, other_start_raw: str, other_end_raw: str) -> bool:
    other_start = parse_datetime(other_start_raw)
    other_end = parse_datetime(other_end_raw)
    return start_at < other_end and other_start < end_at


def _resolve_schedule_window(laboratory_id: str, reservation_day) -> tuple[datetime, datetime, int]:
    weekday = reservation_day.weekday()
    schedule = lab_schedule_repo.get_active_for_laboratory_weekday(laboratory_id, weekday)
    if schedule:
        day_start = combine_date_time(reservation_day, schedule.open_time)
        day_end = combine_date_time(reservation_day, schedule.close_time)
        slot_minutes = schedule.slot_minutes or 60
    else:
        day_start = combine_date_time(reservation_day, "08:00")
        day_end = combine_date_time(reservation_day, "20:00")
        slot_minutes = 60

    return day_start, day_end, slot_minutes


def _validate_reservation_time_rules(
    *,
    laboratory_id: str,
    start_at_raw: str,
    end_at_raw: str,
    skip_reservation_id: str | None = None,
) -> None:
    start_at = parse_datetime(start_at_raw)
    end_at = parse_datetime(end_at_raw)
    now = now_local_naive()

    if end_at <= start_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La hora de fin debe ser mayor a la hora de inicio",
        )

    if start_at.date() != end_at.date():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La reserva debe mantenerse dentro del mismo dia",
        )

    if start_at <= now:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No puedes registrar ni reprogramar reservas en horarios ya pasados o iniciados",
        )

    max_allowed_day = _max_allowed_reservation_date(now.date())
    if start_at.date() > max_allowed_day:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Solo puedes registrar o mover reservas dentro del plazo maximo de un mes",
        )

    day_start, day_end, slot_minutes = _resolve_schedule_window(laboratory_id, start_at.date())
    if start_at < day_start or end_at > day_end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El horario seleccionado esta fuera del horario habilitado del laboratorio",
        )

    slot_ranges = iter_time_ranges(day_start, day_end, slot_minutes)
    matches_any_slot = any(start_at == slot_start and end_at == slot_end for slot_start, slot_end in slot_ranges)
    if not matches_any_slot:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Debes seleccionar un bloque horario valido del laboratorio. "
                f"Los bloques vigentes para ese dia son de {slot_minutes} minutos."
            ),
        )

    day = start_at.date().isoformat()

    for block in lab_block_repo.list_for_laboratory_day(laboratory_id, day):
        if _has_schedule_overlap(start_at, end_at, block.start_at, block.end_at):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El bloque seleccionado no esta disponible porque el laboratorio se encuentra bloqueado o en mantenimiento",
            )

    for reservation in lab_reservation_repo.list_for_laboratory_day(laboratory_id, day):
        if skip_reservation_id and reservation.id == skip_reservation_id:
            continue
        if reservation.status in {"rejected", "cancelled", "completed", "absent"}:
            continue
        if _has_schedule_overlap(start_at, end_at, reservation.start_at, reservation.end_at):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Ese bloque ya no esta disponible porque existe otra reserva activa en el mismo horario",
            )

    for tutorial_session in tutorial_session_repo.list_public_for_laboratory_day(laboratory_id, day):
        if _has_schedule_overlap(start_at, end_at, tutorial_session.start_at, tutorial_session.end_at):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Ese bloque ya no esta disponible porque existe una tutoria publicada en el mismo horario",
            )


def _serialize_reservation(reservation: LabReservationResponse) -> LabReservationResponse:
    return LabReservationResponse.model_validate(lab_access_session_repo.enrich_reservation(reservation))


def _occupant_name_for_access(reservation: LabReservationResponse, body: ReservationAccessUpdate) -> str:
    return str(body.occupant_name or reservation.requested_by_name or reservation.requested_by or "").strip()


def _occupant_email_for_access(reservation: LabReservationResponse, body: ReservationAccessUpdate) -> str:
    return str(body.occupant_email or reservation.requested_by_email or "").strip()


async def _broadcast_access_event(action: str, reservation: LabReservationResponse) -> None:
    await realtime_manager.broadcast(
        {
            "topic": "lab_access",
            "action": action,
            "record": reservation.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )


def _can_manage_reservations(current_user: dict) -> bool:
    permissions = set(current_user.get("permissions") or [])
    return current_user.get("role") == "admin" or "*" in permissions or bool(permissions.intersection(_MANAGEMENT_PERMISSIONS))


def _reservation_field_value(reservation: LabReservationResponse, field: str) -> str:
    if field == "date":
        return str(reservation.start_at).split("T", 1)[0]

    value = getattr(reservation, field, "")
    if value is None:
        return ""
    return str(value)


def _reservation_field_value_for_where(reservation: LabReservationResponse, field: str):
    if field == "date":
        return str(reservation.start_at).split("T", 1)[0]

    value = getattr(reservation, field, None)
    if field in {"attendees_count", "user_modification_count"}:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    if field == "is_walk_in":
        return bool(value)

    if value is None:
        return ""
    return str(value)


def _apply_where_filter(items: list[LabReservationResponse], where: str | None) -> list[LabReservationResponse]:
    if not where:
        return items

    clauses = [clause.strip() for clause in str(where).split(";") if clause.strip()]
    if not clauses:
        return items

    filtered = items
    for clause in clauses:
        match = _WHERE_PATTERN.match(clause)
        if match is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Formato invalido en 'where'. Usa clausulas como "
                    "'purpose~practica;status=approved;date>=2026-03-01'"
                ),
            )

        field = match.group("field")
        operator = match.group("operator")
        expected = match.group("value").strip()

        if field not in _SUPPORTED_SORT_FIELDS and field not in {"area_id", "is_walk_in", "cancel_reason", "notes"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"El campo '{field}' no es valido para el filtro where",
            )

        def _matches(item: LabReservationResponse) -> bool:
            actual_value = _reservation_field_value_for_where(item, field)
            expected_lower = expected.lower()

            if operator == "~":
                return expected_lower in str(actual_value).lower()
            if operator == "=":
                if isinstance(actual_value, bool):
                    return actual_value == (expected_lower in {"true", "1", "yes", "si", "sí"})
                return str(actual_value).lower() == expected_lower
            if operator == "!=":
                if isinstance(actual_value, bool):
                    return actual_value != (expected_lower in {"true", "1", "yes", "si", "sí"})
                return str(actual_value).lower() != expected_lower

            if isinstance(actual_value, (int, float)):
                try:
                    expected_value = float(expected)
                except ValueError:
                    return False

                if operator == ">":
                    return actual_value > expected_value
                if operator == ">=":
                    return actual_value >= expected_value
                if operator == "<":
                    return actual_value < expected_value
                if operator == "<=":
                    return actual_value <= expected_value
                return False

            actual = str(actual_value)
            actual_lower = actual.lower()
            if operator == ">":
                return actual > expected
            if operator == ">=":
                return actual >= expected
            if operator == "<":
                return actual < expected
            if operator == "<=":
                return actual <= expected
            return False

        filtered = [item for item in filtered if _matches(item)]

    return filtered


def _sort_reservations(items: list[LabReservationResponse], sort_by: str, sort_type: str) -> list[LabReservationResponse]:
    normalized_sort_by = str(sort_by or "start_at").strip()
    normalized_sort_type = str(sort_type or "ASC").strip().upper()

    if normalized_sort_by not in _SUPPORTED_SORT_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"sortBy invalido: {normalized_sort_by}",
        )

    if normalized_sort_type not in {"ASC", "DESC"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"sortType invalido: {normalized_sort_type}",
        )

    reverse = normalized_sort_type == "DESC"
    return sorted(
        items,
        key=lambda item: (_reservation_field_value(item, normalized_sort_by).lower(), item.id),
        reverse=reverse,
    )


def _validate_sort_params(sort_by: str, sort_type: str) -> tuple[str, str]:
    normalized_sort_by = str(sort_by or "start_at").strip()
    normalized_sort_type = str(sort_type or "ASC").strip().upper()

    if normalized_sort_by not in _SUPPORTED_SORT_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"sortBy invalido: {normalized_sort_by}",
        )

    if normalized_sort_type not in {"ASC", "DESC"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"sortType invalido: {normalized_sort_type}",
        )

    return normalized_sort_by, normalized_sort_type


def _ensure_user_can_change_reservation(
    reservation: LabReservationResponse,
    *,
    current_user: dict,
    operation: str,
) -> None:
    if _can_manage_reservations(current_user):
        return

    start_at = parse_datetime(reservation.start_at)
    now = now_local_naive()
    remaining_seconds = (start_at - now).total_seconds()

    if remaining_seconds <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La reserva ya transcurrio y no puede modificarse ni cancelarse",
        )

    if operation == "modify" and remaining_seconds < _USER_RESERVATION_MODIFICATION_WINDOW_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No puedes modificar una reserva cuando faltan menos de 2 horas para su inicio",
        )

    if operation == "modify" and int(reservation.user_modification_count or 0) >= 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Solo puedes modificar una reserva una vez",
        )


def _resolve_laboratory_name(laboratory_id: str) -> str:
    record = laboratory_access_repo.get_by_id(laboratory_id)
    if not isinstance(record, dict):
        return ""
    return str(record.get("name") or record.get("laboratory_name") or record.get("label") or "").strip()


def _build_schedule_change_payload(
    previous: LabReservationResponse,
    updated: LabReservationResponse,
    current_user: dict,
) -> tuple[str, str, dict] | None:
    changed_time = previous.start_at != updated.start_at or previous.end_at != updated.end_at
    changed_location = previous.laboratory_id != updated.laboratory_id

    if not changed_time and not changed_location:
        return None

    change_kinds: list[str] = []
    if changed_time:
        change_kinds.append("schedule")
    if changed_location:
        change_kinds.append("location")

    if change_kinds == ["schedule"]:
        title = "Cambio de Horario"
        message = "Tu reserva fue reprogramada. Revisa el horario actualizado."
    elif change_kinds == ["location"]:
        title = "Cambio de Laboratorio"
        message = "Tu reserva cambio de espacio fisico. Revisa el laboratorio actualizado."
    else:
        title = "Cambio de Horario y Laboratorio"
        message = "Tu reserva fue actualizada con un nuevo horario y laboratorio."

    payload = {
        "reservation_id": updated.id,
        "purpose": updated.purpose,
        "change_kinds": change_kinds,
        "old_start_at": previous.start_at,
        "old_end_at": previous.end_at,
        "new_start_at": updated.start_at,
        "new_end_at": updated.end_at,
        "old_laboratory_id": previous.laboratory_id,
        "new_laboratory_id": updated.laboratory_id,
        "old_laboratory_name": _resolve_laboratory_name(previous.laboratory_id),
        "new_laboratory_name": _resolve_laboratory_name(updated.laboratory_id),
        "status": updated.status,
        "actor_user_id": str(current_user.get("user_id") or ""),
        "actor_name": str(current_user.get("name") or current_user.get("username") or "Sistema"),
    }
    return title, message, payload


async def _notify_schedule_change(
    previous: LabReservationResponse,
    updated: LabReservationResponse,
    current_user: dict,
) -> None:
    recipient_user_id = str(updated.requested_by or "").strip()
    actor_user_id = str(current_user.get("user_id") or "").strip()
    if not recipient_user_id or recipient_user_id == actor_user_id:
        return

    notification_data = _build_schedule_change_payload(previous, updated, current_user)
    if notification_data is None:
        return

    title, message, payload = notification_data
    notification = await asyncio.to_thread(
        notification_store.create,
        recipient_user_id=recipient_user_id,
        notification_type="reservation_schedule_change",
        title=title,
        message=message,
        payload=payload,
    )

    await realtime_manager.broadcast(
        {
            "topic": "user_notification",
            "action": "create",
            "recipients": [recipient_user_id],
            "record": notification.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )


async def _notify_status_change(
    previous: LabReservationResponse,
    updated: LabReservationResponse,
    current_user: dict,
) -> None:
    if previous.status == updated.status:
        return

    recipient_user_id = str(updated.requested_by or "").strip()
    if not recipient_user_id:
        return

    actor_name = str(current_user.get("name") or current_user.get("username") or "Sistema")

    if updated.status == "approved":
        title = "Reserva Confirmada"
        message = "Tu solicitud fue aceptada. Ya puedes usar el laboratorio en el horario aprobado."
    elif updated.status == "rejected":
        rejection_reason = str(updated.cancel_reason or "").strip()
        title = "Reserva Rechazada"
        message = f"Tu solicitud fue rechazada. Motivo: {rejection_reason}"
    else:
        return

    notification = await asyncio.to_thread(
        notification_store.create,
        recipient_user_id=recipient_user_id,
        notification_type="reservation_status_update",
        title=title,
        message=message,
        payload={
            "reservation_id": updated.id,
            "purpose": updated.purpose,
            "status": updated.status,
            "cancel_reason": updated.cancel_reason,
            "laboratory_id": updated.laboratory_id,
            "start_at": updated.start_at,
            "end_at": updated.end_at,
            "actor_name": actor_name,
            "target_path": "/app/reservas/nueva",
        },
    )

    await realtime_manager.broadcast(
        {
            "topic": "user_notification",
            "action": "create",
            "recipients": [recipient_user_id],
            "record": notification.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )


async def _notify_operations_reservation_cancelled(
    reservation: LabReservationResponse,
    current_user: dict,
) -> None:
    actor_name = str(current_user.get("name") or current_user.get("username") or "Usuario")
    start_time = parse_datetime(reservation.start_at).strftime("%d/%m/%Y %H:%M") if reservation.start_at else "N/A"
    
    message = f"{actor_name} canceló una reserva aprobada programada para {start_time}. Propósito: {reservation.purpose}"
    
    notification = await asyncio.to_thread(
        notification_store.create,
        recipient_user_id=OPERATIONS_RECIPIENT_ID,
        notification_type="reservation_cancelled_by_user",
        title="⚠️ Reserva Cancelada por Usuario",
        message=message,
        payload={
            "reservation_id": reservation.id,
            "purpose": reservation.purpose,
            "status": "cancelled",
            "laboratory_id": reservation.laboratory_id,
            "start_at": reservation.start_at,
            "end_at": reservation.end_at,
            "requested_by": reservation.requested_by,
            "actor_name": actor_name,
            "actor_id": current_user.get("user_id") or "",
            "target_path": "/app/admin/reservas",
        },
    )

    await realtime_manager.broadcast(
        {
            "topic": "user_notification",
            "action": "create",
            "recipients": [OPERATIONS_RECIPIENT_ID],
            "record": notification.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )


@router.get("", response_model=list[LabReservationResponse])
def list_reservations(
    laboratory_id: str | None = Query(default=None),
    day: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: dict = Depends(get_current_user),
) -> list[LabReservationResponse]:
    requester = None if _can_manage_reservations(current_user) else (current_user.get("user_id") or "")

    data = lab_reservation_repo.list_filtered(
        laboratory_id=laboratory_id,
        day=day,
        status_filter=status_filter,
        requested_by=requester,
        sort_by="start_at",
        sort_type="ASC",
    )

    return [_serialize_reservation(item) for item in data]


@router.get("/search", response_model=PaginatedLabReservationResponse)
def search_reservations(
    laboratory_id: str | None = Query(default=None),
    day: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    page_number: int = Query(default=0, ge=0, alias="pageNumber"),
    page_size: int = Query(default=10, ge=1, le=100, alias="pageSize"),
    sort_by: str = Query(default="start_at", alias="sortBy"),
    sort_type: str = Query(default="DESC", alias="sortType"),
    where: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> PaginatedLabReservationResponse:
    normalized_sort_by, normalized_sort_type = _validate_sort_params(sort_by, sort_type)
    requester = None if _can_manage_reservations(current_user) else str(current_user.get("user_id") or "")
    normalized_where = str(where or "").strip() or None

    if normalized_where is None:
        paginated_source_items, total_elements = lab_reservation_repo.search_page(
            laboratory_id=laboratory_id,
            day=day,
            status_filter=status_filter,
            requested_by=requester,
            page_number=page_number,
            page_size=page_size,
            sort_by=normalized_sort_by,
            sort_type=normalized_sort_type,
        )
        paginated_items = [
            LabReservationResponse.model_validate(item)
            for item in lab_access_session_repo.enrich_reservations(paginated_source_items)
        ]
    else:
        source_items = lab_reservation_repo.list_filtered(
            laboratory_id=laboratory_id,
            day=day,
            status_filter=status_filter,
            requested_by=requester,
            sort_by=normalized_sort_by,
            sort_type=normalized_sort_type,
        )
        serialized = [
            LabReservationResponse.model_validate(item)
            for item in lab_access_session_repo.enrich_reservations(source_items)
        ]
        filtered = _apply_where_filter(serialized, normalized_where)
        ordered = _sort_reservations(filtered, normalized_sort_by, normalized_sort_type)

        total_elements = len(ordered)
        start_index = page_number * page_size
        end_index = start_index + page_size
        paginated_items = ordered[start_index:end_index]

    total_pages = math.ceil(total_elements / page_size) if total_elements > 0 else 0

    return PaginatedLabReservationResponse(
        items=paginated_items,
        pageNumber=page_number,
        pageSize=page_size,
        totalElements=total_elements,
        totalPages=total_pages,
        sortBy=normalized_sort_by,
        sortType=normalized_sort_type,
        where=str(normalized_where or ""),
    )


@router.get("/mine", response_model=list[LabReservationResponse])
def list_my_reservations(current_user: dict = Depends(get_current_user)) -> list[LabReservationResponse]:
    requester = str(current_user.get("user_id") or "").strip()
    if not requester:
        return []
    items = lab_reservation_repo.list_filtered(requested_by=requester, sort_by="start_at", sort_type="ASC")
    return [_serialize_reservation(item) for item in items]


@router.get("/summary", response_model=AgendaSummaryResponse)
def get_my_agenda_summary(
    current_user: dict = Depends(get_current_user),
    limit: int = Query(default=5, ge=1, le=12),
) -> AgendaSummaryResponse:
    requester = str(current_user.get("user_id") or "").strip()
    now = now_local_naive()

    if requester:
        my_reservations = lab_reservation_repo.list_filtered(
            requested_by=requester,
            sort_by="start_at",
            sort_type="ASC",
        )
    else:
        my_reservations = []

    def _is_upcoming(value: str) -> bool:
        try:
            return parse_datetime(value) >= now
        except ValueError:
            return False

    upcoming_reservations = [
        _serialize_reservation(item)
        for item in my_reservations
        if _is_upcoming(item.end_at)
    ]
    upcoming_reservations.sort(key=lambda item: (item.start_at, item.end_at, item.id))

    combined_tutorials: dict[str, TutorialSessionResponse] = {}
    if requester:
        for session in tutorial_session_repo.list_for_student(requester):
            if _is_upcoming(session.end_at):
                combined_tutorials[session.id] = session

        for session in tutorial_session_repo.list_for_tutor(requester):
            if _is_upcoming(session.end_at):
                combined_tutorials[session.id] = session

    upcoming_tutorials = sorted(
        combined_tutorials.values(),
        key=lambda item: (item.start_at, item.end_at, item.id),
    )

    return AgendaSummaryResponse(
        generated_at=datetime.utcnow().isoformat(),
        reservation_count=len(upcoming_reservations),
        tutorial_count=len(upcoming_tutorials),
        total_count=len(upcoming_reservations) + len(upcoming_tutorials),
        upcoming_reservations=upcoming_reservations[:limit],
        upcoming_tutorials=upcoming_tutorials[:limit],
    )


@router.get("/mine/history/search", response_model=PaginatedLabReservationResponse)
def search_my_reservation_history(
    page_number: int = Query(default=0, ge=0, alias="pageNumber"),
    page_size: int = Query(default=10, ge=1, le=100, alias="pageSize"),
    sort_by: str = Query(default="start_at", alias="sortBy"),
    sort_type: str = Query(default="DESC", alias="sortType"),
    current_user: dict = Depends(get_current_user),
) -> PaginatedLabReservationResponse:
    normalized_sort_by, normalized_sort_type = _validate_sort_params(sort_by, sort_type)
    requester = str(current_user.get("user_id") or "")

    if not requester:
        source_items = []
    else:
        source_items = lab_reservation_repo.list_filtered(
            requested_by=requester,
            sort_by=normalized_sort_by,
            sort_type=normalized_sort_type,
        )
    serialized = [
        LabReservationResponse.model_validate(item)
        for item in lab_access_session_repo.enrich_reservations(source_items)
    ]
    history_items = [item for item in serialized if _is_history_reservation(item)]
    ordered = _sort_reservations(history_items, normalized_sort_by, normalized_sort_type)

    total_elements = len(ordered)
    start_index = page_number * page_size
    end_index = start_index + page_size
    paginated_items = ordered[start_index:end_index]
    total_pages = math.ceil(total_elements / page_size) if total_elements > 0 else 0

    return PaginatedLabReservationResponse(
        items=paginated_items,
        pageNumber=page_number,
        pageSize=page_size,
        totalElements=total_elements,
        totalPages=total_pages,
        sortBy=normalized_sort_by,
        sortType=normalized_sort_type,
        where="",
    )


@router.get("/occupancy", response_model=OccupancyDashboardResponse)
def get_occupancy_dashboard(
    laboratory_id: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> OccupancyDashboardResponse:
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No tienes permisos para consultar la ocupacion del laboratorio",
    )
    return lab_access_session_repo.get_dashboard(laboratory_id=laboratory_id)


@router.get("/{reservation_id}", response_model=LabReservationResponse)
def get_reservation(reservation_id: str, current_user: dict = Depends(get_current_user)) -> LabReservationResponse:
    reservation = lab_reservation_repo.get_by_id(reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    can_manage = _can_manage_reservations(current_user)
    if not can_manage and reservation.requested_by != (current_user.get("user_id") or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta reserva")

    return _serialize_reservation(reservation)


@router.post("", response_model=LabReservationResponse, status_code=status.HTTP_201_CREATED)
async def create_reservation(body: LabReservationCreate, current_user: dict = Depends(get_current_user)) -> LabReservationResponse:
    active_penalty = user_penalty_repo.get_active_for_user(str(current_user.get("user_id") or "").strip())
    if active_penalty is not None:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                "Tu cuenta tiene una penalizacion activa y no puede crear nuevas reservas. "
                f"Motivo: {active_penalty.reason}. Vigente hasta {active_penalty.ends_at}"
            ),
        )

    ensure_user_can_reserve_laboratory(body.laboratory_id, current_user)

    _validate_reservation_time_rules(
        laboratory_id=body.laboratory_id,
        start_at_raw=body.start_at,
        end_at_raw=body.end_at,
    )

    try:
        created = await lab_reservation_repo.acreate(body, current_user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "create",
            "record": _serialize_reservation(created).model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return _serialize_reservation(created)


@router.post("/walk-in", response_model=LabReservationResponse, status_code=status.HTTP_201_CREATED)
async def create_walk_in_reservation(
    body: WalkInReservationCreate,
    current_user: dict = Depends(get_current_user),
) -> LabReservationResponse:
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No tienes permisos para registrar ingresos rapidos",
    )

    active_penalty = user_penalty_repo.get_active_for_user(str(body.requested_by or "").strip())
    if active_penalty is not None:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="El usuario tiene una penalizacion activa y no puede ingresar mediante un walk-in",
        )

    try:
        created = await lab_reservation_repo.acreate(
            LabReservationCreate(
                laboratory_id=body.laboratory_id,
                area_id=body.area_id,
                requested_by=body.requested_by,
                purpose=body.purpose.strip() or "Ingreso rapido sin reserva previa",
                start_at=body.start_at,
                end_at=body.end_at,
                notes=body.notes,
            ),
            current_user=current_user,
        )
        updated = await lab_reservation_repo.aupdate(
            created.id,
            LabReservationUpdate(
                status="in_progress",
                approved_by=str(current_user.get("user_id") or ""),
                approved_at=datetime.utcnow().isoformat(),
            ),
        )
        if updated is None:
            raise ValueError("No se pudo registrar el walk-in")
        await asyncio.to_thread(
            lab_access_session_repo.create,
            reservation_id=updated.id,
            laboratory_id=updated.laboratory_id,
            requested_by=updated.requested_by,
            occupant_name=body.occupant_name.strip(),
            occupant_email=body.occupant_email.strip(),
            station_label=body.station_label.strip(),
            purpose=updated.purpose,
            start_at=updated.start_at,
            end_at=updated.end_at,
            is_walk_in=True,
            recorded_by=str(current_user.get("name") or current_user.get("username") or "Encargado"),
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    enriched = _serialize_reservation(updated)
    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "create",
            "record": enriched.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    await _broadcast_access_event("check_in", enriched)
    return enriched


@router.patch("/{reservation_id}", response_model=LabReservationResponse)
@router.put("/{reservation_id}", response_model=LabReservationResponse)
async def update_reservation(
    reservation_id: str,
    body: LabReservationUpdate,
    current_user: dict = Depends(get_current_user),
) -> LabReservationResponse:
    existing_reservation = await lab_reservation_repo.aget_by_id(reservation_id)
    if existing_reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    can_manage = _can_manage_reservations(current_user)
    if not can_manage and existing_reservation.requested_by != (current_user.get("user_id") or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta reserva")

    _ensure_user_can_change_reservation(existing_reservation, current_user=current_user, operation="modify")

    change_fields = {field for field in {"laboratory_id", "area_id", "start_at", "end_at"} if getattr(body, field) is not None}
    has_meaningful_schedule_change = any(
        [
            body.laboratory_id is not None and body.laboratory_id != existing_reservation.laboratory_id,
            body.area_id is not None and body.area_id != existing_reservation.area_id,
            body.start_at is not None and body.start_at != existing_reservation.start_at,
            body.end_at is not None and body.end_at != existing_reservation.end_at,
        ]
    )
    payload = body
    if not can_manage and has_meaningful_schedule_change:
        payload = body.model_copy(
            update={
                "user_modification_count": int(existing_reservation.user_modification_count or 0) + 1,
            }
        )

        ensure_user_can_reserve_laboratory(str(payload.laboratory_id or existing_reservation.laboratory_id), current_user)

    _validate_reservation_time_rules(
        laboratory_id=str(payload.laboratory_id or existing_reservation.laboratory_id),
        start_at_raw=str(payload.start_at or existing_reservation.start_at),
        end_at_raw=str(payload.end_at or existing_reservation.end_at),
        skip_reservation_id=reservation_id,
    )

    try:
        updated = await lab_reservation_repo.aupdate(reservation_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    await _notify_schedule_change(existing_reservation, updated, current_user)

    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "update",
            "record": _serialize_reservation(updated).model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return _serialize_reservation(updated)


@router.patch("/{reservation_id}/status", response_model=LabReservationResponse)
async def update_reservation_status(
    reservation_id: str,
    body: LabReservationStatusUpdate,
    current_user: dict = Depends(get_current_user),
) -> LabReservationResponse:
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No tienes permisos para actualizar estados de reserva",
    )

    existing_reservation = await lab_reservation_repo.aget_by_id(reservation_id)
    if existing_reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    if existing_reservation.status in _FINAL_RESERVATION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No puedes cambiar el estado de una reserva finalizada",
        )

    if body.status == "rejected" and not str(body.cancel_reason or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debes ingresar el motivo de rechazo para rechazar la reserva",
        )

    payload = LabReservationUpdate(
        status=body.status,
        cancel_reason=str(body.cancel_reason or "").strip() if body.status == "rejected" else "",
        approved_by=current_user.get("user_id") if body.status == "approved" else None,
        approved_at=datetime.utcnow().isoformat() if body.status == "approved" else None,
    )

    try:
        updated = await lab_reservation_repo.aupdate(reservation_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    await _notify_status_change(existing_reservation, updated, current_user)

    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "update",
            "record": _serialize_reservation(updated).model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return _serialize_reservation(updated)


@router.patch("/{reservation_id}/check-in", response_model=LabReservationResponse)
async def register_reservation_entry(
    reservation_id: str,
    body: ReservationAccessUpdate,
    current_user: dict = Depends(get_current_user),
) -> LabReservationResponse:
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No tienes permisos para registrar ingresos",
    )

    reservation = await lab_reservation_repo.aget_by_id(reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")
    if reservation.status not in {"approved", "in_progress"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Solo puedes registrar entrada sobre reservas aprobadas")
    if await asyncio.to_thread(lab_access_session_repo.get_open_by_reservation, reservation_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La reserva ya tiene una entrada registrada")

    updated = reservation
    if reservation.status != "in_progress":
        updated = await lab_reservation_repo.aupdate(reservation_id, LabReservationUpdate(status="in_progress"))
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    await asyncio.to_thread(
        lab_access_session_repo.create,
        reservation_id=updated.id,
        laboratory_id=updated.laboratory_id,
        requested_by=updated.requested_by,
        occupant_name=_occupant_name_for_access(updated, body),
        occupant_email=_occupant_email_for_access(updated, body),
        station_label=str(body.station_label or updated.station_label or "").strip(),
        purpose=updated.purpose,
        start_at=updated.start_at,
        end_at=updated.end_at,
        is_walk_in=updated.is_walk_in,
        recorded_by=str(current_user.get("name") or current_user.get("username") or "Encargado"),
        notes=str(body.notes or "").strip(),
    )

    enriched = _serialize_reservation(updated)
    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "update",
            "record": enriched.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    await _broadcast_access_event("check_in", enriched)
    return enriched


@router.patch("/{reservation_id}/check-out", response_model=LabReservationResponse)
async def register_reservation_exit(
    reservation_id: str,
    current_user: dict = Depends(get_current_user),
) -> LabReservationResponse:
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No tienes permisos para registrar salidas",
    )

    reservation = await lab_reservation_repo.aget_by_id(reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    session = await asyncio.to_thread(lab_access_session_repo.get_open_by_reservation, reservation_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La reserva no tiene una entrada activa")

    await asyncio.to_thread(lab_access_session_repo.close, session.id)
    updated = await lab_reservation_repo.aupdate(reservation_id, LabReservationUpdate(status="completed"))
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    enriched = _serialize_reservation(updated)
    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "update",
            "record": enriched.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    await _broadcast_access_event("check_out", enriched)
    return enriched


@router.patch("/{reservation_id}/absent", response_model=LabReservationResponse)
async def mark_reservation_absent(
    reservation_id: str,
    current_user: dict = Depends(get_current_user),
) -> LabReservationResponse:
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No tienes permisos para marcar ausencias",
    )

    reservation = await lab_reservation_repo.aget_by_id(reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")
    if reservation.status != "approved":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Solo las reservas aprobadas pueden marcarse como ausentes")
    if await asyncio.to_thread(lab_access_session_repo.get_open_by_reservation, reservation_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La reserva ya registro entrada y no puede marcarse como ausente")

    now = now_local_naive()
    if (now - parse_datetime(reservation.start_at)).total_seconds() < _ABSENT_GRACE_PERIOD_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Solo puedes marcar ausente cuando hayan pasado al menos 15 minutos del inicio",
        )

    updated = await lab_reservation_repo.aupdate(reservation_id, LabReservationUpdate(status="absent"))
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    enriched = _serialize_reservation(updated)
    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "update",
            "record": enriched.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    await _broadcast_access_event("absent", enriched)
    return enriched


@router.patch("/{reservation_id}/cancel", response_model=LabReservationResponse)
async def cancel_reservation(reservation_id: str, current_user: dict = Depends(get_current_user)) -> LabReservationResponse:
    logger.warning(f"🛑 [CANCEL RESERVATION] Starting cancellation of reservation: {reservation_id}")
    
    reservation = await lab_reservation_repo.aget_by_id(reservation_id)
    if reservation is None:
        logger.error(f"❌ [CANCEL RESERVATION] Reservation not found: {reservation_id}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")
    
    logger.info(f"📋 [CANCEL RESERVATION] Current reservation status: {reservation.status}")

    can_manage = _can_manage_reservations(current_user)
    if not can_manage and reservation.requested_by != (current_user.get("user_id") or ""):
        logger.warning(f"🚫 [CANCEL RESERVATION] User {current_user.get('user_id')} denied access to cancel reservation {reservation_id}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta reserva")

    _ensure_user_can_change_reservation(reservation, current_user=current_user, operation="cancel")

    # IMPORTANTE: Solo actualizar status a 'cancelled', SIN BORRAR el registro
    logger.warning(f"🔄 [CANCEL RESERVATION] Updating reservation {reservation_id} status to 'cancelled' (NOT deleting)")
    cancelled = await lab_reservation_repo.aupdate(
        reservation_id,
        LabReservationUpdate(status="cancelled", is_active=False),
    )
    if cancelled is None:
        logger.error(f"❌ [CANCEL RESERVATION] Failed to update reservation {reservation_id}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    logger.info(f"✅ [CANCEL RESERVATION] Successfully updated reservation {reservation_id} to cancelled status")

    # Limpiar notificaciones antiguas ANTES de crear la nueva notificación de cancelación
    # Pero NO borrar las notificaciones de cancelación si existen
    await asyncio.to_thread(
        notification_store.delete_for_reservation,
        reservation_id=reservation_id,
        exclude_types=["reservation_cancelled_by_user"],
    )

    # Enviar notificación al encargado SIEMPRE que se cancele una reserva aprobada
    # (Ya sea por usuario regular o por admin)
    if reservation.status == "approved":
        logger.info(f"📢 [CANCEL RESERVATION] Notifying operations about cancellation of approved reservation {reservation_id}")
        await _notify_operations_reservation_cancelled(cancelled, current_user)
    else:
        logger.info(f"ℹ️ [CANCEL RESERVATION] No notification sent (reservation wasn't approved, status: {reservation.status})")

    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "update",
            "record": cancelled.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return _serialize_reservation(cancelled)


# Mantener DELETE para compatibilidad, pero redirige a cancel
@router.delete("/{reservation_id}", response_model=LabReservationResponse)
async def delete_reservation(reservation_id: str, current_user: dict = Depends(get_current_user)) -> LabReservationResponse:
    # Esta ruta ahora redirige a cancel por seguridad - nunca borra, solo cancela
    return await cancel_reservation(reservation_id, current_user)
