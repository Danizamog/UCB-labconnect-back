import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.application.container import lab_block_repo
from app.api.v1.endpoints.availability import invalidate_availability_cache
from app.core.datetime_utils import extract_iso_date
from app.core.dependencies import ensure_any_permission, get_current_user
from app.realtime.manager import realtime_manager
from app.schemas.lab_block import LabBlockCreate, LabBlockResponse, LabBlockUpdate

router = APIRouter(prefix="/lab-blocks", tags=["lab-blocks"])


def _block_day(block: LabBlockResponse) -> str:
    return extract_iso_date(block.start_at)


def _invalidate_block_availability(block: LabBlockResponse) -> None:
    invalidate_availability_cache(block.laboratory_id, _block_day(block))


@router.get("", response_model=list[LabBlockResponse])
async def list_blocks(_: dict = Depends(get_current_user)) -> list[LabBlockResponse]:
    return await asyncio.to_thread(lab_block_repo.list_all)


@router.post("", response_model=LabBlockResponse, status_code=status.HTTP_201_CREATED)
async def create_block(body: LabBlockCreate, current_user: dict = Depends(get_current_user)) -> LabBlockResponse:
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No tienes permisos para crear bloqueos",
    )
    payload = body.model_copy(update={"created_by": body.created_by or current_user.get("user_id") or ""})
    try:
        created = await asyncio.to_thread(lab_block_repo.create, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    _invalidate_block_availability(created)
    await realtime_manager.broadcast(
        {
            "topic": "lab_block",
            "action": "create",
            "record": created.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return created


@router.patch("/{block_id}", response_model=LabBlockResponse)
@router.put("/{block_id}", response_model=LabBlockResponse)
async def update_block(block_id: str, body: LabBlockUpdate, current_user: dict = Depends(get_current_user)) -> LabBlockResponse:
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No tienes permisos para actualizar bloqueos",
    )
    existing = await asyncio.to_thread(lab_block_repo.get_by_id, block_id)
    try:
        updated = await asyncio.to_thread(lab_block_repo.update, block_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bloqueo no encontrado")

    if existing is not None and (
        existing.laboratory_id != updated.laboratory_id or _block_day(existing) != _block_day(updated)
    ):
        _invalidate_block_availability(existing)
    _invalidate_block_availability(updated)
    await realtime_manager.broadcast(
        {
            "topic": "lab_block",
            "action": "update",
            "record": updated.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return updated


@router.delete("/{block_id}", response_class=Response)
async def delete_block(block_id: str, current_user: dict = Depends(get_current_user)) -> None:
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No tienes permisos para eliminar bloqueos",
    )
    existing = await asyncio.to_thread(lab_block_repo.get_by_id, block_id)
    deleted = await asyncio.to_thread(lab_block_repo.delete, block_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bloqueo no encontrado")

    if existing is not None:
        _invalidate_block_availability(existing)
    await realtime_manager.broadcast(
        {
            "topic": "lab_block",
            "action": "delete",
            "record": {"id": block_id},
            "at": datetime.utcnow().isoformat(),
        }
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
