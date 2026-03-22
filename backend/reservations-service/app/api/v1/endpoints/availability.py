import calendar
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.core.dependencies import get_db, get_current_user_payload
from app.models.laboratory import Laboratory
from app.models.practice_request import PracticeRequest
from app.schemas.availability import DayAvailabilityOut, LabCalendarOut
from app.schemas.day_reservations import DayReservationItemOut, DayReservationsGroupOut

router = APIRouter(prefix="/availability", tags=["availability"])


@router.get("/calendar", response_model=list[LabCalendarOut])
def get_labs_calendar(
    year: int = Query(..., ge=2024, le=2100),
    month: int = Query(..., ge=1, le=12),
    lab_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    labs_query = (
        db.query(Laboratory)
        .options(joinedload(Laboratory.area))
        .filter(Laboratory.is_active == True)
    )

    if lab_id is not None:
        labs_query = labs_query.filter(Laboratory.id == lab_id)

    labs = labs_query.order_by(Laboratory.name.asc()).all()

    _, total_days = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)

    reservations_query = db.query(PracticeRequest).filter(
        PracticeRequest.date >= start_date,
        PracticeRequest.date <= end_date,
        PracticeRequest.status.in_(["pending", "approved"]),
    )

    if lab_id is not None:
        reservations_query = reservations_query.filter(PracticeRequest.laboratory_id == lab_id)

    reservations = reservations_query.order_by(
        PracticeRequest.date.asc(),
        PracticeRequest.start_time.asc(),
    ).all()

    reservations_count_by_lab_and_day: dict[tuple[int, int], int] = {}

    for reservation in reservations:
        key = (reservation.laboratory_id, reservation.date.day)
        reservations_count_by_lab_and_day[key] = reservations_count_by_lab_and_day.get(key, 0) + 1

    result: list[LabCalendarOut] = []

    for lab in labs:
        days_out: list[DayAvailabilityOut] = []

        for day in range(1, total_days + 1):
            current_date = date(year, month, day)
            occupied_slots = reservations_count_by_lab_and_day.get((lab.id, day), 0)

            if occupied_slots == 0:
                status = "available"
            elif occupied_slots >= 3:
                status = "occupied"
                occupied_slots = 3
            else:
                status = "partial"

            days_out.append(
                DayAvailabilityOut(
                    day=day,
                    date=current_date.isoformat(),
                    status=status,
                    occupied_slots=occupied_slots,
                    total_slots=3,
                )
            )

        result.append(
            LabCalendarOut(
                laboratory_id=lab.id,
                laboratory_name=lab.name,
                area_id=lab.area_id,
                area_name=lab.area.name if lab.area else None,
                year=year,
                month=month,
                days=days_out,
            )
        )

    return result


@router.get("/day", response_model=list[DayReservationsGroupOut])
def get_day_reservations(
    date_value: str = Query(..., alias="date"),
    lab_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    target_date = datetime.strptime(date_value, "%Y-%m-%d").date()

    labs_query = (
        db.query(Laboratory)
        .options(joinedload(Laboratory.area))
        .filter(Laboratory.is_active == True)
    )

    if lab_id is not None:
        labs_query = labs_query.filter(Laboratory.id == lab_id)

    labs = labs_query.order_by(Laboratory.name.asc()).all()

    reservations = (
        db.query(PracticeRequest)
        .filter(
            PracticeRequest.date == target_date,
            PracticeRequest.status.in_(["pending", "approved"]),
        )
        .order_by(PracticeRequest.start_time.asc())
        .all()
    )

    result: list[DayReservationsGroupOut] = []

    for lab in labs:
        lab_reservations = [r for r in reservations if r.laboratory_id == lab.id]

        result.append(
            DayReservationsGroupOut(
                laboratory_id=lab.id,
                laboratory_name=lab.name,
                area_id=lab.area_id,
                area_name=lab.area.name if lab.area else None,
                reservations=[
                    DayReservationItemOut(
                        start_time=r.start_time.strftime("%H:%M"),
                        end_time=r.end_time.strftime("%H:%M"),
                        status="occupied",
                    )
                    for r in lab_reservations
                ],
            )
        )

    return result