import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status

from app.application.container import user_repository
from app.core.config import settings
from app.core.local_test_accounts import seed_local_test_accounts
from app.interfaces.http.router import router as auth_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    seeded_count = seed_local_test_accounts(
        user_repository,
        settings.local_test_account_emails,
        settings.local_test_account_password,
        settings.local_test_teacher_emails,
    )
    if seeded_count:
        logger.warning("Se inicializaron %s cuentas de prueba locales en memoria", seeded_count)
    yield
    close_repository = getattr(user_repository, "close", None)
    if callable(close_repository):
        close_repository()


app = FastAPI(title="LabConnect Auth Service", version="2.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "auth-service"}


@app.get("/health/ready")
async def health_ready() -> dict:
    """Readiness: verifica que se puede autenticar el admin contra PocketBase.

    Separado del liveness `/health` a proposito: este puede devolver 503 cuando
    PocketBase no responde, sin afectar el healthcheck de docker-compose.
    """
    check_ready = getattr(user_repository, "check_ready", None)
    if callable(check_ready):
        try:
            await asyncio.to_thread(check_ready)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Readiness fallida: PocketBase no disponible: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="PocketBase no disponible",
            ) from exc
    return {"status": "ready", "service": "auth-service"}


app.include_router(auth_router)
