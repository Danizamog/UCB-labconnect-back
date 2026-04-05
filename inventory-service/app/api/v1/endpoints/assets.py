from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.container import asset_repo
from app.core.dependencies import get_current_user
from app.schemas.asset import (
    AssetCreate,
    AssetResponse,
    AssetStatusHistoryEntry,
    AssetStatusUpdateRequest,
    AssetUpdate,
)

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[AssetResponse])
def list_assets() -> list[AssetResponse]:
    return asset_repo.list_all()


@router.get("/{asset_id}", response_model=AssetResponse)
def get_asset(asset_id: str, _: dict = Depends(get_current_user)) -> AssetResponse:
    asset = asset_repo.get_by_id(asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset no encontrado")
    return asset


@router.get("/{asset_id}/status-history", response_model=list[AssetStatusHistoryEntry])
def list_asset_status_history(
    asset_id: str,
    limit: int = Query(default=100, ge=1, le=200),
    _: dict = Depends(get_current_user),
) -> list[AssetStatusHistoryEntry]:
    return asset_repo.list_status_history(asset_id, limit=limit)


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
def create_asset(body: AssetCreate, _: dict = Depends(get_current_user)) -> AssetResponse:
    try:
        return asset_repo.create(body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.patch("/{asset_id}", response_model=AssetResponse)
@router.put("/{asset_id}", response_model=AssetResponse)
def update_asset(asset_id: str, body: AssetUpdate, _: dict = Depends(get_current_user)) -> AssetResponse:
    try:
        asset = asset_repo.update(asset_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset no encontrado")
    return asset


@router.patch("/{asset_id}/status", response_model=AssetResponse)
def update_asset_status(
    asset_id: str,
    body: AssetStatusUpdateRequest,
    current_user: dict = Depends(get_current_user),
) -> AssetResponse:
    changed_by = current_user.get("username") or current_user.get("email") or "sistema"
    try:
        asset = asset_repo.update_status(
            asset_id,
            status=body.status,
            changed_by=str(changed_by),
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset no encontrado")
    return asset


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: str, _: dict = Depends(get_current_user)) -> None:
    deleted = asset_repo.delete(asset_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset no encontrado")
