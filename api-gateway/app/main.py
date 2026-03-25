from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.interfaces.http.local_router import router as local_router
from app.interfaces.http.proxy_router import router as proxy_router

app = FastAPI(title="LabConnect API Gateway", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api-gateway"}


app.include_router(local_router)
app.include_router(proxy_router)
