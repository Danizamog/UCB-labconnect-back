from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.container import lab_block_repo, lab_reservation_repo, lab_schedule_repo
from app.core.datetime_utils import combine_date_time, format_time, iter_time_ranges, parse_datetime
from app.core.dependencies import get_current_user
from app.schemas.availability import AvailabilitySlot, LabAvailabilityResponse

router = APIRouter(prefix="/availability", tags=["availability"])


def _has_overlap(slot_start: datetime, slot_end: datetime, event_start_raw: str, event_end_raw: str) -> bool:
    event_start = parse_datetime(event_start_raw)
    event_end = parse_datetime(event_end_raw)
    return slot_start < event_end and event_start < slot_end


@router.get("/labs/{laboratory_id}", response_model=LabAvailabilityResponse)
def get_lab_availability(
    laboratory_id: str,
    day: str = Query(..., description="Fecha en formato YYYY-MM-DD"),
    _: dict = Depends(get_current_user),
) -> LabAvailabilityResponse:
    try:
        current_date = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="day debe tener formato YYYY-MM-DD") from exc

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
        and item.status not in {"rejected", "cancelled"}
        and item.is_active
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
