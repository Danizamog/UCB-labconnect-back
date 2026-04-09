from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.infrastructure.http.proxy import close_proxy_client
from app.interfaces.http.proxy_router import router as proxy_router

app = FastAPI(title="LabConnect API Gateway", version="2.0.0")

origins = settings.cors_allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api-gateway"}


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await close_proxy_client()

app.include_router(proxy_router)
