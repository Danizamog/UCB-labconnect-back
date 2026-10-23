from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import Any

from app.core.config import settings
from app.services import data_loader
from app.services.cleaning import DataQuality

logger = logging.getLogger(__name__)

# Ventana corta para el panorama (heuristica rapida: demanda diaria promedio).
# El detalle por item/lab usa la red neuronal; aqui se prioriza la amplitud.
_CRITICAL_DAYS = 7
_WARNING_DAYS = 21
_ALERT_ORDER = {"red": 0, "yellow": 1, "green": 2}
_WEEKDAY_LABELS = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]


def _usage_distributions(window: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Tablas de frecuencia: horas-del-dia y dias-de-semana mas usados."""
    try:
        hourly, weekday = data_loader.load_usage_distributions(window)
    except Exception:
        logger.exception("ml-service: no se pudieron calcular las distribuciones de uso")
        return [], []

    total_h = sum(hourly) or 1.0
    peak_hours = [
        {"hour": hour, "occupied_hours": round(value, 2), "percentage": round(value / total_h * 100, 1)}
        for hour, value in enumerate(hourly)
    ]
    total_w = sum(weekday) or 1.0
    weekday_usage = [
        {
            "weekday": index,
            "label": _WEEKDAY_LABELS[index],
            "occupied_hours": round(value, 2),
            "percentage": round(value / total_w * 100, 1),
        }
        for index, value in enumerate(weekday)
    ]
    return peak_hours, weekday_usage

_CACHE_LOCK = Lock()
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _num(raw: Any) -> float:
    if isinstance(raw, bool):
        return float(raw)
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw or 0)
        except ValueError:
            return 0.0
    if isinstance(raw, list) and raw:
        return _num(raw[0])
    return 0.0


def _alert_level(days_remaining: int | None, quantity: float, minimum: float) -> str:
    if quantity <= minimum:
        return "red"
    if days_remaining is None:
        return "green"
    if days_remaining <= _CRITICAL_DAYS:
        return "red"
    if days_remaining <= _WARNING_DAYS:
        return "yellow"
    return "green"


def _trend(values: list[float]) -> str:
    if len(values) < 14:
        return "flat"
    recent = sum(values[-7:])
    previous = sum(values[-14:-7])
    if recent == 0 and previous == 0:
        return "flat"
    if recent > previous * 1.15:
        return "up"
    if recent < previous * 0.85:
        return "down"
    return "flat"


def _supplies_from_view(window: int) -> list[dict[str, Any]] | None:
    """Calcula el riesgo de insumos desde la vista SQL (rapido). None si falla."""
    try:
        rows = data_loader.list_supply_demand_view()
    except Exception:
        logger.exception("ml-service: no se pudo leer la vista de demanda de insumos; uso fallback")
        return None

    supplies: list[dict[str, Any]] = []
    for row in rows:
        item_id = str(row.get("id") or "")
        if not item_id:
            continue
        total_demand = _num(row.get("total_demand"))
        active_days = int(_num(row.get("active_days")))
        avg_demand = total_demand / window if window > 0 else 0.0
        quantity = _num(row.get("quantity_available"))
        minimum = _num(row.get("minimum_stock"))
        days_remaining = int(max(0.0, quantity - minimum) / avg_demand) if avg_demand > 0 else None
        supplies.append(
            {
                "stock_item_id": item_id,
                "name": str(row.get("name") or ""),
                "unit": str(row.get("unit") or ""),
                "quantity_available": quantity,
                "minimum_stock": minimum,
                "avg_daily_demand": round(avg_demand, 3),
                "projected_days_remaining": days_remaining,
                "alert_level": _alert_level(days_remaining, quantity, minimum),
                "confidence": "high" if active_days >= 5 else "low",
            }
        )
    return supplies


def _supplies_from_python(window: int) -> tuple[list[dict[str, Any]], DataQuality]:
    """Fallback: agrega en Python desde supply_reservation (con limpieza/calidad)."""
    items = data_loader.list_stock_items()
    consumption_by_id, supply_quality = data_loader.load_all_supply_consumption(window)

    supplies: list[dict[str, Any]] = []
    for item in items:
        item_id = str(item.get("id") or "")
        if not item_id:
            continue
        values = [value for _, value in consumption_by_id.get(item_id, [])]
        avg_demand = (sum(values) / len(values)) if values else 0.0
        quantity = data_loader._as_float(item.get("quantity_available"))
        minimum = data_loader._as_float(item.get("minimum_stock"))
        days_remaining = int(max(0.0, quantity - minimum) / avg_demand) if avg_demand > 0 else None
        supplies.append(
            {
                "stock_item_id": item_id,
                "name": str(item.get("name") or ""),
                "unit": str(item.get("unit") or ""),
                "quantity_available": quantity,
                "minimum_stock": minimum,
                "avg_daily_demand": round(avg_demand, 3),
                "projected_days_remaining": days_remaining,
                "alert_level": _alert_level(days_remaining, quantity, minimum),
                "confidence": "high" if sum(1 for value in values if value > 0) >= 5 else "low",
            }
        )
    return supplies, supply_quality


def build_overview() -> dict[str, Any]:
    window = settings.overview_window_days

    quality = DataQuality()

    # Insumos: primero la vista SQL (rapida); si no, fallback en Python.
    supplies = _supplies_from_view(window)
    if supplies is None:
        supplies, supply_quality = _supplies_from_python(window)
        quality.merge(supply_quality)

    labs = data_loader.list_laboratories()
    occupancy_by_id, lab_quality = data_loader.load_all_lab_occupancy(window)
    quality.merge(lab_quality)

    supplies.sort(
        key=lambda row: (
            _ALERT_ORDER[row["alert_level"]],
            row["projected_days_remaining"] if row["projected_days_remaining"] is not None else 10**6,
            -row["avg_daily_demand"],
        )
    )

    laboratories: list[dict[str, Any]] = []
    for lab in labs:
        lab_id = str(lab.get("id") or "")
        if not lab_id:
            continue
        values = [value for _, value in occupancy_by_id.get(lab_id, [])]
        avg_hours = (sum(values) / len(values)) if values else 0.0
        laboratories.append(
            {
                "laboratory_id": lab_id,
                "name": str(lab.get("name") or ""),
                "avg_daily_hours": round(avg_hours, 3),
                "recent_trend": _trend(values),
                "active_days": sum(1 for value in values if value > 0),
            }
        )

    laboratories.sort(key=lambda row: -row["avg_daily_hours"])

    supplies_at_risk = sum(1 for row in supplies if row["alert_level"] in ("red", "yellow"))
    soonest = min(
        (row for row in supplies if row["alert_level"] != "green" and row["projected_days_remaining"] is not None),
        key=lambda row: row["projected_days_remaining"],
        default=None,
    )
    busiest = laboratories[0] if laboratories else None

    peak_hours, weekday_usage = _usage_distributions(window)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": window,
        "supplies_total": len(supplies),
        "supplies_at_risk": supplies_at_risk,
        "soonest_depletion_days": soonest["projected_days_remaining"] if soonest else None,
        "soonest_depletion_name": soonest["name"] if soonest else "",
        "busiest_lab_name": busiest["name"] if busiest else "",
        "busiest_lab_hours": busiest["avg_daily_hours"] if busiest else 0.0,
        "supplies": supplies,
        "laboratories": laboratories,
        "peak_hours": peak_hours,
        "weekday_usage": weekday_usage,
        "data_quality": quality.as_dict(),
    }


def build_overview_cached() -> dict[str, Any]:
    now = monotonic()
    with _CACHE_LOCK:
        entry = _CACHE.get("overview")
        if entry and entry[0] > now:
            return entry[1]
    data = build_overview()
    with _CACHE_LOCK:
        _CACHE["overview"] = (now + settings.model_cache_ttl_seconds, data)
    return data
