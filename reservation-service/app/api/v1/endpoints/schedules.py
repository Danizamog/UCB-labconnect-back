import asyncio
import httpx
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import ValidationError

from app.application.container import lab_schedule_repo, lab_reservation_repo, tutorial_session_repo, lab_block_repo
from app.application.laboratory_access import ensure_user_can_reserve_laboratory
from app.application.schedule_conflicts import weekly_windows, first_conflict
from app.api.v1.endpoints.availability import invalidate_availability_cache
from app.core.dependencies import ensure_any_permission, get_current_user
from app.core.datetime_utils import ACADEMIC_BLOCKS
from app.core.locks import laboratory_lock_registry
from app.realtime.manager import realtime_manager
from app.schemas.lab_schedule import LabScheduleApproval, LabScheduleCreate, LabScheduleResponse, LabScheduleUpdate

router = APIRouter(prefix="/lab-schedules", tags=["lab-schedules"])
EDITABLE = {"laboratory_id", "weekday", "start_time", "end_time", "subject", "description"}
SNAPSHOT_FIELDS = EDITABLE | {"id", "teacher_id", "teacher_name", "approval_status", "is_active", "updated"}


def _snapshot(schedule):
    return schedule.model_dump(include=SNAPSHOT_FIELDS)


def _has_permission(user: dict, permission: str) -> bool:
    return permission in set(user.get("permissions") or [])


def _ensure_editor(user: dict, existing: LabScheduleResponse | None = None) -> bool:
    manager = _has_permission(user, "gestionar_horarios_laboratorio")
    if not manager:
        ensure_any_permission(user, {"gestionar_clases_propias"}, "No tienes permisos para gestionar clases propias")
        if existing and existing.teacher_id != str(user.get("user_id") or ""):
            raise HTTPException(403, "Solo puedes gestionar tus propias clases")
    return manager


async def _windows(laboratory_id, weekday, exclude_id=""):
    classes, reservations, tutorials, blocks = await asyncio.gather(
        asyncio.to_thread(lab_schedule_repo.list_active_for_laboratory_weekday, laboratory_id, weekday),
        asyncio.to_thread(lab_reservation_repo.list_all),
        asyncio.to_thread(tutorial_session_repo.list_all, laboratory_id=laboratory_id),
        asyncio.to_thread(lab_block_repo.list_all),
    )
    events = [(source, item) for source, rows in (
        ("lab_reservation", reservations), ("tutorial_session", tutorials), ("lab_block", blocks)
    ) for item in rows]
    return weekly_windows(laboratory_id, weekday, classes, events, exclude_id)


async def _ensure_no_conflicts(candidate, exclude_id=""):
    conflict = first_conflict(candidate.start_time, candidate.end_time,
                              await _windows(candidate.laboratory_id, candidate.weekday, exclude_id))
    if conflict:
        when = f" ({conflict['date']})" if conflict["date"] else ""
        raise HTTPException(409, f"El horario se superpone con {conflict['label'].lower()}{when}")


def _decision(user, approval_status, reason=""):
    return dict(approval_status=approval_status, approval_reason=reason,
                approved_by=str(user.get("user_id") or ""), approved_at=datetime.utcnow().isoformat())


async def _broadcast(record, action="update"):
    if record is None:
        return
    await realtime_manager.broadcast({"topic": "lab_schedule", "action": action,
        "record": {"id": record.id, "laboratory_id": record.laboratory_id} if action == "delete" else record.model_dump(),
        "at": datetime.utcnow().isoformat()})


@router.get("", response_model=list[LabScheduleResponse])
async def list_schedules(laboratory_id: str | None = None, weekday: int | None = Query(None, ge=0, le=6),
                         teacher_id: str | None = None, current_user: dict = Depends(get_current_user)):
    if teacher_id in {"me", "mine"}:
        teacher_id = str(current_user.get("user_id") or "")
    if teacher_id:
        if teacher_id == str(current_user.get("user_id") or ""):
            ensure_any_permission(current_user, {"gestionar_clases_propias", "solicitar_recursos_clase"}, "No tienes permisos para consultar clases propias")
        elif not _has_permission(current_user, "gestionar_horarios_laboratorio"):
            raise HTTPException(403, "Solo puedes consultar tus propias clases")
        return await asyncio.to_thread(lab_schedule_repo.list_for_teacher, teacher_id)
    if laboratory_id and weekday is not None:
        return await asyncio.to_thread(lab_schedule_repo.list_active_for_laboratory_weekday, laboratory_id, weekday)
    records = await asyncio.to_thread(lab_schedule_repo.list_for_laboratory, laboratory_id) if laboratory_id else await asyncio.to_thread(lab_schedule_repo.list_all)
    if _has_permission(current_user, "gestionar_horarios_laboratorio"):
        return records
    return [item for item in records if item.is_active and item.approval_status == "approved" and not item.original_schedule_id]


