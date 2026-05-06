from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.container import asset_maintenance_repo, asset_repo
from app.core.dependencies import ensure_any_permission, get_current_user
from app.core.laboratory_access import is_lab_in_scope, resolve_accessible_lab_ids
from app.schemas.asset_maintenance import (
    AssetMaintenanceTicketClose,
    AssetMaintenanceTicketCreate,
    AssetMaintenanceTicketResponse,
    AssetResponsibilityFlagResponse,
)

router = APIRouter(prefix="/asset-maintenance", tags=["asset-maintenance"])
_MANAGE_MAINTENANCE = {"gestionar_mantenimiento", "gestionar_estado_equipos", "gestionar_inventario"}

_TICKET_NOT_FOUND_DETAIL = "Ticket no encontrado"
_ASSET_OUT_OF_SCOPE_DETAIL = "Equipo no encontrado"


@router.get("", response_model=list[AssetMaintenanceTicketResponse])
def list_tickets(
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: dict = Depends(get_current_user),
) -> list[AssetMaintenanceTicketResponse]:
    ensure_any_permission(current_user, _MANAGE_MAINTENANCE, "No tienes permisos para gestionar mantenimiento")
    accessible = resolve_accessible_lab_ids(current_user)
    return asset_maintenance_repo.list_all(status_filter=status_filter, lab_ids=accessible)


@router.get("/user-flags", response_model=list[AssetResponsibilityFlagResponse])
def list_user_flags(current_user: dict = Depends(get_current_user)) -> list[AssetResponsibilityFlagResponse]:
    ensure_any_permission(
        current_user,
        {"gestionar_roles_permisos", "reactivar_cuentas", * _MANAGE_MAINTENANCE},
        "No tienes permisos para consultar banderas de responsabilidad",
    )
    accessible = resolve_accessible_lab_ids(current_user)
    return asset_maintenance_repo.list_user_responsibility_flags(lab_ids=accessible)


@router.get("/assets/{asset_id}/history", response_model=list[AssetMaintenanceTicketResponse])
def list_asset_history(asset_id: str, current_user: dict = Depends(get_current_user)) -> list[AssetMaintenanceTicketResponse]:
    ensure_any_permission(current_user, _MANAGE_MAINTENANCE, "No tienes permisos para gestionar mantenimiento")
    accessible = resolve_accessible_lab_ids(current_user)
    asset = asset_repo.get_by_id(asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_ASSET_OUT_OF_SCOPE_DETAIL)
    if not is_lab_in_scope(asset.laboratory_id, accessible):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_ASSET_OUT_OF_SCOPE_DETAIL)
    return asset_maintenance_repo.list_for_asset(asset_id)


@router.post("/assets/{asset_id}/tickets", response_model=AssetMaintenanceTicketResponse, status_code=status.HTTP_201_CREATED)
def create_ticket(
    asset_id: str,
    body: AssetMaintenanceTicketCreate,
    current_user: dict = Depends(get_current_user),
) -> AssetMaintenanceTicketResponse:
    ensure_any_permission(current_user, _MANAGE_MAINTENANCE, "No tienes permisos para gestionar mantenimiento")
    accessible = resolve_accessible_lab_ids(current_user)
    asset = asset_repo.get_by_id(asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_ASSET_OUT_OF_SCOPE_DETAIL)
    if not is_lab_in_scope(asset.laboratory_id, accessible):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_ASSET_OUT_OF_SCOPE_DETAIL)
    try:
        return asset_maintenance_repo.create(asset_id, body, current_user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.patch("/tickets/{ticket_id}/close", response_model=AssetMaintenanceTicketResponse)
def close_ticket(
    ticket_id: str,
    body: AssetMaintenanceTicketClose,
    current_user: dict = Depends(get_current_user),
) -> AssetMaintenanceTicketResponse:
    ensure_any_permission(current_user, _MANAGE_MAINTENANCE, "No tienes permisos para gestionar mantenimiento")
    accessible = resolve_accessible_lab_ids(current_user)
    if accessible is not None:
        ticket = asset_maintenance_repo.get_by_id(ticket_id)
        if ticket is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_TICKET_NOT_FOUND_DETAIL)
        # Caso comun: el ticket trae laboratory_id denormalizado y resolvemos
        # el scope sin pegarle a asset_repo.
        if ticket.laboratory_id:
            if not is_lab_in_scope(ticket.laboratory_id, accessible):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_TICKET_NOT_FOUND_DETAIL)
        else:
            # Ticket legado sin laboratory_id; recurrimos al asset una sola vez.
            asset = asset_repo.get_by_id(ticket.asset_id)
            if asset is None or not is_lab_in_scope(asset.laboratory_id, accessible):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_TICKET_NOT_FOUND_DETAIL)
    try:
        return asset_maintenance_repo.close(ticket_id, body, current_user=current_user)
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if "no encontrado" in detail.lower() else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=status_code, detail=detail) from exc
