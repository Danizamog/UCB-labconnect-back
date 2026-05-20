from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.application.container import user_repository
from app.interfaces.http.router import router as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close_repository = getattr(user_repository, "close", None)
    if callable(close_repository):
        close_repository()


app = FastAPI(title="LabConnect Auth Service", version="2.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "auth-service"}


app.include_router(auth_router)
