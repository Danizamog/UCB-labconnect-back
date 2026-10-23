from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.core.config import settings
from app.infrastructure.pocketbase_client import PocketBaseClient
from app.services.cleaning import DataQuality, cap_outliers

# Same "real usage" filter the reservation-service analytics uses.
_COUNTED_RESERVATION_STATUSES = {"approved", "in_progress", "completed"}
# Supply demand that actually leaves the shelf.
_COUNTED_SUPPLY_STATUSES = {"approved", "delivered"}

_pb = PocketBaseClient()


def close() -> None:
    _pb.close()


def _parse_dt(raw: Any) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = text.replace("T", " ")
    if text.endswith("Z"):
        text = text[:-1]
    head = text.split("+")[0].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(head, fmt)
        except ValueError:
            continue
    return None


def _window_start(days: int) -> date:
    return date.today() - timedelta(days=days - 1)


def _empty_daily_map(days: int) -> dict[date, float]:
    start = _window_start(days)
    return {start + timedelta(days=offset): 0.0 for offset in range(days)}


def _date_lower_bound(days: int) -> str:
    # PocketBase filtra por fecha como string ("YYYY-MM-DD HH:MM:SS"); acotar la
    # consulta a la ventana evita traer todo el historico (clave con muchos datos).
    return f"{_window_start(days).isoformat()} 00:00:00"


