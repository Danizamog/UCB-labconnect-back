from fastapi import APIRouter, Depends, HTTPException, status

from app.application.container import asset_repo
from app.core.dependencies import ensure_any_permission, get_current_user
from app.core.laboratory_access import is_lab_in_scope, resolve_accessible_lab_ids
from app.schemas.asset import AssetCreate, AssetResponse, AssetUpdate

router = APIRouter(prefix="/assets", tags=["assets"])

_VIEW_ASSETS = {"gestionar_inventario", "gestionar_estado_equipos", "gestionar_mantenimiento", "gestionar_prestamos"}
_MANAGE_ASSETS = {"gestionar_inventario"}
_UPDATE_STATUS = {"gestionar_inventario", "gestionar_estado_equipos", "gestionar_mantenimiento"}

_OUT_OF_SCOPE_DETAIL = "Asset no encontrado"
_OUT_OF_SCOPE_LAB_DETAIL = "Solo puedes operar sobre equipos de tus laboratorios asignados"


def _filter_assets_in_scope(items, accessible: list[str] | None) -> list[AssetResponse]:
    if accessible is None:
        return items
    return [item for item in items if is_lab_in_scope(item.laboratory_id, accessible)]


@router.get("", response_model=list[AssetResponse])
def list_assets(current_user: dict = Depends(get_current_user)) -> list[AssetResponse]:
    ensure_any_permission(current_user, _VIEW_ASSETS, "No tienes permisos para consultar el inventario")
    accessible = resolve_accessible_lab_ids(current_user)
    return _filter_assets_in_scope(asset_repo.list_all(), accessible)


@router.get("/{asset_id}", response_model=AssetResponse)
def get_asset(asset_id: str, current_user: dict = Depends(get_current_user)) -> AssetResponse:
    ensure_any_permission(current_user, _VIEW_ASSETS, "No tienes permisos para consultar el inventario")
    asset = asset_repo.get_by_id(asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    accessible = resolve_accessible_lab_ids(current_user)
    if not is_lab_in_scope(asset.laboratory_id, accessible):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    return asset


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
def create_asset(body: AssetCreate, current_user: dict = Depends(get_current_user)) -> AssetResponse:
    ensure_any_permission(current_user, _MANAGE_ASSETS, "No tienes permisos para registrar equipos")
    accessible = resolve_accessible_lab_ids(current_user)
    if not is_lab_in_scope(body.laboratory_id, accessible):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_OUT_OF_SCOPE_LAB_DETAIL)
    try:
        return asset_repo.create(body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.patch("/{asset_id}", response_model=AssetResponse)
@router.put("/{asset_id}", response_model=AssetResponse)
def update_asset(asset_id: str, body: AssetUpdate, current_user: dict = Depends(get_current_user)) -> AssetResponse:
    ensure_any_permission(current_user, _MANAGE_ASSETS, "No tienes permisos para modificar equipos")
    accessible = resolve_accessible_lab_ids(current_user)
    existing = asset_repo.get_by_id(asset_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    if not is_lab_in_scope(existing.laboratory_id, accessible):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    if body.laboratory_id is not None and not is_lab_in_scope(body.laboratory_id, accessible):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_OUT_OF_SCOPE_LAB_DETAIL)
    try:
        asset = asset_repo.update(asset_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    return asset


@router.patch("/{asset_id}/status", response_model=AssetResponse)
def update_asset_status(asset_id: str, body: dict, current_user: dict = Depends(get_current_user)) -> AssetResponse:
    ensure_any_permission(current_user, _UPDATE_STATUS, "No tienes permisos para cambiar el estado de equipos")
    accessible = resolve_accessible_lab_ids(current_user)
    existing = asset_repo.get_by_id(asset_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    if not is_lab_in_scope(existing.laboratory_id, accessible):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    try:
        asset = asset_repo.update(asset_id, AssetUpdate(status=body.get("status")))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    return asset


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: str, current_user: dict = Depends(get_current_user)) -> None:
    ensure_any_permission(current_user, _MANAGE_ASSETS, "No tienes permisos para eliminar equipos")
    accessible = resolve_accessible_lab_ids(current_user)
    existing = asset_repo.get_by_id(asset_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    if not is_lab_in_scope(existing.laboratory_id, accessible):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    deleted = asset_repo.delete(asset_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
