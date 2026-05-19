import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.application.container import stock_item_repo, stock_movement_repo
from app.core.dependencies import ensure_any_permission, get_current_user
from app.core.laboratory_access import is_lab_in_scope, resolve_accessible_lab_ids
from app.core.locks import stock_item_lock_registry
from app.schemas.stock_item import StockItemCreate, StockItemResponse, StockItemUpdate, StockItemQuantityUpdate


def _extract_pocketbase_error(exc: Exception) -> str:
    if not isinstance(exc, httpx.HTTPStatusError):
        return str(exc)
    try:
        body = exc.response.json()
    except ValueError:
        return f"{exc.response.status_code}: {exc.response.text[:500]}"
    if not isinstance(body, dict):
        return str(body)
    message = str(body.get("message") or "").strip()
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    field_errors = []
    for field_name, info in data.items():
        if isinstance(info, dict):
            field_errors.append(f"{field_name}={info.get('message') or info.get('code')}")
    detail = message or f"HTTP {exc.response.status_code}"
    if field_errors:
        detail = f"{detail} ({'; '.join(field_errors)})"
    return detail


router = APIRouter(prefix="/stock-items", tags=["stock-items"])

_VIEW_STOCK = {"gestionar_stock", "gestionar_reactivos_quimicos", "gestionar_reservas_materiales"}
_MANAGE_STOCK = {"gestionar_stock", "gestionar_reactivos_quimicos"}
_MOVE_STOCK = {"gestionar_stock", "gestionar_reactivos_quimicos", "gestionar_reservas_materiales"}

_OUT_OF_SCOPE_DETAIL = "Stock item no encontrado"
_OUT_OF_SCOPE_LAB_DETAIL = "Solo puedes operar sobre materiales de tus laboratorios asignados"


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


def _filter_items_in_scope(items, accessible: list[str] | None) -> list[StockItemResponse]:
    if accessible is None:
        return items
    return [item for item in items if is_lab_in_scope(item.laboratory_id, accessible)]


@router.get("", response_model=list[StockItemResponse])
def list_stock_items(
    laboratory_id: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> list[StockItemResponse]:
    requested_lab = str(laboratory_id or "").strip()

    if requested_lab:
        # Catalogo publico por laboratorio: cualquier usuario autenticado puede verlo
        # para poder seleccionar materiales al hacer una reserva o tutoria.
        return stock_item_repo.list_by_laboratories([requested_lab])

    ensure_any_permission(current_user, _VIEW_STOCK, "No tienes permisos para consultar el inventario de materiales")
    accessible = resolve_accessible_lab_ids(current_user)
    if accessible is None:
        return stock_item_repo.list_all()
    if not accessible:
        return []
    return stock_item_repo.list_by_laboratories(list(accessible))


@router.get("/movements", response_model=list[StockMovementResponse])
def list_movements(
    limit: int = Query(default=40, ge=1, le=200),
    stock_item_id: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> list[StockMovementResponse]:
    ensure_any_permission(current_user, _VIEW_STOCK, "No tienes permisos para consultar movimientos de materiales")
    accessible = resolve_accessible_lab_ids(current_user)
    if accessible is not None:
        # Filtramos los movimientos a items dentro del alcance del usuario.
        in_scope_ids = {
            str(item.id)
            for item in stock_item_repo.list_all()
            if is_lab_in_scope(item.laboratory_id, accessible)
        }
        if stock_item_id is not None and str(stock_item_id) not in in_scope_ids:
            return []
    else:
        in_scope_ids = None

    records = stock_movement_repo.list_recent(limit=limit, stock_item_id=stock_item_id)
    if in_scope_ids is not None:
        records = [r for r in records if str(r.stock_item_id) in in_scope_ids]
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
    print(f"[DEBUG] create_movement called for {item_id} with body: {body.model_dump()}")
    if body.quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La cantidad del movimiento debe ser mayor a cero",
        )

    accessible = resolve_accessible_lab_ids(current_user)

    with stock_item_lock_registry.lock(item_id):
        item = stock_item_repo.get_by_id_fresh(item_id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
        if not is_lab_in_scope(item.laboratory_id, accessible):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)

        if body.movement_type in ("entry", "return"):
            change = body.quantity
        else:
            change = -body.quantity
            # Validar limite_reserva_usuario si es consumo
            if body.movement_type == "consumption":
                limit = item.limite_reserva_usuario
                if limit is not None and limit > 0 and body.quantity > limit:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Has superado la cantidad maxima permitida ({limit}) para este insumo",
                    )

            if item.quantity_available + change < 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Stock insuficiente para el movimiento. Disponible: {item.quantity_available}, "
                        f"solicitado: {body.quantity}."
                    ),
                )
        new_qty = item.quantity_available + change
        updated_item = stock_item_repo.update(item_id, StockItemUpdate(quantity_available=new_qty))
        if updated_item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)

        performed_by = str(current_user.get("username") or "sistema")
        # stock_movement.stock_item_name es required en PocketBase; evitamos enviar ""
        # que algunas versiones rechazan como vacio para campos required.
        movement_item_name = (item.name or "").strip() or f"Material {item_id}"

        try:
            record = stock_movement_repo.create(
                stock_item_id=item_id,
                stock_item_name=movement_item_name,
                movement_type=body.movement_type,
                quantity_change=change,
                quantity_after=new_qty,
                performed_by=performed_by,
                notes=body.notes or "",
            )
        except Exception as movement_error:
            # Saga: el stock ya se actualizo en PB pero el movimiento fallo.
            # Revertimos para no dejar el inventario inconsistente.
            try:
                stock_item_repo.update(
                    item_id,
                    StockItemUpdate(quantity_available=item.quantity_available),
                )
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"No se pudo registrar el movimiento (PocketBase): {_extract_pocketbase_error(movement_error)}",
            ) from movement_error

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    accessible = resolve_accessible_lab_ids(current_user)
    if not is_lab_in_scope(item.laboratory_id, accessible):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    return item


