from fastapi import FastAPI

from app.interfaces.http.router import router as roles_router

app = FastAPI(title="LabConnect Role Service", version="1.0.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "role-service"}


app.include_router(roles_router)
