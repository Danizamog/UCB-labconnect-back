from calendar import monthrange
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.container import lab_block_repo, lab_reservation_repo, lab_schedule_repo, tutorial_session_repo
from app.application.laboratory_access import ensure_user_can_reserve_laboratory
from app.core.datetime_utils import combine_date_time, format_time, iter_time_ranges, now_local_naive, parse_datetime
from app.core.dependencies import get_current_user
from app.schemas.availability import AvailabilitySlot, LabAvailabilityResponse

router = APIRouter(prefix="/availability", tags=["availability"])


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


@router.get("/labs/{laboratory_id}", response_model=LabAvailabilityResponse)
def get_lab_availability(
    laboratory_id: str,
    day: str = Query(..., description="Fecha en formato YYYY-MM-DD"),
    current_user: dict = Depends(get_current_user),
) -> LabAvailabilityResponse:
    ensure_user_can_reserve_laboratory(laboratory_id, current_user)

    try:
        current_date = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="day debe tener formato YYYY-MM-DD") from exc

    current_local_time = now_local_naive()
    max_allowed_day = _max_allowed_reservation_date(current_local_time.date())
    if current_date > max_allowed_day:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Solo puedes consultar disponibilidad dentro del plazo maximo de un mes",
        )

    weekday = current_date.weekday()
    schedules = [
        item for item in lab_schedule_repo.list_all()
        if item.laboratory_id == laboratory_id and item.weekday == weekday and item.is_active
    ]

    schedule = schedules[0] if schedules else None
    if schedule:
        day_start = combine_date_time(current_date, schedule.open_time)
        day_end = combine_date_time(current_date, schedule.close_time)
        slot_minutes = schedule.slot_minutes or 60
    else:
        day_start = combine_date_time(current_date, "08:00")
        day_end = combine_date_time(current_date, "20:00")
        slot_minutes = 60

    ranges = iter_time_ranges(day_start, day_end, slot_minutes)

    reservations = [
        item for item in lab_reservation_repo.list_all()
        if item.laboratory_id == laboratory_id
        and item.status not in {"rejected", "cancelled", "completed", "absent"}
        and item.is_active
        and item.start_at.startswith(day)
    ]

    tutorial_sessions = [
        item for item in tutorial_session_repo.list_public()
        if item.laboratory_id == laboratory_id
        and item.start_at.startswith(day)
    ]

    blocks = [
        item for item in lab_block_repo.list_all()
        if item.laboratory_id == laboratory_id
        and item.is_active
        and item.start_at.startswith(day)
    ]

    slots: list[AvailabilitySlot] = []
    for start_dt, end_dt in ranges:
        state = "available"
        source = ""
        source_id = ""
        source_status = ""

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

    return LabAvailabilityResponse(
        laboratory_id=laboratory_id,
        date=day,
        slot_minutes=slot_minutes,
        slots=slots,
    )
