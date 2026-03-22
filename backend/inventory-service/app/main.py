from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.models.asset import Asset
from app.models.asset_loan import AssetLoan
from app.models.stock_item import StockItem


def ensure_inventory_schema():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        if "assets" in existing_tables:
            asset_columns = {column["name"] for column in inspector.get_columns("assets")}
            if "quantity_total" not in asset_columns:
                connection.execute(text("ALTER TABLE assets ADD COLUMN quantity_total INTEGER NOT NULL DEFAULT 1"))
            if "quantity_available" not in asset_columns:
                connection.execute(text("ALTER TABLE assets ADD COLUMN quantity_available INTEGER NOT NULL DEFAULT 1"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_inventory_schema()
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def root():
    return {"message": "LabConnect Inventory Service running"}
