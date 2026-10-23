from __future__ import annotations

from pydantic import BaseModel


class SeriesPointModel(BaseModel):
    date: str
    value: float


class DataQualityModel(BaseModel):
    total_records: int
    used_records: int
    excluded_status: int
    invalid_date: int
    out_of_window: int
    duplicates: int
    outliers_capped: int


class ForecastMetrics(BaseModel):
    mae: float       # error absoluto medio (mismas unidades del objetivo)
    rmse: float      # raiz del error cuadratico medio (penaliza errores grandes)
    test_days: int   # dias usados como prueba (backtesting)
    train_days: int  # dias usados para entrenar


class LaboratoryForecastResponse(BaseModel):
    laboratory_id: str
    laboratory_name: str
    metric: str
    period_days: int
    horizon_days: int
    confidence: str
    model: str
    history: list[SeriesPointModel]
    forecast: list[SeriesPointModel]
    projected_peak: float
    generated_at: str
    data_quality: DataQualityModel
    metrics: ForecastMetrics | None = None


class SupplyForecastPoint(BaseModel):
    date: str
    predicted_demand: float
    projected_stock: float


class SupplyForecastResponse(BaseModel):
    stock_item_id: str
    stock_item_name: str
    unit: str
    quantity_available: float
    minimum_stock: float
    period_days: int
    horizon_days: int
    confidence: str
    model: str
    history: list[SeriesPointModel]
    forecast: list[SupplyForecastPoint]
    projected_days_remaining: int | None
    alert_level: str
    generated_at: str
    data_quality: DataQualityModel
    metrics: ForecastMetrics | None = None


class SupplyRiskItem(BaseModel):
    stock_item_id: str
    name: str
    unit: str
    quantity_available: float
    minimum_stock: float
    avg_daily_demand: float
    projected_days_remaining: int | None
    alert_level: str
    confidence: str


class LabUsageSummary(BaseModel):
    laboratory_id: str
    name: str
    avg_daily_hours: float
    recent_trend: str
    active_days: int


class HourUsage(BaseModel):
    hour: int
    occupied_hours: float
    percentage: float


class WeekdayUsage(BaseModel):
    weekday: int
    label: str
    occupied_hours: float
    percentage: float


class PredictionsOverviewResponse(BaseModel):
    generated_at: str
    window_days: int
    supplies_total: int
    supplies_at_risk: int
    soonest_depletion_days: int | None
    soonest_depletion_name: str
    busiest_lab_name: str
    busiest_lab_hours: float
    supplies: list[SupplyRiskItem]
    laboratories: list[LabUsageSummary]
    peak_hours: list[HourUsage] = []
    weekday_usage: list[WeekdayUsage] = []
    data_quality: DataQualityModel
