from datetime import datetime

import httpx

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.container import lab_block_repo, lab_reservation_repo, lab_schedule_repo
from app.core.config import settings
from app.core.datetime_utils import combine_date_time, format_time, iter_time_ranges, parse_datetime
from app.core.dependencies import get_current_user
from app.schemas.availability import AvailabilitySlot, LabAvailabilityResponse, LabOccupancyResponse

router = APIRouter(prefix="/availability", tags=["availability"])


def _has_overlap(slot_start: datetime, slot_end: datetime, event_start_raw: str, event_end_raw: str) -> bool:
    event_start = parse_datetime(event_start_raw)
    event_end = parse_datetime(event_end_raw)
    return slot_start < event_end and event_start < slot_end


def _fetch_laboratories() -> list[dict]:
    base_url = settings.inventory_service_url.rstrip("/")
    if not base_url:
        return []

    url = f"{base_url}/v1/laboratories/all"
    try:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return []

    return data if isinstance(data, list) else []


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
        and item.status not in {"rejected", "cancelled", "completed", "absent"}
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


@router.get("/occupancy", response_model=list[LabOccupancyResponse])
def get_lab_occupancy(
    laboratory_id: str | None = Query(default=None),
    _: dict = Depends(get_current_user),
) -> list[LabOccupancyResponse]:
    reservations = [
        item for item in lab_reservation_repo.list_all()
        if item.is_active and item.status == "in_progress"
        and (not laboratory_id or item.laboratory_id == laboratory_id)
    ]

    occupancy_by_lab: dict[str, int] = {}
    for reservation in reservations:
        lab_id = str(reservation.laboratory_id or "").strip()
        if not lab_id:
            continue
        occupancy_by_lab[lab_id] = occupancy_by_lab.get(lab_id, 0) + 1

    laboratories = _fetch_laboratories()
    laboratories_by_id = {
        str(lab.get("id") or "").strip(): lab
        for lab in laboratories
        if str(lab.get("id") or "").strip()
    }

    if laboratory_id:
        candidate_ids = [laboratory_id]
    else:
        candidate_ids = sorted(
            set(laboratories_by_id.keys()).union(occupancy_by_lab.keys()),
            key=lambda lab_id: str(laboratories_by_id.get(lab_id, {}).get("name") or lab_id).lower(),
        )

    occupancy_items: list[LabOccupancyResponse] = []
    for lab_id in candidate_ids:
        lab = laboratories_by_id.get(lab_id, {})
        capacity = int(lab.get("capacity") or 0)
        current_occupancy = int(occupancy_by_lab.get(lab_id, 0))
        available_slots = max(capacity - current_occupancy, 0)
        if capacity > 0:
            occupancy_percentage = round((current_occupancy / capacity) * 100, 1)
            if current_occupancy >= capacity:
                status = "occupied"
            elif current_occupancy > 0:
                status = "partial"
            else:
                status = "available"
        else:
            occupancy_percentage = 100.0 if current_occupancy > 0 else 0.0
            status = "occupied" if current_occupancy > 0 else "available"

        occupancy_items.append(
            LabOccupancyResponse(
                laboratory_id=lab_id,
                laboratory_name=str(lab.get("name") or lab_id).strip() or lab_id,
                area_id=str(lab.get("area_id") or "").strip(),
                capacity=capacity,
                current_occupancy=current_occupancy,
                available_slots=available_slots,
                occupancy_percentage=occupancy_percentage,
                status=status,
            )
        )

    return occupancy_items
