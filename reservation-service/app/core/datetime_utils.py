from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings


def _app_timezone() -> ZoneInfo | timezone:
    try:
        return ZoneInfo(settings.app_timezone)
    except ZoneInfoNotFoundError:
        return timezone.utc


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

    # PocketBase persists date fields with timezone markers, but the project
    # treats reservation schedules as wall-clock local times entered by users.
    # Preserve the original clock values instead of converting them across
    # timezones so UI, availability, and business rules stay aligned.
    if parsed.tzinfo is not None:
        return parsed.replace(tzinfo=None)

    return parsed


def parse_timestamp_to_local_naive(value: str) -> datetime:
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

    if parsed.tzinfo is None:
        return parsed

    return parsed.astimezone(_app_timezone()).replace(tzinfo=None)


def now_local_naive() -> datetime:
    return datetime.now(_app_timezone()).replace(tzinfo=None)


def extract_iso_date(value: str | None) -> str:
    """Devuelve el prefijo YYYY-MM-DD de cualquier datetime string.

    PocketBase persiste fechas con espacio (ej. "2026-05-18 14:30:00.000Z")
    pero el codigo a veces guarda formato ISO con 'T'. Usar split('T') falla
    con el formato de PocketBase y deja basura en la clave de cache,
    impidiendo invalidar la disponibilidad cuando se crea/edita/cancela una
    reserva. Tomamos los primeros 10 caracteres porque YYYY-MM-DD siempre
    mide 10 sin importar el separador.
    """
    normalized = str(value or "").strip()
    if len(normalized) < 10:
        return ""
    return normalized[:10]


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


# Bloques académicos canónicos del laboratorio. Cada par (inicio, fin) tiene 45 min.
# Las horas son uniformes para todos los laboratorios y reflejan la malla académica.
ACADEMIC_BLOCKS: list[tuple[str, str]] = [
    ("07:15", "08:00"),
    ("08:00", "08:45"),
    ("09:00", "09:45"),
    ("09:45", "10:30"),
    ("10:45", "11:30"),
    ("11:30", "12:15"),
    ("12:30", "13:15"),
    ("13:15", "14:00"),
    ("14:15", "15:00"),
    ("15:00", "15:45"),
    ("16:00", "16:45"),
    ("16:45", "17:30"),
    ("17:45", "18:30"),
    ("18:30", "19:15"),
    ("19:30", "20:15"),
    ("20:15", "21:00"),
]

LAB_DAY_START: str = ACADEMIC_BLOCKS[0][0]
LAB_DAY_END: str = ACADEMIC_BLOCKS[-1][1]
ACADEMIC_BLOCK_MINUTES: int = 45

_ACADEMIC_BLOCK_STARTS: frozenset[str] = frozenset(start for start, _ in ACADEMIC_BLOCKS)
_ACADEMIC_BLOCK_ENDS: frozenset[str] = frozenset(end for _, end in ACADEMIC_BLOCKS)


def iter_lab_blocks(day: date) -> list[tuple[datetime, datetime]]:
    """Materializa los bloques académicos canónicos en una fecha concreta."""
    return [
        (combine_date_time(day, start), combine_date_time(day, end))
        for start, end in ACADEMIC_BLOCKS
    ]


def is_valid_block_start(value: str) -> bool:
    return value in _ACADEMIC_BLOCK_STARTS


def is_valid_block_end(value: str) -> bool:
    return value in _ACADEMIC_BLOCK_ENDS


def matches_academic_range(start_time: str, end_time: str) -> bool:
    """True si el rango (start, end) coincide con algún subrango contiguo de bloques académicos."""
    if not is_valid_block_start(start_time) or not is_valid_block_end(end_time):
        return False
    if start_time >= end_time:
        return False
    return True
