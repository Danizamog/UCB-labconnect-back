from fastapi import FastAPI

from app.application.container import sync_shadow_users_from_primary, user_repository
from app.interfaces.http.router import router as auth_router

app = FastAPI(title="LabConnect Auth Service", version="2.0.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "auth-service"}


@app.on_event("startup")
def on_startup() -> None:
    sync_shadow_users_from_primary()


@app.on_event("shutdown")
def on_shutdown() -> None:
    close_repository = getattr(user_repository, "close", None)
    if callable(close_repository):
        close_repository()


app.include_router(auth_router)