@router.post("", response_model=StockItemResponse, status_code=status.HTTP_201_CREATED)
def create_stock_item(body: StockItemCreate, current_user: dict = Depends(get_current_user)) -> StockItemResponse:
    print(f"[DEBUG] Endpoint create_stock_item received body: {body.model_dump()}")
    ensure_any_permission(current_user, _MANAGE_STOCK, "No tienes permisos para registrar materiales")
    accessible = resolve_accessible_lab_ids(current_user)
    if not is_lab_in_scope(body.laboratory_id, accessible):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_OUT_OF_SCOPE_LAB_DETAIL)
    return stock_item_repo.create(body)


@router.patch("/{item_id}", response_model=StockItemResponse)
@router.put("/{item_id}", response_model=StockItemResponse)
def update_stock_item(item_id: str, body: StockItemUpdate, current_user: dict = Depends(get_current_user)) -> StockItemResponse:
    print(f"[DEBUG] update_stock_item called for {item_id}. Body: {body.model_dump()}")
    ensure_any_permission(current_user, _MANAGE_STOCK, "No tienes permisos para modificar materiales")
    accessible = resolve_accessible_lab_ids(current_user)
    existing = stock_item_repo.get_by_id(item_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    
    print(f"[DEBUG] Existing stock: {existing.quantity_available}, Limit: {existing.limite_reserva_usuario}")
    
    # Validar limite_reserva_usuario si se está actualizando la cantidad
    if body.quantity_available is not None and existing.limite_reserva_usuario is not None and existing.limite_reserva_usuario > 0:
        if body.quantity_available < existing.quantity_available:
            cantidad_a_consumir = existing.quantity_available - body.quantity_available
            print(f"[DEBUG] Consumiendo {cantidad_a_consumir}. Limit: {existing.limite_reserva_usuario}")
            if cantidad_a_consumir > existing.limite_reserva_usuario:
                print(f"[DEBUG] Validation failed! Consumed {cantidad_a_consumir} > {existing.limite_reserva_usuario}")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Has superado la cantidad maxima permitida ({existing.limite_reserva_usuario}) para este insumo",
                )
    
    if not is_lab_in_scope(existing.laboratory_id, accessible):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    if body.laboratory_id is not None and not is_lab_in_scope(body.laboratory_id, accessible):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_OUT_OF_SCOPE_LAB_DETAIL)
    
    item = stock_item_repo.update(item_id, body)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    return item


@router.patch("/{item_id}/quantity", response_model=StockItemResponse)
def update_stock_item_quantity(
    item_id: str,
    body: StockItemQuantityUpdate,
    current_user: dict = Depends(get_current_user),
) -> StockItemResponse:
    print(f"[DEBUG] update_stock_item_quantity called for {item_id} with body: {body.model_dump()}")
    ensure_any_permission(current_user, _MOVE_STOCK, "No tienes permisos para ajustar cantidades de stock")
    
    accessible = resolve_accessible_lab_ids(current_user)

    with stock_item_lock_registry.lock(item_id):
        existing = stock_item_repo.get_by_id_fresh(item_id)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
        if not is_lab_in_scope(existing.laboratory_id, accessible):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
            
        # Validación estricta del límite
        if existing.limite_reserva_usuario is not None and existing.limite_reserva_usuario > 0:
            # Si la nueva cantidad es menor que la actual, estamos "consumiendo"
            if body.quantity_available < existing.quantity_available:
                cantidad_a_consumir = existing.quantity_available - body.quantity_available
                if cantidad_a_consumir > existing.limite_reserva_usuario:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Has superado la cantidad maxima permitida ({existing.limite_reserva_usuario}) para este insumo",
                    )
                
        item = stock_item_repo.update(item_id, StockItemUpdate(quantity_available=body.quantity_available))
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stock_item(item_id: str, current_user: dict = Depends(get_current_user)) -> None:
    ensure_any_permission(current_user, _MANAGE_STOCK, "No tienes permisos para eliminar materiales")
    accessible = resolve_accessible_lab_ids(current_user)
    existing = stock_item_repo.get_by_id(item_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    if not is_lab_in_scope(existing.laboratory_id, accessible):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
    deleted = stock_item_repo.delete(item_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_OUT_OF_SCOPE_DETAIL)
