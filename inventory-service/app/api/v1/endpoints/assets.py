from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user_payload
from app.models.asset import Asset
from app.schemas.asset import AssetCreate, AssetOut, AssetStatusUpdate, AssetUpdate

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/", response_model=list[AssetOut])
def get_assets(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    return db.query(Asset).order_by(Asset.id.desc()).all()


@router.post("/", response_model=AssetOut)
def create_asset(
    payload: AssetCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede registrar equipos")

    allowed_status = {"available", "maintenance", "damaged"}
    if payload.status not in allowed_status:
        raise HTTPException(status_code=400, detail="Estado inválido")

    asset = Asset(
        name=payload.name,
        category=payload.category,
        description=payload.description,
        serial_number=payload.serial_number,
        laboratory_id=payload.laboratory_id,
        status=payload.status,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.put("/{asset_id}", response_model=AssetOut)
def update_asset(
    asset_id: int,
    payload: AssetUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede editar equipos")

    allowed_status = {"available", "maintenance", "damaged"}
    if payload.status not in allowed_status:
        raise HTTPException(status_code=400, detail="Estado inválido")

    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    asset.name = payload.name
    asset.category = payload.category
    asset.description = payload.description
    asset.serial_number = payload.serial_number
    asset.laboratory_id = payload.laboratory_id
    asset.status = payload.status

    db.commit()
    db.refresh(asset)
    return asset


@router.patch("/{asset_id}/status", response_model=AssetOut)
def update_asset_status(
    asset_id: int,
    payload: AssetStatusUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede cambiar estados")

    allowed_status = {"available", "maintenance", "damaged"}
    if payload.status not in allowed_status:
        raise HTTPException(status_code=400, detail="Estado inválido. Usa: available, maintenance o damaged")

    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    asset.status = payload.status
    db.commit()
    db.refresh(asset)
    return asset