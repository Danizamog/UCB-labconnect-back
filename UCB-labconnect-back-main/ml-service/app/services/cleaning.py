from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

# Recorte robusto de outliers: valores por encima de mediana + K*MAD se recortan
# para que un registro anomalo (p. ej. una reserva cargada con datos erroneos) no
# distorsione el entrenamiento del modelo.
_OUTLIER_K = 6.0
_MIN_POINTS_FOR_OUTLIER = 6


@dataclass
class DataQuality:
    """Resumen de limpieza de datos del ETL para mostrar al usuario."""

    total_records: int = 0
    used_records: int = 0
    excluded_status: int = 0
    invalid_date: int = 0
    out_of_window: int = 0
    duplicates: int = 0
    outliers_capped: int = 0

    def merge(self, other: "DataQuality") -> None:
        self.total_records += other.total_records
        self.used_records += other.used_records
        self.excluded_status += other.excluded_status
        self.invalid_date += other.invalid_date
        self.out_of_window += other.out_of_window
        self.duplicates += other.duplicates
        self.outliers_capped += other.outliers_capped

    def as_dict(self) -> dict[str, int]:
        return {
            "total_records": self.total_records,
            "used_records": self.used_records,
            "excluded_status": self.excluded_status,
            "invalid_date": self.invalid_date,
            "out_of_window": self.out_of_window,
            "duplicates": self.duplicates,
            "outliers_capped": self.outliers_capped,
        }


def cap_outliers(daily: dict[date, float]) -> int:
    """Recorta in-place los picos anomalos de una serie diaria.

    Devuelve cuantos dias fueron recortados. Usa mediana + K*MAD (robusto a
    outliers, a diferencia de media + desviacion estandar)."""
    positive = np.array([value for value in daily.values() if value > 0], dtype=float)
    if len(positive) < _MIN_POINTS_FOR_OUTLIER:
        return 0

    median = float(np.median(positive))
    mad = float(np.median(np.abs(positive - median)))
    if mad <= 0:
        return 0

    cap = median + _OUTLIER_K * mad
    capped = 0
    for day, value in list(daily.items()):
        if value > cap:
            daily[day] = round(cap, 4)
            capped += 1
    return capped
