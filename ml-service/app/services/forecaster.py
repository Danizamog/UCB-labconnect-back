from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from threading import Lock
from time import monotonic
from typing import Callable

import numpy as np

from app.core.config import settings

# Lag features fed to the network plus a weekday one-hot to capture the strong
# day-of-week seasonality of lab usage / supply consumption.
_LAGS = (1, 2, 3, 7)
_MAX_LAG = max(_LAGS)
# Minimum number of (features, target) rows required before we trust the NN.
_MIN_TRAINING_ROWS = 12
# Minimum non-zero observations before the NN is worthwhile (else baseline).
_MIN_NONZERO = 5


@dataclass
class SeriesPoint:
    date: str
    value: float


@dataclass
class ForecastOutput:
    history: list[SeriesPoint]
    forecast: list[SeriesPoint]
    confidence: str  # "high" | "low"
    model: str       # "mlp_regressor" | "baseline_weekday_mean"


# --- in-memory TTL cache for fitted forecasts ---------------------------------
_CACHE_LOCK = Lock()
_CACHE: dict[str, tuple[float, object]] = {}


def cached_forecast(key: str, builder: Callable[[], object]) -> object:
    """Return a cached result or build, cache and return a fresh one.

    Training on-demand and caching the result keeps the first iteration simple
    (no separate retraining cron) while avoiding re-fitting on every request.
    """
    now = monotonic()
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry and entry[0] > now:
            return entry[1]
    result = builder()
    with _CACHE_LOCK:
        _CACHE[key] = (now + settings.model_cache_ttl_seconds, result)
    return result


def _weekday_onehot(day: date) -> list[float]:
    vec = [0.0] * 7
    vec[day.weekday()] = 1.0
    return vec


def _build_supervised(values: np.ndarray, dates: list[date]) -> tuple[np.ndarray, np.ndarray]:
    rows: list[list[float]] = []
    targets: list[float] = []
    for i in range(_MAX_LAG, len(values)):
        lags = [float(values[i - lag]) for lag in _LAGS]
        rows.append(lags + _weekday_onehot(dates[i]))
        targets.append(float(values[i]))
    return np.asarray(rows, dtype=float), np.asarray(targets, dtype=float)


def _mlp_forecast(values: np.ndarray, dates: list[date], horizon: int) -> list[float]:
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import MinMaxScaler

    features, targets = _build_supervised(values, dates)
    if len(features) < _MIN_TRAINING_ROWS:
        raise ValueError("insufficient training rows for the neural network")

    x_scaler = MinMaxScaler()
    y_scaler = MinMaxScaler()
    scaled_x = x_scaler.fit_transform(features)
    scaled_y = y_scaler.fit_transform(targets.reshape(-1, 1)).ravel()

    model = MLPRegressor(
        hidden_layer_sizes=(32, 16),
        activation="relu",
        solver="adam",
        max_iter=800,
        random_state=42,
    )
    model.fit(scaled_x, scaled_y)

    buffer = [float(v) for v in values]
    last_date = dates[-1]
    predictions: list[float] = []
    for step in range(1, horizon + 1):
        target_day = last_date + timedelta(days=step)
        lags = [buffer[-lag] for lag in _LAGS]
        feats = np.asarray([lags + _weekday_onehot(target_day)], dtype=float)
        scaled_pred = model.predict(x_scaler.transform(feats))
        value = float(y_scaler.inverse_transform(scaled_pred.reshape(-1, 1)).ravel()[0])
        value = max(0.0, value)
        buffer.append(value)
        predictions.append(value)
    return predictions


def _weekday_mean_forecast(values: np.ndarray, dates: list[date], horizon: int) -> list[float]:
    sums: dict[int, float] = defaultdict(float)
    counts: dict[int, int] = defaultdict(int)
    for value, day in zip(values, dates):
        sums[day.weekday()] += float(value)
        counts[day.weekday()] += 1

    overall = float(np.mean(values)) if len(values) else 0.0
    last_date = dates[-1] if dates else date.today()

    predictions: list[float] = []
    for step in range(1, horizon + 1):
        target_day = last_date + timedelta(days=step)
        weekday = target_day.weekday()
        if counts[weekday]:
            predictions.append(max(0.0, sums[weekday] / counts[weekday]))
        else:
            predictions.append(max(0.0, overall))
    return predictions


def forecast_series(series: list[tuple[date, float]], horizon: int | None = None) -> ForecastOutput:
    """Forecast a daily series with an MLPRegressor, falling back to a weekday
    mean baseline (flagged low confidence) when there is not enough history."""
    horizon = horizon or settings.forecast_days
    ordered = sorted(series, key=lambda item: item[0])
    dates = [day for day, _ in ordered]
    values = np.asarray([float(value) for _, value in ordered], dtype=float)

    history = [SeriesPoint(date=day.isoformat(), value=round(float(value), 3)) for day, value in ordered]

    predictions: list[float] | None = None
    model_name = "mlp_regressor"
    confidence = "high"

    enough_history = len(values) >= _MAX_LAG + _MIN_TRAINING_ROWS
    enough_signal = int(np.count_nonzero(values)) >= _MIN_NONZERO
    if enough_history and enough_signal:
        try:
            predictions = _mlp_forecast(values, dates, horizon)
        except Exception:
            predictions = None

    if predictions is None:
        model_name = "baseline_weekday_mean"
        confidence = "low"
        predictions = _weekday_mean_forecast(values, dates, horizon)

    last_date = dates[-1] if dates else date.today()
    forecast = [
        SeriesPoint(date=(last_date + timedelta(days=offset + 1)).isoformat(), value=round(float(value), 3))
        for offset, value in enumerate(predictions)
    ]
    return ForecastOutput(history=history, forecast=forecast, confidence=confidence, model=model_name)
