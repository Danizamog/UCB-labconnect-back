from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.dependencies import auth_validation_client

app = FastAPI(title="LabConnect Inventory Service", version="1.0.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "inventory-service"}


@app.on_event("shutdown")
def on_shutdown() -> None:
    auth_validation_client.close()


app.include_router(api_router)