@router.get("/availability")
async def weekly_availability(laboratory_id: str, weekday: int = Query(..., ge=0, le=6),
                              exclude_id: str = "", current_user: dict = Depends(get_current_user)):
    _ensure_editor(current_user)
    ensure_user_can_reserve_laboratory(laboratory_id, current_user)
    if exclude_id:
        existing = await asyncio.to_thread(lab_schedule_repo.get_by_id, exclude_id)
        if not existing:
            raise HTTPException(404, "Clase no encontrada")
        _ensure_editor(current_user, existing)
        exclude_id = existing.original_schedule_id or existing.id
    windows = await _windows(laboratory_id, weekday, exclude_id)
    return {"laboratory_id": laboratory_id, "weekday": weekday, "blocked_ranges": windows,
            "slots": [{"start_time": start, "end_time": end,
                       "state": "blocked" if (conflict := first_conflict(start, end, windows)) else "available",
                       "conflict": conflict} for start, end in ACADEMIC_BLOCKS]}


@router.get("/pending", response_model=list[LabScheduleResponse])
async def list_pending_classes(current_user: dict = Depends(get_current_user)):
    ensure_any_permission(current_user, {"aprobar_clases"}, "No tienes permisos para aprobar clases")
    records = await asyncio.to_thread(lab_schedule_repo.list_pending)
    async def with_current(item):
        if not item.original_schedule_id:
            return item
        original = await asyncio.to_thread(lab_schedule_repo.get_by_id, item.original_schedule_id)
        return item.model_copy(update={"current_schedule": _snapshot(original) if original else None,
            "source_changed": not original or _snapshot(original) != item.original_snapshot})
    return await asyncio.gather(*(with_current(item) for item in records))


@router.patch("/{schedule_id}/approval", response_model=LabScheduleResponse)
async def approve_class(schedule_id: str, body: LabScheduleApproval, current_user: dict = Depends(get_current_user)):
    ensure_any_permission(current_user, {"aprobar_clases"}, "No tienes permisos para aprobar clases")
    existing = await asyncio.to_thread(lab_schedule_repo.get_by_id, schedule_id)
    if not existing:
        raise HTTPException(404, "Clase no encontrada")
    async with laboratory_lock_registry.lock(f"schedule:{existing.original_schedule_id or schedule_id}"):
        existing = await asyncio.to_thread(lab_schedule_repo.get_by_id, schedule_id)
        if not existing or existing.approval_status != "pending":
            raise HTTPException(409, "La solicitud ya no esta pendiente de aprobacion")
        original = await asyncio.to_thread(lab_schedule_repo.get_by_id, existing.original_schedule_id) if existing.original_schedule_id else None
        async with laboratory_lock_registry.lock_many(existing.laboratory_id, original.laboratory_id if original else existing.laboratory_id):
            decision = _decision(current_user, body.status, body.reason)
            if body.status == "approved":
                ensure_user_can_reserve_laboratory(existing.laboratory_id, current_user, approval=True)
                if existing.teacher_id:
                    try:
                        await asyncio.to_thread(lab_schedule_repo.resolve_teacher, existing.teacher_id)
                    except ValueError as exc:
                        raise HTTPException(422, str(exc)) from exc
                if existing.original_schedule_id:
                    if not original or original.approval_status != "approved" or not original.is_active:
                        raise HTTPException(409, "La clase original ya no esta activa")
                    if _snapshot(original) != existing.original_snapshot:
                        raise HTTPException(409, "La clase original cambio. El docente debe actualizar su solicitud")
                    await _ensure_no_conflicts(existing, exclude_id=original.id)
                    try:
                        updated = await asyncio.to_thread(lab_schedule_repo.apply_change, existing, original, decision)
                    except (ValueError, httpx.HTTPError) as exc:
                        raise HTTPException(503, "No se pudo confirmar el cambio. Actualiza para comprobar su estado antes de reintentar") from exc
                else:
                    await _ensure_no_conflicts(existing, exclude_id=existing.id)
                    updated = await asyncio.to_thread(lab_schedule_repo.update, schedule_id, LabScheduleUpdate(**decision, is_active=True))
            else:
                updated = await asyncio.to_thread(lab_schedule_repo.update, schedule_id, LabScheduleUpdate(**decision, is_active=False))
    for lab_id in {existing.laboratory_id, original.laboratory_id if original else existing.laboratory_id}:
        invalidate_availability_cache(lab_id)
    if original and body.status == "approved":
        await _broadcast(await asyncio.to_thread(lab_schedule_repo.get_by_id, original.id))
    await _broadcast(updated)
    return updated


