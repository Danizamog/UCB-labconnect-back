import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials

from app.application.container import _pb_client, stock_item_repo, stock_movement_repo, supply_reservation_repo
from app.core.config import settings
from app.core.dependencies import ensure_any_permission, get_current_user, security
from app.core.locks import stock_item_lock_registry
from app.schemas.supply_reservation import (
    SupplyReservationCreate,
    SupplyReservationResponse,
    SupplyReservationStatusUpdate,
)

router = APIRouter(prefix="/supply-reservations", tags=["supply-reservations"])
logger = logging.getLogger(__name__)
reservation_validation_client = httpx.Client(
    timeout=httpx.Timeout(5.0, connect=3.0),
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
)

_ALLOWED_STATUSES = {"pending", "approved", "delivered", "cancelled"}
_VIEW_SUPPLY_RESERVATIONS = {"gestionar_reservas_materiales", "gestionar_stock", "gestionar_reactivos_quimicos"}
_MANAGE_SUPPLY_RESERVATIONS = {"gestionar_reservas_materiales", "gestionar_stock", "gestionar_reactivos_quimicos"}
_TUTORIAL_SUPPLY_RESERVATIONS = {"gestionar_tutorias_propias"}


def _is_global_supply_manager(current_user: dict) -> bool:
    permissions = set(current_user.get("permissions") or [])
    return "*" in permissions or "gestionar_estructura_laboratorios" in permissions


def _managed_laboratory_ids(current_user: dict) -> set[str]:
    user_id = str(current_user.get("user_id") or "").strip()
    if not user_id:
        return set()
    result: set[str] = set()
    page = 1
    while True:
        payload = _pb_client.request(
            "GET", "/api/collections/laboratory/records",
            params={"page": page, "perPage": 200, "filter": f'manager = "{user_id}"'},
        )
        if not isinstance(payload, dict):
            return result
        result.update(str(item.get("id") or "") for item in payload.get("items", []) if isinstance(item, dict))
        if page >= int(payload.get("totalPages") or 1):
            return result
        page += 1


def _ensure_stock_item_scope(stock_item_id: str, current_user: dict) -> None:
    if _is_global_supply_manager(current_user):
        return
    stock_item = stock_item_repo.get_raw_by_id(stock_item_id)
    if not stock_item or str(stock_item.get("laboratory_id") or "") not in _managed_laboratory_ids(current_user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material no encontrado en tu laboratorio")

# Lock por stock_item para serializar la verificacion+descuento al aprobar y
# evitar que dos aprobaciones simultaneas descuenten dos veces sobre el mismo
# inventario. El registry libera la entrada cuando no quedan waiters.
# NOTA: solo es correcto con --workers=1 por servicio (lock in-proc).


@router.get("", response_model=list[SupplyReservationResponse])
def list_supply_reservations(
    status_filter: str | None = Query(default=None, alias="status"),
    tutorial_session_id: str | None = Query(default=None),
    stock_item_id: str | None = Query(default=None),
    lab_reservation_id: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> list[SupplyReservationResponse]:
    can_manage = _can_manage(current_user) or _can_manage_tutorial_supplies(current_user)
    requester_filter = None if can_manage else str(current_user.get("user_id") or current_user.get("username") or "")

    records = supply_reservation_repo.list_all(
        status_filter=status_filter,
        tutorial_session_id=tutorial_session_id,
        stock_item_id=stock_item_id,
        lab_reservation_id=lab_reservation_id,
        requested_by=requester_filter,
    )
    if _can_manage(current_user) and not _is_global_supply_manager(current_user):
        managed = _managed_laboratory_ids(current_user)
        return [record for record in records if record.laboratory_id in managed]
    return records


@router.get("/{reservation_id}", response_model=SupplyReservationResponse)
def get_supply_reservation(reservation_id: str, current_user: dict = Depends(get_current_user)) -> SupplyReservationResponse:
    reservation = supply_reservation_repo.get_by_id(reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva de insumo no encontrada")
    if _can_manage(current_user):
        _ensure_stock_item_scope(reservation.stock_item_id, current_user)
    if not _can_manage(current_user) and reservation.requested_by != str(current_user.get("user_id") or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta reserva")
    return reservation


def _get_owned_reference(path: str, *, token: str, current_user: dict, owner_field: str, resource_name: str) -> dict:
    base_url = settings.reservations_service_url.strip().rstrip("/")
    try:
        response = reservation_validation_client.get(
            f"{base_url}{path}",
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as exc:
        logger.warning("No se pudo validar la referencia %s: %s", resource_name, type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo validar el recurso asociado",
        ) from exc

    if response.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource_name} no encontrada")
    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La sesion ya no es valida")
    if response.status_code == status.HTTP_403_FORBIDDEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"No tienes acceso a la {resource_name.lower()}")
    if response.status_code >= 400:
        logger.warning("La validacion de %s respondio con estado %s", resource_name, response.status_code)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo validar el recurso asociado",
        )

    try:
        record = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo validar el recurso asociado",
        ) from exc
    if not isinstance(record, dict):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No se pudo validar el recurso asociado")

    owner_id = str(record.get(owner_field) or "").strip()
    current_user_id = str(current_user.get("user_id") or "").strip()
    if not current_user_id or owner_id != current_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"No tienes acceso a la {resource_name.lower()}")
    return record


