from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.container import asset_maintenance_repo
from app.core.dependencies import ensure_any_permission, get_current_user
from app.schemas.asset_maintenance import (
    AssetMaintenanceTicketClose,
    AssetMaintenanceTicketCreate,
    AssetMaintenanceTicketResponse,
    AssetResponsibilityFlagResponse,
)

router = APIRouter(prefix="/asset-maintenance", tags=["asset-maintenance"])
_MANAGE_MAINTENANCE = {"gestionar_mantenimiento", "gestionar_estado_equipos", "gestionar_inventario"}


@router.get("", response_model=list[AssetMaintenanceTicketResponse])
def list_tickets(
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: dict = Depends(get_current_user),
) -> list[AssetMaintenanceTicketResponse]:
    ensure_any_permission(current_user, _MANAGE_MAINTENANCE, "No tienes permisos para gestionar mantenimiento")
    return asset_maintenance_repo.list_all(status_filter=status_filter)


@router.get("/user-flags", response_model=list[AssetResponsibilityFlagResponse])
def list_user_flags(current_user: dict = Depends(get_current_user)) -> list[AssetResponsibilityFlagResponse]:
    ensure_any_permission(
        current_user,
        {"gestionar_roles_permisos", "reactivar_cuentas", * _MANAGE_MAINTENANCE},
        "No tienes permisos para consultar banderas de responsabilidad",
    )
    return asset_maintenance_repo.list_user_responsibility_flags()


@router.get("/assets/{asset_id}/history", response_model=list[AssetMaintenanceTicketResponse])
def list_asset_history(asset_id: str, current_user: dict = Depends(get_current_user)) -> list[AssetMaintenanceTicketResponse]:
    ensure_any_permission(current_user, _MANAGE_MAINTENANCE, "No tienes permisos para gestionar mantenimiento")
    return asset_maintenance_repo.list_for_asset(asset_id)


@router.post("/assets/{asset_id}/tickets", response_model=AssetMaintenanceTicketResponse, status_code=status.HTTP_201_CREATED)
def create_ticket(
    asset_id: str,
    body: AssetMaintenanceTicketCreate,
    current_user: dict = Depends(get_current_user),
) -> AssetMaintenanceTicketResponse:
    ensure_any_permission(current_user, _MANAGE_MAINTENANCE, "No tienes permisos para gestionar mantenimiento")
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
    try:
        return asset_maintenance_repo.close(ticket_id, body, current_user=current_user)
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if "no encontrado" in detail.lower() else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=status_code, detail=detail) from exc
