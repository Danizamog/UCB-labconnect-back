from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.infrastructure import prediction_cache_repository as cache
from app.services import data_loader
from app.services import predictions_service as preds

logger = logging.getLogger(__name__)

_started = False
_start_lock = threading.Lock()


def _now_local() -> datetime:
    """Hora local (naive) usando un offset fijo, sin depender de tzdata en la imagen."""
    return (datetime.now(timezone.utc) + timedelta(hours=settings.refresh_tz_offset_hours)).replace(tzinfo=None)


def _seconds_until_next_run() -> float:
    """Segundos hasta la proxima madrugada programada (hora local)."""
    now = _now_local()
    target = now.replace(hour=settings.refresh_hour, minute=settings.refresh_minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max(60.0, (target - now).total_seconds())


def refresh_once(include_supplies: bool = False) -> None:
    """Recalcula el panorama + el pronostico por laboratorio y lo guarda en la cache.

    Diseño escalable: el panorama usa la vista SQL (agregacion, sin entrenar) y solo se
    entrena un modelo por laboratorio (son pocos). El detalle por insumo NO se entrena en
    masa aqui (pueden ser cientos): se calcula on-demand y se cachea al primer clic. Asi el
    job no se cae aunque haya muchos registros/insumos."""
    started = time.monotonic()

    try:
        cache.upsert("overview", "", preds.compute_overview())
    except Exception:
        logger.exception("ml-service: fallo al calcular el panorama (overview)")

    labs_ok = labs_fail = 0
    for lab in data_loader.list_laboratories():
        lab_id = str(lab.get("id") or "")
        if not lab_id:
            continue
        try:
            payload = preds.compute_lab_forecast(lab_id)
            if payload:
                cache.upsert("lab", lab_id, payload, str(payload.get("confidence") or ""))
                labs_ok += 1
        except Exception:
            labs_fail += 1
            logger.exception("ml-service: fallo el pronostico del laboratorio %s", lab_id)

    supplies_ok = 0
    if include_supplies:
        for item in data_loader.list_stock_items():
            item_id = str(item.get("id") or "")
            if not item_id:
                continue
            try:
                payload = preds.compute_supply_forecast(item_id)
                if payload:
                    cache.upsert("supply", item_id, payload, str(payload.get("confidence") or ""))
                    supplies_ok += 1
            except Exception:
                logger.exception("ml-service: fallo el pronostico del insumo %s", item_id)

    logger.info(
        "ml-service: cache actualizada en %.1fs (labs ok=%s, labs fallidos=%s, insumos=%s)",
        time.monotonic() - started,
        labs_ok,
        labs_fail,
        supplies_ok if include_supplies else "lazy",
    )


def _loop() -> None:
    # Pre-calentado al arrancar: panorama + laboratorios (rapido) para no quedar con cache vacia.
    try:
        logger.info("ml-service: pre-calentando cache (panorama + laboratorios)...")
        refresh_once(include_supplies=False)
    except Exception:
        logger.exception("ml-service: error en el pre-calentado inicial")

    while True:
        wait = _seconds_until_next_run()
        logger.info(
            "ml-service: proximo refresco programado en %.1f h (madrugada %02d:%02d, UTC%+g)",
            wait / 3600.0,
            settings.refresh_hour,
            settings.refresh_minute,
            settings.refresh_tz_offset_hours,
        )
        time.sleep(wait)
        try:
            refresh_once(include_supplies=settings.precompute_supplies)
        except Exception:
            logger.exception("ml-service: error en el refresco programado")


def start() -> None:
    """Lanza el refresco en un hilo daemon. Idempotente.

    IMPORTANTE: el ml-service debe correr con un solo worker de uvicorn; con varias
    replicas el refresco se dispararia en paralelo (ver Dockerfile: 1 worker)."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="ml-prediction-refresh", daemon=True).start()
    logger.info("ml-service: scheduler de predicciones iniciado")
