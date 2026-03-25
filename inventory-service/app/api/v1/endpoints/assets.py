from fastapi import APIRouter, Depends, HTTPException

from app.application.container import asset_use_cases
from app.core.dependencies import ensure_any_permission, get_current_user_payload
from app.schemas.asset import AssetCreate, AssetOut, AssetStatusLogOut, AssetStatusUpdate, AssetUpdate

router = APIRouter(prefix="/assets", tags=["assets"])


def serialize_asset(asset) -> AssetOut:
    return AssetOut.model_validate(
        {
            "id": str(asset.id),
            "name": asset.name,
            "category": asset.category,
            "location": asset.location,
            "description": asset.description,
            "serial_number": asset.serial_number,
            "laboratory_id": asset.laboratory_id,
            "status": asset.status,
            "status_updated_at": asset.status_updated_at,
            "status_updated_by": asset.status_updated_by,
        }
    )


@router.get("/", response_model=list[AssetOut])
def get_assets():
    return [serialize_asset(asset) for asset in asset_use_cases.list_assets()]


@router.post("/", response_model=AssetOut)
def create_asset(
    payload: AssetCreate,
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(current_user, {"gestionar_inventario"}, "No autorizado para registrar equipos")
    try:
        asset = asset_use_cases.create_asset(
            name=payload.name,
            category=payload.category,
            location=payload.location,
            description=payload.description,
            serial_number=payload.serial_number,
            laboratory_id=payload.laboratory_id,
            status=payload.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return serialize_asset(asset)


@router.put("/{asset_id}", response_model=AssetOut)
def update_asset(
    asset_id: int,
    payload: AssetUpdate,
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(current_user, {"gestionar_inventario"}, "No autorizado para editar equipos")
    try:
        asset = asset_use_cases.update_asset(
            asset_id=asset_id,
            name=payload.name,
            category=payload.category,
            location=payload.location,
            description=payload.description,
            serial_number=payload.serial_number,
            laboratory_id=payload.laboratory_id,
            status=payload.status,
            changed_by=current_user.get("username"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return serialize_asset(asset)


@router.patch("/{asset_id}/status", response_model=AssetOut)
def update_asset_status(
    asset_id: int,
    payload: AssetStatusUpdate,
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(
        current_user,
        {"gestionar_estado_equipos", "gestionar_mantenimiento"},
        "No autorizado para actualizar el estado de equipos",
    )
    try:
        asset = asset_use_cases.update_asset_status(
            asset_id=asset_id,
            status=payload.status,
            changed_by=current_user.get("username"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

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

    return {"message": "Equipo eliminado"}
