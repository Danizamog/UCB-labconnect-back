from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import ensure_any_permission, get_current_user
from app.infrastructure import prediction_cache_repository as cache
from app.schemas.predictions import (
    LaboratoryForecastResponse,
    PredictionsOverviewResponse,
    SupplyForecastResponse,
)
from app.services import predictions_service as preds

router = APIRouter(prefix="/analytics/predict", tags=["ml-predictions"])

# Same permission the analytics view is gated on, front and back.
_VIEW_PREDICTIONS = {"consultar_estadisticas"}


@router.get("/overview", response_model=PredictionsOverviewResponse)
def predictions_overview(
    current_user: dict = Depends(get_current_user),
) -> PredictionsOverviewResponse:
    ensure_any_permission(current_user, _VIEW_PREDICTIONS, "No tienes permisos para consultar predicciones")

    cached = _safe_read("overview", "")
    if cached and cache.is_fresh(cached):
        return PredictionsOverviewResponse(**cached)

    data = preds.compute_overview()
    _safe_upsert("overview", "", data)
    return PredictionsOverviewResponse(**data)


@router.get("/laboratories/{lab_id}", response_model=LaboratoryForecastResponse)
def predict_laboratory_usage(
    lab_id: str,
    current_user: dict = Depends(get_current_user),
) -> LaboratoryForecastResponse:
    ensure_any_permission(current_user, _VIEW_PREDICTIONS, "No tienes permisos para consultar predicciones de uso")

    cached = _safe_read("lab", lab_id)
    if cached and cache.is_fresh(cached):
        return LaboratoryForecastResponse(**cached)

    data = preds.compute_lab_forecast(lab_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Laboratorio no encontrado")
    _safe_upsert("lab", lab_id, data, str(data.get("confidence") or ""))
    return LaboratoryForecastResponse(**data)


@router.get("/supplies/{stock_item_id}", response_model=SupplyForecastResponse)
def predict_supply_depletion(
    stock_item_id: str,
    current_user: dict = Depends(get_current_user),
) -> SupplyForecastResponse:
    ensure_any_permission(current_user, _VIEW_PREDICTIONS, "No tienes permisos para consultar predicciones de insumos")

    cached = _safe_read("supply", stock_item_id)
    if cached and cache.is_fresh(cached):
        return SupplyForecastResponse(**cached)

    data = preds.compute_supply_forecast(stock_item_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material no encontrado")
    _safe_upsert("supply", stock_item_id, data, str(data.get("confidence") or ""))
    return SupplyForecastResponse(**data)


def _safe_read(kind: str, target_id: str) -> dict | None:
    """Lee de la cache; si PocketBase falla, devuelve None para caer al calculo on-demand."""
    try:
        return cache.read(kind, target_id)
    except Exception:  # noqa: BLE001 - mejor recalcular que romper la respuesta
        return None


def _safe_upsert(kind: str, target_id: str, payload: dict, confidence: str = "") -> None:
    """Guarda en la cache sin romper la respuesta si PocketBase falla al escribir."""
    try:
        cache.upsert(kind, target_id, payload, confidence)
    except Exception:  # noqa: BLE001 - la respuesta ya esta lista; el cron reintentara
        pass
