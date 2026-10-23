import asyncio
import threading
from calendar import monthrange
from datetime import datetime, timedelta
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.container import lab_block_repo, lab_reservation_repo, lab_schedule_repo, tutorial_session_repo
from app.application.laboratory_access import ensure_user_can_reserve_laboratory
from app.core.datetime_utils import (
    ACADEMIC_BLOCK_MINUTES,
    combine_date_time,
    extract_iso_date,
    format_time,
    iter_lab_blocks,
    iter_time_ranges,
    now_local_naive,
    parse_datetime,
)
from app.core.dependencies import get_current_user
from app.schemas.availability import AvailabilitySlot, LabAvailabilityResponse, LabAvailabilityWeekResponse

router = APIRouter(prefix="/availability", tags=["availability"])

_AVAILABILITY_CACHE: dict[str, tuple[float, LabAvailabilityResponse]] = {}
_AVAILABILITY_CACHE_MAX_ITEMS = 250
_AVAILABILITY_CACHE_TTL_TODAY = 60
_AVAILABILITY_CACHE_TTL_OTHER = 120


def _run_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, object] = {}

    def _runner() -> None:
        result["value"] = asyncio.run(coro)

    thread = threading.Thread(target=_runner)
    thread.start()
    thread.join()
    return result["value"]


def _max_allowed_reservation_date(base_day):
    next_month = base_day.month + 1
    year = base_day.year
    if next_month > 12:
        next_month = 1
        year += 1

    day = min(base_day.day, monthrange(year, next_month)[1])
    return base_day.replace(year=year, month=next_month, day=day)


def _has_overlap(slot_start: datetime, slot_end: datetime, event_start_raw: str, event_end_raw: str) -> bool:
    event_start = parse_datetime(event_start_raw)
    event_end = parse_datetime(event_end_raw)
    return slot_start < event_end and event_start < slot_end


def _cache_key(laboratory_id: str, day: str) -> str:
    return f"{laboratory_id}:{day}"


def _get_cached_availability(laboratory_id: str, day: str) -> LabAvailabilityResponse | None:
    cached = _AVAILABILITY_CACHE.get(_cache_key(laboratory_id, day))
    if not cached:
        return None

    expires_at, response = cached
    if expires_at <= monotonic():
        _AVAILABILITY_CACHE.pop(_cache_key(laboratory_id, day), None)
        return None

    return response


def _set_cached_availability(laboratory_id: str, day: str, response: LabAvailabilityResponse, ttl_seconds: int) -> None:
    if len(_AVAILABILITY_CACHE) >= _AVAILABILITY_CACHE_MAX_ITEMS:
        oldest_key = next(iter(_AVAILABILITY_CACHE))
        _AVAILABILITY_CACHE.pop(oldest_key, None)

    _AVAILABILITY_CACHE[_cache_key(laboratory_id, day)] = (monotonic() + ttl_seconds, response)


def invalidate_availability_cache(laboratory_id: str | None, day: str | None = None) -> None:
    laboratory_id = str(laboratory_id or "").strip()
    if not laboratory_id:
        return

    if day:
        normalized_day = extract_iso_date(day) or str(day).strip()
        _AVAILABILITY_CACHE.pop(_cache_key(laboratory_id, normalized_day), None)
        return

    prefix = f"{laboratory_id}:"
    for key in list(_AVAILABILITY_CACHE.keys()):
        if key.startswith(prefix):
            _AVAILABILITY_CACHE.pop(key, None)


