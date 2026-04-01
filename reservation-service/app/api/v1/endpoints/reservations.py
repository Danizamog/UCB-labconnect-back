import math
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.application.container import lab_access_session_repo, lab_reservation_repo, user_penalty_repo
from app.core.datetime_utils import parse_datetime
from app.core.dependencies import ensure_any_permission, get_current_user
from app.notifications.store import OPERATIONS_RECIPIENT_ID, notification_store
from app.realtime.manager import realtime_manager
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

router = APIRouter(prefix="/reservations", tags=["reservations"])
_USER_RESERVATION_MODIFICATION_WINDOW_SECONDS = 2 * 60 * 60
_ABSENT_GRACE_PERIOD_SECONDS = 15 * 60
_MANAGEMENT_PERMISSIONS = {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"}
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
            actual = _reservation_field_value(item, field).strip()
            actual_lower = actual.lower()
            expected_lower = expected.lower()

            if operator == "~":
                return expected_lower in actual_lower
            if operator == "=":
                return actual_lower == expected_lower
            if operator == "!=":
                return actual_lower != expected_lower
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


def _ensure_user_can_change_reservation(
    reservation: LabReservationResponse,
    *,
    current_user: dict,
    operation: str,
) -> None:
    if _can_manage_reservations(current_user):
        return

    start_at = parse_datetime(reservation.start_at)
    now = datetime.utcnow()
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
    notification = notification_store.create(
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

    notification = notification_store.create(
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
    notification = notification_store.create(
        recipient_user_id=OPERATIONS_RECIPIENT_ID,
        notification_type="reservation_cancelled_by_user",
        title="Reserva Cancelada por Usuario",
        message="Una reserva aprobada fue cancelada por el usuario y requiere seguimiento operativo.",
        payload={
            "reservation_id": reservation.id,
            "purpose": reservation.purpose,
            "status": "cancelled",
            "laboratory_id": reservation.laboratory_id,
            "start_at": reservation.start_at,
            "end_at": reservation.end_at,
            "actor_name": str(current_user.get("name") or current_user.get("username") or "Usuario"),
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
    data = lab_reservation_repo.list_all()

    if not _can_manage_reservations(current_user):
        requester = current_user.get("user_id") or ""
        data = [item for item in data if item.requested_by == requester]

    if laboratory_id:
        data = [item for item in data if item.laboratory_id == laboratory_id]
    if status_filter:
        data = [item for item in data if item.status == status_filter]
    if day:
        data = [item for item in data if item.start_at.startswith(day)]

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
    data = lab_reservation_repo.list_all()

    if not _can_manage_reservations(current_user):
        requester = current_user.get("user_id") or ""
        data = [item for item in data if item.requested_by == requester]

    if laboratory_id:
        data = [item for item in data if item.laboratory_id == laboratory_id]
    if status_filter:
        data = [item for item in data if item.status == status_filter]
    if day:
        data = [item for item in data if item.start_at.startswith(day)]

    serialized = [_serialize_reservation(item) for item in data]
    filtered = _apply_where_filter(serialized, where)
    ordered = _sort_reservations(filtered, sort_by, sort_type)

    total_elements = len(ordered)
    total_pages = math.ceil(total_elements / page_size) if total_elements > 0 else 0
    start_index = page_number * page_size
    end_index = start_index + page_size
    paginated_items = ordered[start_index:end_index]

    return PaginatedLabReservationResponse(
        items=paginated_items,
        pageNumber=page_number,
        pageSize=page_size,
        totalElements=total_elements,
        totalPages=total_pages,
        sortBy=str(sort_by or "start_at"),
        sortType=str(sort_type or "DESC").upper(),
        where=str(where or ""),
    )


@router.get("/mine", response_model=list[LabReservationResponse])
def list_my_reservations(current_user: dict = Depends(get_current_user)) -> list[LabReservationResponse]:
    requester = current_user.get("user_id") or ""
    return [_serialize_reservation(item) for item in lab_reservation_repo.list_all() if item.requested_by == requester]


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

    try:
        created = lab_reservation_repo.create(body, current_user=current_user)
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
        created = lab_reservation_repo.create(
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
        updated = lab_reservation_repo.update(
            created.id,
            LabReservationUpdate(
                status="in_progress",
                approved_by=str(current_user.get("user_id") or ""),
                approved_at=datetime.utcnow().isoformat(),
            ),
        )
        if updated is None:
            raise ValueError("No se pudo registrar el walk-in")
        lab_access_session_repo.create(
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
    existing_reservation = lab_reservation_repo.get_by_id(reservation_id)
    if existing_reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    can_manage = _can_manage_reservations(current_user)
    if not can_manage and existing_reservation.requested_by != (current_user.get("user_id") or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta reserva")

    _ensure_user_can_change_reservation(existing_reservation, current_user=current_user, operation="modify")

    change_fields = {field for field in {"laboratory_id", "area_id", "start_at", "end_at"} if getattr(body, field) is not None}
    payload = body
    if not can_manage and existing_reservation.status == "approved" and change_fields:
        payload = body.model_copy(
            update={
                "status": "pending",
                "approved_by": "",
                "approved_at": "",
                "cancel_reason": "",
            }
        )

    try:
        updated = lab_reservation_repo.update(reservation_id, payload)
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

    existing_reservation = lab_reservation_repo.get_by_id(reservation_id)
    if existing_reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

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
        updated = lab_reservation_repo.update(reservation_id, payload)
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

    reservation = lab_reservation_repo.get_by_id(reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")
    if reservation.status not in {"approved", "in_progress"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Solo puedes registrar entrada sobre reservas aprobadas")
    if lab_access_session_repo.get_open_by_reservation(reservation_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La reserva ya tiene una entrada registrada")

    updated = reservation
    if reservation.status != "in_progress":
        updated = lab_reservation_repo.update(reservation_id, LabReservationUpdate(status="in_progress"))
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    lab_access_session_repo.create(
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

    reservation = lab_reservation_repo.get_by_id(reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    session = lab_access_session_repo.get_open_by_reservation(reservation_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La reserva no tiene una entrada activa")

    lab_access_session_repo.close(session.id)
    updated = lab_reservation_repo.update(reservation_id, LabReservationUpdate(status="completed"))
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

    reservation = lab_reservation_repo.get_by_id(reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")
    if reservation.status != "approved":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Solo las reservas aprobadas pueden marcarse como ausentes")
    if lab_access_session_repo.get_open_by_reservation(reservation_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La reserva ya registro entrada y no puede marcarse como ausente")

    now = datetime.utcnow()
    if (now - parse_datetime(reservation.start_at)).total_seconds() < _ABSENT_GRACE_PERIOD_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Solo puedes marcar ausente cuando hayan pasado al menos 15 minutos del inicio",
        )

    updated = lab_reservation_repo.update(reservation_id, LabReservationUpdate(status="absent"))
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


@router.delete("/{reservation_id}", response_class=Response)
async def delete_reservation(reservation_id: str, current_user: dict = Depends(get_current_user)) -> None:
    reservation = lab_reservation_repo.get_by_id(reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    can_manage = _can_manage_reservations(current_user)
    if not can_manage and reservation.requested_by != (current_user.get("user_id") or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta reserva")

    _ensure_user_can_change_reservation(reservation, current_user=current_user, operation="cancel")

    deleted = lab_reservation_repo.delete(reservation_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    if not can_manage and reservation.status == "approved":
        await _notify_operations_reservation_cancelled(reservation, current_user)

    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "delete",
            "record": {"id": reservation_id},
            "at": datetime.utcnow().isoformat(),
        }
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
