from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.stock_item import StockItem
from app.models.stock_movement import StockMovement


def apply_stock_change(
    db: Session,
    item: StockItem,
    *,
    quantity_change: int,
    movement_type: str,
    performed_by: str,
    notes: str | None = None,
    reference_type: str | None = None,
    reference_id: int | None = None,
) -> StockMovement | None:
    if quantity_change == 0:
        return None

    previous_quantity = int(item.quantity_available or 0)
    next_quantity = previous_quantity + int(quantity_change)

    if next_quantity < 0:
        raise HTTPException(
            status_code=400,
            detail="La transaccion supera el stock actual disponible del material",
        )

    item.quantity_available = next_quantity

    movement = StockMovement(
        stock_item_id=item.id,
        movement_type=movement_type,
        quantity_change=int(quantity_change),
        quantity_before=previous_quantity,
        quantity_after=next_quantity,
        reference_type=reference_type,
        reference_id=reference_id,
        performed_by=performed_by,
        notes=notes.strip() if isinstance(notes, str) and notes.strip() else None,
    )
    db.add(movement)
    return movement
