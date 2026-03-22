from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user_payload
from app.models.stock_item import StockItem
from app.schemas.stock_item import (
    StockItemCreate,
    StockItemOut,
    StockItemUpdate,
    StockQuantityUpdate,
)

router = APIRouter(prefix="/stock-items", tags=["stock-items"])


def ensure_manager(current_user: dict):
    if current_user.get("role") not in {"admin", "lab_manager"}:
        raise HTTPException(status_code=403, detail="Solo personal autorizado puede gestionar stock")


@router.get("/", response_model=list[StockItemOut])
def get_stock_items(
    laboratory_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    query = db.query(StockItem)
    if laboratory_id is not None:
        query = query.filter(StockItem.laboratory_id == laboratory_id)
    return query.order_by(StockItem.id.desc()).all()


@router.post("/", response_model=StockItemOut)
def create_stock_item(
    payload: StockItemCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)
    if payload.quantity_available < 0:
        raise HTTPException(status_code=400, detail="La cantidad no puede ser negativa")
    if payload.minimum_stock < 0:
        raise HTTPException(status_code=400, detail="El stock minimo no puede ser negativo")

    item = StockItem(
        name=payload.name,
        category=payload.category,
        unit=payload.unit,
        quantity_available=payload.quantity_available,
        minimum_stock=payload.minimum_stock,
        laboratory_id=payload.laboratory_id,
        description=payload.description,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{item_id}", response_model=StockItemOut)
def update_stock_item(
    item_id: int,
    payload: StockItemUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)
    if payload.quantity_available < 0:
        raise HTTPException(status_code=400, detail="La cantidad no puede ser negativa")
    if payload.minimum_stock < 0:
        raise HTTPException(status_code=400, detail="El stock minimo no puede ser negativo")

    item = db.query(StockItem).filter(StockItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Reactivo no encontrado")

    item.name = payload.name
    item.category = payload.category
    item.unit = payload.unit
    item.quantity_available = payload.quantity_available
    item.minimum_stock = payload.minimum_stock
    item.laboratory_id = payload.laboratory_id
    item.description = payload.description

    db.commit()
    db.refresh(item)
    return item


@router.patch("/{item_id}/quantity", response_model=StockItemOut)
def update_stock_quantity(
    item_id: int,
    payload: StockQuantityUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)
    if payload.quantity_available < 0:
        raise HTTPException(status_code=400, detail="La cantidad no puede ser negativa")

    item = db.query(StockItem).filter(StockItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Reactivo no encontrado")

    item.quantity_available = payload.quantity_available
    db.commit()
    db.refresh(item)
    return item
