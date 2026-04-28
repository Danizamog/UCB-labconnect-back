import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.application.container import lab_schedule_repo
from app.core.dependencies import ensure_any_permission, get_current_user
from app.realtime.manager import realtime_manager
from app.schemas.lab_schedule import LabScheduleCreate, LabScheduleResponse, LabScheduleUpdate

router = APIRouter(prefix="/lab-schedules", tags=["lab-schedules"])


@router.get("", response_model=list[LabScheduleResponse])
def list_schedules(_: dict = Depends(get_current_user)) -> list[LabScheduleResponse]:
    return lab_schedule_repo.list_all()


@router.post("", response_model=LabScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(body: LabScheduleCreate, current_user: dict = Depends(get_current_user)) -> LabScheduleResponse:
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No tienes permisos para crear horarios",
    )
    try:
        created = await asyncio.to_thread(lab_schedule_repo.create, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    await realtime_manager.broadcast(
        {
            "topic": "lab_schedule",
            "action": "create",
            "record": created.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return created


@router.patch("/{schedule_id}", response_model=LabScheduleResponse)
@router.put("/{schedule_id}", response_model=LabScheduleResponse)
async def update_schedule(
    schedule_id: str,
    body: LabScheduleUpdate,
    current_user: dict = Depends(get_current_user),
) -> LabScheduleResponse:
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No tienes permisos para actualizar horarios",
    )
    try:
        updated = await asyncio.to_thread(lab_schedule_repo.update, schedule_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Horario no encontrado")

    await realtime_manager.broadcast(
        {
            "topic": "lab_schedule",
            "action": "update",
            "record": updated.model_dump(),
            "at": datetime.utcnow().isoformat(),
        }
    )
    return updated


@router.delete("/{schedule_id}", response_class=Response)
async def delete_schedule(schedule_id: str, current_user: dict = Depends(get_current_user)) -> None:
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No tienes permisos para eliminar horarios",
    )
    deleted = await asyncio.to_thread(lab_schedule_repo.delete, schedule_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Horario no encontrado")

    await realtime_manager.broadcast(
        {
            "topic": "lab_schedule",
            "action": "delete",
            "record": {"id": schedule_id},
            "at": datetime.utcnow().isoformat(),
        }
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
