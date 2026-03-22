from fastapi import FastAPI

from app.interfaces.http.router import api_router

app = FastAPI(title="LabConnect Inventory Service", version="2.0.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "inventory-service"}


app.include_router(api_router)
