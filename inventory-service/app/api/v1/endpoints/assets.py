import os
from fastapi import APIRouter, Depends, HTTPException

from app.schemas.asset import AssetCreate, AssetOut, AssetStatusUpdate, AssetUpdate
from app.infrastructure.repositories.pocketbase_asset_repository import PocketBaseAssetRepository
from app.domain.entities.asset import Asset as AssetEntity

router = APIRouter(prefix="/assets", tags=["assets"])


def get_asset_repository() -> PocketBaseAssetRepository:
    """Obtiene instancia del repositorio de assets con PocketBase."""
    base_url = os.getenv("POCKETBASE_URL", "https://bd-labconnect.zamoranogamarra.online")
    identity = os.getenv("POCKETBASE_IDENTITY", "daniel.zamorano@ucb.edu.bo")
    password = os.getenv("POCKETBASE_PASSWORD", "daniel.zamorano")
    
    return PocketBaseAssetRepository(
        base_url=base_url,
        collection="assets",
        auth_identity=identity,
        auth_password=password,
        auth_collection="_superusers",
    )


@router.get("/", response_model=list[AssetOut])
def get_assets(
    repo: PocketBaseAssetRepository = Depends(get_asset_repository),
):
    assets = repo.list_all()
    return [
        AssetOut(
            id=asset.id or "",
            name=asset.name,
            category=asset.category,
            description=asset.description,
            serial_number=asset.serial_number,
            laboratory_id=asset.laboratory_id,
            status=asset.status,
        )
        for asset in assets
    ]


@router.post("/", response_model=AssetOut)
def create_asset(
    payload: AssetCreate,
    repo: PocketBaseAssetRepository = Depends(get_asset_repository),
):
    allowed_status = {"available", "maintenance", "damaged"}
    if payload.status not in allowed_status:
        raise HTTPException(status_code=400, detail="Estado inválido")

    asset_entity = AssetEntity(
        id=None,
        name=payload.name,
        category=payload.category,
        description=payload.description,
        serial_number=payload.serial_number,
        laboratory_id=payload.laboratory_id,
        status=payload.status,
    )

    created_asset = repo.create(asset_entity)

    return AssetOut(
        id=created_asset.id or "",
        name=created_asset.name,
        category=created_asset.category,
        description=created_asset.description,
        serial_number=created_asset.serial_number,
        laboratory_id=created_asset.laboratory_id,
        status=created_asset.status,
    )


@router.put("/{asset_id}", response_model=AssetOut)
def update_asset(
    asset_id: str,
    payload: AssetUpdate,
    repo: PocketBaseAssetRepository = Depends(get_asset_repository),
):
    allowed_status = {"available", "maintenance", "damaged"}
    if payload.status not in allowed_status:
        raise HTTPException(status_code=400, detail="Estado inválido")

    existing_asset = repo.get_by_id(asset_id)
    if not existing_asset:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    asset_entity = AssetEntity(
        id=asset_id,
        name=payload.name,
        category=payload.category,
        description=payload.description,
        serial_number=payload.serial_number,
        laboratory_id=payload.laboratory_id,
        status=payload.status,
    )

    updated_asset = repo.update(asset_entity)

    return AssetOut(
        id=updated_asset.id or "",
        name=updated_asset.name,
        category=updated_asset.category,
        description=updated_asset.description,
        serial_number=updated_asset.serial_number,
        laboratory_id=updated_asset.laboratory_id,
        status=updated_asset.status,
    )


@router.patch("/{asset_id}/status", response_model=AssetOut)
def update_asset_status(
    asset_id: str,
    payload: AssetStatusUpdate,
    repo: PocketBaseAssetRepository = Depends(get_asset_repository),
):
    allowed_status = {"available", "maintenance", "damaged"}
    if payload.status not in allowed_status:
        raise HTTPException(status_code=400, detail="Estado inválido. Usa: available, maintenance o damaged")

    existing_asset = repo.get_by_id(asset_id)
    if not existing_asset:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    existing_asset.status = payload.status
    updated_asset = repo.update(existing_asset)

    return AssetOut(
        id=updated_asset.id or "",
        name=updated_asset.name,
        category=updated_asset.category,
        description=updated_asset.description,
        serial_number=updated_asset.serial_number,
        laboratory_id=updated_asset.laboratory_id,
        status=updated_asset.status,
    )


@router.delete("/{asset_id}")
def delete_asset(
    asset_id: str,
    repo: PocketBaseAssetRepository = Depends(get_asset_repository),
):
    existing_asset = repo.get_by_id(asset_id)
    if not existing_asset:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    repo.delete(asset_id)
    return {"message": "Equipo eliminado"}
