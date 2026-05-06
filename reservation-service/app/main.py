from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging

import anyio.to_thread

from app.api.v1.router import api_router
from app.core.dependencies import auth_validation_client
from app.reminders.scheduler import reservation_reminder_scheduler


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


app = FastAPI(title="LabConnect Reservation Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "reservation-service"}


app.include_router(api_router)
