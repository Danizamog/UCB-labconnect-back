from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.container import equipment_request_repo
from app.core.dependencies import ensure_any_permission, get_current_user
from app.core.laboratory_access import resolve_accessible_lab_ids
from app.schemas.equipment_request import (
    EquipmentRequestCreate,
    EquipmentRequestResponse,
    EquipmentRequestStatusUpdate,
)

router = APIRouter(prefix="/equipment-requests", tags=["equipment-requests"])

_MANAGE_LOANS = {"gestionar_prestamos", "gestionar_inventario", "gestionar_estado_equipos"}
_CREATE_EQUIPMENT_REQUESTS = {"solicitar_recursos_clase"} | _MANAGE_LOANS


def _can_manage(current_user: dict) -> bool:
    role = str(current_user.get("role") or "").strip().lower()
    if role in {"admin", "administrador"}:
        return True
    permissions = set(current_user.get("permissions") or [])
    if "*" in permissions:
        return True
    return bool(permissions.intersection(_MANAGE_LOANS))


@router.get("", response_model=list[EquipmentRequestResponse])
def list_equipment_requests(
    status_filter: str | None = Query(default=None, alias="status"),
    recurrence_group_id: str | None = Query(default=None),
    lab_reservation_id: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> list[EquipmentRequestResponse]:
    if _can_manage(current_user):
        lab_ids = resolve_accessible_lab_ids(current_user)
        return equipment_request_repo.list_all(
            status_filter=status_filter,
            recurrence_group_id=recurrence_group_id,
            lab_reservation_id=lab_reservation_id,
            lab_ids=lab_ids,
        )
    # Un solicitante (docente) solo ve sus propias solicitudes.
    requester = str(current_user.get("user_id") or current_user.get("username") or "")
    return equipment_request_repo.list_all(
        status_filter=status_filter,
        requested_by=requester,
        recurrence_group_id=recurrence_group_id,
        lab_reservation_id=lab_reservation_id,
    )


@router.post("", response_model=EquipmentRequestResponse, status_code=status.HTTP_201_CREATED)
def create_equipment_request(
    body: EquipmentRequestCreate,
    current_user: dict = Depends(get_current_user),
) -> EquipmentRequestResponse:
    ensure_any_permission(
        current_user,
        _CREATE_EQUIPMENT_REQUESTS,
        "No tienes permisos para solicitar equipos",
    )
    try:
        return equipment_request_repo.create(body, current_user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.patch("/{request_id}/status", response_model=EquipmentRequestResponse)
def update_equipment_request_status(
    request_id: str,
    body: EquipmentRequestStatusUpdate,
    current_user: dict = Depends(get_current_user),
) -> EquipmentRequestResponse:
    ensure_any_permission(
        current_user,
        _MANAGE_LOANS,
        "No tienes permisos para gestionar solicitudes de equipo",
    )
    try:
        return equipment_request_repo.update_status(
            request_id,
            body.status,
            current_user=current_user,
            notes=body.notes,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if "no encontrada" in detail.lower() else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=status_code, detail=detail) from exc
