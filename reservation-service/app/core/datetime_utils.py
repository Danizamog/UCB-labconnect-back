from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def parse_datetime(value: str) -> datetime:
    normalized = (value or "").strip()
    if not normalized:
        raise ValueError("Fecha/hora requerida")

    normalized = normalized.replace(" ", "T")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Fecha/hora invalida: {value}") from exc

    # Normalize to naive UTC to avoid aware/naive comparison errors.
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed


def combine_date_time(day: date, hhmm: str) -> datetime:
    try:
        hour, minute = [int(part) for part in hhmm.split(":", 1)]
    except (ValueError, AttributeError) as exc:
        raise ValueError("Hora invalida, formato esperado HH:MM") from exc

    return datetime(day.year, day.month, day.day, hour, minute)


def format_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def iter_time_ranges(start: datetime, end: datetime, slot_minutes: int) -> list[tuple[datetime, datetime]]:
    if slot_minutes <= 0:
        raise ValueError("slot_minutes debe ser mayor a 0")

    items: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        next_value = cursor + timedelta(minutes=slot_minutes)
        if next_value > end:
            break
        items.append((cursor, next_value))
        cursor = next_value
    return items
