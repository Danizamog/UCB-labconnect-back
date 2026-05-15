import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.container import stock_item_repo, stock_movement_repo, supply_reservation_repo
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

# Lock por stock_item para serializar la verificacion+descuento al aprobar y
# evitar que dos aprobaciones simultaneas descuenten dos veces sobre el mismo
# inventario. Mismo patron que reservation-service usa para reservas de lab.
_STOCK_ITEM_LOCKS: dict[str, asyncio.Lock] = {}
_STOCK_ITEM_LOCKS_GUARD = asyncio.Lock()


async def _stock_item_lock(stock_item_id: str) -> asyncio.Lock:
    key = str(stock_item_id or "").strip()
    async with _STOCK_ITEM_LOCKS_GUARD:
        lock = _STOCK_ITEM_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _STOCK_ITEM_LOCKS[key] = lock
        return lock


@router.get("", response_model=list[SupplyReservationResponse])
def list_supply_reservations(
    status_filter: str | None = Query(default=None, alias="status"),
    tutorial_session_id: str | None = Query(default=None),
    stock_item_id: str | None = Query(default=None),
    lab_reservation_id: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> list[SupplyReservationResponse]:
    can_manage = _can_manage(current_user)
    requester_filter = None if can_manage else str(current_user.get("user_id") or current_user.get("username") or "")

    return supply_reservation_repo.list_all(
        status_filter=status_filter,
        tutorial_session_id=tutorial_session_id,
        stock_item_id=stock_item_id,
        lab_reservation_id=lab_reservation_id,
        requested_by=requester_filter,
    )


@router.get("/{reservation_id}", response_model=SupplyReservationResponse)
def get_supply_reservation(reservation_id: str, current_user: dict = Depends(get_current_user)) -> SupplyReservationResponse:
    reservation = supply_reservation_repo.get_by_id(reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva de insumo no encontrada")
    if not _can_manage(current_user) and reservation.requested_by != (current_user.get("username") or current_user.get("user_id") or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta reserva")
    return reservation


@router.post("", response_model=SupplyReservationResponse, status_code=status.HTTP_201_CREATED)
def create_supply_reservation(
    body: SupplyReservationCreate,
    current_user: dict = Depends(get_current_user),
) -> SupplyReservationResponse:
    stock_item = stock_item_repo.get_raw_by_id(body.stock_item_id)
    if stock_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo no encontrado")

    item_lab_id = str(stock_item.get("laboratory_id") or "")
    requested_lab_id = str(body.laboratory_id or "").strip()
    if requested_lab_id and item_lab_id and requested_lab_id != item_lab_id:
        # PA 3: el material no pertenece al laboratorio que el usuario seleccionó.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El material no pertenece al laboratorio seleccionado",
        )

    current_qty = int(stock_item.get("quantity_available") or 0)
    if current_qty <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El material esta agotado",
        )

    # Reserva pesimista a nivel logico: el stock se descuenta solo al aprobar,
    # pero descontamos las reservas pendientes para no aceptar mas de lo que
    # realmente hay disponible.
    reserved_pending = supply_reservation_repo.sum_pending_quantity(body.stock_item_id)
    effective_available = max(0, current_qty - reserved_pending)
    if body.quantity > effective_available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"No hay cantidad suficiente disponible para reservar. "
                f"Disponible: {effective_available} (stock {current_qty}, reservado {reserved_pending})."
            ),
        )

    requested_by_id = str(current_user.get("user_id") or current_user.get("id") or "").strip()
    if not requested_by_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo identificar al usuario autenticado para registrar la reserva",
        )

    payload: dict = {
        "stock_item_id": body.stock_item_id,
        "quantity": body.quantity,
        "status": "pending",
        "requested_by": requested_by_id,
        "requested_for": body.requested_for or "",
        "notes": body.notes or "",
    }

    tutorial_session_id = str(body.tutorial_session_id or "").strip()
    if tutorial_session_id:
        payload["tutorial_session_id"] = tutorial_session_id

    lab_reservation_id = str(body.lab_reservation_id or "").strip()
    if lab_reservation_id:
        payload["lab_reservation_id"] = lab_reservation_id

    return supply_reservation_repo.create(payload)


@router.patch("/{reservation_id}/status", response_model=SupplyReservationResponse)
async def update_supply_reservation_status(
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
    actor = str(current_user.get("username") or current_user.get("user_id") or "sistema")

    lock = await _stock_item_lock(existing.stock_item_id)
    async with lock:
        # Re-leer para tener la cantidad actual correcta tras el lock.
        stock_item = stock_item_repo.get_raw_by_id(existing.stock_item_id)
        if stock_item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo asociado no encontrado")
        current_qty = int(stock_item.get("quantity_available") or 0)
        stock_item_name = str(stock_item.get("name") or "")

        if new_status == "approved" and existing.status != "approved":
            if existing.quantity > current_qty:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Stock insuficiente para aprobar. Disponible: {current_qty}, "
                        f"solicitado: {existing.quantity}."
                    ),
                )
            new_qty = current_qty - existing.quantity
            updated_item = stock_item_repo.update_available_quantity(existing.stock_item_id, new_qty)
            if updated_item is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo asociado no encontrado")
            stock_movement_repo.create(
                stock_item_id=existing.stock_item_id,
                stock_item_name=stock_item_name,
                movement_type="consumption",
                quantity_change=-existing.quantity,
                quantity_after=new_qty,
                performed_by=actor,
                notes=f"Aprobacion de reserva {reservation_id}",
            )

        elif new_status == "cancelled" and existing.status == "approved":
            # Reponer stock que se habia descontado al aprobar.
            new_qty = current_qty + existing.quantity
            updated_item = stock_item_repo.update_available_quantity(existing.stock_item_id, new_qty)
            if updated_item is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo asociado no encontrado")
            stock_movement_repo.create(
                stock_item_id=existing.stock_item_id,
                stock_item_name=stock_item_name,
                movement_type="return",
                quantity_change=existing.quantity,
                quantity_after=new_qty,
                performed_by=actor,
                notes=f"Cancelacion de reserva aprobada {reservation_id}",
            )

        # Estados restantes (pending->cancelled, approved->delivered) no tocan stock.

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


def _can_manage(current_user: dict) -> bool:
    role = str(current_user.get("role") or "").strip().lower()
    if role in {"admin", "administrador"}:
        return True
    permissions = set(current_user.get("permissions") or [])
    if "*" in permissions:
        return True
    return bool(permissions.intersection(_MANAGE_SUPPLY_RESERVATIONS))
