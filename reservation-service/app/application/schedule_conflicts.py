"""Proyecta ocupaciones con fecha sobre un horario semanal, en hora local."""
from datetime import datetime, timedelta

from app.core.datetime_utils import combine_date_time, now_local_naive, parse_datetime


def weekly_windows(laboratory_id, weekday, classes, events, exclude_id="", now=None):
    now = now or now_local_naive()
    windows = []
    for item in classes:
        if item.id != exclude_id and item.is_active and item.approval_status == "approved":
            windows.append({"start_time": item.start_time, "end_time": item.end_time,
                            "source": "class", "date": "", "label": "Clase aprobada"})
    for source, item in events:
        if item.laboratory_id != laboratory_id or not getattr(item, "is_active", True):
            continue
        state = getattr(item, "approval_status", getattr(item, "status", "approved"))
        if state not in {"approved", "in_progress"}:
            continue
        if source == "tutorial_session" and not getattr(item, "is_published", True):
            continue
        start, end = parse_datetime(item.start_at), parse_datetime(item.end_at)
        if end <= now:
            continue
        pivot = max(start, now)
        first_day = pivot.date() + timedelta(days=(weekday - pivot.weekday()) % 7)
        # Un bloqueo de mas de una semana puede empezar a media jornada:
        # su siguiente ocurrencia tambien ocupa las horas anteriores al inicio.
        for day in (first_day, first_day + timedelta(days=7)):
            midnight = datetime.combine(day, datetime.min.time())
            day_end = midnight + timedelta(days=1)
            if midnight >= end:
                continue
            local_start = max(start, midnight, now)
            local_end = min(end, day_end)
            if local_end <= local_start:
                continue
            rounded_end = local_end.replace(second=0, microsecond=0)
            if local_end.second or local_end.microsecond:
                rounded_end += timedelta(minutes=1)
            windows.append({
                "start_time": local_start.strftime("%H:%M"),
                "end_time": "24:00" if rounded_end == day_end else rounded_end.strftime("%H:%M"),
                "source": source, "date": day.isoformat(),
                "label": {"lab_reservation": "Reserva", "tutorial_session": "Tutoría", "lab_block": "Bloqueo"}[source],
            })
    return windows


def first_conflict(start_time, end_time, windows):
    return next((item for item in windows
                 if start_time < item["end_time"] and item["start_time"] < end_time), None)


def ensure_no_classes_or_blocks(session, schedules, blocks):
    start, end = parse_datetime(session.start_at), parse_datetime(session.end_at)
    day = start.date()
    while day <= end.date():
        for klass in schedules.list_active_for_laboratory_weekday(session.laboratory_id, day.weekday()):
            if start < combine_date_time(day, klass.end_time) and combine_date_time(day, klass.start_time) < end:
                raise ValueError("Ese horario esta ocupado por una clase aprobada")
        for block in blocks.list_for_laboratory_day(session.laboratory_id, day.isoformat()):
            if start < parse_datetime(block.end_at) and parse_datetime(block.start_at) < end:
                raise ValueError("Ese horario tiene un bloqueo activo")
        day += timedelta(days=1)
