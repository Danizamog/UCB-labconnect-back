import calendar
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.models.class_session import ClassSession
from app.models.class_tutorial import ClassTutorial
from app.models.laboratory import Laboratory
from app.models.practice_request import PracticeRequest


router = APIRouter(prefix="/availability", tags=["availability"])

OPENING_HOUR = 7
CLOSING_HOUR = 21
TOTAL_HOURLY_SLOTS = CLOSING_HOUR - OPENING_HOUR


def _query_active_labs(
    db: Session,
    lab_id: int | None = None,
    area_id: int | None = None,
) -> list[Laboratory]:
    labs_query = db.query(Laboratory).filter(Laboratory.is_active.is_(True))
    if area_id is not None:
        labs_query = labs_query.filter(Laboratory.area_id == area_id)
    if lab_id is not None:
        labs_query = labs_query.filter(Laboratory.id == lab_id)
    return labs_query.order_by(Laboratory.name.asc()).all()


def _format_time(value: time) -> str:
    return value.strftime("%H:%M")


def _time_to_minutes(value: time | str) -> int:
    if isinstance(value, str):
        parsed = datetime.strptime(value, "%H:%M").time()
    else:
        parsed = value
    return parsed.hour * 60 + parsed.minute


def _slot_boundaries() -> list[tuple[time, time]]:
    return [
        (time(hour, 0), time(hour + 1, 0))
        for hour in range(OPENING_HOUR, CLOSING_HOUR)
    ]


def _build_time_slots(events: list[dict]) -> list[dict]:
    slots: list[dict] = []
    for slot_start, slot_end in _slot_boundaries():
        slot_start_minutes = _time_to_minutes(slot_start)
        slot_end_minutes = _time_to_minutes(slot_end)
        overlapping_events = [
            {
                "id": event["id"],
                "type": event["type"],
                "title": event["title"],
            }
            for event in events
            if _event_overlaps_slot(event, slot_start_minutes, slot_end_minutes)
        ]
        slots.append(
            {
                "start_time": _format_time(slot_start),
                "end_time": _format_time(slot_end),
                "label": _format_time(slot_start),
                "status": "occupied" if overlapping_events else "available",
                "events": overlapping_events,
            }
        )
    return slots


def _count_occupied_slots(events: list[dict]) -> int:
    return sum(1 for slot in _build_time_slots(events) if slot["status"] == "occupied")


def _status_from_occupied_slots(occupied_slots: int, total_slots: int = TOTAL_HOURLY_SLOTS) -> str:
    if occupied_slots <= 0:
        return "available"
    if occupied_slots >= total_slots:
        return "occupied"
    return "partial"


def _event_overlaps_slot(event: dict, slot_start_minutes: int, slot_end_minutes: int) -> bool:
    event_start_minutes = _time_to_minutes(event["start_time"])
    event_end_minutes = _time_to_minutes(event["end_time"])
    return event_start_minutes < slot_end_minutes and event_end_minutes > slot_start_minutes


def _truncate_text(value: str | None, limit: int = 60) -> str:
    normalized = (value or "").strip()
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"


def _serialize_practice(practice: PracticeRequest) -> dict:
    preview_title = (
        _truncate_text(practice.subject_name)
        or _truncate_text(practice.support_topic)
        or _truncate_text(practice.notes)
        or "Practica de laboratorio"
    )
    return {
        "type": "practice",
        "id": practice.id,
        "start_time": _format_time(practice.start_time),
        "end_time": _format_time(practice.end_time),
        "status": practice.status,
        "title": preview_title,
        "subject_name": practice.subject_name or preview_title,
        "reserved_by": practice.username,
        "owner_label": "Solicitante",
        "event_label": "Reserva de practica",
        "notes": practice.notes,
        "support_topic": practice.support_topic,
    }


def _serialize_class(session: ClassSession) -> dict:
    return {
        "type": "class",
        "id": session.id,
        "start_time": _format_time(session.start_time),
        "end_time": _format_time(session.end_time),
        "status": "scheduled",
        "title": session.subject_name,
        "subject_name": session.subject_name,
        "reserved_by": session.teacher_name,
        "owner_label": "Docente",
        "event_label": "Clase",
        "notes": session.notes,
        "support_topic": session.support_topic,
    }


def _serialize_class_tutorial(item: ClassTutorial) -> dict:
    session_label = {
        "class": "Clase",
        "tutorial": "Tutoria",
        "guest": "Invitado",
    }.get(item.session_type, item.session_type)
    return {
        "type": item.session_type,
        "id": item.id,
        "start_time": _format_time(item.start_time),
        "end_time": _format_time(item.end_time),
        "status": "scheduled",
        "title": item.title,
        "subject_name": item.title,
        "reserved_by": item.facilitator_name,
        "owner_label": "Responsable",
        "event_label": session_label,
        "notes": item.notes,
        "support_topic": item.support_topic,
    }


def _build_day_payload(lab: Laboratory, reservations: list[dict]) -> dict:
    occupied_slots = _count_occupied_slots(reservations)
    return {
        "laboratory_id": lab.id,
        "laboratory_name": lab.name,
        "area_id": lab.area_id,
        "reservations": reservations,
        "time_slots": _build_time_slots(reservations),
        "occupied_slots": occupied_slots,
        "total_slots": TOTAL_HOURLY_SLOTS,
        "status": _status_from_occupied_slots(occupied_slots),
    }


def _build_week_day_payload(current_date: date, reservations: list[dict]) -> dict:
    occupied_slots = _count_occupied_slots(reservations)
    return {
        "date": current_date.isoformat(),
        "weekday": current_date.strftime("%A").lower(),
        "status": _status_from_occupied_slots(occupied_slots),
        "occupied_slots": occupied_slots,
        "total_slots": TOTAL_HOURLY_SLOTS,
        "reservations": reservations,
        "time_slots": _build_time_slots(reservations),
    }


