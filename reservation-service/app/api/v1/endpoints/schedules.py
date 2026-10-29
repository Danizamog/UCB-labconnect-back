import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import ValidationError

from app.application.container import lab_schedule_repo, lab_reservation_repo, tutorial_session_repo, lab_block_repo
from app.application.laboratory_access import ensure_user_can_reserve_laboratory
from app.api.v1.endpoints.availability import invalidate_availability_cache
from app.core.dependencies import ensure_any_permission, get_current_user
from app.core.datetime_utils import now_local_naive, parse_timestamp_to_local_naive
from app.core.locks import laboratory_lock_registry
from app.realtime.manager import realtime_manager
from app.schemas.lab_schedule import LabScheduleApproval, LabScheduleCreate, LabScheduleResponse, LabScheduleUpdate

router = APIRouter(prefix="/lab-schedules", tags=["lab-schedules"])


def _has_permission(user: dict, permission: str) -> bool:
    return permission in set(user.get("permissions") or [])


def _ensure_editor(user: dict, existing: LabScheduleResponse | None = None) -> bool:
    manager = _has_permission(user, "gestionar_horarios_laboratorio")
    if not manager:
        ensure_any_permission(user, {"gestionar_clases_propias"}, "No tienes permisos para gestionar clases propias")
        if existing and existing.teacher_id != str(user.get("user_id") or ""):
            raise HTTPException(status_code=403, detail="Solo puedes gestionar tus propias clases")
    return manager


async def _ensure_no_conflicts(candidate: LabScheduleResponse | LabScheduleCreate, exclude_id: str = "") -> None:
    schedules = await asyncio.to_thread(
        lab_schedule_repo.list_active_for_laboratory_weekday, candidate.laboratory_id, candidate.weekday,
    )
    for other in schedules:
        if other.id != exclude_id and candidate.start_time < other.end_time and other.start_time < candidate.end_time:
            raise HTTPException(status_code=409, detail="El horario se superpone con una clase aprobada")
    # Un horario recurrente no puede invalidar reservas o tutorias ya aprobadas.
    reservations = await asyncio.to_thread(lab_reservation_repo.list_all)
    tutorials = await asyncio.to_thread(tutorial_session_repo.list_all, laboratory_id=candidate.laboratory_id)
    blocks = await asyncio.to_thread(lab_block_repo.list_all)
    for other in [*reservations, *tutorials, *blocks]:
        if other.laboratory_id != candidate.laboratory_id or not getattr(other, "is_active", True):
            continue
        state = getattr(other, "approval_status", getattr(other, "status", "approved"))
        if state not in {"approved", "in_progress"}:
            continue
        start = parse_timestamp_to_local_naive(other.start_at)
        end = parse_timestamp_to_local_naive(other.end_at)
        if end <= now_local_naive():
            continue
        day = start + timedelta(days=(candidate.weekday - start.weekday()) % 7)
        slot_start = day.replace(hour=int(candidate.start_time[:2]), minute=int(candidate.start_time[3:]), second=0, microsecond=0)
        slot_end = day.replace(hour=int(candidate.end_time[:2]), minute=int(candidate.end_time[3:]), second=0, microsecond=0)
        if slot_end <= start:
            slot_start += timedelta(days=7)
            slot_end += timedelta(days=7)
        if slot_start < end and start < slot_end:
            raise HTTPException(status_code=409, detail="El horario se superpone con una reserva, tutoria o bloqueo vigente")


