from fastapi import APIRouter, Depends, HTTPException, status

from app.application.container import asset_repo
from app.core.dependencies import get_current_user
from app.schemas.asset import AssetCreate, AssetResponse, AssetUpdate

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
def update_asset_status(asset_id: str, body: dict, _: dict = Depends(get_current_user)) -> AssetResponse:
    try:
        asset = asset_repo.update(asset_id, AssetUpdate(status=body.get("status")))
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