def _compute_slots_for_day(
    *,
    laboratory_id: str,
    current_date,
    current_local_time: datetime,
    raw_reservations: list,
    tutorial_sessions: list,
    blocks: list,
    classes: list,
) -> list[AvailabilitySlot]:
    raw_reservations = raw_reservations or []
    tutorial_sessions = tutorial_sessions or []
    blocks = blocks or []
    if classes is None:
        classes = []
    elif not isinstance(classes, list):
        classes = [classes]

    normalized_classes: list[tuple[datetime, datetime, object]] = []
    for klass in classes:
        if not getattr(klass, "subject", None):
            continue
        start_value = getattr(klass, "start_time", None) or getattr(klass, "open_time", None)
        end_value = getattr(klass, "end_time", None) or getattr(klass, "close_time", None)
        if start_value is None or end_value is None:
            continue
        try:
            normalized_classes.append((combine_date_time(current_date, start_value), combine_date_time(current_date, end_value), klass))
        except ValueError:
            continue

    schedule_source = next(iter(classes), None) if classes else None
    schedule_minutes = getattr(schedule_source, "slot_minutes", None)
    start_hint = getattr(schedule_source, "open_time", None)
    end_hint = getattr(schedule_source, "close_time", None)
    if classes:
        ranges = iter_lab_blocks(
            current_date,
            start_time=start_hint,
            end_time=end_hint,
            slot_minutes=schedule_minutes,
        )
    else:
        ranges = iter_time_ranges(
            combine_date_time(current_date, "08:00"),
            combine_date_time(current_date, "20:00"),
            60,
        )

    reservations = [
        item for item in raw_reservations or []
        if getattr(item, "status", None) in {"approved", "in_progress"}
        and getattr(item, "is_active", True)
    ]
    class_windows = normalized_classes

    slots: list[AvailabilitySlot] = []
    for start_dt, end_dt in ranges:
        state = "available"
        source = ""
        source_id = ""
        source_status = ""

        if state == "available":
            for class_start, class_end, klass in class_windows:
                if start_dt < class_end and class_start < end_dt:
                    state = "blocked"
                    source = "class"
                    source_id = getattr(klass, "id", "")
                    source_status = getattr(klass, "subject", "class")
                    break

        if state == "available":
            for block in blocks or []:
                if getattr(block, "is_active", True) is False:
                    continue
                block_start = getattr(block, "start_at", None)
                block_end = getattr(block, "end_at", None)
                if block_start is None or block_end is None:
                    continue
                try:
                    if _has_overlap(start_dt, end_dt, block_start, block_end):
                        state = "blocked"
                        source = "lab_block"
                        source_id = getattr(block, "id", "")
                        source_status = getattr(block, "block_type", "maintenance")
                        break
                except (TypeError, ValueError):
                    continue

        if state == "available":
            overlapping_res = [
                reservation for reservation in reservations
                if reservation.is_active and _has_overlap(start_dt, end_dt, reservation.start_at, reservation.end_at)
            ]
            overlapping_tut = [
                session for session in tutorial_sessions
                if _has_overlap(start_dt, end_dt, session.start_at, session.end_at)
            ]
            if overlapping_res or overlapping_tut:
                exclusive_res = next((r for r in overlapping_res if r.requires_full_lab), None)
                exclusive_tut = next(
                    (s for s in overlapping_tut if getattr(s, "requires_full_lab", True)), None
                )
                state = "occupied" if (exclusive_res or exclusive_tut) else "partial"
                # Fuente a mostrar: preferimos el ocupante exclusivo.
                if exclusive_res is not None:
                    source, source_id, source_status = "lab_reservation", exclusive_res.id, exclusive_res.status
                elif exclusive_tut is not None:
                    source, source_id, source_status = "tutorial_session", exclusive_tut.id, "published"
                elif overlapping_res:
                    source, source_id, source_status = "lab_reservation", overlapping_res[0].id, overlapping_res[0].status
                else:
                    source, source_id, source_status = "tutorial_session", overlapping_tut[0].id, "published"

        if state == "available" and (
            current_date < current_local_time.date() or (
                current_date == current_local_time.date() and start_dt <= current_local_time
            )
        ):
            state = "blocked"
            source = "system"
            source_status = "past"

        slots.append(
            AvailabilitySlot(
                start_time=format_time(start_dt),
                end_time=format_time(end_dt),
                state=state,
                source=source,
                source_id=source_id,
                status=source_status,
            )
        )
    return slots