@router.get("", response_model=list[LabScheduleResponse])
async def list_schedules(
    laboratory_id: str | None = Query(default=None),
    weekday: int | None = Query(default=None, ge=0, le=6),
    teacher_id: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> list[LabScheduleResponse]:
    # "mine" resuelve al docente autenticado para que pueda ver sus clases sin
    # exponer el id de otros usuarios.
    if teacher_id == "me" or teacher_id == "mine":
        teacher_id = str(current_user.get("user_id") or "")
    if teacher_id:
        own_id = str(current_user.get("user_id") or "")
        if teacher_id == own_id:
            ensure_any_permission(current_user, {"gestionar_clases_propias", "solicitar_recursos_clase"}, "No tienes permisos para consultar clases propias")
        elif not _has_permission(current_user, "gestionar_horarios_laboratorio"):
            raise HTTPException(status_code=403, detail="Solo puedes consultar tus propias clases")
        return await asyncio.to_thread(lab_schedule_repo.list_for_teacher, teacher_id)
    if laboratory_id and weekday is not None:
        return await asyncio.to_thread(
            lab_schedule_repo.list_active_for_laboratory_weekday, laboratory_id, weekday
        )
    records = await asyncio.to_thread(lab_schedule_repo.list_for_laboratory, laboratory_id) if laboratory_id else await asyncio.to_thread(lab_schedule_repo.list_all)
    if _has_permission(current_user, "gestionar_horarios_laboratorio"):
        return records
    return [item for item in records if item.is_active and item.approval_status == "approved"]


@router.get("/pending", response_model=list[LabScheduleResponse])
async def list_pending_classes(current_user: dict = Depends(get_current_user)) -> list[LabScheduleResponse]:
    ensure_any_permission(current_user, {"aprobar_clases"}, "No tienes permisos para aprobar clases")
    return await asyncio.to_thread(lab_schedule_repo.list_pending)


@router.patch("/{schedule_id}/approval", response_model=LabScheduleResponse)
async def approve_class(schedule_id: str, body: LabScheduleApproval, current_user: dict = Depends(get_current_user)) -> LabScheduleResponse:
    ensure_any_permission(current_user, {"aprobar_clases"}, "Solo el administrador autorizado puede aprobar o rechazar clases")
    existing = await asyncio.to_thread(lab_schedule_repo.get_by_id, schedule_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Clase no encontrada")
    async with laboratory_lock_registry.lock(existing.laboratory_id):
        existing = await asyncio.to_thread(lab_schedule_repo.get_by_id, schedule_id)
        if not existing or existing.approval_status != "pending":
            raise HTTPException(status_code=409, detail="La clase ya no esta pendiente de aprobacion")
        if body.status == "approved":
            ensure_user_can_reserve_laboratory(existing.laboratory_id, current_user, approval=True)
            await _ensure_no_conflicts(existing, exclude_id=existing.id)
        updated = await asyncio.to_thread(lab_schedule_repo.update, schedule_id, LabScheduleUpdate(
            approval_status=body.status, approval_reason=body.reason,
            approved_by=str(current_user.get("user_id") or ""), approved_at=datetime.utcnow().isoformat(),
            is_active=body.status == "approved",
        ))
    invalidate_availability_cache(existing.laboratory_id)
    await realtime_manager.broadcast({"topic": "lab_schedule", "action": "update", "record": updated.model_dump(), "at": datetime.utcnow().isoformat()})
    return updated


@router.post("", response_model=LabScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(body: LabScheduleCreate, current_user: dict = Depends(get_current_user)) -> LabScheduleResponse:
    manager = _ensure_editor(current_user)
    ensure_user_can_reserve_laboratory(body.laboratory_id, current_user)
    # La identidad y el estado de aprobacion se deciden en el servidor.
    approved = manager and _has_permission(current_user, "aprobar_clases")
    body = body.model_copy(update={
        "teacher_id": body.teacher_id if manager else str(current_user.get("user_id") or ""),
        "teacher_name": body.teacher_name if manager else str(current_user.get("name") or current_user.get("username") or ""),
        "approval_status": "approved" if approved else "pending", "is_active": approved,
        "approval_reason": "", "approved_by": str(current_user.get("user_id") or "") if approved else "",
        "approved_at": datetime.utcnow().isoformat() if approved else "",
    })
    try:
        async with laboratory_lock_registry.lock(body.laboratory_id):
            if approved:
                await _ensure_no_conflicts(body)
            created = await asyncio.to_thread(lab_schedule_repo.create, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    invalidate_availability_cache(created.laboratory_id)
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
    existing = await asyncio.to_thread(lab_schedule_repo.get_by_id, schedule_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Clase no encontrada")
    manager = _ensure_editor(current_user, existing)
    proposed = existing.model_dump()
    proposed.update(body.model_dump(exclude_none=True))
    # Validar el rango combinado tambien cuando PATCH solo cambia una hora.
    try:
        candidate = LabScheduleCreate(**{key: value for key, value in proposed.items() if key in LabScheduleCreate.model_fields})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Revisa el rango horario de la clase") from exc
    ensure_user_can_reserve_laboratory(candidate.laboratory_id, current_user)
    approved = manager and _has_permission(current_user, "aprobar_clases") and existing.approval_status == "approved"
    changes = body.model_dump(exclude_none=True)
    changes.update(approval_status="approved" if approved else "pending", is_active=bool(changes.get("is_active", existing.is_active)) if approved else False,
                   approval_reason="", approved_by=str(current_user.get("user_id") or "") if approved else "", approved_at=datetime.utcnow().isoformat() if approved else "")
    if not manager:
        changes.update(teacher_id=str(current_user.get("user_id") or ""), teacher_name=existing.teacher_name)
    try:
        async with laboratory_lock_registry.lock(candidate.laboratory_id):
            if approved and changes["is_active"]:
                await _ensure_no_conflicts(candidate, exclude_id=schedule_id)
            updated = await asyncio.to_thread(lab_schedule_repo.update, schedule_id, LabScheduleUpdate(**changes))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Horario no encontrado")

    if existing is not None and existing.laboratory_id != updated.laboratory_id:
        invalidate_availability_cache(existing.laboratory_id)
    invalidate_availability_cache(updated.laboratory_id)
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
    existing = await asyncio.to_thread(lab_schedule_repo.get_by_id, schedule_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Clase no encontrada")
    _ensure_editor(current_user, existing)
    deleted = await asyncio.to_thread(lab_schedule_repo.delete, schedule_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Horario no encontrado")

    if existing is not None:
        invalidate_availability_cache(existing.laboratory_id)
    await realtime_manager.broadcast(
        {
            "topic": "lab_schedule",
            "action": "delete",
            "record": {"id": schedule_id},
            "at": datetime.utcnow().isoformat(),
        }
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
