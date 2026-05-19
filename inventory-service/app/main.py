import logging
import os

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.dependencies import auth_validation_client

logger = logging.getLogger(__name__)


def _warn_if_multi_worker() -> None:
    raw = os.getenv("WEB_CONCURRENCY") or os.getenv("UVICORN_WORKERS") or "1"
    try:
        workers = int(raw)
    except (TypeError, ValueError):
        return
    if workers > 1:
        logger.critical(
            "inventory-service detecto %s workers. Los locks de stock son in-proc; "
            "con >1 worker la condicion de carrera TOCTOU reaparece. Usa workers=1 "
            "hasta que exista un lock distribuido (Redis).",
            workers,
        )


_warn_if_multi_worker()

app = FastAPI(title="LabConnect Inventory Service", version="1.0.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "inventory-service"}


@app.on_event("shutdown")
def on_shutdown() -> None:
    auth_validation_client.close()


app.include_router(api_router)
