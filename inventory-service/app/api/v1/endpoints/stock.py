from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import ensure_any_permission, get_db, get_current_user_payload
from app.infrastructure.pocketbase_sync import sync_inventory_to_pocketbase
from app.models.stock_movement import StockMovement
from app.models.stock_item import StockItem
from app.schemas.stock_item import (
    StockMovementCreate,
    StockMovementOut,
    StockItemCreate,
    StockItemOut,
    StockItemUpdate,
    StockQuantityUpdate,
)
from app.services.stock_movements import apply_stock_change

router = APIRouter(prefix="/stock-items", tags=["stock-items"])

READ_HISTORY_PERMISSIONS = {
    "gestionar_stock",
    "gestionar_reactivos_quimicos",
    "gestionar_prestamos",
    "generar_reportes",
    "consultar_estadisticas",
}


def serialize_movement(movement: StockMovement, item_name: str) -> StockMovementOut:
    return StockMovementOut(
        id=movement.id,
        stock_item_id=movement.stock_item_id,
        stock_item_name=item_name,
        movement_type=movement.movement_type,
        quantity_change=movement.quantity_change,
        quantity_before=movement.quantity_before,
        quantity_after=movement.quantity_after,
        reference_type=movement.reference_type,
        reference_id=movement.reference_id,
        performed_by=movement.performed_by,
        notes=movement.notes,
        created_at=movement.created_at,
    )


@router.get("/", response_model=list[StockItemOut])
def get_stock_items(
    laboratory_id: int | None = Query(default=None),
    available_only: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    query = db.query(StockItem)
    if laboratory_id is not None:
        query = query.filter(
            (StockItem.laboratory_id == laboratory_id) | (StockItem.laboratory_id.is_(None))
        )
    if available_only:
        query = query.filter(StockItem.quantity_available > 0)
    return query.order_by(StockItem.name.asc()).all()


@router.post("/", response_model=StockItemOut)
def create_stock_item(
    payload: StockItemCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(
        current_user,
        {"gestionar_stock", "gestionar_reactivos_quimicos"},
        "No autorizado para registrar reactivos",
    )

    item = StockItem(
        name=payload.name,
        category=payload.category,
        unit=payload.unit,
        quantity_available=0,
        minimum_stock=payload.minimum_stock,
        laboratory_id=payload.laboratory_id,
        description=payload.description,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    if payload.quantity_available > 0:
        apply_stock_change(
            db,
            item,
            quantity_change=payload.quantity_available,
            movement_type="entry",
            performed_by=current_user.get("username") or "system",
            notes="Stock inicial registrado al crear el material.",
            reference_type="material_create",
            reference_id=item.id,
        )
        db.commit()
        db.refresh(item)

    sync_inventory_to_pocketbase()
    return item


@router.put("/{item_id}", response_model=StockItemOut)
def update_stock_item(
    item_id: int,
    payload: StockItemUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(
        current_user,
        {"gestionar_stock", "gestionar_reactivos_quimicos"},
        "No autorizado para editar reactivos",
    )

    item = db.query(StockItem).filter(StockItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Reactivo no encontrado")

    if payload.quantity_available < 0:
        raise HTTPException(status_code=400, detail="El stock no puede quedar en negativo")

    item.name = payload.name
    item.category = payload.category
    item.unit = payload.unit
    item.minimum_stock = payload.minimum_stock
    item.laboratory_id = payload.laboratory_id
    item.description = payload.description

    quantity_change = payload.quantity_available - item.quantity_available
    if quantity_change != 0:
        apply_stock_change(
            db,
            item,
            quantity_change=quantity_change,
            movement_type="adjustment",
            performed_by=current_user.get("username") or "system",
            notes="Ajuste manual desde edicion del material.",
            reference_type="material_update",
            reference_id=item.id,
        )

    db.commit()
    db.refresh(item)
    sync_inventory_to_pocketbase()
    return item


@router.patch("/{item_id}/quantity", response_model=StockItemOut)
def update_stock_quantity(
    item_id: int,
    payload: StockQuantityUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(
        current_user,
        {"gestionar_stock"},
        "No autorizado para actualizar stock",
    )

    item = db.query(StockItem).filter(StockItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Reactivo no encontrado")

    if payload.quantity_available < 0:
        raise HTTPException(status_code=400, detail="El stock no puede quedar en negativo")

    quantity_change = payload.quantity_available - item.quantity_available
    if quantity_change != 0:
        apply_stock_change(
            db,
            item,
            quantity_change=quantity_change,
            movement_type="adjustment",
            performed_by=current_user.get("username") or "system",
            notes="Ajuste directo de stock.",
            reference_type="quantity_patch",
            reference_id=item.id,
        )

    db.commit()
    db.refresh(item)
    sync_inventory_to_pocketbase()
    return item


@router.get("/movements", response_model=list[StockMovementOut])
def get_stock_movements(
    stock_item_id: int | None = Query(default=None),
    limit: int = Query(default=40, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(
        current_user,
        READ_HISTORY_PERMISSIONS,
        "No autorizado para ver el historial de stock",
    )

    query = (
        db.query(StockMovement, StockItem.name)
        .join(StockItem, StockItem.id == StockMovement.stock_item_id)
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
    )

    if stock_item_id is not None:
        query = query.filter(StockMovement.stock_item_id == stock_item_id)

    rows = query.limit(limit).all()
    return [serialize_movement(movement, item_name) for movement, item_name in rows]


@router.post("/{item_id}/movements", response_model=StockMovementOut)
def create_stock_movement(
    item_id: int,
    payload: StockMovementCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(
        current_user,
        {"gestionar_stock", "gestionar_reactivos_quimicos"},
        "No autorizado para registrar movimientos de stock",
    )

    item = db.query(StockItem).filter(StockItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Reactivo no encontrado")

    direction = 1 if payload.movement_type in {"entry", "return", "reservation_release"} else -1
    movement = apply_stock_change(
        db,
        item,
        quantity_change=payload.quantity * direction,
        movement_type=payload.movement_type,
        performed_by=current_user.get("username") or "system",
        notes=payload.notes,
        reference_type=payload.reference_type or "manual_movement",
        reference_id=payload.reference_id if payload.reference_id is not None else item.id,
    )

    db.commit()
    db.refresh(item)
    db.refresh(movement)
    sync_inventory_to_pocketbase()
    return serialize_movement(movement, item.name)


@router.delete("/{item_id}")
def delete_stock_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(
        current_user,
        {"gestionar_stock", "gestionar_reactivos_quimicos"},
        "No autorizado para eliminar reactivos",
    )

    item = db.query(StockItem).filter(StockItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Reactivo no encontrado")

    db.delete(item)
    db.commit()
    sync_inventory_to_pocketbase()
    return {"message": "Material eliminado"}
