from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user_payload
from app.models.asset import Asset
from app.models.asset_loan import AssetLoan
from app.schemas.asset import AssetCreate, AssetOut, AssetStatusUpdate, AssetUpdate
from app.schemas.asset_loan import AssetLoanCreate, AssetLoanOut

router = APIRouter(prefix="/assets", tags=["assets"])


def ensure_manager(current_user: dict):
    if current_user.get("role") not in {"admin", "lab_manager"}:
        raise HTTPException(status_code=403, detail="Solo personal autorizado puede gestionar equipos")


@router.get("/", response_model=list[AssetOut])
def get_assets(
    laboratory_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    query = db.query(Asset)
    if laboratory_id is not None:
        query = query.filter(Asset.laboratory_id == laboratory_id)
    return query.order_by(Asset.id.desc()).all()


@router.post("/", response_model=AssetOut)
def create_asset(
    payload: AssetCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)

    allowed_status = {"available", "maintenance", "damaged"}
    if payload.status not in allowed_status:
        raise HTTPException(status_code=400, detail="Estado invalido")
    if payload.quantity_total <= 0:
        raise HTTPException(status_code=400, detail="La cantidad total debe ser mayor a 0")
    if payload.quantity_available < 0:
        raise HTTPException(status_code=400, detail="La cantidad disponible no puede ser negativa")
    if payload.quantity_available > payload.quantity_total:
        raise HTTPException(status_code=400, detail="La cantidad disponible no puede ser mayor a la total")

    asset = Asset(
        name=payload.name,
        category=payload.category,
        description=payload.description,
        serial_number=payload.serial_number,
        laboratory_id=payload.laboratory_id,
        quantity_total=max(payload.quantity_total, 1),
        quantity_available=min(max(payload.quantity_available, 0), max(payload.quantity_total, 1)),
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
    ensure_manager(current_user)

    allowed_status = {"available", "maintenance", "damaged"}
    if payload.status not in allowed_status:
        raise HTTPException(status_code=400, detail="Estado invalido")
    if payload.quantity_total <= 0:
        raise HTTPException(status_code=400, detail="La cantidad total debe ser mayor a 0")
    if payload.quantity_available < 0:
        raise HTTPException(status_code=400, detail="La cantidad disponible no puede ser negativa")
    if payload.quantity_available > payload.quantity_total:
        raise HTTPException(status_code=400, detail="La cantidad disponible no puede ser mayor a la total")

    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    asset.name = payload.name
    asset.category = payload.category
    asset.description = payload.description
    asset.serial_number = payload.serial_number
    asset.laboratory_id = payload.laboratory_id
    asset.quantity_total = max(payload.quantity_total, 1)
    asset.quantity_available = min(max(payload.quantity_available, 0), asset.quantity_total)
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
    ensure_manager(current_user)

    allowed_status = {"available", "maintenance", "damaged"}
    if payload.status not in allowed_status:
        raise HTTPException(status_code=400, detail="Estado invalido. Usa: available, maintenance o damaged")

    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    asset.status = payload.status
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/loans", response_model=list[AssetLoanOut])
def get_asset_loans(
    asset_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    query = db.query(AssetLoan)
    if asset_id is not None:
        query = query.filter(AssetLoan.asset_id == asset_id)
    return query.order_by(AssetLoan.created_at.desc()).all()


@router.post("/loans", response_model=AssetLoanOut)
def create_asset_loan(
    payload: AssetLoanCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)

    asset = db.query(Asset).filter(Asset.id == payload.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Cantidad invalida")
    if not payload.borrower_name.strip():
        raise HTTPException(status_code=400, detail="El responsable es obligatorio")
    if not payload.borrower_email.strip():
        raise HTTPException(status_code=400, detail="El correo es obligatorio")
    if payload.quantity > asset.quantity_available:
        raise HTTPException(status_code=400, detail="No hay suficiente cantidad disponible")

    asset.quantity_available -= payload.quantity

    loan = AssetLoan(
        asset_id=payload.asset_id,
        borrower_name=payload.borrower_name,
        borrower_email=payload.borrower_email,
        quantity=payload.quantity,
        notes=payload.notes,
        due_at=payload.due_at,
        status="loaned",
    )
    db.add(loan)
    db.commit()
    db.refresh(loan)
    return loan


@router.patch("/loans/{loan_id}/return", response_model=AssetLoanOut)
def return_asset_loan(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)

    loan = db.query(AssetLoan).filter(AssetLoan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Prestamo no encontrado")
    if loan.status == "returned":
        return loan

    asset = db.query(Asset).filter(Asset.id == loan.asset_id).first()
    if asset:
        asset.quantity_available = min(asset.quantity_total, asset.quantity_available + loan.quantity)

    loan.status = "returned"
    loan.returned_at = datetime.utcnow()
    db.commit()
    db.refresh(loan)
    return loan