@router.get("/labs/{laboratory_id}", response_model=LabAvailabilityResponse)
def get_lab_availability(
    laboratory_id: str,
    day: str = Query(..., description="Fecha en formato YYYY-MM-DD"),
    current_user: dict = Depends(get_current_user),
) -> LabAvailabilityResponse:
    async def _impl() -> LabAvailabilityResponse:
        try:
            current_date = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="day debe tener formato YYYY-MM-DD") from exc

        ensure_user_can_reserve_laboratory(laboratory_id, current_user)

        current_local_time = now_local_naive()
        max_allowed_day = _max_allowed_reservation_date(current_local_time.date())
        if current_date > max_allowed_day:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Solo puedes consultar disponibilidad dentro del plazo maximo de un mes",
            )

        cached_response = _get_cached_availability(laboratory_id, day)
        if cached_response is not None:
            return cached_response

        raw_reservations, tutorial_sessions, blocks, classes = await asyncio.gather(
            asyncio.to_thread(lab_reservation_repo.list_for_laboratory_day, laboratory_id, day),
            asyncio.to_thread(tutorial_session_repo.list_public_for_laboratory_day, laboratory_id, day),
            asyncio.to_thread(lab_block_repo.list_for_laboratory_day, laboratory_id, day),
            asyncio.to_thread(lab_schedule_repo.list_active_for_laboratory_weekday, laboratory_id, current_date.weekday()),
        )

        slots = _compute_slots_for_day(
            laboratory_id=laboratory_id,
            current_date=current_date,
            current_local_time=current_local_time,
            raw_reservations=raw_reservations,
            tutorial_sessions=tutorial_sessions,
            blocks=blocks,
            classes=classes,
        )

        response = LabAvailabilityResponse(
            laboratory_id=laboratory_id,
            date=day,
            slot_minutes=ACADEMIC_BLOCK_MINUTES,
            slots=slots,
        )
        cache_ttl_seconds = (
            _AVAILABILITY_CACHE_TTL_TODAY
            if current_date == current_local_time.date()
            else _AVAILABILITY_CACHE_TTL_OTHER
        )
        _set_cached_availability(laboratory_id, day, response, cache_ttl_seconds)
        return response

    return _run_sync(_impl())


@router.get("/labs/{laboratory_id}/week", response_model=LabAvailabilityWeekResponse)
async def get_lab_availability_week(
    laboratory_id: str,
    monday: str = Query(..., description="Fecha del lunes en formato YYYY-MM-DD"),
    current_user: dict = Depends(get_current_user),
) -> LabAvailabilityWeekResponse:
    """Devuelve los 7 dias de la semana en una sola respuesta.

    Reusa el cache por dia, asi que dias ya solicitados individualmente vuelven
    desde el cache. Para los dias faltantes, paraleliza las 4 consultas por dia
    via asyncio.gather, reduciendo la latencia total al maximo round-trip.
    """
    try:
        monday_date = datetime.strptime(monday, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="monday debe tener formato YYYY-MM-DD",
        ) from exc

    ensure_user_can_reserve_laboratory(laboratory_id, current_user)

    current_local_time = now_local_naive()
    max_allowed_day = _max_allowed_reservation_date(current_local_time.date())

    week_days = [monday_date + timedelta(days=offset) for offset in range(7)]
    if monday_date > max_allowed_day:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Solo puedes consultar disponibilidad dentro del plazo maximo de un mes",
        )

    async def _resolve_day(current_date) -> LabAvailabilityResponse:
        day_iso = current_date.isoformat()
        cached = _get_cached_availability(laboratory_id, day_iso)
        if cached is not None:
            return cached

        raw_reservations, tutorial_sessions, blocks, classes = await asyncio.gather(
            asyncio.to_thread(lab_reservation_repo.list_for_laboratory_day, laboratory_id, day_iso),
            asyncio.to_thread(tutorial_session_repo.list_public_for_laboratory_day, laboratory_id, day_iso),
            asyncio.to_thread(lab_block_repo.list_for_laboratory_day, laboratory_id, day_iso),
            asyncio.to_thread(lab_schedule_repo.list_active_for_laboratory_weekday, laboratory_id, current_date.weekday()),
        )
        slots = _compute_slots_for_day(
            laboratory_id=laboratory_id,
            current_date=current_date,
            current_local_time=current_local_time,
            raw_reservations=raw_reservations,
            tutorial_sessions=tutorial_sessions,
            blocks=blocks,
            classes=classes,
        )
        response = LabAvailabilityResponse(
            laboratory_id=laboratory_id,
            date=day_iso,
            slot_minutes=ACADEMIC_BLOCK_MINUTES,
            slots=slots,
        )
        cache_ttl_seconds = (
            _AVAILABILITY_CACHE_TTL_TODAY
            if current_date == current_local_time.date()
            else _AVAILABILITY_CACHE_TTL_OTHER
        )
        _set_cached_availability(laboratory_id, day_iso, response, cache_ttl_seconds)
        return response

    days = await asyncio.gather(*[_resolve_day(d) for d in week_days])

    return LabAvailabilityWeekResponse(
        laboratory_id=laboratory_id,
        monday=monday,
        slot_minutes=ACADEMIC_BLOCK_MINUTES,
        days=list(days),
    )
