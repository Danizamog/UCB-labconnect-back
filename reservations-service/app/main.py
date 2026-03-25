from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.dependencies import auth_validation_client
from app.db.bootstrap import initialize_reservations_database
from app.infrastructure.inventory_client import inventory_service_client
import app.models.area  # noqa: F401
import app.models.class_session  # noqa: F401
import app.models.class_tutorial  # noqa: F401
import app.models.laboratory  # noqa: F401
import app.models.practice_material  # noqa: F401
import app.models.practice_request  # noqa: F401


app = FastAPI(title=settings.app_name, version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "reservations-service"}


@app.on_event("startup")
def on_startup() -> None:
    initialize_reservations_database()


@app.on_event("shutdown")
def on_shutdown() -> None:
    auth_validation_client.close()
    inventory_service_client.close()


app.include_router(api_router)
