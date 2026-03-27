from fastapi import FastAPI

<<<<<<< HEAD
from app.api.v1.router import router as v1_router
from app.application.container import _pb_client
=======
from app.api.v1.router import api_router
from app.core.dependencies import auth_validation_client
from app.db.bootstrap import initialize_inventory_database
from app.infrastructure.pocketbase_sync import (
    initialize_inventory_pocketbase_sync,
    inventory_pocketbase_client,
)
import app.models.asset  # noqa: F401
import app.models.asset_status_log  # noqa: F401
import app.models.loan_record  # noqa: F401
import app.models.stock_movement  # noqa: F401
import app.models.stock_item  # noqa: F401
>>>>>>> 0fd8dd8e4fef7ab90058217a1e359fa5cfe45cbf

app = FastAPI(title="LabConnect Inventory Service", version="1.0.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "inventory-service"}


<<<<<<< HEAD
@app.on_event("shutdown")
def on_shutdown() -> None:
    _pb_client.close()
=======
@app.on_event("startup")
def on_startup() -> None:
    initialize_inventory_database()
    initialize_inventory_pocketbase_sync()


@app.on_event("shutdown")
def on_shutdown() -> None:
    auth_validation_client.close()
    inventory_pocketbase_client.close()
>>>>>>> 0fd8dd8e4fef7ab90058217a1e359fa5cfe45cbf


app.include_router(v1_router)
