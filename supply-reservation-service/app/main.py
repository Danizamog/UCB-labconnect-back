from fastapi import FastAPI

from app.api.v1.router import api_router
from app.application.container import close_resources
from app.core.dependencies import auth_validation_client

app = FastAPI(title="LabConnect Supply Reservation Service", version="1.0.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "supply-reservation-service"}


@app.on_event("shutdown")
def on_shutdown() -> None:
    auth_validation_client.close()
    close_resources()


app.include_router(api_router)
