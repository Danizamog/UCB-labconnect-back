import asyncio
from calendar import monthrange
from datetime import datetime
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
    now_local_naive,
    parse_datetime,
)
from app.core.dependencies import get_current_user
from app.schemas.availability import AvailabilitySlot, LabAvailabilityResponse

router = APIRouter(prefix="/availability", tags=["availability"])

_AVAILABILITY_CACHE: dict[str, tuple[float, LabAvailabilityResponse]] = {}
_AVAILABILITY_CACHE_MAX_ITEMS = 250
_AVAILABILITY_CACHE_TTL_TODAY = 60
_AVAILABILITY_CACHE_TTL_OTHER = 120


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


@router.get("/labs/{laboratory_id}", response_model=LabAvailabilityResponse)
async def get_lab_availability(
    laboratory_id: str,
    day: str = Query(..., description="Fecha en formato YYYY-MM-DD"),
    current_user: dict = Depends(get_current_user),
) -> LabAvailabilityResponse:
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

    ranges = iter_lab_blocks(current_date)
    slot_minutes = ACADEMIC_BLOCK_MINUTES

    raw_reservations, tutorial_sessions, blocks, classes = await asyncio.gather(
        asyncio.to_thread(lab_reservation_repo.list_for_laboratory_day, laboratory_id, day),
        asyncio.to_thread(tutorial_session_repo.list_public_for_laboratory_day, laboratory_id, day),
        asyncio.to_thread(lab_block_repo.list_for_laboratory_day, laboratory_id, day),
        asyncio.to_thread(lab_schedule_repo.list_active_for_laboratory_weekday, laboratory_id, current_date.weekday()),
    )

    reservations = [
        item for item in raw_reservations
        if item.status not in {"rejected", "cancelled", "completed", "absent"}
        and item.is_active
    ]
    class_windows = [
        (combine_date_time(current_date, klass.start_time), combine_date_time(current_date, klass.end_time), klass)
        for klass in classes
    ]

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
                    source_id = klass.id
                    source_status = klass.subject
                    break

        if state == "available":
            for block in blocks:
                if _has_overlap(start_dt, end_dt, block.start_at, block.end_at):
                    state = "blocked"
                    source = "lab_block"
                    source_id = block.id
                    source_status = block.block_type
                    break

        if state == "available":
            for reservation in reservations:
                if _has_overlap(start_dt, end_dt, reservation.start_at, reservation.end_at):
                    state = "occupied"
                    source = "lab_reservation"
                    source_id = reservation.id
                    source_status = reservation.status
                    break

        if state == "available":
            for session in tutorial_sessions:
                if _has_overlap(start_dt, end_dt, session.start_at, session.end_at):
                    state = "occupied"
                    source = "tutorial_session"
                    source_id = session.id
                    source_status = "published"
                    break

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

    response = LabAvailabilityResponse(
        laboratory_id=laboratory_id,
        date=day,
        slot_minutes=slot_minutes,
        slots=slots,
    )
    cache_ttl_seconds = (
        _AVAILABILITY_CACHE_TTL_TODAY
        if current_date == current_local_time.date()
        else _AVAILABILITY_CACHE_TTL_OTHER
    )
    _set_cached_availability(laboratory_id, day, response, cache_ttl_seconds)
    return response
