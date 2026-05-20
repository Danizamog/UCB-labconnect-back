import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging

import anyio.to_thread

from app.api.v1.router import api_router
from app.api.v1.endpoints.penalties import _penalty_http_client
from app.core.dependencies import auth_validation_client
from app.reminders.scheduler import reservation_reminder_scheduler


logger = logging.getLogger(__name__)


def _warn_if_multi_worker() -> None:
    raw = os.getenv("WEB_CONCURRENCY") or os.getenv("UVICORN_WORKERS") or "1"
    try:
        workers = int(raw)
    except (TypeError, ValueError):
        return
    if workers > 1:
        logger.critical(
            "reservation-service detecto %s workers. Los locks por laboratorio, el "
            "NotificationStore, los recordatorios y el realtime manager son in-proc. "
            "Con >1 worker hay condiciones de carrera, notificaciones duplicadas y "
            "perdida de eventos. Usa workers=1 hasta que exista infra distribuida (Redis).",
            workers,
        )


_warn_if_multi_worker()


_THREADPOOL_TOKENS = 200


class _SkipHealthAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return 'GET /health' not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_SkipHealthAccessLogFilter())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = max(limiter.total_tokens, _THREADPOOL_TOKENS)
    reservation_reminder_scheduler.start()
    try:
        yield
    finally:
        await reservation_reminder_scheduler.stop()
        auth_validation_client.close()
        await _penalty_http_client.aclose()


app = FastAPI(title="LabConnect Reservation Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "reservation-service"}


app.include_router(api_router)