def _escape(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def _as_float(raw: Any) -> float:
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


# --- catalog ------------------------------------------------------------------
def list_stock_items() -> list[dict[str, Any]]:
    return _pb.list_records(settings.pb_stock_items_collection, per_page=200, max_items=2000)


def list_laboratories() -> list[dict[str, Any]]:
    return _pb.list_records(settings.pb_laboratory_collection, per_page=200, max_items=1000)


def list_supply_demand_view() -> list[dict[str, Any]]:
    """Lee la vista SQL `vista_supply_demand_60d` (agregacion en SQLite).

    Cada fila trae, por stock_item: name, unit, quantity_available, minimum_stock,
    total_demand (suma de consumo 60d) y active_days. Evita traer todas las
    reservas de insumos a Python para el panorama."""
    return _pb.list_records(settings.pb_supply_demand_view, per_page=200, max_items=5000)


def _spread_hours(start: datetime, end: datetime | None, hourly: list[float]) -> float:
    """Reparte las horas de una reserva entre los buckets de hora-del-dia (0..23).

    Devuelve el total de horas de la reserva. Una reserva 14:00-16:00 suma 1 h a la 14
    y 1 h a la 15. Acota las iteraciones por seguridad."""
    if not end or end <= start:
        hourly[start.hour] += 1.0
        return 1.0
    total = 0.0
    cursor = start
    guard = 0
    while cursor < end and guard < 48:
        next_hour = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        segment_end = min(next_hour, end)
        fraction = (segment_end - cursor).total_seconds() / 3600.0
        hourly[cursor.hour] += fraction
        total += fraction
        cursor = segment_end
        guard += 1
    return total


def load_usage_distributions(days: int | None = None) -> tuple[list[float], list[float]]:
    """Frecuencia de uso de laboratorios por hora-del-dia (24) y por dia-de-semana (7).

    Un solo escaneo acotado por fecha. Alimenta la tabla de 'horarios mas frecuentes'."""
    days = days or settings.overview_window_days
    window_start = _window_start(days)
    hourly = [0.0] * 24
    weekday = [0.0] * 7

    records = _pb.list_records(
        settings.pb_lab_reservation_collection,
        filter=f'start_at >= "{_date_lower_bound(days)}"',
        sort="-start_at",
        per_page=200,
        max_items=20000,
    )

    seen: set[str] = set()
    for record in records:
        record_id = str(record.get("id") or "")
        if record_id and record_id in seen:
            continue
        if record_id:
            seen.add(record_id)
        if str(record.get("status") or "").strip().lower() not in _COUNTED_RESERVATION_STATUSES:
            continue
        start = _parse_dt(record.get("start_at"))
        if not start or start.date() < window_start:
            continue
        total = _spread_hours(start, _parse_dt(record.get("end_at")), hourly)
        weekday[start.weekday()] += total

    return hourly, weekday


def get_laboratory(lab_id: str) -> dict[str, Any] | None:
    return _pb.get_record(settings.pb_laboratory_collection, lab_id)


def get_stock_item(stock_item_id: str) -> dict[str, Any] | None:
    return _pb.get_record(settings.pb_stock_items_collection, stock_item_id)


# --- single-series loaders (used by the detail endpoints) ---------------------
def load_lab_daily_occupancy(lab_id: str, days: int | None = None) -> tuple[list[tuple[date, float]], DataQuality]:
    """Daily reserved hours for a laboratory (gaps -> 0), with a cleaning report."""
    days = days or settings.history_days
    daily = _empty_daily_map(days)
    quality = DataQuality()

    records = _pb.list_records(
        settings.pb_lab_reservation_collection,
        filter=f'laboratory_id = "{_escape(lab_id)}" && start_at >= "{_date_lower_bound(days)}"',
        sort="start_at",
        per_page=200,
        max_items=5000,
    )

    seen: set[str] = set()
    for record in records:
        quality.total_records += 1
        record_id = str(record.get("id") or "")
        if record_id and record_id in seen:
            quality.duplicates += 1
            continue
        if record_id:
            seen.add(record_id)
        status = str(record.get("status") or "").strip().lower()
        if status not in _COUNTED_RESERVATION_STATUSES:
            quality.excluded_status += 1
            continue
        start = _parse_dt(record.get("start_at"))
        if not start:
            quality.invalid_date += 1
            continue
        day = start.date()
        if day not in daily:
            quality.out_of_window += 1
            continue
        end = _parse_dt(record.get("end_at"))
        hours = (end - start).total_seconds() / 3600.0 if end and end > start else 1.0
        daily[day] += round(max(0.0, hours), 4)
        quality.used_records += 1

    quality.outliers_capped += cap_outliers(daily)
    return sorted(daily.items()), quality


def load_supply_daily_consumption(
    stock_item_id: str, days: int | None = None
) -> tuple[list[tuple[date, float]], DataQuality]:
    """Daily approved/delivered supply quantity (gaps -> 0), with a cleaning report."""
    days = days or settings.history_days
    daily = _empty_daily_map(days)
    quality = DataQuality()

    records = _pb.list_records(
        settings.pb_supply_reservations_collection,
        filter=f'stock_item_id = "{_escape(stock_item_id)}" && created >= "{_date_lower_bound(days)}"',
        sort="created",
        per_page=200,
        max_items=5000,
    )

    seen: set[str] = set()
    for record in records:
        quality.total_records += 1
        record_id = str(record.get("id") or "")
        if record_id and record_id in seen:
            quality.duplicates += 1
            continue
        if record_id:
            seen.add(record_id)
        status = str(record.get("status") or "").strip().lower()
        if status not in _COUNTED_SUPPLY_STATUSES:
            quality.excluded_status += 1
            continue
        when = _parse_dt(record.get("created") or record.get("updated"))
        if not when:
            quality.invalid_date += 1
            continue
        day = when.date()
        if day not in daily:
            quality.out_of_window += 1
            continue
        daily[day] += max(0.0, _as_float(record.get("quantity")))
        quality.used_records += 1

    quality.outliers_capped += cap_outliers(daily)
    return sorted(daily.items()), quality


# --- bulk loaders (used by the overview) --------------------------------------
def load_all_supply_consumption(
    days: int | None = None,
) -> tuple[dict[str, list[tuple[date, float]]], DataQuality]:
    """One pass over recent supply reservations, bucketed by stock item."""
    days = days or settings.history_days
    known_ids = {str(item.get("id") or "") for item in list_stock_items() if item.get("id")}
    daily_by_id = {item_id: _empty_daily_map(days) for item_id in known_ids}
    quality = DataQuality()

    records = _pb.list_records(
        settings.pb_supply_reservations_collection,
        filter=f'created >= "{_date_lower_bound(days)}"',
        sort="-created",
        per_page=200,
        max_items=20000,
    )

    seen: set[str] = set()
    for record in records:
        quality.total_records += 1
        record_id = str(record.get("id") or "")
        if record_id and record_id in seen:
            quality.duplicates += 1
            continue
        if record_id:
            seen.add(record_id)
        status = str(record.get("status") or "").strip().lower()
        if status not in _COUNTED_SUPPLY_STATUSES:
            quality.excluded_status += 1
            continue
        when = _parse_dt(record.get("created") or record.get("updated"))
        if not when:
            quality.invalid_date += 1
            continue
        item_id = str(record.get("stock_item_id") or "").strip()
        daily = daily_by_id.get(item_id)
        if daily is None or when.date() not in daily:
            quality.out_of_window += 1
            continue
        daily[when.date()] += max(0.0, _as_float(record.get("quantity")))
        quality.used_records += 1

    result: dict[str, list[tuple[date, float]]] = {}
    for item_id, daily in daily_by_id.items():
        quality.outliers_capped += cap_outliers(daily)
        result[item_id] = sorted(daily.items())
    return result, quality


def load_all_lab_occupancy(days: int | None = None) -> tuple[dict[str, list[tuple[date, float]]], DataQuality]:
    """One pass over recent lab reservations, bucketed by laboratory."""
    days = days or settings.history_days
    known_ids = {str(lab.get("id") or "") for lab in list_laboratories() if lab.get("id")}
    daily_by_id = {lab_id: _empty_daily_map(days) for lab_id in known_ids}
    quality = DataQuality()

    records = _pb.list_records(
        settings.pb_lab_reservation_collection,
        filter=f'start_at >= "{_date_lower_bound(days)}"',
        sort="-start_at",
        per_page=200,
        max_items=20000,
    )

    seen: set[str] = set()
    for record in records:
        quality.total_records += 1
        record_id = str(record.get("id") or "")
        if record_id and record_id in seen:
            quality.duplicates += 1
            continue
        if record_id:
            seen.add(record_id)
        status = str(record.get("status") or "").strip().lower()
        if status not in _COUNTED_RESERVATION_STATUSES:
            quality.excluded_status += 1
            continue
        start = _parse_dt(record.get("start_at"))
        if not start:
            quality.invalid_date += 1
            continue
        lab_id = str(record.get("laboratory_id") or "").strip()
        daily = daily_by_id.get(lab_id)
        if daily is None or start.date() not in daily:
            quality.out_of_window += 1
            continue
        end = _parse_dt(record.get("end_at"))
        hours = (end - start).total_seconds() / 3600.0 if end and end > start else 1.0
        daily[start.date()] += round(max(0.0, hours), 4)
        quality.used_records += 1

    result: dict[str, list[tuple[date, float]]] = {}
    for lab_id, daily in daily_by_id.items():
        quality.outliers_capped += cap_outliers(daily)
        result[lab_id] = sorted(daily.items())
    return result, quality