@router.post("", response_model=LabScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(body: LabScheduleCreate, current_user: dict = Depends(get_current_user)):
    manager = _ensure_editor(current_user)
    ensure_user_can_reserve_laboratory(body.laboratory_id, current_user)
    approved = manager and _has_permission(current_user, "aprobar_clases")
    try:
        teacher_name = await asyncio.to_thread(lab_schedule_repo.resolve_teacher, body.teacher_id) if manager else str(current_user.get("name") or current_user.get("username") or "")
        body = body.model_copy(update={
            "teacher_id": str(body.teacher_id or "") if manager else str(current_user.get("user_id") or ""),
            "teacher_name": teacher_name, "approval_status": "approved" if approved else "pending",
            "is_active": approved, "approval_reason": "", "original_schedule_id": "", "original_snapshot": {},
            "approved_by": str(current_user.get("user_id") or "") if approved else "",
            "approved_at": datetime.utcnow().isoformat() if approved else "",
        })
        async with laboratory_lock_registry.lock(body.laboratory_id):
            await _ensure_no_conflicts(body)
            created = await asyncio.to_thread(lab_schedule_repo.create, body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    invalidate_availability_cache(created.laboratory_id)
    await _broadcast(created, "create")
    return created


@router.patch("/{schedule_id}", response_model=LabScheduleResponse)
@router.put("/{schedule_id}", response_model=LabScheduleResponse)
async def update_schedule(schedule_id: str, body: LabScheduleUpdate, current_user: dict = Depends(get_current_user)):
    existing = await asyncio.to_thread(lab_schedule_repo.get_by_id, schedule_id)
    if not existing:
        raise HTTPException(404, "Clase no encontrada")
    manager = _ensure_editor(current_user, existing)
    async with laboratory_lock_registry.lock(f"schedule:{existing.original_schedule_id or schedule_id}"):
        existing = await asyncio.to_thread(lab_schedule_repo.get_by_id, schedule_id)
        if not existing:
            raise HTTPException(404, "Clase no encontrada")
        _ensure_editor(current_user, existing)
        if existing.original_schedule_id:
            raise HTTPException(409, "Actualiza la solicitud desde la clase original")
        proposed = existing.model_dump()
        previous = None
        if not manager and existing.approval_status == "approved":
            previous = await asyncio.to_thread(lab_schedule_repo.pending_change, schedule_id)
            if previous:
                proposed.update({key: getattr(previous, key) for key in EDITABLE})
        changes = {key: value for key, value in body.model_dump(exclude_none=True).items() if key in EDITABLE or (manager and key in {"teacher_id", "is_active"})}
        proposed.update(changes)
        try:
            candidate = LabScheduleCreate(**{key: value for key, value in proposed.items() if key in LabScheduleCreate.model_fields})
        except ValidationError as exc:
            raise HTTPException(422, "Revisa el rango horario de la clase") from exc
        ensure_user_can_reserve_laboratory(candidate.laboratory_id, current_user)
        try:
            if manager and "teacher_id" in changes:
                changes["teacher_name"] = await asyncio.to_thread(lab_schedule_repo.resolve_teacher, changes["teacher_id"])
            async with laboratory_lock_registry.lock_many(existing.laboratory_id, candidate.laboratory_id):
                await _ensure_no_conflicts(candidate, exclude_id=existing.id)
                if not manager and existing.approval_status == "approved":
                    if not existing.is_active:
                        raise HTTPException(409, "La clase original ya no esta activa")
                    proposal = candidate.model_copy(update={"original_schedule_id": schedule_id, "original_snapshot": _snapshot(existing),
                        "approval_status": "pending", "is_active": False, "approval_reason": "", "approved_by": "", "approved_at": ""})
                    updated = await asyncio.to_thread(lab_schedule_repo.save_change, previous, proposal)
                else:
                    approved = manager and _has_permission(current_user, "aprobar_clases") and existing.approval_status == "approved"
                    changes.update(_decision(current_user, "approved") if approved else dict(approval_status="pending", approval_reason="", approved_by="", approved_at=""))
                    changes["is_active"] = proposed["is_active"] if approved else False
                    updated = await asyncio.to_thread(lab_schedule_repo.update, schedule_id, LabScheduleUpdate(**changes))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    invalidate_availability_cache(existing.laboratory_id)
    invalidate_availability_cache(candidate.laboratory_id)
    await _broadcast(updated)
    return updated


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(schedule_id: str, current_user: dict = Depends(get_current_user)):
    existing = await asyncio.to_thread(lab_schedule_repo.get_by_id, schedule_id)
    if not existing:
        raise HTTPException(404, "Clase no encontrada")
    _ensure_editor(current_user, existing)
    async with laboratory_lock_registry.lock(f"schedule:{existing.original_schedule_id or schedule_id}"):
        existing = await asyncio.to_thread(lab_schedule_repo.get_by_id, schedule_id)
        if not existing:
            raise HTTPException(404, "Clase no encontrada")
        _ensure_editor(current_user, existing)
        if existing.original_schedule_id and existing.approval_status != "pending":
            raise HTTPException(409, "Solo puedes retirar solicitudes pendientes")
        async with laboratory_lock_registry.lock(existing.laboratory_id):
            await asyncio.to_thread(lab_schedule_repo.delete, schedule_id)
    invalidate_availability_cache(existing.laboratory_id)
    await _broadcast(existing, "delete")
    return Response(status_code=204)
