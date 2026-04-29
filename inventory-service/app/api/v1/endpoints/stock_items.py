import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.application.container import stock_item_repo, stock_movement_repo
from app.core.dependencies import ensure_any_permission, get_current_user
from app.schemas.stock_item import StockItemCreate, StockItemResponse, StockItemUpdate

router = APIRouter(prefix="/stock-items", tags=["stock-items"])

_VIEW_STOCK = {"gestionar_stock", "gestionar_reactivos_quimicos", "gestionar_reservas_materiales"}
_MANAGE_STOCK = {"gestionar_stock", "gestionar_reactivos_quimicos"}
_MOVE_STOCK = {"gestionar_stock", "gestionar_reactivos_quimicos", "gestionar_reservas_materiales"}


class StockMovementCreate(BaseModel):
    movement_type: str  # entry | return | consumption
    quantity: int
    notes: str = ""


class StockMovementResponse(BaseModel):
    id: str
    stock_item_id: str
    stock_item_name: str
    movement_type: str
    quantity_change: int
    quantity_after: int
    performed_by: str
    notes: str
    created_at: str


@router.get("", response_model=list[StockItemResponse])
def list_stock_items(current_user: dict = Depends(get_current_user)) -> list[StockItemResponse]:
    ensure_any_permission(current_user, _VIEW_STOCK, "No tienes permisos para consultar el inventario de materiales")
    return stock_item_repo.list_all()


@router.get("/movements", response_model=list[StockMovementResponse])
def list_movements(
    limit: int = Query(default=40, ge=1, le=200),
    stock_item_id: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> list[StockMovementResponse]:
    ensure_any_permission(current_user, _VIEW_STOCK, "No tienes permisos para consultar movimientos de materiales")
    records = stock_movement_repo.list_recent(limit=limit, stock_item_id=stock_item_id)
    return [
        StockMovementResponse(
            id=r.id,
            stock_item_id=r.stock_item_id,
            stock_item_name=r.stock_item_name,
            movement_type=r.movement_type,
            quantity_change=r.quantity_change,
            quantity_after=r.quantity_after,
            performed_by=r.performed_by,
            notes=r.notes,
            created_at=r.created_at,
        )
        for r in records
    ]


@router.post("/{item_id}/movements", response_model=StockMovementResponse, status_code=status.HTTP_201_CREATED)
def create_movement(
    item_id: str,
    body: StockMovementCreate,
    current_user: dict = Depends(get_current_user),
) -> StockMovementResponse:
    ensure_any_permission(current_user, _MOVE_STOCK, "No tienes permisos para registrar movimientos de stock")
    item = stock_item_repo.get_by_id(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stock item no encontrado")

    if body.movement_type in ("entry", "return"):
        change = body.quantity
    else:
        change = -body.quantity

    new_qty = max(0, item.quantity_available + change)
    stock_item_repo.update(item_id, StockItemUpdate(quantity_available=new_qty))

    performed_by = str(current_user.get("username") or "sistema")

    record = stock_movement_repo.create(
        stock_item_id=item_id,
        stock_item_name=item.name,
        movement_type=body.movement_type,
        quantity_change=change,
        quantity_after=new_qty,
        performed_by=performed_by,
        notes=body.notes or "",
    )

    return StockMovementResponse(
        id=record.id,
        stock_item_id=record.stock_item_id,
        stock_item_name=record.stock_item_name,
        movement_type=record.movement_type,
        quantity_change=record.quantity_change,
        quantity_after=record.quantity_after,
        performed_by=record.performed_by,
        notes=record.notes,
        created_at=record.created_at,
    )


@router.get("/{item_id}", response_model=StockItemResponse)
def get_stock_item(item_id: str, current_user: dict = Depends(get_current_user)) -> StockItemResponse:
    ensure_any_permission(current_user, _VIEW_STOCK, "No tienes permisos para consultar materiales")
    item = stock_item_repo.get_by_id(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stock item no encontrado")
    return item


@router.post("", response_model=StockItemResponse, status_code=status.HTTP_201_CREATED)
def create_stock_item(body: StockItemCreate, current_user: dict = Depends(get_current_user)) -> StockItemResponse:
    ensure_any_permission(current_user, _MANAGE_STOCK, "No tienes permisos para registrar materiales")
    return stock_item_repo.create(body)


@router.patch("/{item_id}", response_model=StockItemResponse)
@router.put("/{item_id}", response_model=StockItemResponse)
def update_stock_item(item_id: str, body: StockItemUpdate, current_user: dict = Depends(get_current_user)) -> StockItemResponse:
    ensure_any_permission(current_user, _MANAGE_STOCK, "No tienes permisos para modificar materiales")
    item = stock_item_repo.update(item_id, body)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stock item no encontrado")
    return item


@router.patch("/{item_id}/quantity", response_model=StockItemResponse)
def update_stock_item_quantity(item_id: str, body: dict, current_user: dict = Depends(get_current_user)) -> StockItemResponse:
    ensure_any_permission(current_user, _MOVE_STOCK, "No tienes permisos para ajustar cantidades de stock")
    qty = body.get("quantity_available")
    if qty is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Se requiere quantity_available")
    item = stock_item_repo.update(item_id, StockItemUpdate(quantity_available=int(qty)))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stock item no encontrado")
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stock_item(item_id: str, current_user: dict = Depends(get_current_user)) -> None:
    ensure_any_permission(current_user, _MANAGE_STOCK, "No tienes permisos para eliminar materiales")
    deleted = stock_item_repo.delete(item_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stock item no encontrado")
