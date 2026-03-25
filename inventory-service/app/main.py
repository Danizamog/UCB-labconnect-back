from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.dependencies import auth_validation_client
from app.db.bootstrap import initialize_inventory_database
import app.models.asset  # noqa: F401
import app.models.asset_status_log  # noqa: F401
import app.models.loan_record  # noqa: F401
import app.models.stock_movement  # noqa: F401
import app.models.stock_item  # noqa: F401

app = FastAPI(title="LabConnect Inventory Service", version="2.0.0")

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "inventory-service"}


@app.on_event("startup")
def on_startup() -> None:
    initialize_inventory_database()


@app.on_event("shutdown")
def on_shutdown() -> None:
    auth_validation_client.close()


app.include_router(api_router)
