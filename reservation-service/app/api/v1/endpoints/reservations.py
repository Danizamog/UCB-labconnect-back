from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.container import lab_reservation_repo
from app.core.datetime_utils import parse_datetime
from app.core.dependencies import ensure_any_permission, get_current_user
from app.realtime.manager import realtime_manager
from app.schemas.lab_reservation import (
    LabReservationCreate,
    LabReservationResponse,
    LabReservationStatusUpdate,
    LabReservationUpdate,
)

router = APIRouter(prefix="/reservations", tags=["reservations"])
_ABSENT_GRACE_PERIOD_SECONDS = 15 * 60
_MANAGEMENT_PERMISSIONS = {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"}


def _can_manage_reservations(current_user: dict) -> bool:
    permissions = set(current_user.get("permissions") or [])
    return current_user.get("role") == "admin" or "*" in permissions or bool(permissions.intersection(_MANAGEMENT_PERMISSIONS))


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

    return data


@router.get("/mine", response_model=list[LabReservationResponse])
def list_my_reservations(current_user: dict = Depends(get_current_user)) -> list[LabReservationResponse]:
    requester = current_user.get("user_id") or ""
    return [item for item in lab_reservation_repo.list_all() if item.requested_by == requester]


@router.get("/{reservation_id}", response_model=LabReservationResponse)
def get_reservation(reservation_id: str, current_user: dict = Depends(get_current_user)) -> LabReservationResponse:
    reservation = lab_reservation_repo.get_by_id(reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    is_admin = current_user.get("role") == "admin"
    if not is_admin and reservation.requested_by != (current_user.get("user_id") or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta reserva")

    return reservation


@router.post("", response_model=LabReservationResponse, status_code=status.HTTP_201_CREATED)
async def create_reservation(body: LabReservationCreate, current_user: dict = Depends(get_current_user)) -> LabReservationResponse:
    try:
        created = lab_reservation_repo.create(body, current_user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "create",
            "record": created.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return created


@router.patch("/{reservation_id}", response_model=LabReservationResponse)
@router.put("/{reservation_id}", response_model=LabReservationResponse)
async def update_reservation(
    reservation_id: str,
    body: LabReservationUpdate,
    current_user: dict = Depends(get_current_user),
) -> LabReservationResponse:
    reservation = lab_reservation_repo.get_by_id(reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    is_admin = current_user.get("role") == "admin"
    if not is_admin and reservation.requested_by != (current_user.get("user_id") or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta reserva")

    try:
        updated = lab_reservation_repo.update(reservation_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "update",
            "record": updated.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return updated


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

    if body.status not in {"approved", "rejected", "cancelled", "in_progress", "completed", "absent"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Estado no permitido para actualizacion manual",
        )

    payload = LabReservationUpdate(
        status=body.status,
        cancel_reason=body.cancel_reason,
        approved_by=current_user.get("user_id") if body.status == "approved" else None,
        approved_at=datetime.utcnow().isoformat() if body.status == "approved" else None,
    )

    try:
        updated = lab_reservation_repo.update(reservation_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "update",
            "record": updated.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return updated


@router.patch("/{reservation_id}/check-in", response_model=LabReservationResponse)
async def mark_reservation_check_in(
    reservation_id: str,
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
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Solo puedes marcar en curso reservas aprobadas",
        )
    if reservation.status == "in_progress":
        return reservation

    try:
        updated = lab_reservation_repo.update(reservation_id, LabReservationUpdate(status="in_progress"))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "update",
            "record": updated.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return updated


@router.patch("/{reservation_id}/check-out", response_model=LabReservationResponse)
async def mark_reservation_check_out(
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
    if reservation.status not in {"in_progress", "completed"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Solo puedes completar reservas en curso",
        )
    if reservation.status == "completed":
        return reservation

    try:
        updated = lab_reservation_repo.update(reservation_id, LabReservationUpdate(status="completed"))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "update",
            "record": updated.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return updated


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
    if reservation.status not in {"approved", "absent"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Solo las reservas aprobadas pueden marcarse como ausentes",
        )
    if reservation.status == "absent":
        return reservation

    now = datetime.utcnow()
    start_at = parse_datetime(reservation.start_at)
    if (now - start_at).total_seconds() < _ABSENT_GRACE_PERIOD_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Solo puedes marcar ausente cuando hayan pasado al menos 15 minutos del inicio",
        )

    try:
        updated = lab_reservation_repo.update(reservation_id, LabReservationUpdate(status="absent"))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "update",
            "record": updated.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return updated


@router.delete("/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reservation(reservation_id: str, current_user: dict = Depends(get_current_user)) -> None:
    reservation = lab_reservation_repo.get_by_id(reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    is_admin = current_user.get("role") == "admin"
    if not is_admin and reservation.requested_by != (current_user.get("user_id") or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta reserva")

    deleted = lab_reservation_repo.delete(reservation_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")

    await realtime_manager.broadcast(
        {
            "topic": "lab_reservation",
            "action": "delete",
            "record": {"id": reservation_id},
            "at": datetime.utcnow().isoformat(),
        }
    )