@router.post("", response_model=SupplyReservationResponse, status_code=status.HTTP_201_CREATED)
def create_supply_reservation(
    body: SupplyReservationCreate,
    current_user: dict = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> SupplyReservationResponse:
    stock_item = stock_item_repo.get_raw_by_id(body.stock_item_id)
    if stock_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo no encontrado")

    limit_per_user = stock_item.get("limite_reserva_usuario")
    if limit_per_user is not None:
        try:
            limit_per_user = int(limit_per_user)
        except (TypeError, ValueError):
            limit_per_user = None
    if limit_per_user is not None and limit_per_user > 0 and body.quantity > limit_per_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Has superado la cantidad maxima permitida para este insumo",
        )

    # Materiales globales: cualquier reserva puede solicitar cualquier material sin importar
    # el laboratorio. Antes se exigia que el material perteneciera al lab seleccionado; esa
    # validacion se elimina para permitir un catalogo compartido entre laboratorios.

    current_qty = int(stock_item.get("quantity_available") or 0)
    if current_qty <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El material esta agotado",
        )

    # La solicitud queda pendiente y el descuento real ocurre al aprobarla.
    # Por eso aqui solo validamos contra el stock actual visible; si varias
    # solicitudes compiten por el mismo material, el encargado decide cuales
    # aprobar y la validacion fuerte de stock se hace en la aprobacion.
    if body.quantity > current_qty:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"No hay cantidad suficiente disponible para solicitar. "
                f"Disponible: {current_qty}, solicitado: {body.quantity}."
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
        _get_owned_reference(
            f"/v1/tutorial-sessions/{tutorial_session_id}",
            token=credentials.credentials,
            current_user=current_user,
            owner_field="tutor_id",
            resource_name="Tutoria",
        )
        payload["tutorial_session_id"] = tutorial_session_id

    lab_reservation_id = str(body.lab_reservation_id or "").strip()
    if lab_reservation_id:
        _get_owned_reference(
            f"/v1/reservations/{lab_reservation_id}",
            token=credentials.credentials,
            current_user=current_user,
            owner_field="requested_by",
            resource_name="Reserva",
        )
        payload["lab_reservation_id"] = lab_reservation_id

    recurrence = str(body.recurrence or "").strip().lower()
    if recurrence in {"once", "weekly"}:
        payload["recurrence"] = recurrence
        if recurrence == "weekly":
            recurrence_end_date = str(body.recurrence_end_date or "").strip()
            if recurrence_end_date:
                payload["recurrence_end_date"] = recurrence_end_date
    recurrence_group_id = str(body.recurrence_group_id or "").strip()
    if recurrence_group_id:
        payload["recurrence_group_id"] = recurrence_group_id

    return supply_reservation_repo.create(payload)


@router.patch("/{reservation_id}/status", response_model=SupplyReservationResponse)
async def update_supply_reservation_status(
    reservation_id: str,
    body: SupplyReservationStatusUpdate,
    current_user: dict = Depends(get_current_user),
) -> SupplyReservationResponse:
    ensure_any_permission(
        current_user,
        _MANAGE_SUPPLY_RESERVATIONS | _TUTORIAL_SUPPLY_RESERVATIONS,
        "No tienes permisos para gestionar reservas de insumos",
    )
    new_status = body.status.strip().lower()
    if new_status not in _ALLOWED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Estado invalido. Usa: {', '.join(sorted(_ALLOWED_STATUSES))}",
        )

    existing = supply_reservation_repo.get_by_id(reservation_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva de insumo no encontrada")
    if _can_manage(current_user):
        _ensure_stock_item_scope(existing.stock_item_id, current_user)

    if existing.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La reserva ya esta cancelada")

    if existing.status == new_status:
        return existing

    notes = existing.notes if body.notes is None else body.notes
    actor = str(current_user.get("username") or current_user.get("user_id") or "sistema")

    async with stock_item_lock_registry.lock(existing.stock_item_id):
        # Re-leer para tener la cantidad actual correcta tras el lock.
        stock_item = stock_item_repo.get_raw_by_id(existing.stock_item_id)
        if stock_item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo asociado no encontrado")
        current_qty = int(stock_item.get("quantity_available") or 0)
        stock_item_name = str(stock_item.get("name") or "")

        # Las solicitudes semanales (recurrentes) quedan AUTORIZADAS al aprobarse,
        # pero el stock no se descuenta de una vez: se entrega/consume cada semana
        # con los movimientos de stock normales. Asi el inventario no se vacia por
        # todo el semestre al dar una sola aprobacion.
        is_weekly = str(existing.recurrence or "").strip().lower() == "weekly"

        if new_status == "approved" and existing.status != "approved" and not is_weekly:
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

        elif new_status == "cancelled" and existing.status == "approved" and not is_weekly:
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

        # Estados restantes (pending->cancelled, approved->delivered, y toda
        # solicitud semanal) no tocan stock automaticamente.

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
    permissions = set(current_user.get("permissions") or [])
    return bool(permissions.intersection(_MANAGE_SUPPLY_RESERVATIONS))


def _can_manage_tutorial_supplies(current_user: dict) -> bool:
    permissions = set(current_user.get("permissions") or [])
    return bool(permissions.intersection(_TUTORIAL_SUPPLY_RESERVATIONS))
