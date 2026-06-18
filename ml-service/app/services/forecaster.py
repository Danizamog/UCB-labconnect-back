from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from threading import Lock
from time import monotonic
from typing import Callable

import numpy as np

from app.core.config import settings


_LAGS = (1, 2, 3, 7)
_MAX_LAG = max(_LAGS)
_MIN_TRAINING_ROWS = 12
_MIN_NONZERO = 5


@dataclass
class SeriesPoint:
    """Un punto de la serie: una fecha (ISO) y su valor."""

    date: str
    value: float


@dataclass
class ForecastOutput:
    """Resultado del pronóstico que se devuelve al consumidor (API/frontend)."""

    history: list[SeriesPoint]
    forecast: list[SeriesPoint]
    confidence: str
    model: str
    # Métricas de validación (MAE/RMSE) por backtesting temporal. None si no aplica.
    metrics: dict | None = None



_CACHE_LOCK = Lock()
_CACHE: dict[str, tuple[float, object]] = {}


def cached_forecast(key: str, builder: Callable[[], object]) -> object:
    """Devuelve un resultado cacheado o lo construye, lo guarda y lo devuelve.
    Entrenar bajo demanda y cachear el resultado mantiene la primera iteración
    simple (sin necesidad de un cron de reentrenamiento aparte) y evita volver a
    entrenar el modelo en cada petición.
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
    """Codifica el día de la semana como vector one-hot de 7 posiciones.
    Ej.: lunes -> [1,0,0,0,0,0,0], martes -> [0,1,0,0,0,0,0], etc. Permite que
    el modelo aprenda un comportamiento distinto para cada día de la semana.
    """
    vec = [0.0] * 7
    vec[day.weekday()] = 1.0
    return vec


def _build_supervised(values: np.ndarray, dates: list[date]) -> tuple[np.ndarray, np.ndarray]:
    """Convierte la serie temporal en un problema supervisado (X, y).
    Por cada día (a partir del día _MAX_LAG, porque antes no hay suficientes
    rezagos) arma una fila de features = [valor_t-1, valor_t-2, valor_t-3,
    valor_t-7] + one_hot(día_semana), y como objetivo el valor de ese mismo día.
    """
    rows: list[list[float]] = []
    targets: list[float] = []
    for i in range(_MAX_LAG, len(values)):
        lags = [float(values[i - lag]) for lag in _LAGS]
        rows.append(lags + _weekday_onehot(dates[i]))
        targets.append(float(values[i]))
    return np.asarray(rows, dtype=float), np.asarray(targets, dtype=float)


def _mlp_forecast(values: np.ndarray, dates: list[date], horizon: int) -> list[float]:
    """Pronostica con una red neuronal multicapa (MLPRegressor de scikit-learn).

    Predice de forma recursiva: el valor pronosticado de un día se reinyecta como
    rezago para predecir el día siguiente, y así hasta cubrir todo el horizonte.
    """
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


def _evaluate_backtest(values: np.ndarray, dates: list[date]) -> dict | None:
    """Backtesting temporal: entrena con la parte antigua y mide el error en la
    cola reciente (predicción a 1 paso). NO mezcla al azar — en series de tiempo
    eso sería fuga de futuro. El escalado se ajusta SOLO con el train.

    Devuelve MAE y RMSE: cuánto se equivoca el modelo, en las mismas unidades del
    objetivo (horas / unidades). Métricas más bajas = mejor."""
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import MinMaxScaler

    features, targets = _build_supervised(values, dates)
    total = len(features)
    # Cola de prueba: 20% de las filas, mínimo 3 y máximo 14 días.
    test_size = max(3, min(int(round(total * 0.2)), 14))
    if total - test_size < _MIN_TRAINING_ROWS:
        return None  # no queda suficiente para entrenar de forma confiable

    x_train, x_test = features[:-test_size], features[-test_size:]
    y_train, y_test = targets[:-test_size], targets[-test_size:]

    # Escalar SOLO con el train evita que el test "filtre" información (data leakage).
    x_scaler = MinMaxScaler().fit(x_train)
    y_scaler = MinMaxScaler().fit(y_train.reshape(-1, 1))

    model = MLPRegressor(
        hidden_layer_sizes=(32, 16),
        activation="relu",
        solver="adam",
        max_iter=800,
        random_state=42,
    )
    model.fit(x_scaler.transform(x_train), y_scaler.transform(y_train.reshape(-1, 1)).ravel())

    pred_scaled = model.predict(x_scaler.transform(x_test))
    predicted = np.clip(y_scaler.inverse_transform(pred_scaled.reshape(-1, 1)).ravel(), 0.0, None)

    errors = predicted - y_test
    return {
        "mae": round(float(np.mean(np.abs(errors))), 3),
        "rmse": round(float(np.sqrt(np.mean(errors ** 2))), 3),
        "test_days": int(test_size),
        "train_days": int(total - test_size),
    }


def _weekday_mean_forecast(values: np.ndarray, dates: list[date], horizon: int) -> list[float]:
    """Baseline simple: pronostica con el promedio histórico de cada día de la semana.
    Se usa cuando no hay suficiente historia para la red. Para cada día futuro
    devuelve el promedio de los valores que históricamente cayeron en ese día de
    la semana (o el promedio general si no hay datos de ese día).
    """
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
    """Pronostica una serie diaria con un MLPRegressor, cayendo a un baseline de
    promedio por día de la semana (marcado como baja confianza) cuando no hay
    suficiente historia.
    Es el punto de entrada público del módulo. Recibe la serie como pares
    (fecha, valor) y devuelve historia + pronóstico + metadatos.
    """
    horizon = horizon or settings.forecast_days
    ordered = sorted(series, key=lambda item: item[0])
    dates = [day for day, _ in ordered]
    values = np.asarray([float(value) for _, value in ordered], dtype=float)

    history = [SeriesPoint(date=day.isoformat(), value=round(float(value), 3)) for day, value in ordered]

    predictions: list[float] | None = None
    model_name = "mlp_regressor"
    confidence = "high"
    metrics: dict | None = None

    enough_history = len(values) >= _MAX_LAG + _MIN_TRAINING_ROWS
    enough_signal = int(np.count_nonzero(values)) >= _MIN_NONZERO
    if enough_history and enough_signal:
        try:
            predictions = _mlp_forecast(values, dates, horizon)
            # Mide el error con un backtest temporal (no rompe el pronóstico si falla).
            try:
                metrics = _evaluate_backtest(values, dates)
            except Exception:
                metrics = None
        except Exception:
            predictions = None

    if predictions is None:
        model_name = "baseline_weekday_mean"
        confidence = "low"
        metrics = None
        predictions = _weekday_mean_forecast(values, dates, horizon)

    last_date = dates[-1] if dates else date.today()
    forecast = [
        SeriesPoint(date=(last_date + timedelta(days=offset + 1)).isoformat(), value=round(float(value), 3))
        for offset, value in enumerate(predictions)
    ]
    return ForecastOutput(history=history, forecast=forecast, confidence=confidence, model=model_name, metrics=metrics)
