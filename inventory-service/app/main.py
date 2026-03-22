from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.base import Base
from app.db.session import engine
from app.interfaces.http.router import api_router
import app.models.asset  # noqa: F401

app = FastAPI(title="LabConnect Inventory Service", version="2.0.0")

# Garantiza que exista la tabla de equipos para persistencia.
Base.metadata.create_all(bind=engine)

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


app.include_router(api_router)
