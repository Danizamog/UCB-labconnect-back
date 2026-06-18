from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.services import data_loader, overview
from app.services.forecaster import forecast_series

# Below this many days of projected stock we raise a red alert.
_CRITICAL_DAYS = 7


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_overview() -> dict[str, Any]:
    return overview.build_overview()


def compute_lab_forecast(lab_id: str) -> dict[str, Any] | None:
    """Payload de pronostico de ocupacion para un laboratorio. None si no existe."""
    laboratory = data_loader.get_laboratory(lab_id)
    if laboratory is None:
        return None

    series, quality = data_loader.load_lab_daily_occupancy(lab_id)
    out = forecast_series(series)

    return {
        "laboratory_id": lab_id,
        "laboratory_name": str(laboratory.get("name") or ""),
        "metric": "reserved_hours_per_day",
        "period_days": settings.history_days,
        "horizon_days": settings.forecast_days,
        "confidence": out.confidence,
        "model": out.model,
        "history": [{"date": point.date, "value": point.value} for point in out.history],
        "forecast": [{"date": point.date, "value": point.value} for point in out.forecast],
        "projected_peak": round(max((point.value for point in out.forecast), default=0.0), 3),
        "generated_at": _now_iso(),
        "data_quality": quality.as_dict(),
        "metrics": out.metrics,
    }


def compute_supply_forecast(stock_item_id: str) -> dict[str, Any] | None:
    """Payload de pronostico de agotamiento para un insumo. None si no existe."""
    item = data_loader.get_stock_item(stock_item_id)
    if item is None:
        return None

    series, quality = data_loader.load_supply_daily_consumption(stock_item_id)
    out = forecast_series(series)

    quantity = data_loader._as_float(item.get("quantity_available"))
    minimum = data_loader._as_float(item.get("minimum_stock"))

    remaining = quantity
    days_remaining: int | None = None
    forecast_points: list[dict[str, Any]] = []
    for index, point in enumerate(out.forecast):
        remaining = max(0.0, remaining - point.value)
        forecast_points.append(
            {
                "date": point.date,
                "predicted_demand": point.value,
                "projected_stock": round(remaining, 3),
            }
        )
        if days_remaining is None and remaining <= minimum:
            days_remaining = index + 1

    if quantity <= minimum:
        alert_level = "red"
    elif days_remaining is not None:
        alert_level = "red" if days_remaining <= _CRITICAL_DAYS else "yellow"
    else:
        alert_level = "green"

    return {
        "stock_item_id": stock_item_id,
        "stock_item_name": str(item.get("name") or ""),
        "unit": str(item.get("unit") or ""),
        "quantity_available": quantity,
        "minimum_stock": minimum,
        "period_days": settings.history_days,
        "horizon_days": settings.forecast_days,
        "confidence": out.confidence,
        "model": out.model,
        "history": [{"date": point.date, "value": point.value} for point in out.history],
        "forecast": forecast_points,
        "projected_days_remaining": days_remaining,
        "alert_level": alert_level,
        "generated_at": _now_iso(),
        "data_quality": quality.as_dict(),
        "metrics": out.metrics,
    }
