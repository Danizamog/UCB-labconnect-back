import logging

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.dependencies import auth_validation_client
from app.infrastructure import prediction_cache_repository as cache
from app.services import data_loader, scheduler

# Para que los logs del scheduler (INFO) sean visibles: uvicorn no configura el
# logger raiz, asi que sin esto los mensajes del cron quedarian ocultos.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

logger = logging.getLogger(__name__)

app = FastAPI(title="LabConnect ML Service", version="1.0.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "ml-service"}


@app.on_event("startup")
def on_startup() -> None:
    # Resiliente: si PocketBase no responde al arrancar, el servicio igual levanta
    # (health funciona) y el scheduler reintenta en su proximo ciclo.
    try:
        cache.ensure_collection()
    except Exception:
        logger.exception("ml-service: fallo verificando la cache; el scheduler reintentara")
    try:
        scheduler.start()
    except Exception:
        logger.exception("ml-service: no se pudo iniciar el scheduler de predicciones")


@app.on_event("shutdown")
def on_shutdown() -> None:
    auth_validation_client.close()
    data_loader.close()
    cache.close()


app.include_router(api_router)
