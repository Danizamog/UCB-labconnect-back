from fastapi import APIRouter, Depends, HTTPException, status

<<<<<<< HEAD
from app.application.container import asset_repo
from app.core.dependencies import get_current_user
from app.schemas.asset import AssetCreate, AssetResponse, AssetUpdate
=======
from app.application.container import asset_use_cases
from app.core.dependencies import ensure_any_permission, get_current_user_payload
from app.infrastructure.pocketbase_sync import sync_inventory_to_pocketbase
from app.schemas.asset import AssetCreate, AssetOut, AssetStatusLogOut, AssetStatusUpdate, AssetUpdate
>>>>>>> 0fd8dd8e4fef7ab90058217a1e359fa5cfe45cbf

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
<<<<<<< HEAD
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
=======
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sync_inventory_to_pocketbase()
    return serialize_asset(asset)
>>>>>>> 0fd8dd8e4fef7ab90058217a1e359fa5cfe45cbf


@router.patch("/{asset_id}", response_model=AssetResponse)
@router.put("/{asset_id}", response_model=AssetResponse)
def update_asset(asset_id: str, body: AssetUpdate, _: dict = Depends(get_current_user)) -> AssetResponse:
    try:
        asset = asset_repo.update(asset_id, body)
    except ValueError as exc:
<<<<<<< HEAD
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset no encontrado")
    return asset
=======
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    sync_inventory_to_pocketbase()
    return serialize_asset(asset)
>>>>>>> 0fd8dd8e4fef7ab90058217a1e359fa5cfe45cbf


@router.patch("/{asset_id}/status", response_model=AssetResponse)
def update_asset_status(asset_id: str, body: dict, _: dict = Depends(get_current_user)) -> AssetResponse:
    try:
        asset = asset_repo.update(asset_id, AssetUpdate(status=body.get("status")))
    except ValueError as exc:
<<<<<<< HEAD
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset no encontrado")
    return asset


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: str, _: dict = Depends(get_current_user)) -> None:
    deleted = asset_repo.delete(asset_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset no encontrado")
=======
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    sync_inventory_to_pocketbase()
    return serialize_asset(asset)


@router.get("/{asset_id}/status-history", response_model=list[AssetStatusLogOut])
def get_asset_status_history(
    asset_id: int,
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(
        current_user,
        {"gestionar_estado_equipos", "gestionar_mantenimiento", "gestionar_inventario", "generar_reportes", "consultar_estadisticas"},
        "No autorizado para ver el historial de estados del equipo",
    )
    try:
        return asset_use_cases.list_asset_status_logs(asset_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{asset_id}")
def delete_asset(
    asset_id: int,
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(current_user, {"gestionar_inventario"}, "No autorizado para eliminar equipos")
    try:
        asset_use_cases.delete_asset(asset_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    sync_inventory_to_pocketbase()
    return {"message": "Equipo eliminado"}
>>>>>>> 0fd8dd8e4fef7ab90058217a1e359fa5cfe45cbf
