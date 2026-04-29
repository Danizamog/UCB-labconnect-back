from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.container import stock_item_repo, supply_reservation_repo
from app.core.dependencies import ensure_any_permission, get_current_user
from app.schemas.supply_reservation import (
    SupplyReservationCreate,
    SupplyReservationResponse,
    SupplyReservationStatusUpdate,
)

router = APIRouter(prefix="/supply-reservations", tags=["supply-reservations"])

_ALLOWED_STATUSES = {"pending", "approved", "delivered", "cancelled"}
_VIEW_SUPPLY_RESERVATIONS = {"gestionar_reservas_materiales", "gestionar_stock", "gestionar_reactivos_quimicos"}
_MANAGE_SUPPLY_RESERVATIONS = {"gestionar_reservas_materiales", "gestionar_stock", "gestionar_reactivos_quimicos"}


@router.get("", response_model=list[SupplyReservationResponse])
def list_supply_reservations(
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: dict = Depends(get_current_user),
) -> list[SupplyReservationResponse]:
    ensure_any_permission(current_user, _VIEW_SUPPLY_RESERVATIONS, "No tienes permisos para consultar reservas de insumos")
    reservations = supply_reservation_repo.list_all()
    if not status_filter:
        return reservations
    return [r for r in reservations if r.status == status_filter]


@router.get("/{reservation_id}", response_model=SupplyReservationResponse)
def get_supply_reservation(reservation_id: str, current_user: dict = Depends(get_current_user)) -> SupplyReservationResponse:
    ensure_any_permission(current_user, _VIEW_SUPPLY_RESERVATIONS, "No tienes permisos para consultar reservas de insumos")
    reservation = supply_reservation_repo.get_by_id(reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva de insumo no encontrada")
    return reservation


@router.post("", response_model=SupplyReservationResponse, status_code=status.HTTP_201_CREATED)
def create_supply_reservation(
    body: SupplyReservationCreate,
    current_user: dict = Depends(get_current_user),
) -> SupplyReservationResponse:
    stock_item = stock_item_repo.get_raw_by_id(body.stock_item_id)
    if stock_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo no encontrado")

    current_qty = int(stock_item.get("quantity_available") or 0)
    if body.quantity > current_qty:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No hay cantidad suficiente disponible para reservar",
        )

    remaining_qty = current_qty - body.quantity
    updated_item = stock_item_repo.update_available_quantity(body.stock_item_id, remaining_qty)
    if updated_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo no encontrado")

    payload = {
        "stock_item_id": body.stock_item_id,
        "quantity": body.quantity,
        "status": "pending",
        "requested_by": current_user.get("username", "sistema"),
        "requested_for": body.requested_for,
        "notes": body.notes,
    }

    try:
        return supply_reservation_repo.create(payload)
    except Exception:
        stock_item_repo.update_available_quantity(body.stock_item_id, current_qty)
        raise


@router.patch("/{reservation_id}/status", response_model=SupplyReservationResponse)
def update_supply_reservation_status(
    reservation_id: str,
    body: SupplyReservationStatusUpdate,
    current_user: dict = Depends(get_current_user),
) -> SupplyReservationResponse:
    ensure_any_permission(current_user, _MANAGE_SUPPLY_RESERVATIONS, "No tienes permisos para gestionar reservas de insumos")
    new_status = body.status.strip().lower()
    if new_status not in _ALLOWED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Estado invalido. Usa: {', '.join(sorted(_ALLOWED_STATUSES))}",
        )

    existing = supply_reservation_repo.get_by_id(reservation_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva de insumo no encontrada")

    if existing.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La reserva ya esta cancelada")

    if existing.status == new_status:
        return existing

    notes = existing.notes if body.notes is None else body.notes

    if new_status == "cancelled" and existing.status != "cancelled":
        stock_item = stock_item_repo.get_raw_by_id(existing.stock_item_id)
        if stock_item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo asociado no encontrado")
        current_qty = int(stock_item.get("quantity_available") or 0)
        stock_item_repo.update_available_quantity(existing.stock_item_id, current_qty + existing.quantity)

    updated = supply_reservation_repo.update(
        reservation_id,
        {
            "status": new_status,
            "notes": notes,
        },
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva de insumo no encontrada")
    return updated