@router.get("/calendar")
def get_labs_calendar(
    year: int = Query(..., ge=2024, le=2100),
    month: int = Query(..., ge=1, le=12),
    lab_id: int | None = Query(default=None),
    area_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    _, total_days = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)

    labs = _query_active_labs(db, lab_id=lab_id, area_id=area_id)

    practice_requests = (
        db.query(PracticeRequest)
        .filter(
            PracticeRequest.date >= start_date,
            PracticeRequest.date <= end_date,
            PracticeRequest.status.in_(["pending", "approved"]),
        )
        .all()
    )
    class_sessions = (
        db.query(ClassSession)
        .filter(ClassSession.date >= start_date, ClassSession.date <= end_date)
        .all()
    )
    class_tutorials = (
        db.query(ClassTutorial)
        .filter(ClassTutorial.date >= start_date, ClassTutorial.date <= end_date)
        .all()
    )

    occupancy: dict[tuple[int, date], list[dict]] = {}
    for item in practice_requests:
        occupancy.setdefault((item.laboratory_id, item.date), []).append(_serialize_practice(item))
    for item in class_sessions:
        occupancy.setdefault((item.laboratory_id, item.date), []).append(_serialize_class(item))
    for item in class_tutorials:
        occupancy.setdefault((item.laboratory_id, item.date), []).append(_serialize_class_tutorial(item))

    result = []
    for lab in labs:
        days_out = []
        for day in range(1, total_days + 1):
            current_date = date(year, month, day)
            reservations = sorted(
                occupancy.get((lab.id, current_date), []),
                key=lambda item: item["start_time"],
            )
            occupied_slots = _count_occupied_slots(reservations)
            days_out.append(
                {
                    "day": day,
                    "date": current_date.isoformat(),
                    "status": _status_from_occupied_slots(occupied_slots),
                    "occupied_slots": occupied_slots,
                    "total_slots": TOTAL_HOURLY_SLOTS,
                    "time_slots": _build_time_slots(reservations),
                }
            )

        result.append(
            {
                "laboratory_id": lab.id,
                "laboratory_name": lab.name,
                "year": year,
                "month": month,
                "days": days_out,
            }
        )

    return result


@router.get("/day")
def get_day_reservations(
    date_value: str = Query(..., alias="date"),
    lab_id: int | None = Query(default=None),
    area_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        target_date = datetime.strptime(date_value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Formato de fecha invalido") from exc

    labs = _query_active_labs(db, lab_id=lab_id, area_id=area_id)

    practice_requests = (
        db.query(PracticeRequest)
        .filter(PracticeRequest.date == target_date, PracticeRequest.status.in_(["pending", "approved"]))
        .all()
    )
    class_sessions = db.query(ClassSession).filter(ClassSession.date == target_date).all()
    class_tutorials = db.query(ClassTutorial).filter(ClassTutorial.date == target_date).all()

    reservations_by_lab: dict[int, list[dict]] = {lab.id: [] for lab in labs}

    for practice in practice_requests:
        if practice.laboratory_id in reservations_by_lab:
            reservations_by_lab[practice.laboratory_id].append(_serialize_practice(practice))

    for session in class_sessions:
        if session.laboratory_id in reservations_by_lab:
            reservations_by_lab[session.laboratory_id].append(_serialize_class(session))
    for item in class_tutorials:
        if item.laboratory_id in reservations_by_lab:
            reservations_by_lab[item.laboratory_id].append(_serialize_class_tutorial(item))

    return [
        _build_day_payload(
            lab,
            sorted(reservations_by_lab.get(lab.id, []), key=lambda item: item["start_time"]),
        )
        for lab in labs
    ]


@router.get("/week")
def get_week_availability(
    start_date: str = Query(..., alias="start_date"),
    lab_id: int | None = Query(default=None),
    area_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        week_start = datetime.strptime(start_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Formato de fecha invalido") from exc

    week_end = week_start + timedelta(days=6)
    labs = _query_active_labs(db, lab_id=lab_id, area_id=area_id)

    practice_requests = (
        db.query(PracticeRequest)
        .filter(
            PracticeRequest.date >= week_start,
            PracticeRequest.date <= week_end,
            PracticeRequest.status.in_(["pending", "approved"]),
        )
        .all()
    )
    class_sessions = (
        db.query(ClassSession)
        .filter(ClassSession.date >= week_start, ClassSession.date <= week_end)
        .all()
    )
    class_tutorials = (
        db.query(ClassTutorial)
        .filter(ClassTutorial.date >= week_start, ClassTutorial.date <= week_end)
        .all()
    )

    occupancy: dict[tuple[int, date], list[dict]] = {}
    for practice in practice_requests:
        occupancy.setdefault((practice.laboratory_id, practice.date), []).append(_serialize_practice(practice))
    for session in class_sessions:
        occupancy.setdefault((session.laboratory_id, session.date), []).append(_serialize_class(session))
    for item in class_tutorials:
        occupancy.setdefault((item.laboratory_id, item.date), []).append(_serialize_class_tutorial(item))

    output = []
    for lab in labs:
        days = []
        for offset in range(7):
            current_date = week_start + timedelta(days=offset)
            reservations = sorted(
                occupancy.get((lab.id, current_date), []),
                key=lambda item: item["start_time"],
            )
            days.append(_build_week_day_payload(current_date, reservations))

        output.append(
            {
                "laboratory_id": lab.id,
                "laboratory_name": lab.name,
                "area_id": lab.area_id,
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "days": days,
            }
        )

    return output
